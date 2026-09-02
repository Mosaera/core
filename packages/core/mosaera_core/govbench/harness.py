"""Drive the intake loop over a governance case and report what it did.

The deterministic arm. It runs the REAL loop — `run_intake_pass`, the real detectors, the real
diversion, the real resolve-through-`enhance` — against an in-memory store, with only the PM's
proposal stubbed. That stub is the honest boundary of this arm: it measures whether a detected
ambiguity ROUTES to the operator and whether a ratified decision silences it. It does not measure
whether the PM would have detected anything, and the scorecard says so.

No model, no Docker, no database. Seconds, so it can live in `make test` and cannot rot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mosaera_core.clauses import Clause, make_clause
from mosaera_core.govbench.cases import GovCase
from mosaera_core.govbench.store import GovStore
from mosaera_core.intake_ask import run_intake_pass
from mosaera_core.reachability import reachability
from mosaera_core.spec_lint import checkability, decidability
from mosaera_core.task_spec import acceptance_text, build_run_task


@dataclass
class GovRun:
    """What one case's intake pass actually did, against what it declared."""

    case_id: str
    case_class: str
    checkability: str
    decidability: str
    # ADR-0089's axis. Added with `expect_reachability` on 2026-08-07 — and for a few hours the
    # EXPECTATION existed while this did not, so `broken_cases` had nothing to compare and the
    # field was inert. Exactly the shape of F74 (`hygiene_unavailable`: declared, populated, read
    # by nobody), committed the same day that one was fixed. A declared expectation with no
    # observation is not a measurement.
    reachability: str
    asked: bool
    asked_again: bool | None = None  # clause-settleable only: did the SECOND pass re-ask?
    task: str = ""  # the task a run would receive after resolution
    notes: list[str] = field(default_factory=list)

    @property
    def detected(self) -> bool:
        return True  # set by the harness against the case's declaration

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_class": self.case_class,
            "checkability": self.checkability,
            "decidability": self.decidability,
            "reachability": self.reachability,
            "asked": self.asked,
            "asked_again": self.asked_again,
        }


def _proposal_for(case: GovCase) -> list[dict[str, Any]]:
    """The PM's stubbed proposal: the operator's own answer, offered as a replacement acceptance.

    Stubbing this is what makes the arm free — and it is also the honest limit of what the arm can
    claim. A real PM might propose something worse; this measures the ROUTING, not the proposal.
    """
    return [{"op": "enhance", "id": 1, "acceptance": case.answer, "why": "govbench stub"}]


def run_gov_case(case: GovCase, *, ask_enabled: bool = True) -> GovRun:
    """Run the intake loop once (twice for the clause-settleable class) and report."""
    store = GovStore()
    item_id = store.add_item(case.id, case.acceptance)
    items = store.list_backlog_items()

    verdicts = checkability(items), decidability(items), reachability(items)
    applied: list[Any] = []

    def _apply(ops: list[Any]) -> None:
        for op in ops:
            if isinstance(op, dict) and op.get("op") == "enhance":
                store.update_backlog_item(
                    int(op["id"]), acceptance=acceptance_text(op.get("acceptance"))
                )
        applied.extend(ops)

    result = run_intake_pass(
        store,
        items,
        (),
        propose=lambda _instruction: _proposal_for(case),
        apply_ops=_apply,
        ask_enabled=ask_enabled,
    )
    run = GovRun(
        case_id=case.id,
        case_class=case.case_class,
        checkability=verdicts[0].get(item_id, ""),
        decidability=verdicts[1].get(item_id, ""),
        reachability=verdicts[2].get(item_id, ""),
        asked=bool(result.asks),
    )

    # The operator answers, through the SAME validated path production uses: an `enhance` op that
    # rewrites the acceptance, after which claims are re-minted ENTAILED from the operator's text.
    if run.asked and case.answer:
        store.update_backlog_item(item_id, acceptance=case.answer)
        store.resolve_item_clarification(item_id, status="resolved", resolution=case.answer)

    # Compounding: ratify the decision, run the pass again, and see whether it asks a second time.
    if case.case_class == "clause-settleable" and case.clause_binds:
        clause: tuple[Clause, ...] = (
            make_clause(
                standard_id="standards/house-style",
                binds=case.clause_binds,
                value_kind="number",
                value_num=case.clause_value,
                project_id="govbench",
                because="ratified by the operator (govbench)",
            ),
        )
        # Re-run against the ORIGINAL acceptance — the question is whether the standing decision
        # silences the ask, not whether rewriting the text did.
        store.update_backlog_item(item_id, acceptance=case.acceptance)
        second = run_intake_pass(
            store,
            store.list_backlog_items(),
            clause,
            propose=lambda _instruction: _proposal_for(case),
            apply_ops=_apply,
            ask_enabled=ask_enabled,
        )
        run.asked_again = bool(second.asks)

    item = store.get_backlog_item(item_id) or {}
    run.task, _ = build_run_task(item, ())
    return run
