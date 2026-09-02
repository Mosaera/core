"""May this item be asked about, and on which axis? (ADR-0080 §1, ADR-0082)

The single authority. Three sites decide whether an intake clarification may be raised — the
prompt clause Quincy reads, the context marker that tells him which item, and the server-side
re-verify that decides whether to store one — and they must never disagree. They all call here.

Two axes, and they mean genuinely different things:

* **checkability** — nothing in the acceptance can be checked at all. Today's behaviour,
  knob-independent, byte-identical.
* **decidability** — a check DOES bind, and the text still never fixes what the right answer is.
  The counter-intuitive one: the item looks fine, the tests will pass, and they will pass against a
  value the coder invented. Measured 2026-08-04: one brief produced two different scoring models
  across two runs, the second with 48 self-consistent tests.

``clauses`` is a REQUIRED positional, deliberately. A ratified standing decision must suppress the
ask as well as the finding — being asked about something you already settled is precisely the
clarification fatigue ADR-0080 names as this feature's hazard — and making the clause set
unskippable means no caller can compute askability without it. There is one place the check lives
and no path around it.

Pure: no I/O, no model, no settings lookup. The knob arrives as an argument.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from mosaera_core.claims import claims_from_acceptance
from mosaera_core.clauses import Clause, clause_for
from mosaera_core.reachability import reachability_findings
from mosaera_core.spec_lint import (
    SpecFinding,
    checkability,
    checkability_findings,
    curate_instruction,
    decidability_findings,
    finding_param,
    lint_backlog,
    undecidable_reason,
)
from mosaera_core.task_spec import acceptance_text

CHECKABILITY = "checkability"
DECIDABILITY = "decidability"
REACHABILITY = "reachability"


def _unsettled(findings: list[SpecFinding], clauses: tuple[Clause, ...]) -> list[SpecFinding]:
    """Findings no ratified clause answers.

    A finding whose ``param`` is empty is unsettleable BY CONSTRUCTION — "how is the score
    composed" names no registered oracle parameter and never will, so no clause reaches it and
    only an operator can. That asymmetry is correct and must not be engineered away by inventing
    a parameter (``standards.py`` names the growing phrase→parameter table as the re-parse trap).
    """
    return [f for f in findings if not (f.param and clause_for(clauses, f.param))]


def settled_findings(
    findings: list[SpecFinding], clauses: tuple[Clause, ...]
) -> tuple[list[SpecFinding], list[tuple[SpecFinding, Clause]]]:
    """Split findings into (unsettled, [(settled, the clause that settled it)]).

    The clause is returned alongside so the caller can SAY which decision answered the finding.
    Silent suppression is indistinguishable from the detector breaking.
    """
    kept: list[SpecFinding] = []
    settled: list[tuple[SpecFinding, Clause]] = []
    for finding in findings:
        answer = clause_for(clauses, finding.param) if finding.param else None
        if answer is None:
            kept.append(finding)
        else:
            settled.append((finding, answer))
    return kept, settled


def askable_items(
    items: list[dict[str, Any]],
    clauses: tuple[Clause, ...],
    *,
    decidability_asks: bool = False,
    reachability_asks: bool = False,
) -> dict[int, str]:
    """Item id → the axis it may be asked about. Deny-by-default; ``{}`` when nothing qualifies.

    ``decidability_asks`` is the ``intake_ask_undecidable`` knob and ``reachability_asks`` is
    ``intake_ask_unreachable``; both default to FALSE, so a caller that forgets to thread either
    gets today's behaviour rather than a new question. With both off, the result is set-equal to
    the UNDER_SPECIFIED set exactly as before this module existed.
    """
    axes: dict[int, str] = {}
    for item_id, verdict in checkability(items).items():
        if verdict == "UNDER_SPECIFIED":
            axes[item_id] = CHECKABILITY
    if decidability_asks:
        for finding in _unsettled(decidability_findings(items), clauses):
            # UNDER_SPECIFIED subsumes: "nothing here is checkable" is the larger question, and one
            # ask per item is the batching rule. Never two questions about one item.
            axes.setdefault(finding.item_id, DECIDABILITY)
    if reachability_asks:
        # Last, so it never displaces a sharper question — but note an UNREACHABLE item is the one
        # whose ask saves the most: the others cost a weaker verdict, this one costs a whole run
        # that could not have succeeded (F76, item 88: five runs, ~2.9M tokens).
        for finding in _unsettled(reachability_findings(items), clauses):
            axes.setdefault(finding.item_id, REACHABILITY)
    return axes


def undecidable_ask(item: dict[str, Any], clauses: tuple[Clause, ...]) -> tuple[str, str] | None:
    """``(claim_text, why)`` for the ask to raise on this item, or None.

    Re-derived from the claim, NOT parsed back out of the finding's rendered sentence. Reading our
    own formatted prose to recover a value is the re-parse trap this whole arc exists to remove,
    and it would be an easy one to reintroduce here.

    The claim text is stored verbatim on the clarification, which is what lets the axis be DERIVED
    at read rather than frozen into a column — the argument the compliance surface already makes.
    """
    if not _unsettled(decidability_findings([item]), clauses):
        return None
    acceptance = str(item.get("acceptance") or "")
    for claim in claims_from_acceptance(int(item["id"]), acceptance):
        if not claim.material:
            continue
        reason = undecidable_reason(claim.text, acceptance)
        if reason:
            return claim.text, reason
    return None


def _as_text(value: Any) -> str:
    """A proposal as the operator will read it — see ``task_spec.acceptance_text``.

    This path (clarification proposals) was the first to hit the list-shaped acceptance and carried
    the only fix for it; the same normalisation is now shared with every acceptance WRITE path, so
    the shape is established once rather than per call site.
    """
    return acceptance_text(value)


class _ClarificationStore(Protocol):
    def set_item_clarification(
        self,
        item_id: int,
        *,
        claim_text: str,
        why_unbindable: str,
        proposals: list[str],
        axis: str,
        proposal_kind: str,
    ) -> None: ...


def divert_undecidable_to_asks(
    memory: _ClarificationStore,
    items: list[dict[str, Any]],
    changeset: list[Any],
    clauses: tuple[Clause, ...],
    *,
    enabled: bool = False,
) -> tuple[list[Any], list[int]]:
    """Turn a rewrite of an UNDECIDABLE item into an operator ASK.

    Returns ``(ops still to apply, item ids asked about)``. It reports the asks rather than
    leaving the caller to re-derive them: recomputing "who did we ask?" from the store is how two
    surfaces end up disagreeing about what happened.

    The defect this closes: an undecidable claim is a question only the operator can answer, and
    the re-curate pass had the PM answering it himself — inventing a rule and applying it silently,
    which is the same failure the detector exists to catch, one level up.

    He is still the right author of the PROPOSAL: an ``enhance`` op already carries a complete
    replacement acceptance, which is exactly what a clarification proposal is. So the op is
    diverted rather than applied, and the operator accepts / edits / dismisses it through the
    existing card — after which resolution rewrites the acceptance through the SAME validated
    ``enhance`` path, minting ENTAILED claims from text the operator approved.

    Deny-by-default: with ``enabled`` false the changeset is returned untouched, so the whole path
    is today's behaviour. Best-effort per item — a store failure leaves that op to be applied as
    before rather than losing the work.
    """
    if not enabled:
        return changeset, []
    asks = {
        i
        for i, axis in askable_items(items, clauses, decidability_asks=True).items()
        if axis == DECIDABILITY
    }
    if not asks:
        return changeset, []
    by_id = {int(i["id"]): i for i in items}
    kept: list[Any] = []
    asked: list[int] = []
    for op in changeset:
        if not isinstance(op, dict) or op.get("op") != "enhance":
            kept.append(op)
            continue
        item_id = int(op.get("id", -1))
        proposal = _as_text(op.get("acceptance"))
        ask = undecidable_ask(by_id[item_id], clauses) if item_id in asks and proposal else None
        if ask is None:
            kept.append(op)
            continue
        try:
            memory.set_item_clarification(
                item_id,
                claim_text=ask[0],
                why_unbindable=ask[1],
                proposals=[proposal],
                # The proposal IS an `enhance` op's acceptance — see the docstring above — so it
                # is genuinely acceptance text and stays one-click (ADR-0091).
                axis=DECIDABILITY,
                proposal_kind="acceptance",
            )
            asked.append(item_id)
        except Exception:
            kept.append(op)
    return kept, asked


@dataclass(frozen=True)
class IntakePass:
    """What one bounded intake pass did, so every caller can report it identically."""

    findings: list[SpecFinding]  # what remained after standing decisions answered their own
    settled: list[tuple[SpecFinding, Clause]]  # (finding, the decision that answered it)
    asks: list[int]  # item ids an operator question was raised on
    applied: list[Any]  # the ops that were actually applied


def run_intake_pass(
    memory: _ClarificationStore,
    items: list[dict[str, Any]],
    clauses: tuple[Clause, ...],
    *,
    propose: Callable[[str], list[Any]],
    apply_ops: Callable[[list[Any]], Any],
    ask_enabled: bool = False,
) -> IntakePass:
    """Detect → let standing decisions answer → propose → divert asks → apply. One bounded pass.

    Extracted from the API so `core` can run the loop an instrument needs to grade. The two steps
    that genuinely belong to the app — asking the PM to propose, and applying a validated
    changeset — arrive as callables; everything else here is pure detection and routing.

    Deliberately NOT best-effort: the caller owns the try/except posture, because "a lint bug must
    never break backlog generation" is a product decision rather than a property of the pass. A
    harness wants the exception.
    """
    findings = (
        lint_backlog(items)
        + checkability_findings(items)
        + decidability_findings(items)
        + reachability_findings(items)
    )
    findings, settled = settled_findings(findings, clauses)
    if not findings:
        return IntakePass(findings, settled, [], [])

    changeset = propose(curate_instruction(findings))
    changeset, asks = divert_undecidable_to_asks(
        memory, items, changeset, clauses, enabled=ask_enabled
    )
    if changeset:
        apply_ops(changeset)
    return IntakePass(findings, settled, asks, changeset)


__all__ = [
    "CHECKABILITY",
    "DECIDABILITY",
    "IntakePass",
    "askable_items",
    "divert_undecidable_to_asks",
    "finding_param",
    "run_intake_pass",
    "settled_findings",
    "undecidable_ask",
]
