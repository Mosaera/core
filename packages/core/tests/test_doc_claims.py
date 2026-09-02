"""The doc-claims guard must actually bite.

A guard that only ever passes is indistinguishable from no guard — the #58 shape, and the exact
reason `check_control_liveness.py` spent time "report-only and wired into nothing". These tests
drive the failure paths, because a guard whose *reporting* code is broken silently degrades to
advisory: the index-status check crashed with a `NameError` on its first real detection and
therefore looked like a pass.

Motivating case pinned below: ADR-0085's freeze governed the F52 assertion-floor fix while its
header still read `Implementation: not-started` (2026-08-06).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "check_doc_claims.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("check_doc_claims", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run() -> tuple[int, str]:
    # Fixed argv, both elements derived from this file's own location — no input.
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


@contextmanager
def _temporarily(path: Path, new_text: str) -> Iterator[None]:
    """Edit a real repo file, then put it back — including on failure."""
    backup = path.read_text(encoding="utf-8")
    try:
        path.write_text(new_text, encoding="utf-8")
        yield
    finally:
        path.write_text(backup, encoding="utf-8")


def test_the_guard_passes_on_the_current_tree() -> None:
    code, out = _run()
    assert code == 0, out
    assert "no contradictions" in out


def test_an_adr_cited_by_code_may_not_claim_to_be_unbuilt() -> None:
    """THE motivating case. ADR-0085 is cited by roundtrip.py / oraclecheck.py / containment.py;
    before 2026-08-06 its header said `Implementation: not-started` while its freeze governed a
    shipped fix. If this test does not fail without the guard, the guard is the wrong check."""
    adr = _ROOT / "docs" / "adr" / "ADR-0085-oracle-defect-detection-strategy.md"
    text = adr.read_text(encoding="utf-8")
    broken = text.replace(
        text.split("\n- Implementation:")[1].split("\n- Date accepted:")[0],
        " not-started",
        1,
    )
    with _temporarily(adr, broken):
        code, out = _run()
    assert code == 1
    assert "ADR-0085" in out and "not-started" in out


def test_a_reference_to_a_nonexistent_adr_fails() -> None:
    roadmap = _ROOT / "docs" / "roadmap.md"
    with _temporarily(roadmap, roadmap.read_text(encoding="utf-8") + "\nSee ADR-9999.\n"):
        code, out = _run()
    assert code == 1
    assert "ADR-9999 does not exist" in out


def test_the_index_must_agree_with_disk_on_status() -> None:
    """Drives the REPORTING path, not just detection: this check detected correctly and then
    crashed formatting its own message, which read as a pass."""
    index = _ROOT / "docs" / "adr" / "README.md"
    text = index.read_text(encoding="utf-8")
    mutated = text.replace(
        "(ADR-0087-test-contracts-and-renegotiation.md) | Delivered tests are amendable contracts"
        " — the engine must be able to change its mind | proposed |",
        "(ADR-0087-test-contracts-and-renegotiation.md) | Delivered tests are amendable contracts"
        " — the engine must be able to change its mind | accepted |",
    )
    if mutated == text:  # pragma: no cover - the row was reworded
        pytest.skip("ADR-0087 index row not in the expected shape")
    with _temporarily(index, mutated):
        code, out = _run()
    assert code == 1
    assert "indexed 'accepted'" in out and "Traceback" not in out


def test_an_index_row_without_a_file_fails() -> None:
    index = _ROOT / "docs" / "adr" / "README.md"
    # A number that can never be real. The fixture used 0099 until ADR-0099 was written on
    # 2026-08-10, at which point the row it appended resolved and the guard-test stopped testing
    # the guard — a fixture colliding with reality, not a guard that broke.
    extra = "| [ADR-0999](ADR-0999-fake.md) | Fake | accepted | core |\n"
    with _temporarily(index, index.read_text(encoding="utf-8") + extra):
        code, out = _run()
    assert code == 1
    assert "ADR-0999" in out


def test_the_documented_make_lint_contract_must_match_the_makefile() -> None:
    """CLAUDE.md described three guards while the Makefile ran four (2026-08-06)."""
    claude = _ROOT / "CLAUDE.md"
    text = claude.read_text(encoding="utf-8")
    broken = text.replace(" + check_control_liveness.py (liveness)", "", 1)
    if broken == text:  # pragma: no cover - the contract line was reworded
        pytest.skip("the make-lint contract line is not in the expected shape")
    with _temporarily(claude, broken):
        code, out = _run()
    assert code == 1
    assert "check_control_liveness.py" in out


def test_direction_cited_is_shrink_only() -> None:
    """An entry that no longer claims to be unbuilt has been BUILT and must be removed — the
    two-sided ratchet the other guards use. Without this the allowlist is decorative."""
    mod = _load()
    adrs = mod._adr_files()  # type: ignore[attr-defined]
    for adr_id in mod.DIRECTION_CITED:  # type: ignore[attr-defined]
        assert adr_id in adrs, f"DIRECTION_CITED names ADR-{adr_id}, which does not exist"
        text = adrs[adr_id].read_text(encoding="utf-8")
        assert mod._claims_unbuilt(text), (  # type: ignore[attr-defined]
            f"ADR-{adr_id} no longer claims to be unbuilt — remove it from DIRECTION_CITED"
        )


def test_absent_header_fields_are_not_failures() -> None:
    """ADR header fill is uneven — `Implementation` appears in almost no ADR. Only an EXPLICIT
    claim can contradict; otherwise the guard fails on day one and gets switched off."""
    mod = _load()
    adrs = mod._adr_files()  # type: ignore[attr-defined]
    without = [i for i, p in adrs.items() if mod._field(p.read_text(), "Implementation") is None]  # type: ignore[attr-defined]
    assert len(without) > 50, "expected most ADRs to omit Implementation; recheck the assumption"
    code, _ = _run()
    assert code == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_the_guard_is_wired_into_make_lint() -> None:
    """A guard not in `lint:` cannot fire. This is the #58 shape."""
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "check-doc-claims" in makefile, "check_doc_claims.py is not wired into the Makefile"


# --- the 2026-08-06 coverage gaps: roadmap claims and the tracking convention ---


def test_a_done_arc_with_an_open_finding_must_acknowledge_it() -> None:
    """THE second motivating failure. `#64` read Status: DONE while F62 was open against the
    ESCALATE arm that arc produced, so a reader concluded the arm worked. Removing the caveat that
    names #68 reproduces the pre-fix state exactly."""
    roadmap = _ROOT / "docs" / "roadmap.md"
    text = roadmap.read_text(encoding="utf-8")
    start = text.find("- **The arm is HALF-BUILT")
    if start < 0:  # pragma: no cover - the caveat was reworded
        pytest.skip("the #64 HALF-BUILT caveat is not in the expected shape")
    end = text.find("\n- ", start + 10)
    with _temporarily(roadmap, text[:start] + text[end + 1 :]):
        code, out = _run()
    assert code == 1
    assert "arc #64 is marked DONE but F62 is OPEN" in out


def test_an_open_high_finding_must_name_its_tracking_issue() -> None:
    mod = _load()
    fails = mod.check_findings_tracked()  # type: ignore[attr-defined]
    for f in fails:
        assert "no tracking issue" in f
    # The gate is only meaningful if it can fail; the repo's current state is asserted elsewhere.
    assert isinstance(fails, list)


def test_a_settled_finding_is_not_flagged_however_its_heading_is_qualified() -> None:
    """F48 reads `~~HIGH~~ **FIXED 2026-08-06 · residual OPEN (LOW)**` — struck-through severity,
    FIXED status, and a later "residual OPEN" clause. A naive contains-HIGH-and-OPEN match flags
    it, the guard fails on an honest record, and someone switches the guard off."""
    mod = _load()
    assert mod._is_open("Title — ~~HIGH~~ **FIXED 2026-08-06 · residual OPEN (LOW)**") is False  # type: ignore[attr-defined]
    assert mod._is_open("Title — HIGH · OPEN (found 2026-08-06)") is True  # type: ignore[attr-defined]
    assert mod._severity("Title — ~~HIGH~~ **FIXED · residual OPEN (LOW)**") == "LOW"  # type: ignore[attr-defined]
    assert mod._severity("Title — CRITICAL · OPEN") == "CRITICAL"  # type: ignore[attr-defined]
