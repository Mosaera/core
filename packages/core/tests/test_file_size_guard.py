"""The god-file ratchet must ratchet — in BOTH directions (2026-08-07 audit, #81).

`GRANDFATHERED` was a bare `set[str]`: names, no sizes. That enforced exactly one direction. A
listed file that dropped under the limit failed as stale (good), but a listed file could **grow
without bound** and nothing noticed — the guard only ever caught you *fixing* something. Over its
life `apps/api/tests/test_api.py` reached 5702 lines, 11x the production ceiling and 37% of every
test line in the repo, entirely invisible because tests were exempt outright rather than given a
looser bar.

`check_file_sizes.py` had no guard-test at all, which is the same gap `test_doc_links_guard.py`
exists to close for the link guard: a check nothing checks is a claim, not a control.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "check_file_sizes.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("check_file_sizes", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _audit_over(tmp_path: Path, monkeypatch: Any, files: dict[str, int], **over: Any) -> Any:
    """Run the guard's audit over a synthetic tree, so the assertions do not drift with the repo."""
    mod = _load()
    for rel, lines in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n" * lines, encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "SCAN_ROOTS", ("packages", "apps", "scripts"))
    for k, v in over.items():
        monkeypatch.setattr(mod, k, v)
    return mod.audit()


def test_a_GRANDFATHERED_file_that_GREW_fails(tmp_path: Path, monkeypatch: Any) -> None:
    """THE hole. Recorded at 600, now 700 — this passed silently for the whole life of the guard."""
    _, grown, _ = _audit_over(
        tmp_path,
        monkeypatch,
        {"packages/big.py": 700},
        GRANDFATHERED={"packages/big.py": 600},
    )
    assert [(rel, n, rec) for rel, n, rec in grown] == [("packages/big.py", 700, 600)]


def test_a_GRANDFATHERED_file_that_HELD_or_SHRANK_passes(tmp_path: Path, monkeypatch: Any) -> None:
    """The debt is allowed to sit; it is not allowed to grow."""
    for lines in (600, 550):
        offenders, grown, stale = _audit_over(
            tmp_path / str(lines),
            monkeypatch,
            {"packages/big.py": lines},
            GRANDFATHERED={"packages/big.py": 600},
        )
        assert (offenders, grown, stale) == ([], [], set()), lines


def test_a_GRANDFATHERED_file_that_dropped_under_the_limit_is_STALE(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The direction that already worked — kept, because a fixed file must leave the list."""
    _, _, stale = _audit_over(
        tmp_path,
        monkeypatch,
        {"packages/big.py": 400},
        GRANDFATHERED={"packages/big.py": 600},
    )
    assert stale == {"packages/big.py"}


def test_scripts_are_scanned(tmp_path: Path, monkeypatch: Any) -> None:
    """A 691-line "script" is a god-file wherever it lives; `scripts/` was outside SCAN_ROOTS."""
    offenders, _, _ = _audit_over(tmp_path, monkeypatch, {"scripts/huge.py": 600}, GRANDFATHERED={})
    assert [rel for rel, _, _ in offenders] == ["scripts/huge.py"]


def test_tests_get_a_LOOSER_ceiling_but_a_ceiling(tmp_path: Path, monkeypatch: Any) -> None:
    """Not exempt, not held to 500. A table-driven suite legitimately runs long; 5702 does not."""
    offenders, _, _ = _audit_over(
        tmp_path,
        monkeypatch,
        {"packages/tests/test_ok.py": 900, "packages/tests/test_huge.py": 1600},
        GRANDFATHERED={},
    )
    assert [rel for rel, _, _ in offenders] == ["packages/tests/test_huge.py"]
    assert offenders[0][2] == 1500  # judged against MAX_TEST_LINES, not MAX_LINES


def test_a_co_located_web_test_counts_as_a_test(tmp_path: Path, monkeypatch: Any) -> None:
    """`*.test.tsx` sits beside production code — it must get the test ceiling, not the exemption
    it used to have and not the production limit."""
    mod = _load()
    assert mod.limit_for("apps/web/src/components/Foo.test.tsx") == mod.MAX_TEST_LINES
    assert mod.limit_for("apps/web/src/components/Foo.tsx") == mod.MAX_LINES
    assert mod.limit_for("packages/core/tests/test_x.py") == mod.MAX_TEST_LINES


def test_the_real_repo_is_clean(tmp_path: Path, monkeypatch: Any) -> None:
    """The guard's own recorded sizes must match reality — otherwise the ratchet is fiction."""
    mod = _load()
    offenders, grown, stale = mod.audit()
    assert (offenders, grown, stale) == ([], [], set())
