"""Two TERMINAL false parks the 1f710222 widening woke up, and one vouch-while-nothing-ran.

`tests_tampered` is terminal and unshippable. All three defects below sat dormant only because the
protected set was EMPTY on this repo shape; populating it (0 -> 249) made every one reachable. So
the fix that closed a real hole is what armed these — which is the whole reason a red-team round
follows a security change rather than preceding it.

Every test here fails against `1f710222`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.graph._tamper import tamper_verdict
from mosaera_core.graph.nodes_impl import _never_rewrite
from mosaera_core.mutation import _never_collected
from mosaera_core.testintegrity import (
    INTEGRITY_ENUMERATOR,
    integrity_baseline,
    integrity_hash,
    tampered_integrity,
)
from mosaera_core.tools.repo import Workspace

_REAL = "def test_requirement():\n    assert compute() == 7\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)  # noqa: S603,S607 — git from PATH, no shell; test fixture


def _repo(root: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    return Workspace(root=root, run_id="t", branch="b")


# --- A. a baseline built by an older enumerator must not CONVICT a pristine tree ----------


def _stale_repo(root: Path) -> Workspace:
    """400 `apps/` files, so `tests/` and the root configs sort past the old 300-path cap."""
    files = {f"apps/f{i:04d}.ts": "export const x = 1\n" for i in range(400)}
    files["tests/test_acceptance.py"] = _REAL
    files["conftest.py"] = "import sys\n"
    files["pyproject.toml"] = "[tool.pytest.ini_options]\naddopts = '-q'\n"
    return _repo(root, files)


def test_a_baseline_from_an_older_enumerator_does_not_convict_a_pristine_tree(
    tmp_path: Path,
) -> None:
    """THE terminal false park. Verified on the real repo: 28-entry baseline, 249 enumerated,
    `tampered_integrity` returned `['conftest.py', 'pyproject.toml']` with NOTHING modified.

    `integrity_baseline` is snapshotted once and deliberately never refreshed — re-baselining would
    absorb writes the coder already made, which is the tamper the guard exists to catch. So when the
    enumerator widened underneath it, "enumerated now but absent from the baseline" stopped meaning
    "created after run start". Every pre-upgrade parked run that resumed into more work parked
    terminally, on a clean tree — the population an operator touches the day after a deploy.
    """
    ws = _stale_repo(tmp_path)
    # A baseline as the OLD enumerator built it: capped, so late-sorting paths are absent.
    old_listing = ws.file_listing()
    old_baseline = {
        rel: integrity_hash(ws, rel) for rel in old_listing if rel.endswith(".py") and "test" in rel
    }
    assert "conftest.py" not in old_baseline, "premise: the old cap dropped it"

    assert tampered_integrity(ws, old_baseline, baseline_complete=False) == [], (
        "a baseline built by a previous enumerator convicted an untouched tree"
    )


def test_branch_A_still_catches_a_real_edit_under_a_stale_baseline(tmp_path: Path) -> None:
    """Suppression is scoped to ONE branch. Without this, 'fix' the false park by returning [].

    The baselined-path comparison never consults the enumerator — it iterates the baseline itself —
    so every path the old baseline does cover stays content-checked. Only 'a new collection control
    appeared' is lost, and only for runs already in flight across the upgrade.
    """
    ws = _stale_repo(tmp_path)
    baseline = {"tests/test_acceptance.py": integrity_hash(ws, "tests/test_acceptance.py")}
    (tmp_path / "tests" / "test_acceptance.py").write_text(
        "def test_requirement():\n    assert True  # neutered\n", encoding="utf-8"
    )
    assert tampered_integrity(ws, baseline, baseline_complete=False) == [
        "tests/test_acceptance.py"
    ], "the producer rewrote a baselined test and the stale-baseline path let it through"


def test_a_CURRENT_baseline_still_flags_a_new_collect_ignore(tmp_path: Path) -> None:
    """THE CONTRAST. Suppressing the branch unconditionally would pass every test above.

    This is the shape the roadmap already records for the security leg's first cut: a control that
    can only reach one outcome is a constant, whichever outcome that is.
    """
    ws = _repo(tmp_path, {"tests/test_a.py": "def test_a():\n    assert False\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests" / "conftest.py").write_text(
        'collect_ignore = ["test_a.py"]\n', encoding="utf-8"
    )
    assert "tests/conftest.py" in tampered_integrity(ws, base, baseline_complete=True)


def test_the_operator_is_TOLD_the_coverage_is_narrowed(tmp_path: Path) -> None:
    """Suppression must not be silent — an evidence gap the operator cannot see is not honest.

    Present-only-when-relevant, the `operator_edits` / `destruction_verdict` convention: an empty
    value would read as "checked, nothing to say".
    """
    ws = _stale_repo(tmp_path)
    ctx: Any = SimpleNamespace(workspace=ws, operator_sanctioned={})
    stale: Any = {"integrity_baseline": {"tests/test_acceptance.py": "h"}}
    assert "integrity_baseline_partial" in tamper_verdict(ctx, stale)

    fresh: Any = {
        "integrity_baseline": {"tests/test_acceptance.py": "h"},
        "integrity_enumerator": INTEGRITY_ENUMERATOR,
    }
    assert "integrity_baseline_partial" not in tamper_verdict(ctx, fresh), (
        "a current baseline must not carry the narrowed-coverage note"
    )


# --- B. hygiene's autofix must not rewrite what the tamper guard judges ------------------


def test_hygiene_never_rewrites_a_baselined_or_SANCTIONED_test() -> None:
    """The filter excluded `ctx.protected_tests` — the AUTHORSHIP set — beneath a comment saying
    the point was to protect BASELINED tests. They are different sets, and neither contains a human
    sanction.

    So `ruff format` normalised an operator-approved amendment (`'`->`"`, `==` spacing), the
    `integrity_hash` moved off the content the human approved, the content-pinned excuse stopped
    matching, and the run parked `tests_tampered` — terminal, on a change the operator had
    explicitly authorised, defeating the amendment path built for a measured 3-run/4M-token
    deadlock. `route_after_hygiene` returns a rewriting pass straight to `test`, so it is
    same-iteration and deterministic.
    """
    ctx: Any = SimpleNamespace(
        protected_tests={"tests/authored.py"},
        operator_sanctioned={"tests/sanctioned.py": "h"},
    )
    state: Any = {
        "integrity_baseline": {"tests/baselined.py": "h"},
        "tests_baseline": {"tests/tester.py": "h"},
        "proctor_edits": {"tests/repaired.py": "h"},
        "operator_edits": {"tests/approved.py": "h"},
    }
    never = _never_rewrite(ctx, state)
    for path in (
        "tests/authored.py",  # the set it already had
        "tests/baselined.py",  # what the comment CLAIMED it had
        "tests/sanctioned.py",  # process-local human approval
        "tests/approved.py",  # durable human approval (survives rehydrate)
        "tests/repaired.py",
        "tests/tester.py",
    ):
        assert path in never, f"hygiene would reformat {path}, which the tamper guard judges"


# --- C. "pytest refused to start" is not evidence that the suite is strong ---------------


def test_a_run_that_never_COLLECTED_anything_is_not_a_caught_mutation() -> None:
    """pytest exits 4 (usage) and 5 (no tests collected) are NON-ZERO, so `passed is False` — and
    the mutation check read any non-zero exit as "the mutation was caught".

    Reachable because `authored_tests` (from the 3-term `protected_test_paths`) admits non-`.py`
    paths under a `tests` dir, so `pytest tests/fixtures/golden.json ...` exited 4 and a
    rubber-stamp suite with no assertion was promoted from a correct rejection to a VOUCH.
    Read from the recorded `exit_code`, never from pytest's prose.
    """
    assert _never_collected(SimpleNamespace(step_results=[{"exit_code": 4}])) is True
    assert _never_collected(SimpleNamespace(step_results=[{"exit_code": 5}])) is True
    # A genuine failure is still a genuine failure — the contrast that stops an over-broad fix.
    assert _never_collected(SimpleNamespace(step_results=[{"exit_code": 1}])) is False
    assert _never_collected(SimpleNamespace(step_results=[{"exit_code": 0}])) is False
    assert _never_collected(SimpleNamespace(step_results=[])) is False
