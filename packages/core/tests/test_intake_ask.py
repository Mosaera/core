"""Askability (ADR-0080 §1, ADR-0082) — one authority, deny-by-default, clause-aware."""

from __future__ import annotations

from typing import Any

from mosaera_core.clauses import Clause, ratify_clause
from mosaera_core.intake_ask import (
    askable_items,
    divert_undecidable_to_asks,
    settled_findings,
    undecidable_ask,
)
from mosaera_core.spec_lint import checkability, decidability_findings

# The four shapes that matter, kept together so the interactions are visible.
GREENFIELD: dict[str, Any] = {  # a check BINDS, the text still never fixes the answer — ask-only
    "id": 1,
    "status": "todo",
    "acceptance": "A CLI entry point reads a password and prints a strength score 0-4.",
}
STATEMENTS: dict[str, Any] = {  # the same shape, but a clause CAN settle it
    "id": 2,
    "status": "todo",
    "acceptance": "`checkout_total` should read as a short orchestrator (a handful of statements).",
}
VAGUE: dict[str, Any] = {"id": 3, "status": "todo", "acceptance": "everything is wired up nicely"}
CRISP: dict[str, Any] = {"id": 4, "status": "todo", "acceptance": "prints every matching note"}
ALL = [GREENFIELD, STATEMENTS, VAGUE, CRISP]


class _FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def clause_insert(self, clause_id: str, **kw: Any) -> dict[str, Any]:
        row = {"id": clause_id, **kw}
        self.rows.append(row)
        return row

    def clause_list(
        self, project_id: str | None = None, *, include_superseded: bool = False
    ) -> list[dict[str, Any]]:
        return self.rows


def _statement_clause() -> tuple[Clause, ...]:
    store = _FakeStore()
    clause = ratify_clause(
        store,
        standard_id="standards/house-style",
        binds="structural.body_statements",
        value_kind="number",
        value_num=5,
        project_id="p1",
        because="correctness over line count",
    )
    return (clause,)


def test_the_knob_off_is_byte_identical_to_today() -> None:
    """The inertness proof.

    With the knob off, askability must be SET-EQUAL to the UNDER_SPECIFIED set — which is what
    the three fence sites keyed on before this module existed. Anything else means turning the
    feature off does not actually turn it off.
    """
    today = {i for i, v in checkability(ALL).items() if v == "UNDER_SPECIFIED"}
    assert set(askable_items(ALL, ())) == today
    assert set(askable_items(ALL, (), decidability_asks=False)) == today
    assert askable_items(ALL, ()) == {int(VAGUE["id"]): "checkability"}


def test_the_knob_on_reaches_the_case_no_clause_can() -> None:
    axes = askable_items(ALL, (), decidability_asks=True)
    assert axes[int(GREENFIELD["id"])] == "decidability"
    assert axes[int(VAGUE["id"])] == "checkability"  # unchanged
    assert int(CRISP["id"]) not in axes  # checkable AND decidable — never asked about


def test_a_ratified_clause_suppresses_the_ask_not_just_the_finding() -> None:
    """Being asked about something you already settled IS the fatigue hazard.

    The finding suppression alone would not be enough: the ask is a separate path, and a decision
    that silences one but not the other would ask the operator to re-answer their own decision.
    """
    clauses = _statement_clause()
    without = askable_items(ALL, (), decidability_asks=True)
    with_clause = askable_items(ALL, clauses, decidability_asks=True)

    assert int(STATEMENTS["id"]) in without, "without a decision it is asked about"
    assert int(STATEMENTS["id"]) not in with_clause, "a ratified decision must not be re-asked"
    # …and the case no clause can reach is untouched by any decision.
    assert with_clause[int(GREENFIELD["id"])] == "decidability"


def test_a_clause_can_never_reach_a_semantic_ambiguity() -> None:
    """The asymmetry is correct and must not be engineered away.

    "How is the score composed" names no registered oracle parameter and never will — inventing a
    `scoring.*` one would be the growing phrase→parameter table `standards.py` calls the re-parse
    trap. So greenfield stays askable no matter what has been ratified.
    """
    axes = askable_items([GREENFIELD], _statement_clause(), decidability_asks=True)
    assert axes == {int(GREENFIELD["id"]): "decidability"}


def test_one_ask_per_item_checkability_subsumes() -> None:
    """An item that is BOTH gets one question, the larger one — the ADR-0080 batching rule."""
    both: dict[str, Any] = {
        "id": 9,
        "status": "todo",
        "acceptance": "The summary is a handful of paragraphs.",
    }
    assert checkability([both])[9] == "UNDER_SPECIFIED"
    assert decidability_findings([both])
    assert askable_items([both], (), decidability_asks=True) == {9: "checkability"}


def test_the_ask_carries_the_claim_and_the_reason() -> None:
    got = undecidable_ask(GREENFIELD, ())
    assert got is not None
    claim, why = got
    assert "strength score 0-4" in claim
    assert "no rule for how the value is composed" in why
    # A settled item yields no ask at all, not an ask with empty text.
    assert undecidable_ask(STATEMENTS, _statement_clause()) is None


def test_settled_findings_names_the_clause_that_answered() -> None:
    """Silent suppression is indistinguishable from the detector breaking."""
    clauses = _statement_clause()
    kept, settled = settled_findings(decidability_findings(ALL), clauses)
    assert [f.item_id for f in kept] == [int(GREENFIELD["id"])]
    assert [(f.item_id, c.id) for f, c in settled] == [(int(STATEMENTS["id"]), clauses[0].id)]


def test_a_bulleted_proposal_is_joined_not_repr_d() -> None:
    """Observed on the first live run: the model returned `acceptance` as a LIST of bullets.

    `str()` would have shown the operator a Python repr — `['The CLI reads…', ' • …']`. The
    content was right and only the shape was off, so it is joined rather than refused.
    """
    stored: dict[str, Any] = {}

    class _Store:
        def set_item_clarification(self, item_id: int, **kw: Any) -> None:
            stored.update(kw)

    changeset = [
        {"op": "enhance", "id": 1, "acceptance": ["The CLI prints a score.", " • length >= 8: +1"]}
    ]
    left, asked = divert_undecidable_to_asks(_Store(), [GREENFIELD], changeset, (), enabled=True)
    assert left == []
    assert asked == [int(GREENFIELD["id"])]  # the diversion reports what it asked on
    assert stored["proposals"] == ["The CLI prints a score.\n• length >= 8: +1"]
