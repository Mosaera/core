"""`supervise_node` — the escalation interrupt, and what it offers the operator (ADR-0012).

The second of the two human-pause sites (the delivery gate is the other). An agent raises its hand,
or the honest-stop progress breaker trips, and this decides between RE-SCOPING and concluding —
then hands the operator named choices rather than a boolean.

Split out of `nodes_plan.py` when #68's option surface pushed that file past the god-file ceiling.
The seam is cohesive rather than incidental: everything here is about one question — *this run
cannot proceed as planned; what now?* — and the file it left is about producing a plan in the first
place.

Two rules govern the offer, and both exist because their absence was measured:

- **The option set is computed, never authored by a model** (ADR-0082 §1). Every option below is a
  pure function of run state.
- **The sentence shown and the branch taken come from ONE predicate** (`escalation_finalizes`). F61
  was a "send back to revise" button that ended the run and discarded 1.1M tokens of notes; F62 was
  an honest stop with nothing to answer. Both are the same defect — a surface that disagreed with
  the engine — so here it is made impossible by construction rather than by care.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from mosaera_core.escalate_arm import blocking_protected_tests, is_oracle_conflict_escalation
from mosaera_core.graph import _amendment
from mosaera_core.graph._baseline import regression_fields
from mosaera_core.graph._gate_outcomes import escalation_finalizes, escalation_outcomes
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState


def supervise_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # An agent raised its hand — or the honest-stop progress breaker tripped (#56, ADR-0060).
    # Raise an escalation INTERRUPT (a plain LangGraph interrupt — NOT a policy GATED_ACTION)
    # that the runner resolves by run mode: autonomous → Quincy re-scopes (recorded,
    # non-blocking); guided/HA → park for a human. The runner's resume value tells us how to
    # proceed. See ADR-0012.
    trip = state.get("progress_trip") or {}
    if state.get("escalate_reason"):
        kind, reason = "escalate", str(state.get("escalate_reason"))
    elif state.get("blocked_reason"):
        kind, reason = "blocked", str(state.get("blocked_reason"))
    else:  # breaker-origin (#56): the deterministic no-convergence diagnosis
        kind, reason = "no_progress", str(trip.get("reason", "no convergence"))
    # What the operator may AMEND (ADR-0087, #65) — or why they may not (F65).
    amend_fields = _amendment.escalation_amendment_fields(state, ctx)
    # Counter-evidence beside the producer's own story, never instead of it (see `_baseline`).
    regress = regression_fields(state, trip.get("failing_tests"))
    # Computed BEFORE interrupting so the options shown and the routing below read the SAME
    # predicate — see `escalation_finalizes` (#68, ADR-0082 §1).
    budget_short = kind == "no_progress" and ctx.max_iter - state.get("iteration", 0) <= max(
        1, ctx.settings.stall_limit - 1
    )
    projected_trip = bool(trip.get("projected"))
    oracle_conflict = bool(ctx.settings.escalate_arm and is_oracle_conflict_escalation(state))

    def _finalizes(conflict: bool) -> str:
        return escalation_finalizes(
            escalations=state.get("escalations", 0) + 1,
            max_escalations=ctx.max_escalations,
            budget_short=budget_short,
            projected_trip=projected_trip,
            oracle_conflict=conflict,
        )

    finalizes = _finalizes(oracle_conflict)
    resume = (
        interrupt(
            {
                "action": "escalation",
                "kind": kind,
                "reason": reason,
                "summary": state.get("coder_summary", ""),
                "task": state.get("task", ""),
                "iteration": state.get("iteration", 0),
                # The honest-stop's diagnosis rides the payload uncapped (the durable
                # termination_reason column is 80 chars): the count trend + trapping tests.
                "trend": list(trip.get("trend") or []),
                "failing_tests": list(trip.get("failing_tests") or []),
                **regress,
                # Keys appear ONLY when populated: an empty dict is truthy in JS and crashed the
                # gate panel live (2026-08-07) — the escalation reached the operator and the
                # screen that would let them answer went blank.
                **amend_fields,
                # #68: named choices, not a boolean. The panel has rendered any `outcomes`
                # generically since ADR-0082 §1; this gate just never populated it.
                "outcomes": [
                    o.as_dict()
                    for o in escalation_outcomes(
                        finalizes=finalizes,
                        finalizes_if_amended=_finalizes(False),
                        amendable=amend_fields.get("amendable"),
                        regressions=regress.get("regressions"),
                    )
                ],
            }
        )
        or {}
    )
    escalations = state.get("escalations", 0) + 1
    resolution = str(resume.get("resolution", ""))
    feedback = str(resume.get("feedback", "")).strip()
    # Clear the hand-raise/trip so a re-scope doesn't instantly re-trip on stale state.
    out: dict[str, Any] = {
        "escalations": escalations,
        "blocked_reason": "",
        "escalate_reason": "",
        "progress_trip": {},
    }
    # The EFFECT the gate computed for the option the operator clicked, read FIRST because it
    # decides whether an amendment is worth computing at all. `GatePanel` submits the ticked tests
    # with every option, so choosing "Stop and record it honestly" with one still ticked used to
    # write `pending_amendment` into a checkpoint the run then abandoned — and skip
    # `ask_blocking_tests`, making the stop reason LESS specific because the operator ticked a box
    # (red team R2). An ending answer needs no amendment.
    effect = str(resume.get("effect", ""))
    # ...unless the operator AUTHORIZED amending the very tests that are in the way (ADR-0087, #65)
    # — see amendment_delta. Without it the arm asks and then ignores the answer.
    amendment = (
        {} if effect == "end_run" else _amendment.amendment_delta(ctx, state, resume, feedback)
    )
    out.update(amendment)
    # Re-read the SAME predicate the options were built from, with the conflict now cleared if the
    # operator authorised an amendment. Recomputing rather than caching is the point: the operator's
    # answer is the one input that changes it, and `finalizes_if_amended` already promised them this
    # exact result. Everything else in it was fixed before they were asked (#68).
    # Named, not inlined: the give-up sentence below reads it too, and inlining it once meant the
    # "blocked by protected test(s)" clause kept firing after an amendment had cleared the conflict.
    conflict_stands = oracle_conflict and not amendment
    finalizes = _finalizes(conflict_stands)
    # The EFFECT the gate computed for the option the operator actually clicked (ADR-0082), carried
    # on the resume by `runner/_lifecycle.approve` and resolved there from the same offered set it
    # validates against. Reading it here is what makes "Stop and record it honestly" stop.
    #
    # It cannot be inferred from `(approve, feedback)`: `stop_honestly` and `send_back` are both
    # `approve=False` carrying whatever is in the notes box. The old `not feedback` clause below
    # was that inference, and it was wrong in precisely the case the option exists for — when
    # `finalizes` is empty the run CAN continue, so an operator who wants it to stop AND wants to
    # say why got a re-scope. Notes are now a message, never a vote. (Read above — it gates the
    # amendment too.)
    # Give up when the escalation is forced to end whatever was answered, or when the answer itself
    # says stop: the operator chose an ending option, the resolver said so, or a human declined
    # without giving a way forward (the legacy path, kept for clients that send no option).
    give_up = (
        bool(finalizes)
        or effect == "end_run"
        or resolution in ("stop", "give_up")
        or (resolution == "human" and not effect and not resume.get("approve") and not feedback)
    )
    if give_up:
        # The HONEST early stop (#56, ADR-0060): a believed hand-raise or a diagnosed
        # no-convergence, concluded strictly below the iteration cap, is an accurate prompt
        # conclusion — the generalization of plan_unworkable_reason's pattern. `stalled`
        # stays False ON PURPOSE (classify_outcome → honest_park, not thrash).
        detail = {
            "no_progress": reason,
            "escalate": f"escalation unresolved: {reason}",
            "blocked": f"blocked: {reason}",
        }[kind]
        if conflict_stands:
            # Name the blocking test. The operator's next move is to amend the ITEM, and a reason
            # that says only "escalation unresolved" leaves them to go and find out which test.
            blocking = blocking_protected_tests(state)
            detail = f"{detail} — blocked by protected test(s): {', '.join(blocking[:3])}"
            # #68 (ADR-0090 MR3): the ASK reads this instead of re-deriving the same predicate from
            # a `gate_decision` that has moved on since. The two halves disagreed in both directions
            # — a stale objection blocked a legitimate stop, a stale clean permitted a stop that
            # then could not ask — and one evaluation, recorded, makes that impossible.
            out["ask_blocking_tests"] = list(blocking)
        out["give_up_reason"] = state.get("give_up_reason") or detail
        out["stalled"] = False
    else:
        out["feedback"] = [f"supervisor re-scope: {feedback or reason}"]
        out["stalled"] = False
        # A re-scope re-plans (and may re-author tests), so the convergence episode restarts.
        out["progress_track"] = {}
        if kind == "no_progress":
            # ...and so does the FINGERPRINT streak, for the same reason (#81). Without this a
            # no-count re-scope re-trips on its very first identical failure — the streak is
            # already at the limit — making the granted re-scope a no-op. Mirrors reason_node,
            # which resets the tripped kind for exactly this reason. Scoped to the breaker-origin
            # kind: a hand-raise re-scope never consumed the test streak, so it must not clear it.
            by_kind = dict(state.get("stall_by_kind") or {})
            by_kind["test"] = ["", 0]
            out["stall_by_kind"] = by_kind
            out["test_repeat"] = 0
    return out


def route_after_supervise(ctx: RunContext, state: RunState) -> str:
    # Give-up → gate (finalizes honest incomplete — give_up_reason since #56, ADR-0060;
    # `stalled` kept for any legacy/parked state); re-scope → back to planning with the
    # supervisor's feedback (Quincy re-scopes in autonomous, the human in guided).
    return "gate" if state.get("stalled") or state.get("give_up_reason") else "plan"
