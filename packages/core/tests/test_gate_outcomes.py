"""The gate says what your answer will DO (ADR-0082 §1, F61) — offline sentinels.

F61, HIGH: at the iteration cap, "Send back to revise" terminated the run and discarded the
operator's notes. ~1.1M tokens of correct work thrown away, HTTP 200, and nothing in the payload or
the UI said this would happen. F63 added a second exception (a tamper verdict is independently
terminal); the gate-stall breaker is a third, and it fires *as a consequence of the denial itself*.

The tests below are in two halves, and the second half is the one that matters long-term: it pins
that the sentence shown to the operator and the branch the engine actually takes cannot disagree.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mosaera_core.graph._gate_outcomes import (
    deny_finalizes,
    escalation_finalizes,
    escalation_outcomes,
    gate_outcomes,
)
from mosaera_core.graph.nodes_review import route_after_gate


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"iteration": 2, "gate_decision": {"reasons": []}}
    base.update(over)
    return base


def _ids(state: dict[str, Any], max_iter: int = 8, **kw: Any) -> list[str]:
    return [o.id for o in gate_outcomes(state, max_iter=max_iter, **kw)]


def _by_id(state: dict[str, Any], oid: str, max_iter: int = 8, **kw: Any) -> Any:
    return next(o for o in gate_outcomes(state, max_iter=max_iter, **kw) if o.id == oid)


# --- an option that cannot function is not offered ---------------------------------------------


def test_at_the_cap_there_is_no_send_back_option() -> None:
    """THE F61 pin. The run that discarded 1.1M tokens was shown a revision channel that could
    not revise anything."""
    ids = _ids(_state(iteration=8), max_iter=8)
    assert "send_back" not in ids
    assert ids == ["approve", "end_run"]


def test_the_terminal_denial_says_WHY_and_that_notes_are_discarded() -> None:
    out = _by_id(_state(iteration=8), "end_run", max_iter=8)
    assert "revision budget is spent" in out.consequence
    assert "NOT acted on" in out.consequence  # the part F61 was actually about


def test_every_finalizing_condition_removes_the_send_back() -> None:
    """Asserted per condition, not once — F63's whole point was that the exceptions accumulate
    and each new one was invisible."""
    for key, val in (
        ("stalled", True),
        ("plan_unworkable_reason", "no workable plan"),
        ("give_up_reason", "concluded"),
    ):
        ids = _ids(_state(**{key: val}))
        assert "send_back" not in ids, key
        assert "end_run" in ids, key


def test_with_budget_remaining_the_send_back_is_offered_and_counts_it() -> None:
    out = _by_id(_state(iteration=2), "send_back", max_iter=8)
    assert out.effect == "send_back"
    assert "revision 3 of 8" in out.consequence


# --- the third exception: a denial that terminates BECAUSE it is a denial -----------------------


def test_a_denial_that_would_trip_the_gate_stall_says_so() -> None:
    """#67/ADR-0069: deny the same reasons once too often and the run concludes. An operator can
    end a run in good faith by using the button labelled 'send back'."""
    from mosaera_core.graph._gate_outcomes import stall_signature
    from mosaera_core.progress import fingerprint

    # ADR-0092 amends ADR-0069: the breaker fingerprints reason CLASSES, so the prior fingerprint
    # must be built the same way. Deriving it via `stall_signature` rather than hand-writing the
    # string is the point — a test that hard-codes the fingerprint input is a second origin.
    reasons = ["reviewer_requested_changes"]
    fp = fingerprint("gate", stall_signature(reasons))
    state = _state(gate_decision={"reasons": reasons}, stall_by_kind={"gate": [fp, 1]})
    out = _by_id(state, "send_back", gate_stall_limit=2)
    assert out.effect == "end_run"  # it is NOT a send-back, whatever it is called
    assert "final attempt" in out.label
    assert "concludes the run" in out.consequence


def test_a_changed_reason_resets_and_the_send_back_is_normal_again() -> None:
    """Progress through blockers must not be punished — bump_stall resets on a different reason,
    and the prediction has to agree or it would cry wolf."""
    from mosaera_core.progress import fingerprint

    state = _state(
        gate_decision={"reasons": ["security_findings"]},
        stall_by_kind={"gate": [fingerprint("gate", "reviewer_requested_changes"), 1]},
    )
    assert _by_id(state, "send_back", gate_stall_limit=2).effect == "send_back"


def test_the_prediction_is_silent_when_stall_detection_is_off() -> None:
    from mosaera_core.progress import fingerprint

    fp = fingerprint("gate", "reviewer_requested_changes")
    state = _state(
        gate_decision={"reasons": ["reviewer_requested_changes"]},
        stall_by_kind={"gate": [fp, 1]},
    )
    out = _by_id(state, "send_back", gate_stall_limit=2, stall_detection=False)
    assert out.effect == "send_back"


# --- approve is labelled honestly ---------------------------------------------------------------


def test_approving_over_blocking_reasons_is_labelled_an_override() -> None:
    """ADR-0082: 'override last and always labelled as an override'."""
    out = _by_id(_state(gate_decision={"reasons": ["validation_failed"]}), "approve")
    assert out.override is True
    assert out.recommended is False  # an override is never the recommendation
    assert "override" in out.consequence


def test_a_clean_gate_recommends_delivering() -> None:
    out = _by_id(_state(), "approve")
    assert out.override is False
    assert out.recommended is True


def test_exactly_one_option_is_recommended() -> None:
    """A gate that recommends two things has recommended nothing."""
    for state in (
        _state(),
        _state(gate_decision={"reasons": ["validation_failed"]}),
        _state(iteration=8),
        _state(stalled=True),
    ):
        rec = [o for o in gate_outcomes(state, max_iter=8) if o.recommended]
        assert len(rec) <= 1, state


# --- THE anti-drift pin -------------------------------------------------------------------------


def test_the_sentence_and_the_routing_can_never_disagree() -> None:
    """The test that keeps this fix from rotting.

    F61 existed because "when does a denial terminate?" was encoded in `route_after_gate` and
    nowhere else, while the UI assumed something different. Both now read `deny_finalizes`, and
    this asserts that across EVERY combination of the routing predicates: if the gate told the
    operator their denial ends the run, the router must finalize — and vice versa.
    """
    ctx: Any = SimpleNamespace(max_iter=8)
    flags = ("stalled", "plan_unworkable_reason", "give_up_reason")
    for bits in range(1 << len(flags)):
        for iteration in (0, 7, 8, 99):
            state = _state(iteration=iteration)
            for i, key in enumerate(flags):
                if bits & (1 << i):
                    state[key] = True if key == "stalled" else "reason"
            told_operator_it_ends = "send_back" not in _ids(state)
            router_finalizes = route_after_gate(ctx, state) == "deliver"  # type: ignore[arg-type]
            assert told_operator_it_ends == router_finalizes, state
            # And the reason string is non-empty exactly when it finalizes.
            assert bool(deny_finalizes(state, 8)) == router_finalizes, state


def test_an_approved_gate_still_delivers() -> None:
    """The routing refactor must not touch the approve path."""
    ctx: Any = SimpleNamespace(max_iter=8)
    assert route_after_gate(ctx, _state(approved=True)) == "deliver"  # type: ignore[arg-type]
    assert route_after_gate(ctx, _state(approved=False)) == "plan"  # type: ignore[arg-type]


# --- The ESCALATION gate: #68, the same rule one gate over ------------------------------------
#
# F62: a run stopped correctly and "the operator got an honest stop and nothing to answer, which
# was the point of building it". Two causes — a predicate evaluated twice against evolving state,
# and this gate never populating `outcomes` even though the machinery was built and generic.


def _fin(**over: Any) -> str:
    args: dict[str, Any] = {
        "escalations": 1,
        "max_escalations": 3,
        "budget_short": False,
        "projected_trip": False,
        "oracle_conflict": False,
    }
    args.update(over)
    return escalation_finalizes(**args)


def test_an_escalation_that_can_continue_finalizes_nothing() -> None:
    assert _fin() == ""


def test_each_forcing_term_names_itself() -> None:
    # A string, not a bool: the operator is shown this, so "why" has to survive the call.
    assert "escalation budget" in _fin(escalations=4)
    assert "remaining iterations" in _fin(budget_short=True)
    assert "too slowly to converge" in _fin(projected_trip=True)
    assert "may not edit" in _fin(oracle_conflict=True)


def test_the_honest_stop_is_always_offered() -> None:
    """ADR-0006/ADR-0082: present by CONSTRUCTION, not by the generator's good manners."""
    for over in ({}, {"oracle_conflict": True}, {"budget_short": True}, {"escalations": 9}):
        ids = [o.id for o in escalation_outcomes(finalizes=_fin(**over), finalizes_if_amended="")]
        assert "stop_honestly" in ids


def test_a_continuable_escalation_offers_a_real_revision_channel() -> None:
    send = next(
        o for o in escalation_outcomes(finalizes="", finalizes_if_amended="") if o.id == "send_back"
    )
    assert send.effect == "send_back"
    assert send.recommended
    assert "continues" in send.consequence


def test_send_back_tells_the_truth_when_the_run_will_end_anyway() -> None:
    """The F61 shape one gate over: never offer a revision channel that is really an exit."""
    forced = _fin(budget_short=True)
    send = next(
        o
        for o in escalation_outcomes(finalizes=forced, finalizes_if_amended=forced)
        if o.id == "send_back"
    )
    assert send.effect == "end_run"  # what the ENGINE does, not what the button says
    assert "ends without delivering" in send.consequence
    assert not send.recommended


def test_amending_is_recommended_only_when_it_leaves_a_way_forward() -> None:
    amendable = {"tests": ["tests/test_x.py::test_a"]}
    # The conflict is the ONLY thing forcing a stop → authorising it clears the way.
    clears = escalation_outcomes(
        finalizes=_fin(oracle_conflict=True), finalizes_if_amended="", amendable=amendable
    )
    amend = next(o for o in clears if o.id == "amend_tests")
    assert amend.recommended and "run continues" in amend.consequence

    # The budget is ALSO spent → amending is still worth offering (it fixes the bar for next time)
    # but it must not pretend to rescue this run.
    forced = _fin(budget_short=True, oracle_conflict=True)
    stuck = escalation_outcomes(
        finalizes=forced, finalizes_if_amended=_fin(budget_short=True), amendable=amendable
    )
    amend2 = next(o for o in stuck if o.id == "amend_tests")
    assert not amend2.recommended
    assert "this run still ends" in amend2.consequence


def test_no_amend_option_without_an_amendable_test() -> None:
    # `amendable_withheld` is a REASON, not an option — offering an amend the engine would refuse
    # is the same defect as offering a revision channel that exits.
    ids = [o.id for o in escalation_outcomes(finalizes="", finalizes_if_amended="")]
    assert "amend_tests" not in ids


def test_regressions_get_their_own_option_naming_the_count() -> None:
    outs = escalation_outcomes(
        finalizes="", finalizes_if_amended="", regressions=["t.py::a", "t.py::b"]
    )
    fix = next(o for o in outs if o.id == "fix_regressions")
    assert "2 test(s)" in fix.label
    assert "what IT broke" in fix.consequence


def test_option_ids_are_unique_so_the_api_can_validate_one() -> None:
    # `RunSession.approve` rejects an option_id not in the offered set; duplicates would make the
    # operator's recorded choice ambiguous.
    outs = escalation_outcomes(
        finalizes="",
        finalizes_if_amended="",
        amendable={"tests": ["t.py::a"]},
        regressions=["t.py::b"],
    )
    ids = [o.id for o in outs]
    assert len(ids) == len(set(ids))
