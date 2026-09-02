"""What each answer at the delivery gate will ACTUALLY do (ADR-0082 §1, F61).

The gate hands an operator evidence and takes a boolean. That boolean means five different things
across the engine, and in three of them it means the OPPOSITE of what the button says:

- at the iteration cap, "send it back to revise" **terminates the run and discards the feedback**
  — measured at ~1.1M tokens of correct work thrown away, HTTP 200, nothing anywhere saying so
  (F61, HIGH);
- on a tamper verdict the same denial is independently terminal (F63: *"'deny sends it back' now
  has at least two exceptions, neither surfaced at the gate"*);
- and the gate-stall breaker can make a denial terminal **as a consequence of that denial** — deny
  the same reasons once too often and the run concludes, which nothing warns about either.

`lessons-2026-08-06`: *"the gate's presentation is part of the trust boundary. Treat a lossy or
misleading evidence surface as a control defect, not a UI polish item."*

**The anti-drift rule, and the whole reason this module is shaped this way:** `deny_finalizes` is
the SINGLE source for both the routing decision (`route_after_gate` consumes it) and the sentence
shown to the human. A second copy of "when does deny terminate?" is precisely the bug being fixed
here, so it is made impossible by construction rather than by care — the same trick as
`_asserts_something_real` being defined as `_real_assertions() > 0`.

ADR-0082's hard rule holds: **the option set is computed, never authored by a model.** Everything
below is a pure function of run state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from mosaera_core.progress import bump_stall, fingerprint


class GateOutcome(NamedTuple):
    """One answer the operator may give, and what it will actually cause.

    ``id`` is the stable `option_id` the API accepts (ADR-0082 §5). ``consequence`` is the part
    that did not exist before: the honest statement of what happens next, in the operator's terms.
    """

    id: str
    label: str
    consequence: str
    # "approve" | "send_back" | "end_run" — what the engine will do, not what the button says.
    effect: str
    recommended: bool = False
    # True when taking this answer overrides blocking evidence. ADR-0082: "override last and
    # always labelled as an override".
    override: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "consequence": self.consequence,
            "effect": self.effect,
            "recommended": self.recommended,
            "override": self.override,
        }


def deny_finalizes(state: Mapping[str, Any], max_iter: int) -> str:
    """WHY a denial would end the run instead of sending it back — ``""`` when it sends back.

    A string rather than a bool on purpose: every caller that needs the answer also needs to be
    able to say why, and returning a bool guarantees the reason gets re-derived somewhere else in
    slightly different words.

    This is the ROUTING truth — the same conditions `route_after_gate` finalizes on, post-hoc. The
    gate-stall breaker is deliberately NOT here: by the time routing runs, a trip has already
    written `give_up_reason` into state, so counting it twice would be wrong. Its *prediction*
    lives in `would_trip_gate_stall`, which is presentation-only.
    """
    if state.get("stalled"):
        return "the run stopped converging"
    if state.get("plan_unworkable_reason"):
        return "the planner already self-stopped"
    if state.get("give_up_reason"):
        return "the run already concluded honestly"
    if state.get("iteration", 0) >= max_iter:
        return f"the revision budget is spent ({max_iter} of {max_iter})"
    return ""


def stall_signature(reasons: list[str]) -> str:
    """What the gate-stall breaker compares between visits — the reason STRINGS, sorted.

    Shared by `gate_node` and `would_trip_gate_stall` so the breaker and its prediction cannot
    drift; they duplicated this expression before ADR-0092.

    **Reason CLASSES were tried here and reverted, in the red team, and the record matters.** The
    argument for classes was that splitting a reason loses stall trips when a run's failing claim
    changes evidence class between visits. Two things killed it. It does not even fix that case —
    `behavioral` and `structural` are different classes, so the fingerprint still differs. And
    where classes DO differ from strings they make the breaker MORE aggressive: `validation_failed`
    and `oracle_unverified` are both `shortfall`, so a run progressing from one blocker to a
    genuinely different one would have its streak held and be cut off. That is precisely the
    guardrail ADR-0069 built — *"a CHANGED deny reason (progress through different blockers) RESETS
    the streak, so a run still working toward a ship is never cut off."*

    So the trip "loss" from a reason split is not a regression: it is ADR-0069 working as designed
    at finer granularity. Finer reasons mean finer progress detection and fewer premature stops,
    which is the direction that ADR wants. ADR-0069 stays untouched.
    """
    return ", ".join(sorted(set(reasons)))


def stall_sentence(reasons: list[str], replans: int, *, limit: int = 80) -> str:
    """The operator-facing give-up line, truncated STRUCTURALLY rather than by byte slice.

    The old `[:80]` cut mid-token once the reason names grew, losing the closing paren and the
    re-plan count — the two parts that say what happened. Dropping whole reasons from the end and
    saying how many were dropped keeps the sentence well-formed at any length, and makes the
    omission a declared selection instead of an accident.

    The count stays at the END on purpose: `bench/containment.py` substring-greps this sentence to
    route a measured bucket, so which tokens survive the cut must not move for reasons of taste.
    """
    ordered = sorted(set(reasons))
    for drop in range(len(ordered)):
        shown = ordered[: len(ordered) - drop]
        core = ", ".join(shown) + (f" +{drop} more" if drop else "")
        line = f"gate kept denying ({core}) across {replans} re-plans"
        if len(line) <= limit:
            return line
    return f"gate kept denying ({len(ordered)} reasons) across {replans} re-plans"[:limit]


def would_trip_gate_stall(
    state: Mapping[str, Any],
    reasons: list[str],
    *,
    max_iter: int,
    gate_stall_limit: int,
    stall_detection: bool,
) -> bool:
    """Whether denying *this* gate, for *these* reasons, would itself end the run (#67, ADR-0069).

    The third invisible exception. The gate-deny → re-plan loop concludes after
    ``gate_stall_limit`` consecutive denials carrying the SAME blocking reasons — so an operator
    can send a run back in good faith and terminate it by doing so. Predicting it costs nothing:
    the streak is already in state and `bump_stall` is already the arbiter.

    Mirrors `gate_node`'s own call exactly, including the strictly-below-cap condition, so the
    prediction cannot claim something the breaker would not do.
    """
    if not stall_detection or not reasons:
        return False
    if state.get("iteration", 0) >= max_iter:
        return False  # the cap finalizes first; deny_finalizes already says so
    prev = (dict(state.get("stall_by_kind") or {})).get("gate") or ["", 0]
    curr = fingerprint("gate", stall_signature(reasons))
    _, tripped = bump_stall(str(prev[0]), curr, int(prev[1]), gate_stall_limit)
    return bool(tripped)


def gate_outcomes(
    state: Mapping[str, Any],
    *,
    max_iter: int,
    gate_stall_limit: int = 2,
    stall_detection: bool = True,
) -> list[GateOutcome]:
    """The answers actually available at this gate, each with its real consequence.

    An option that cannot function is NOT offered. That is the F61 fix in one sentence: the run
    that discarded 1.1M tokens showed a "Send back to revise" button whose only effect was to end
    the run and throw the feedback away.
    """
    gd = state.get("gate_decision")
    reasons = [str(r) for r in (gd.get("reasons") or [])] if isinstance(gd, dict) else []
    blocked = bool(reasons)
    iteration = int(state.get("iteration", 0) or 0)
    final = deny_finalizes(state, max_iter)

    approve = GateOutcome(
        id="approve",
        label="Approve anyway" if blocked else "Approve & deliver",
        consequence=(
            f"Delivers over {len(reasons)} unresolved gate reason(s) — recorded on the receipt as "
            "an override."
            if blocked
            else "Commits the change on the run branch and writes the delivery report."
        ),
        effect="approve",
        # Recommended only when nothing is blocking. ADR-0082: prefer the choice preserving the
        # most evidence while still unblocking; an override is never the recommendation.
        recommended=not blocked,
        override=blocked,
    )

    if final:
        # The denial is terminal. Offer it as what it IS, and do not pretend a revision channel
        # exists — offering one is what made F61 cost a run's worth of correct work.
        return [
            approve,
            GateOutcome(
                id="end_run",
                label="End the run without delivering",
                consequence=(
                    f"Nothing is committed and your notes are NOT acted on — {final}. "
                    "Re-run the item to try again."
                ),
                effect="end_run",
                recommended=blocked,
            ),
        ]

    if would_trip_gate_stall(
        state,
        reasons,
        max_iter=max_iter,
        gate_stall_limit=gate_stall_limit,
        stall_detection=stall_detection,
    ):
        # Sending back is still permitted — but it is the LAST one, and saying so is the point.
        send_back = GateOutcome(
            id="send_back",
            label="Send it back to revise (final attempt)",
            consequence=(
                "The gate has denied for the same reason(s) repeatedly, so this send-back "
                "concludes the run instead of re-planning again. Change what you ask for, or "
                "approve/end deliberately."
            ),
            effect="end_run",
        )
    else:
        send_back = GateOutcome(
            id="send_back",
            label="Send it back to revise",
            # "revision 3 of 8" and nothing else. An added "(N remaining)" reads ambiguously
            # (does N include this one?) and a number the operator has to interpret is the same
            # class of defect as a label that misstates the effect.
            consequence=f"Re-plans with your notes — revision {iteration + 1} of {max_iter}.",
            effect="send_back",
            recommended=blocked,
        )
    return [approve, send_back]


def escalation_finalizes(
    *,
    escalations: int,
    max_escalations: int,
    budget_short: bool,
    projected_trip: bool,
    oracle_conflict: bool,
) -> str:
    """WHY this escalation ends the run WHATEVER the operator answers — ``""`` when it can continue.

    The escalation twin of `deny_finalizes`, and it exists for the same reason: `supervise_node`
    decides give-up from these terms, and the operator is shown a sentence about what their answer
    will do. Deriving those separately is how "send it back" comes to mean "end the run and discard
    the feedback" (F61) — so both read this, and a disagreement is impossible by construction.

    A string, not a bool, because every caller that needs the answer also needs to say why.

    Note what is NOT here: the resolution-dependent terms (`stop`/`give_up`, or a human declining
    with no way forward). Those are the operator's OWN answer — the thing the options are choosing
    between — so folding them in would make the offer a function of its own outcome.
    """
    if escalations > max_escalations:
        return f"the escalation budget is spent ({escalations} of {max_escalations})"
    if budget_short:
        return "the remaining iterations cannot fit another fix cycle"
    if projected_trip:
        return "the failure count is improving too slowly to converge in the remaining budget"
    if oracle_conflict:
        return "every failing test is one the producer may not edit, so re-planning cannot help"
    return ""


def escalation_outcomes(
    *,
    finalizes: str,
    finalizes_if_amended: str,
    amendable: Mapping[str, Any] | None = None,
    regressions: list[str] | None = None,
) -> list[GateOutcome]:
    """The answers available at a SUPERVISE escalation, each with its real consequence.

    #68: the run could stop honestly but the operator was handed a boolean. The ADR-0082 machinery
    (`GateOutcome`, `option_id`, the generic panel) was already built and simply never populated
    here, so this is the missing call, not a new mechanism.

    ADR-0082's rule holds exactly as it does above: **the option set is computed, never authored by
    a model.** Every branch below is a pure function of facts already on the escalation payload.

    ``finalizes_if_amended`` is what would still force a stop AFTER an authorised amendment clears
    the oracle conflict. It is what makes the amend option honest: authorising is only worth
    offering as a way forward when it actually leaves one.

    The caller computes both strings BEFORE interrupting, which is possible because every term
    except the oracle conflict is already fixed by then — the conflict is the single term the
    operator's own answer can clear. The resolution-dependent terms (`stop`/`give_up`, or declining
    with no way forward) are deliberately excluded: those ARE the answer being chosen here, and
    folding them in would make the offer a function of its own outcome.
    """
    out: list[GateOutcome] = []
    tests = [str(t) for t in ((amendable or {}).get("tests") or [])]
    if tests:
        named = ", ".join(tests[:3]) + (f" (+{len(tests) - 3} more)" if len(tests) > 3 else "")
        out.append(
            GateOutcome(
                id="amend_tests",
                label=f"Authorise amending {named}",
                consequence=(
                    f"The Proctor re-authors {named} coder-blind, once, and the run continues."
                    if not finalizes_if_amended
                    # Honest even when it does not help: the amendment is still RECORDED, so the
                    # next run starts from a corrected bar rather than the same wall.
                    else f"Amends {named} for the next run, but this run still ends — "
                    f"{finalizes_if_amended}."
                ),
                effect="send_back",
                recommended=not finalizes_if_amended,
            )
        )
    out.append(
        GateOutcome(
            id="send_back",
            label="Send it back with notes",
            consequence=(
                "Re-scopes and the run continues from your notes."
                if not finalizes
                # This is the F61 shape, caught before it can happen here: an option that reads
                # like a revision channel while the engine is about to terminate.
                else f"The run ends without delivering — {finalizes}. Your notes are recorded."
            ),
            effect="send_back" if not finalizes else "end_run",
            recommended=not finalizes and not out,
        )
    )
    if regressions:
        n = len(regressions)
        out.append(
            GateOutcome(
                id="fix_regressions",
                label=f"Send it back to fix the {n} test(s) this run broke",
                consequence=(
                    f"Re-scopes with the {n} regression(s) named, so the producer is pointed at "
                    "what IT broke rather than at what was already failing."
                    if not finalizes
                    else f"The run ends without delivering — {finalizes}."
                ),
                effect="send_back" if not finalizes else "end_run",
                recommended=not finalizes,
            )
        )
    # ADR-0006/ADR-0082: the honest stop is present by CONSTRUCTION, never by the generator's good
    # manners — and it is the recommendation exactly when nothing else can move the run forward.
    out.append(
        GateOutcome(
            id="stop_honestly",
            label="Stop and record it honestly",
            consequence=(
                f"Ends the run as an honest park: {finalizes}."
                if finalizes
                else "Ends the run without delivering; the reason is recorded, not dressed up."
            ),
            recommended=bool(finalizes) and not any(o.recommended for o in out),
            effect="end_run",
        )
    )
    return out
