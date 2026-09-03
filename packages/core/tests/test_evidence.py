"""Does every acceptance criterion have evidence? — the question Quincy could not answer.

The North Star names it as his defining one: he *"never trusts 'Done'"*. The ledger recorded the
answer per RUN and nothing reconciled it against the item's current acceptance, so the question was
answerable about an execution and never about a piece of work.

The property these tests exist to defend: **absence is not a verdict.** A criterion nobody has
evaluated is `unmeasured`, never satisfied and never failed.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.evidence import UNMEASURED, reconcile


def _row(claim_id: str, verdict: str, ref: str = "") -> dict[str, Any]:
    return {"claim_id": claim_id, "verdict": verdict, "oracle_ref": ref}


ACCEPTANCE = (
    "The CLI exits 0 on a valid file.\n"
    "`budget list` prints one row per expense.\n"
    "The README documents the export command."
)


def test_a_criterion_no_run_has_evaluated_is_unmeasured_not_failed() -> None:
    """The whole point. Claims are re-derived from acceptance at every launch, so a criterion added
    after the last run has no ledger row — and reading that as a failure would condemn work nobody
    has looked at, while reading it as satisfied is the false-green this project keeps finding."""
    ev = reconcile(ACCEPTANCE, [_row("7-c1", "satisfied")], item_id=7)

    assert len(ev.criteria) == 3
    assert ev.criteria[0].verdict == "satisfied"
    assert ev.criteria[1].verdict == UNMEASURED
    assert ev.criteria[2].verdict == UNMEASURED
    assert [c.claim_id for c in ev.unmeasured] == ["7-c2", "7-c3"]
    assert ev.measured == 1


def test_the_ledgers_own_non_answers_do_not_count_as_evidence() -> None:
    """`unbound` and `unevaluable` are the ledger being honest that it could not decide. Counting
    them as evidence would launder "we could not tell" into "we checked"."""
    ev = reconcile(
        ACCEPTANCE,
        [_row("7-c1", "unbound"), _row("7-c2", "unevaluable"), _row("7-c3", "failed")],
        item_id=7,
    )
    assert ev.measured == 1, "only the failed one was actually evaluated"
    assert ev.satisfied == 0
    assert {c.claim_id for c in ev.unmeasured} == {"7-c1", "7-c2"}


def test_fully_evidenced_needs_every_material_criterion_satisfied() -> None:
    all_good = reconcile(
        ACCEPTANCE,
        [_row("7-c1", "satisfied"), _row("7-c2", "satisfied"), _row("7-c3", "satisfied")],
        item_id=7,
    )
    assert all_good.fully_evidenced is True

    one_missing = reconcile(
        ACCEPTANCE, [_row("7-c1", "satisfied"), _row("7-c2", "satisfied")], item_id=7
    )
    assert one_missing.fully_evidenced is False, "an unmeasured criterion is not a satisfied one"


def test_an_item_with_no_acceptance_is_not_fully_evidenced() -> None:
    """Vacuous truth would make the emptiest item look the best-proven — `all([])` is True, and that
    is precisely the shape that turns "nothing was checked" into "everything passed"."""
    ev = reconcile("", [], item_id=7)
    assert ev.criteria == ()
    assert ev.fully_evidenced is False


def test_the_current_acceptance_drives_it_not_the_ledger() -> None:
    """A criterion deleted from the item still has ledger rows. Reporting it would describe a bar
    nobody is held to any more — the text is the promise, the ledger only what happened to it."""
    ev = reconcile(
        "The CLI exits 0 on a valid file.",
        [_row("7-c1", "satisfied"), _row("7-c9", "failed")],  # c9 is no longer a criterion
        item_id=7,
    )
    assert [c.claim_id for c in ev.criteria] == ["7-c1"]
    assert "7-c9" not in {c.claim_id for c in ev.criteria}


def test_an_immaterial_criterion_cannot_hold_an_item_back() -> None:
    """Quality-soft phrasing informs review but never gates (`Claim.material`), so it must not gate
    here either — otherwise a stylistic sentence would make an item permanently unfinished."""
    text = "The CLI exits 0 on a valid file.\nThe code should be reasonably clean and readable."
    ev = reconcile(text, [_row("7-c1", "satisfied")], item_id=7)

    soft = [c for c in ev.criteria if not c.material]
    assert soft, "the fixture must actually contain an immaterial criterion"
    assert soft[0].verdict == UNMEASURED
    assert ev.fully_evidenced is True, "an unmeasured IMMATERIAL criterion does not block"


def test_the_evidence_pointer_is_carried_so_a_claim_is_traceable() -> None:
    """`oracle_ref` is a pointer (a location or name), never a value — the provenance rule. Carrying
    it is what lets an operator check the claim rather than take it on faith."""
    ev = reconcile(ACCEPTANCE, [_row("7-c1", "satisfied", "tests/test_cli.py::test_exit_code")], 7)
    assert ev.criteria[0].oracle_ref == "tests/test_cli.py::test_exit_code"
