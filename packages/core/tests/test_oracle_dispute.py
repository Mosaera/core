"""When two bars disagree about the same tree, the human hears about it.

Measured on the 0.6.3 sweep: 26 over-parks were an authored assertion refusing a tree the hidden
grader passed 100%, and in 24 of them the repository's own standing suite vouched for that tree. The
engine held a second, human-written opinion that was right nearly every time and never consulted it.

The existing ask fired on 0 of those 26 — it needs the CODER to raise its hand, and 19 never tripped
the progress breaker, so they reached no ask path at all and parked as `validation_failed`: a reason
asserting the implementation was at fault, which on these runs is false.

The tests that carry the weight are the ones proving this SPEAKS without ACTING.
"""

from __future__ import annotations

from typing import Any

import pytest
from mosaera_core.oracle_dispute import dispute_note


def _note(**kw: Any) -> str:
    base: dict[str, Any] = dict(
        gate_reasons=["validation_failed"],
        oracle_legs={"standing_suite": True},
        tests_modified=False,
        failing_tests=["tests/test_x.py::test_a"],
        standing_suite=lambda: True,
    )
    base.update(kw)
    return dispute_note(**base)  # type: ignore[arg-type]


def test_the_disagreement_is_reported() -> None:
    got = _note()
    assert "TWO BARS DISAGREE" in got
    assert "tests/test_x.py::test_a" in got, "the operator must be told WHICH assertion refused"


def test_it_reports_the_measured_precision_not_a_certainty() -> None:
    """91%, not 'the bar is wrong'. The 3 misses in 34 are why this asks instead of acting."""
    got = _note()
    assert "91%" in got
    assert "cannot tell which" in got


# --- it must SPEAK, never ACT -----------------------------------------------------------------


def test_it_returns_only_a_string() -> None:
    """ADR-0062: the engine may not mechanically widen the acceptance class. This module's entire
    surface is a sentence — there is no verdict to change and no code path that advances."""
    assert isinstance(_note(), str)


def test_silent_when_no_bar_refused() -> None:
    """A reviewer opinion or a security gap is not two bars disagreeing."""
    assert _note(gate_reasons=["reviewer_requested_changes", "security_unverified"]) == ""
    assert _note(gate_reasons=[]) == ""


def test_silent_when_the_standing_suite_does_NOT_vouch() -> None:
    """No disagreement — both bars refuse. Speaking here would be noise, and noise is how an ask
    channel dies."""
    assert _note(oracle_legs={"standing_suite": False}, standing_suite=lambda: False) == ""


def test_a_TAMPERED_run_is_never_re_read_as_a_wrong_bar() -> None:
    """The coder edited a test. The park stands on its own terms, and offering 'perhaps the bar was
    wrong' is precisely the excuse the tamper guard exists to refuse."""
    assert _note(tests_modified=True) == ""


def test_it_asks_the_standing_suite_when_the_OR_short_circuited_past_it() -> None:
    """`not_evaluated` is the normal recording when `tester_vouched` won the OR first — which is
    exactly the case this exists for, so it must evaluate rather than give up."""
    calls: list[int] = []

    def walk() -> bool:
        calls.append(1)
        return True

    got = dispute_note(
        gate_reasons=["validation_failed"],
        oracle_legs={"standing_suite": "not_evaluated"},
        tests_modified=False,
        failing_tests=["tests/t.py::test_a"],
        standing_suite=walk,
    )
    assert calls == [1], "the walk must happen on a refusal the OR never asked about"
    assert "TWO BARS DISAGREE" in got


def test_a_DELIVERING_run_never_pays_for_the_walk() -> None:
    """The walk is rationed for a reason. No refusal → the callable is never invoked."""
    calls: list[int] = []
    dispute_note(
        gate_reasons=[],
        oracle_legs={},
        tests_modified=False,
        failing_tests=[],
        standing_suite=lambda: calls.append(1) or True,  # type: ignore[func-returns-value]
    )
    assert calls == [], "a clean run walked the workspace for a question nobody asked"


def test_a_walk_that_EXPLODES_stays_silent_rather_than_breaking_the_run() -> None:
    """A diagnostic may never break a run, and for a channel that only speaks, silence is the safe
    direction."""

    def boom() -> bool:
        raise RuntimeError("workspace gone")

    assert _note(oracle_legs={"standing_suite": "not_evaluated"}, standing_suite=boom) == ""


@pytest.mark.parametrize("reason", ["validation_failed", "claim_behavioral_failed"])
def test_both_bar_refusal_reasons_trigger_it(reason: str) -> None:
    assert "TWO BARS DISAGREE" in _note(gate_reasons=[reason])


def test_many_failing_tests_are_summarised_not_dumped() -> None:
    got = _note(failing_tests=[f"tests/t.py::test_{i}" for i in range(9)])
    assert "+6 more" in got


def test_the_dispute_is_captured_at_the_INTERRUPT_seam_not_from_final() -> None:
    """A park never commits the gate node's work, so `final["gate_decision"]` is blank on exactly
    the runs the question exists for. This was shipped wrong once and cost half a sweep's
    observability — the same ADR-0078 residual that made Layer 2 eligible zero times in 2,049
    cards. Pin the seam, not the value.
    """
    from mosaera_core.bench.harness import RunOutcome

    assert "terminal_oracle_dispute" in RunOutcome.__dataclass_fields__, (
        "the dispute must ride the payload-capture seam beside terminal_oracle_legs"
    )
    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0)  # type: ignore[call-arg]
    assert out.terminal_oracle_dispute == "", "absent must read as empty, never as None"
