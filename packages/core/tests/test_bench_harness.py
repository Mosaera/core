"""Harness gate-resolution, signal extraction, grader parsing, case loading.
Offline — no model, no sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from mosaera_core.bench.cases import load_case
from mosaera_core.bench.grade import GraderOutcome, _parse
from mosaera_core.bench.harness import RunOutcome, _resolve, build_inputs


@dataclass
class FakeInterrupt:
    id: str
    value: dict[str, Any]


def _deliver(reasons: list[str]) -> FakeInterrupt:
    return FakeInterrupt(
        id="i1",
        value={"action": "deliver", "review": "notes", "gate_decision": {"reasons": reasons}},
    )


# --- _resolve: faithful autonomous gate policy ---


def test_resolve_approves_on_empty_reasons() -> None:
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    resume, stop = _resolve([_deliver([])], out)
    assert stop is False and resume["i1"] == {"approve": True}
    assert not out.parked and not out.revised


def test_resolve_denies_with_feedback_on_reviewer_changes() -> None:
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    resume, stop = _resolve([_deliver(["reviewer_requested_changes"])], out)
    assert stop is False
    assert resume["i1"]["approve"] is False and resume["i1"]["feedback"] == "notes"
    assert out.revised is True


def test_resolve_parks_and_stops_on_hard_reasons() -> None:
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    _resume, stop = _resolve([_deliver(["validation_failed"])], out)
    assert stop is True and out.parked is True


def test_resolve_malformed_gate_parks() -> None:
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    bad = FakeInterrupt(id="i1", value={"action": "deliver", "gate_decision": "oops"})
    _, stop = _resolve([bad], out)
    assert stop is True and out.parked is True


# --- terminal gate visibility (ADR-0078) ---
#
# A parking gate visit never resumes, so the gate node never returns `gate_decision` into state.
# Measured cost before this: `gate_reasons` was [] on all 526 instrumented scorecards and
# `critic_vetoed`, derived from it, was False on 643/643 — always False BY CONSTRUCTION, because a
# veto causes the very park whose evidence is thrown away.


def test_resolve_captures_the_terminal_gate_decision_on_park() -> None:
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    _resume, stop = _resolve([_deliver(["validation_failed", "oracle_unverified"])], out)
    assert stop is True and out.parked is True
    assert out.terminal_gate_decision == {"reasons": ["validation_failed", "oracle_unverified"]}
    assert out.terminal_reasons == ["validation_failed", "oracle_unverified"]


def test_capture_never_mutates_the_frozen_classifier_input() -> None:
    """THE safety property — the whole reason capture rides a separate field.

    `classify_outcome` reads `final["gate_decision"]["reasons"]` and buckets `iteration_limit` as
    THRASH. If the captured decision were merged into `final` (as the live runner does for its own,
    unscored purposes), previously-`honest_park` runs would silently reclassify and the frozen
    clean-conclusion headline would move. `iteration_limit` is used here deliberately: it is the
    exact reason whose leakage would do that. Invariance here is structural, not empirical — bench
    runs are stochastic, so this test IS the evidence.
    """
    from mosaera_core.bench.reliability import HONEST_PARK, classify_outcome, classify_park_cause

    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    _resolve([_deliver(["iteration_limit", "validation_failed"])], out)

    assert out.terminal_reasons == ["iteration_limit", "validation_failed"]  # measurement sees it
    assert out.final == {}  # ...and the classifier's input is byte-identical to construction
    assert classify_outcome(
        out.final, errored=False, acceptance_failed=False, max_iterations=3
    ) == (HONEST_PARK)
    assert classify_park_cause(out.final, max_iterations=3) == "parked"


def test_critic_veto_is_visible_on_a_parked_run() -> None:
    """Pins the 643/643 defect: ADR-0065's arc metric was structurally zero.

    `bench/cli.py` derives `critic_vetoed` as `"critic_vetoed" in gate_reasons`, and a veto is a
    downgrade that PARKS — so the one outcome the metric exists to count was the one it could
    never see.
    """
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    _resolve([_deliver(["critic_vetoed"])], out)
    assert "critic_vetoed" in out.terminal_reasons
    # The committed decision still shows nothing — that is the bug this routes around, not a fix to
    # the graph. Any pre-ADR-0078 scorecard's `critic_vetoed: False` means UNMEASURED, not no-veto.
    committed = (out.final.get("gate_decision") or {}).get("reasons") or []
    assert "critic_vetoed" not in committed


def test_last_gate_visit_wins_across_a_deny_replan_loop() -> None:
    # A deny→replan run revisits the gate. The earlier visit RESUMED (so it also committed a now
    # stale decision to state); the last one is the visit that actually terminated the drive.
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    _resolve([_deliver(["reviewer_requested_changes"])], out)
    assert out.terminal_reasons == ["reviewer_requested_changes"]
    _resolve([_deliver(["validation_failed"])], out)
    assert out.terminal_reasons == ["validation_failed"]
    assert out.revised is True and out.parked is True


def test_terminal_reasons_falls_back_to_the_committed_decision() -> None:
    # Nothing captured (e.g. a resumed/guided drive that DID commit): use what state has.
    out = RunOutcome(
        final={"gate_decision": {"reasons": ["oracle_unverified"]}}, rollup={}, elapsed_s=0.0
    )
    assert out.terminal_reasons == ["oracle_unverified"]


def test_terminal_reasons_is_empty_when_nothing_was_captured_or_committed() -> None:
    # A crashed run that never reached a gate — no reasons, and no exception.
    assert RunOutcome(final={}, rollup={}, elapsed_s=0.0).terminal_reasons == []
    assert (
        RunOutcome(final={"gate_decision": None}, rollup={}, elapsed_s=0.0).terminal_reasons == []
    )


# --- build_inputs: extract objective signals from a run + grade ---


def test_build_inputs_extracts_signals() -> None:
    final = {
        "plan": "1. do it",
        "design": "## Approach\nx",
        "diff": "+++ b/todo/__init__.py\n+++ b/tests/test_todo.py\n+++ b/README.md\n",
        "validation_plan": {"project_type": "python-pytest"},
        "gate_decision": {"reviewer_verdict": "APPROVE"},
        "tests_passed": True,
        "iteration": 3,
        "approved": True,
    }
    run = RunOutcome(
        final=final, rollup={"usd": 0.01, "total_tokens": 1234, "calls": 9}, elapsed_s=5
    )
    grader = GraderOutcome(ran=True, passed=7, failed=1, errors=0, output="")

    from mosaera_core.bench.cases import BenchCase

    d = Path()  # dir fields are unused by build_inputs; dummy Paths avoid a type-ignore
    case = BenchCase(
        id="MCB-01", brief="b", grader_dir=d, seed_dir=d, reference_dir=d, max_iterations=6
    )
    si = build_inputs(run, grader, case)

    assert si.kind == "python-cli"  # from the case
    assert si.has_plan and si.has_design
    assert si.delivered_test_files == 1  # only tests/test_todo.py counts
    assert si.validation_ran_tests is True  # project_type "python-pytest" (not "pytest")
    assert si.reviewer_verdict == "APPROVE"
    assert si.grader_passed == 7 and si.grader_total == 8
    assert si.total_tokens == 1234 and si.approved is True and si.iteration == 3


# --- grader summary parsing ---


def test_grade_parse_summary() -> None:
    assert _parse("3 passed, 1 failed in 0.2s") == (3, 1, 0)
    assert _parse("8 passed in 1.1s") == (8, 0, 0)
    assert _parse("2 passed, 1 error in 0.1s") == (2, 0, 1)


def test_grader_outcome_helpers() -> None:
    assert GraderOutcome(True, 8, 0, 0, "").all_passed is True
    assert GraderOutcome(True, 6, 2, 0, "").all_passed is False
    assert GraderOutcome(False, 0, 0, 0, "").all_passed is False
    assert GraderOutcome(True, 6, 2, 0, "").total == 8


# --- case loading ---


def test_load_mcb01_case() -> None:
    case = load_case("MCB-01")
    assert "todo" in case.brief.lower()
    assert case.grader_dir.name == "grader"
    assert (case.grader_dir / "test_acceptance.py").is_file()


def test_load_unknown_case_raises() -> None:
    with pytest.raises(ValueError, match="unknown benchmark case"):
        load_case("does-not-exist")


def test_load_mcb02_case_reads_case_toml() -> None:
    case = load_case("MCB-02")
    assert case.kind == "static-site"  # from case.toml
    assert case.max_iterations == 4 and case.budget_tokens == 300_000  # per-case budgets
    assert (case.grader_dir / "test_acceptance.py").is_file()
    assert "static" in case.brief.lower() or "html" in case.brief.lower()


# --- `#64` guided posture: write gates, and the promise that MCB is unchanged. ---------------


def test_the_headless_default_is_unchanged() -> None:
    """MCB and the standing baseline were measured with write gates OFF. That default is the
    thing this feature must not move: a guided posture that silently became the default would
    change what every historical number means."""
    import inspect

    from mosaera_core.bench.harness import run_case

    params = inspect.signature(run_case).parameters
    assert params["approve_writes"].default is False
    assert params["operator"].default is None
    # And a headless run records no proposals, so nothing reading MCB sees a new field populated.
    assert RunOutcome(final={}, rollup={}, elapsed_s=0.0).write_proposals == []


def test_a_write_gate_is_answered_by_the_operator_not_auto_approved() -> None:
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    intr = FakeInterrupt(
        id="w1",
        value={
            "action": "write_file",
            "path": "src/cli.py",
            "summary": "Coder wants to write src/cli.py (10 chars)",
            "content": "x = 1\n",
        },
    )
    resume, stop = _resolve([intr], out)
    assert stop is False
    assert resume["w1"] == {"approve": True}  # permissive default
    assert len(out.write_proposals) == 1
    assert out.write_proposals[0]["path"] == "src/cli.py"
    assert out.write_proposals[0]["outcome"] == "approve"


def test_a_denying_operator_refuses_the_write_and_it_is_recorded() -> None:
    from mosaera_core.bench.operator import OperatorDecision

    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    intr = FakeInterrupt(
        id="w1",
        value={"action": "write_file", "path": "src/cli.py", "summary": "", "content": "x = 1\n"},
    )
    resume, _ = _resolve([intr], out, None, lambda _p: OperatorDecision("deny", "not like that"))
    assert resume["w1"] == {"approve": False, "feedback": "not like that"}
    assert out.write_proposals[0]["outcome"] == "deny"


def test_write_gates_do_not_disturb_the_deliver_gate_capture() -> None:
    # The two interrupt kinds share one resolver; a write gate must not clear or overwrite the
    # terminal gate decision the frozen classifier's fallback depends on.
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)
    write = FakeInterrupt(
        id="w1",
        value={"action": "write_file", "path": "a.py", "summary": "", "content": "x = 1\n"},
    )
    deliver = FakeInterrupt(
        id="d1",
        value={"action": "deliver", "gate_decision": {"action": "require_human", "reasons": ["x"]}},
    )
    _resolve([write, deliver], out)
    assert out.terminal_gate_decision == {"action": "require_human", "reasons": ["x"]}
    assert out.parked is True
