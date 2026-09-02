"""How a run's ENDING is described.

`_termination_reason` renders the durable 80-character column; the session's
`_record_terminal_diagnosis` writes the structured record behind it. Both answer the same
question — why did this stop — and they are kept together because the failure mode is having one
without the other: a run that recorded a status and nothing else. Measured 2026-08-06, all 11
LedgerCLI runs were cancelled and therefore diagnostically blank, which is what left the PM with
nothing to read (F47/F50).
"""

from __future__ import annotations

from typing import Any


def _termination_reason(final: dict[str, Any]) -> str:
    """A short, honest reason a run ended WITHOUT delivering. Prefers the no-progress
    breaker's own message; else derives from the gate's evidence reasons; else a
    generic fallback. Kept ≤80 chars for the durable column."""
    # Plan-level breaker (#51, ADR-0056): the planner couldn't form a workable plan and the run
    # self-stopped EARLY + honestly (NOT stalled → a clean honest_park). Named first so the reason
    # reads accurately instead of the generic "no validation available" the empty-diff gate emits.
    if final.get("plan_unworkable_reason"):
        return str(final["plan_unworkable_reason"])[:80]
    # The honest-stop (#56, ADR-0060): the supervisor concluded EARLY with an accurate reason —
    # a diagnosed no-convergence (with the count trend + trapping tests in the gate payload) or a
    # believed coder hand-raise. Named before the stall branches: this is an honest conclusion.
    if final.get("give_up_reason"):
        return str(final["give_up_reason"])[:80]
    if final.get("stalled") and final.get("stall_reason"):
        return str(final["stall_reason"])[:80]
    reasons = (final.get("gate_decision") or {}).get("reasons") or []
    if "iteration_limit" in reasons:
        return "reached the iteration limit without meeting acceptance"
    if "validation_failed" in reasons:
        return "validation kept failing"
    # verb-arc slice 1. Named BEFORE the generic lines because a removal park's cause is specific
    # and actionable: either something still calls the removed thing, or the proof could not run.
    # The operator needs the distinction to know whether to fix a caller or re-scope the item.
    if "impact_unassessed" in reasons:
        return "the behaviour change is unassessed — nothing checks who depended on it"
    if "removal_unproven" in reasons:
        return "the removal is unproven — something may still reference what was removed"
    if "oracle_unverified" in reasons:
        # #44 (ADR-0052): the acceptance suite is green on the UNTOUCHED tree (the Proctor's tests
        # pass pre-implementation). The task may already be done — but a green-pre-impl suite can't
        # independently confirm the requirement is met, so this concludes early + honestly for a
        # human to confirm, rather than thrashing to a wrong-reasoned give-up. Named before the
        # generic oracle_unverified so the already-satisfied case reads accurately.
        if final.get("already_satisfied"):
            return "appears already satisfied — confirm the acceptance is met (green pre-impl)"
        # #60/#62 (ADR-0071 amendment): the structural vouch FIRED but a comprehensive-mutation
        # survivor blocked — a priced, named residual, not a generic oracle gap. Named before
        # the generic line so the operator's approve decision is informed.
        gate = final.get("gate_decision") or {}
        if str(gate.get("oracle_vouched_by", "")).startswith("structural_claims:") and (
            final.get("tests_mutation_caught") is False
        ):
            return (
                "vouched refactor blocked by a surviving mutation — approve the named "
                "residual or add a covering test"
            )
        # ADR-0044: green, but the passing suite is the coder's own — no independent oracle. Named
        # before the reviewer branch so the silence+oracle_unverified case reads honestly (the
        # reviewer requested nothing — the blocker is the missing oracle).
        return "no independent oracle vouched — the passing tests are the coder's own"
    if "tests_tampered" in reasons:
        # ADR-0036. Named BEFORE the reviewer branch: a reviewer can APPROVE a run whose tests were
        # tampered with, in which case `reasons == ["tests_tampered"]` and every branch below misses
        # it — so the single most serious park the engine can produce has been reading "ended
        # without meeting the acceptance criteria" in the durable 80-char column. Found 2026-08-08.
        return "the run modified the tests it was judged by — the green suite proves nothing"
    if "content_destroyed" in reasons:
        # ADR-0099. Named beside tests_tampered for the same reason: a reviewer can APPROVE a
        # run that emptied a file, so this can be the SOLE reason and every branch below would
        # miss it. The operator must be told a file was destroyed, not that criteria went
        # unmet — those are different facts and only one of them is recoverable by re-running.
        return "a pre-existing file was emptied, not deleted — an undeclared removal"
    if "claim_integrity_failed" in reasons:
        # ADR-0092. Provably co-present with tests_tampered today, so this is unreachable in
        # practice — named anyway, because the guard requires totality and the day the tamper
        # claim's oracle diverges from the guard's is the day this matters.
        return "a claim that the tests were left untouched was broken"
    if "claim_structural_failed" in reasons:
        return "the delivered code is not shaped the way the item asked for"
    if "claim_behavioral_failed" in reasons:
        return "the change did not do something the item's acceptance asked for"
    if "unsatisfied_claim" in reasons:
        # ADR-0079 Wave 2, minted 2026-08-02 and never given a branch here. Retired by ADR-0092 in
        # favour of the per-class reasons, but kept: stored runs carry it forever.
        return "an acceptance criterion the run was judged against was not satisfied"
    if "security_stale" in reasons:
        # ADR-0108: the distinction the operator needs is that nothing is broken — the code simply
        # moved after it was checked, so the check no longer describes what would ship.
        return "the code changed after the security scan ran — this version was never scanned"
    if "reviewer_stale" in reasons:
        return "the code changed after the reviewer approved it — this version was never reviewed"
    if "security_not_attempted" in reasons:
        # ADR-0107, and the distinction is the operator's next MOVE: nothing is wrong with the
        # scanner, the run simply ended before reaching it (a give-up or an unworkable plan route
        # straight to the gate). Sending them to look at Docker is the hour F39 cost on the
        # validation half of this same split.
        return "the run ended before the security scan ran — unchecked, not clean"
    if "security_unverified" in reasons:
        # ADR-0076: deny-by-default. "We did not check" is never "clean", and the operator needs to
        # know which of the two happened — the whole point of the reason existing.
        return "the security scan could not verify this change — unchecked, not clean"
    if "critic_vetoed" in reasons:
        # #60 (ADR-0065): the held-out critic judged the delivered OUTCOME against the spec and
        # found a specific unmet requirement — an honest park for a human, distinct from a reviewer
        # objection (the reviewer approved/was silent; the independent judge is the blocker).
        return "the held-out critic found the delivered code doesn't meet the spec"
    if any(str(r).startswith("reviewer") for r in reasons):
        return "the reviewer's requested changes weren't resolved"
    if "security_findings" in reasons:
        return "unresolved security findings"
    if "validation_unavailable" in reasons:
        return "no automated validation was available to confirm the change"
    if "validation_not_attempted" in reasons:
        # F39/#71 split `validation_unavailable` in two precisely so these would read differently —
        # and then never added the branch, so the case landed on the generic sentence below, which
        # is the outcome that split existed to prevent.
        return "validation was never attempted — no plan reached the gate"
    return "ended without meeting the acceptance criteria"
