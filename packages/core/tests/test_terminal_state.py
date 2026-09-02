"""Layer 2 must judge the TERMINATING gate visit, not a blank field (ADR-0078's fourth residual).

`gate_node` calls `request_approval` (which interrupts) before its only returns, so an autonomous
run that parks and is never resumed leaves nothing it computed in the checkpoint —
`gate_decision`, `claim_dispositions`, `claims`. ADR-0078 measured that (`gate_reasons == []` on all
526 instrumented runs) and fixed the bench's *measurement* reads via a payload capture. It listed
three deferred residuals. **Layer 2's eligibility read was a fourth it did not enumerate**, and it
gates the one mechanism that can ship code unattended: 2,049 stored scorecards, 544 honest parks,
**zero** ever eligible.

`terminal_state` is the composed view — `final`, with the terminating visit's facts layered on.
Readers that need the terminating truth take it; **the frozen classifier keeps `final`**, which is
ADR-0078's load-bearing constraint and the reason this is not a writer-side fix.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.bench.harness import RunOutcome
from mosaera_core.disposition import convertible_decline_reason, convertible_park_class

_PARKED_FINAL: dict[str, Any] = {
    # What the checkpoint actually holds for a run parked at the gate: everything the nodes BEFORE
    # the gate wrote, and nothing the gate node computed.
    "tests_passed": True,
    "iteration": 1,
    "give_up_reason": "",
    "authored_tests": ["tests/test_acceptance.py"],
    "test_output": "FAILED tests/test_acceptance.py::test_shape\n1 failed, 3 passed\n",
    "integrity_baseline": {"tests/test_old.py": "h1"},
}

_TERMINAL_GATE = {
    "action": "require_human",
    "reasons": ["oracle_unverified"],
    "tests_passed": True,
    "unsatisfied_claims": [],
}


def _run(**kw: Any) -> RunOutcome:
    out = RunOutcome(final=dict(_PARKED_FINAL), rollup={}, elapsed_s=0.0)
    for k, v in kw.items():
        setattr(out, k, v)
    return out


def test_a_parked_run_is_invisible_to_layer_2_through_final() -> None:
    """The defect, reproduced. `final` alone makes a convertible park look like no park at all."""
    run = _run(terminal_gate_decision=dict(_TERMINAL_GATE))
    assert convertible_park_class(run.final) is None
    assert "no blocking gate reason" in convertible_decline_reason(run.final), (
        "the decline should be the plausible-sounding wrong answer its own docstring warns about"
    )


def test_terminal_state_makes_the_same_run_visible() -> None:
    """The fix. Same run, same predicates, the terminating visit's decision layered on."""
    run = _run(terminal_gate_decision=dict(_TERMINAL_GATE))
    assert convertible_park_class(run.terminal_state) == "oracle_unverified"


def test_terminal_state_falls_back_to_the_committed_decision() -> None:
    """An approved run captures nothing — `final`'s own values must survive untouched.

    Same fallback semantics `terminal_reasons` already documents: correct for an approved run
    (reasons empty either way) and for a crash that never reached a gate.
    """
    run = _run()
    run.final = {**_PARKED_FINAL, "gate_decision": {"reasons": ["oracle_unverified"]}}
    assert run.terminal_state["gate_decision"] == {"reasons": ["oracle_unverified"]}


def test_terminal_state_never_mutates_final() -> None:
    """The classifier's input must be untouched — ADR-0078's constraint, pinned.

    Merging the capture into `final` would let `classify_outcome` see `iteration_limit` on parks
    and flip `honest_park -> thrash_park`, silently moving the clean-conclusion headline. That
    classifier is FROZEN (ADR-0069) and already compensates via `rode_to_cap`.
    """
    run = _run(terminal_gate_decision=dict(_TERMINAL_GATE))
    before = dict(run.final)
    _ = run.terminal_state
    assert run.final == before
    assert "gate_decision" not in run.final


def test_the_claim_evidence_is_captured_too() -> None:
    """`claim_dispositions` and `claims` ride the same payload and were never captured.

    That is why `unsatisfied_claim_kinds` recorded `{}` on a parked card while the claim ids
    beside it were populated — a declared-but-unpopulated field (F74's shape) on a field added
    hours earlier, by me.
    """
    run = _run(
        terminal_gate_decision=dict(_TERMINAL_GATE),
        terminal_claim_dispositions=[{"claim_id": "c1", "verdict": "failed"}],
        terminal_claims=[{"id": "c1", "oracle_kind": "acceptance_test"}],
    )
    state = run.terminal_state
    assert state["claim_dispositions"] == [{"claim_id": "c1", "verdict": "failed"}]
    assert state["claims"] == [{"id": "c1", "oracle_kind": "acceptance_test"}]

    from mosaera_core.claim_oracles import failed_claim_kinds

    assert failed_claim_kinds(state["claim_dispositions"], state["claims"]) == {
        "acceptance_test": 1
    }
