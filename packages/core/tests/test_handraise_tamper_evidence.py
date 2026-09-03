"""The hand-raise branch must carry its own tamper evidence (red team 2026-08-21, R1 + R2).

`tests_modified` / `tampered_paths` / `destroyed_paths` were written only by `test_node`, and
`implement -> capture -> supervise` never enters it. Every reader — the gate, both disposition arms,
the `tests_unmodified` oracle, the amendment guard — then read an unwritten key's falsy `.get()` as
CLEAN. The red team found it twice: as a vacuous exclusion letting a tampering producer reach the
operator-facing ask, and then, after that was patched AT THE READER, as both an over-block (the
patch killed the ask on the branch #68 exists to serve) and a live under-block (a stale verdict from
an earlier iteration, trusted after the producer tampered).

Two rounds, one defect class, one control — the STOP rule, escalated to this: put the evidence on
the branch. `capture_node` computes it fresh immediately before `supervise`, which closes the
over-block (the keys are PRESENT) and the under-block (they are FRESH) with the same change,
because they were always the same bug.

These tests drive the REAL `capture_node` against a REAL workspace. That is the point: the existing
`capture_node` tests in `test_graph_build.py` use a `SimpleNamespace` ctx with no workspace, so they
exercise the fail-closed path and would stay green if this never worked at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.escalate_arm import ask_withheld_reason
from mosaera_core.testintegrity import integrity_baseline
from mosaera_core.tools.repo import Workspace

_PROTECTED = "tests/test_contract.py"
_ORIGINAL = "def test_row():\n    assert render() == 'a,b'\n"


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    """A real git workspace — `destroyed_paths` diffs against HEAD, so a bare directory would
    silently exercise the fail-closed path and prove nothing."""
    import subprocess

    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def run(*a: str) -> None:
        subprocess.run(a, cwd=tmp_path, check=True, capture_output=True)  # noqa: S603

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")
    return Workspace(root=tmp_path, run_id="t", branch="b")


def _capture(ws: Workspace, state: dict[str, Any]) -> dict[str, Any]:
    """The real `capture_node`, with the minimum ctx it actually touches."""
    from mosaera_core.graph import nodes_plan

    ctx = SimpleNamespace(
        workspace=ws,
        operator_sanctioned={},
        coder_validation={"output": "1 failed", "tree_hash": ws.tree_hash()},
    )
    return nodes_plan.capture_node(ctx, state)  # type: ignore[arg-type]


def _handraise_state(ws: Workspace) -> dict[str, Any]:
    return {
        "messages": [],
        "integrity_baseline": integrity_baseline(ws),
        "authored_tests": [],
    }


def test_capture_records_a_CLEAN_verdict_so_the_ask_is_admitted() -> None:
    """The over-block, closed. A clean hand-raise is the case #68 exists for; before this it was
    withheld because the keys were absent and absence is (correctly) read as UNKNOWN."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ws = _ws(Path(td), {_PROTECTED: _ORIGINAL})
        out = _capture(ws, _handraise_state(ws))

    assert out["tests_modified"] is False
    assert out["tampered_paths"] == []
    assert "destroyed_paths" in out, "absence is UNKNOWN — a clean run must say so positively"


def test_capture_CATCHES_a_producer_that_tampered_before_raising_its_hand() -> None:
    """The security hole R1 found, closed at the source rather than at the reader."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ws = _ws(Path(td), {_PROTECTED: _ORIGINAL})
        state = _handraise_state(ws)
        # The producer weakens the baselined test, then raises its hand — no `test_node` between.
        (Path(td) / _PROTECTED).write_text("def test_row():\n    assert True\n", encoding="utf-8")
        out = _capture(ws, state)

    assert out["tests_modified"] is True
    assert _PROTECTED in out["tampered_paths"]


def test_the_verdict_is_FRESH_which_is_what_closes_the_stale_under_block() -> None:
    """R2's under-block: a verdict from iteration 1 was trusted after the producer tampered in
    iteration 2, because nothing recomputed it on the way to the stop. `capture_node` runs on every
    implement iteration, so the stale value is overwritten rather than inherited."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ws = _ws(Path(td), {_PROTECTED: _ORIGINAL})
        state = _handraise_state(ws)
        clean = _capture(ws, state)
        assert clean["tests_modified"] is False  # iteration 1: genuinely clean

        # Iteration 2: the coder tampers. A STALE False would survive here; a fresh read cannot.
        (Path(td) / _PROTECTED).write_text("def test_row():\n    pass\n", encoding="utf-8")
        stale_carrying_state = {**state, **clean}
        after = _capture(ws, stale_carrying_state)

    assert after["tests_modified"] is True, "the stale clean verdict was trusted — R2's under-block"


def test_the_ask_follows_the_verdict_end_to_end() -> None:
    """The two halves joined: what `capture_node` writes is what `ask_withheld_reason` reads."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ws = _ws(Path(td), {_PROTECTED: _ORIGINAL})
        state = _handraise_state(ws)
        clean = _capture(ws, state)
        (Path(td) / _PROTECTED).write_text("def test_row():\n    pass\n", encoding="utf-8")
        tampered = _capture(ws, state)

    # A clean hand-raise: no tamper exclusion stands in the way of the ask.
    assert ask_withheld_reason({**clean, "gate_decision": {"reasons": []}}) == ""
    # A tampering one: refused, and named as tamper rather than as "we didn't check".
    assert ask_withheld_reason({**tampered, "gate_decision": {"reasons": []}}) == "a tamper verdict"


def test_an_unreadable_workspace_fails_CLOSED_by_whichever_route() -> None:
    """A torn clone must never yield a clean verdict, and it does not — by a route worth recording.

    `tampered_integrity` does not raise on an unreadable tree; it cannot hash the baselined paths
    and reports them CHANGED. So the failure mode is a positive tamper verdict, not an absent key —
    stricter than the fail-closed wrapper this was written to exercise, which only catches an
    exception. Asserted at the property both routes share, because the property is what matters and
    the route is an implementation detail that has already surprised me once."""
    from mosaera_core.graph import nodes_plan

    broken = Workspace(root=Path("/nonexistent-xyz-torn-clone"), run_id="t", branch="b")
    ctx = SimpleNamespace(workspace=broken, operator_sanctioned={}, coder_validation={})
    out = nodes_plan.capture_node(ctx, {"messages": [], "integrity_baseline": {"a.py": "h"}})  # type: ignore[arg-type]
    assert out.get("tests_modified") is not False, "an unreadable tree must never read as clean"
    assert ask_withheld_reason(out) != "", "and the ask must be withheld, by whichever route"
