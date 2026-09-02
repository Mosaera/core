"""The no-progress breakers and the fix loop's convergence decision.

Extracted from ``nodes_impl`` (#81): that module was at 460/500 against the shrink-only god-file
ratchet, and the convergence arc grows exactly this code. Same reason ``_proctor_authoring`` came
out of ``nodes_plan``. Extraction also fixes a layering smell — ``nodes_review`` was reaching into
``nodes_impl`` for the *private* ``_stall_bump`` / ``_apply_trip``; both are public here.

Two breakers live here, and they answer different questions:

- ``stall_bump`` — "is this loop producing the SAME outcome over and over?" A digit-stripped
  fingerprint per loop kind (test/hygiene/review). Language-neutral, works on any text.
- ``bump_progress`` / ``wont_converge`` (in ``progress``) — "is the failing COUNT still beating its
  best?" Strictly stronger, but needs a countable result, which today only a pytest-shaped validator
  yields. That asymmetry is issue #81: the count path concludes honestly via ``supervise`` while the
  fingerprint path sets ``stalled`` and is bucketed as thrash.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState
from mosaera_core.languages import interpret_outcome
from mosaera_core.progress import (
    bump_progress,
    bump_stall,
    fingerprint,
    first_error_lines,
    parse_failing_tests,
    wont_converge,
)
from mosaera_core.validation import ValidationOutcome, ValidationPlan


def stall_bump(
    ctx: RunContext, state: RunState, kind: str, text: str
) -> tuple[dict[str, Any], int, bool]:
    """Per-kind no-progress bump: each self-heal loop (test/hygiene/review) tracks its
    OWN streak keyed by kind, so interleaved loops don't reset each other's fingerprint
    (which defeated the breaker → it never tripped early). Returns the updated
    stall_by_kind map, the new streak, and whether it tripped."""
    fp = fingerprint(kind, text)
    by_kind = dict(state.get("stall_by_kind") or {})
    prev = by_kind.get(kind) or ["", 0]
    count, tripped = bump_stall(str(prev[0]), fp, int(prev[1]), ctx.settings.stall_limit)
    by_kind[kind] = [fp, count]
    return by_kind, count, tripped


def apply_trip(
    ctx: RunContext, state: RunState, result: dict[str, Any], kind: str, text: str, reason_text: str
) -> None:
    """A tripped no-progress breaker either diverts to a ONE-shot reason-and-change-
    approach pass (reason-before-park, ADR-0017 — opt-in, budget-bounded) or, budget
    spent / feature off, sets today's honest park signal. Kept here so the three trip
    sites (test/hygiene/review) stay symmetric. `needs_reason` and `stalled` are mutually
    exclusive; reason_node is the only consumer of `needs_reason`."""
    if ctx.settings.reason_on_stall_enabled and state.get("reason_attempts", 0) < ctx.max_reason:
        result["needs_reason"] = {"kind": kind, "text": text, "reason": reason_text}
    else:
        spent = (
            " (a reason-and-change-approach pass was already attempted)"
            if (state.get("reason_attempts", 0))
            else ""
        )
        result["stalled"] = True
        result["stall_reason"] = reason_text + spent


def convergence_update(
    ctx: RunContext,
    state: RunState,
    outcome: ValidationOutcome,
    plan: ValidationPlan,
    result: dict[str, Any],
) -> None:
    """Fold this validation attempt into the run's convergence signals, mutating ``result``.

    Called by ``test_node`` AFTER the tamper branch has had its chance to return early — so a
    tampering run never reaches here, and ``stalled`` keeps its security meaning (ADR-0060).
    """
    # Convergence signal (#55, ADR-0059): read the failing count and carry the previous one, so the
    # fix prompt can show the coder whether it's actually getting closer (12 → 3) or spinning
    # (12 → 12). The same count feeds the honest-stop progress breaker below (#56).
    #
    # The count comes from the LanguagePack that BUILT this plan (#81), not from regexing pytest's
    # summary out of whatever the runner printed. `None` is the honest "this validator does not
    # report a count", which is a different claim from zero failures.
    failing_count: int | None = None
    if outcome.passed is False:
        report = interpret_outcome(plan, outcome)
        failing_count = report.failing if report is not None else None
        if report is not None:
            result["test_report"] = report.as_dict()
        result["test_failing_prev"] = state.get("test_failing_now")
        result["test_failing_now"] = failing_count
    elif outcome.passed is True and state.get("progress_track"):
        # A green run ends the failing-convergence episode — reset so a later re-failure
        # (e.g. a hygiene_fix regression) starts a fresh episode, not a stale streak.
        result["progress_track"] = {}
    # The honest-stop progress breaker (#56, ADR-0060) — the fix loop's ONE convergence question,
    # answered deterministically: is the failing count still beating its best? BEST-SO-FAR
    # semantics catch oscillation (5→6→5) that both the #55 two-value window and the fingerprint
    # (digit-stripped) miss. On a trip, the run does NOT park — it routes to `supervise` for a
    # decision (re-scope once vs give up honestly), each rung budget-aware so the eventual give-up
    # always lands strictly BELOW the iteration cap (else the frozen classifier's rode-to-cap check
    # would label an honest conclusion thrash). Unparseable output (a non-pytest validator) keeps
    # the pre-#56 fingerprint-stall path byte-for-byte.
    if not (ctx.settings.stall_detection_enabled and outcome.passed is False):
        return
    if failing_count is not None:
        _count_path(ctx, state, outcome, result, failing_count)
    else:
        _no_signal_path(ctx, state, outcome, result)


def _no_signal_path(
    ctx: RunContext, state: RunState, outcome: ValidationOutcome, result: dict[str, Any]
) -> None:
    """The uncountable branch: no number to trend, so the fingerprint is the only progress signal.

    Bookkeeping is unchanged — ``stall_bump`` still maintains ``stall_by_kind`` so the per-kind
    streaks, ``reason_node``'s reset and ``diagnose_bottleneck`` all behave as before. What changes
    (#81, knob-gated) is the CONCLUSION: instead of setting ``stalled`` — which routes past every
    self-heal loop to the gate and is bucketed ``thrash_park`` — the trip climbs the SAME ladder the
    counted path uses, so the run concludes as an honest give-up below the cap.
    """
    by_kind, count, tripped = stall_bump(ctx, state, "test", outcome.output)
    result["stall_by_kind"] = by_kind
    # Tell the coder its last edit changed nothing the validator can see. Carried even before the
    # trip: on this path there is no count, so without it the fix prompt has NO feedback at all.
    result["test_repeat"] = count
    if not tripped:
        return
    if not ctx.settings.honest_stop_no_signal:
        # Pre-#81 behaviour, byte-for-byte — the rollback lever and the bench A/B's OFF arm.
        apply_trip(
            ctx,
            state,
            result,
            "test",
            outcome.output,
            f"validation failed the same way {count + 1} times in a row",
        )
        return
    reason = (
        f"no convergence (no countable result): validation failed identically "
        f"{count + 1} times — {first_error_lines(outcome.output)}"
    )
    # Rung 1 — reason-and-change-approach (ADR-0017), same conditions apply_trip used.
    if ctx.settings.reason_on_stall_enabled and state.get("reason_attempts", 0) < ctx.max_reason:
        result["needs_reason"] = {"kind": "test", "text": outcome.output, "reason": reason}
    elif state.get("iteration", 0) < ctx.max_iter:
        # Rung 2 — supervise (a DECISION: re-scope once vs give up honestly), reachable only below
        # the cap. No `stalled`: route_after_test already sends progress_trip to supervise, and
        # supervise_node already treats a missing count as kind="no_progress". `trend` and
        # `failing_tests` are empty by construction — there is nothing to count — so the reason
        # string carries the diagnosis instead.
        result["progress_trip"] = {
            "reason": reason,
            "failing_now": None,
            "best": None,
            "trend": [],
            "failing_tests": [],
            "projected": False,
            "signal": "fingerprint",
        }
    else:
        # Rung 3 — at/over the cap the honest window is closed. Rode-to-cap IS thrash; identical
        # to the counted path's final rung. Never dress it up.
        result["stalled"] = True
        result["stall_reason"] = reason


def _count_path(
    ctx: RunContext,
    state: RunState,
    outcome: ValidationOutcome,
    result: dict[str, Any],
    failing_count: int,
) -> None:
    """The countable-result branch: best-so-far streak + slow-crawl projection, concluding via
    the reason → supervise ladder rather than a park."""
    track = dict(state.get("progress_track") or {})
    best, streak, tripped = bump_progress(
        track.get("best"),
        int(track.get("streak", 0)),
        failing_count,
        ctx.settings.stall_limit,
    )
    history = [*(track.get("history") or []), failing_count][-ctx.settings.max_iterations_ceiling :]
    result["progress_track"] = {"best": best, "streak": streak, "history": history}
    iteration = state.get("iteration", 0)
    remaining = ctx.max_iter - iteration
    # Projected non-convergence (#65): a run improving too SLOWLY to reach 0 by the cap
    # concludes early too. The streak breaker above only catches stagnation/oscillation, so
    # a 12->10->8->6 crawl (a weak coder inching toward a bar it won't clear in budget) else
    # rides to the cap as thrash. Conservative (optimistic average-rate projection) so it
    # never trips a run that would actually converge; enters the SAME conclusion ladder.
    projected = (
        not tripped and ctx.settings.honest_stop_projection and wont_converge(history, remaining)
    )
    if not (tripped or projected):
        return
    trend = " → ".join(str(n) for n in history[-6:])
    reason = (
        f"no convergence: failing count {trend} — improving too slowly to pass in the "
        f"remaining {remaining} attempt(s)"
        if projected
        else f"no convergence: failing count {trend} over {streak + 1} non-improving attempts"
    )
    # Rung 1 — reason-and-change-approach (ADR-0017), only if a FULL rung (the reason
    # pass + up to stall_limit-1 fixes to the next trip) still concludes below the cap.
    # A PROJECTED trip (#65) SKIPS the retry: the run is already improving, just too
    # slowly to converge — another retry/re-scope only re-thrashes, so route it straight
    # to the supervisor's give-up (an honest_park), never a re-scope.
    if (
        not projected
        and ctx.settings.reason_on_stall_enabled
        and state.get("reason_attempts", 0) < ctx.max_reason
        and remaining > ctx.settings.stall_limit
    ):
        result["needs_reason"] = {"kind": "test", "text": outcome.output, "reason": reason}
    elif iteration < ctx.max_iter:
        # Rung 2 — supervise (a decision), reachable only below the cap. The
        # deterministic diagnosis replaces the deleted LLM park-note (#54 react).
        # `projected` forces the supervisor to GIVE UP (not re-scope) — #65.
        result["progress_trip"] = {
            "reason": reason,
            "failing_now": failing_count,
            "best": best,
            "trend": history,
            "failing_tests": parse_failing_tests(outcome.output),
            "projected": projected,
        }
    else:
        # At/over the cap the honest window is closed — today's stall park stands
        # (rode-to-cap IS thrash; never dress it up).
        result["stalled"] = True
        result["stall_reason"] = reason


def fallback_escalate_reason(ctx: RunContext, why: str) -> str:
    """The hand-raise text for a planner that produced nothing usable, naming the actual cause."""
    if why == "budget_exhausted":
        return (
            f"planner spent its entire {ctx.settings.pm_step_limit}-call budget reading the repo "
            "and never wrote a plan — raise pm_step_limit"
        )
    if why == "model_failed":
        return "planner never reached the model (transport failure) — check the model endpoint"
    return "planner returned no grounded plan"


def plan_unworkable_reason(ctx: RunContext, streak: int, why: str) -> str:
    """Why the run is giving up on planning — capped for the 80-char termination_reason column.

    "needs clarification or a smaller scope" is reserved for `empty`. Saying it after a BUDGET
    exhaustion blames the operator's backlog item for an engine resource limit, and would send a
    human to rewrite a perfectly good item (measured 2026-08-07: it did).
    """
    if why == "budget_exhausted":
        return (
            f"planner ran out of model calls ({ctx.settings.pm_step_limit}) before writing a plan, "
            f"{streak}x — raise pm_step_limit; the item is not the problem"
        )
    if why == "model_failed":
        return (
            f"planner could not reach the model {streak}x — an infrastructure failure, "
            "not a limit of the task"
        )
    return (
        f"couldn't form a workable plan for this task after {streak} "
        "attempt(s) — needs clarification or a smaller scope"
    )
