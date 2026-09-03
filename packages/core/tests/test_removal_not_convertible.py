"""An unproven removal must never be auto-shippable (verb-arc slice 1, the hole it closes).

This is the reason `non_use` got its OWN evidence class instead of reusing `structural`, and it is
worth stating as a test rather than a comment because the cheap version was genuinely tempting.

`claim_structural_failed` is the exact bucket ADR-0094 widened for Layer-2 eligibility on
2026-08-09. Had an unproven removal emitted that reason, it would have become **auto-ship-eligible
the moment the widening knob is on** — and Layer 2 verifies by asking a held-out model to author a
BEHAVIOURAL acceptance test and then checking it catches a mutation. That procedure says exactly
nothing about whether the removed symbol is still referenced. A removal that breaks every caller
can pass a behavioural test suite of the code that remains.

So the separation is structural, not procedural: the reason is in no admissible class, and these
tests pin that with the knob explicitly ON — the configuration where the hole would open.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.eligibility import convertible_decline_reason, convertible_park_class
from mosaera_policies.gate import REASON_CLASS, reason_class
from mosaera_policies.standards import NOT_PROOF_BEARING, PROOF_BEARING


def _park(*reasons: str) -> dict[str, Any]:
    return {
        "gate_decision": {"reasons": list(reasons)},
        "tests_passed": True,
        "tests_modified": False,
    }


def test_a_removal_park_is_refused_with_the_widening_knob_ON() -> None:
    """THE test. With `admit_structural_claim=True` — the configuration ADR-0094 added — an
    unproven removal must still be refused."""
    final = _park("removal_unproven")
    assert convertible_park_class(final, admit_structural_claim=True) is None
    assert convertible_decline_reason(final, admit_structural_claim=True) != ""


def test_it_is_refused_alongside_the_widened_reason_too() -> None:
    """The composite case: a park carrying BOTH the widened structural claim and an unproven
    removal. The widening must not drag the removal in with it."""
    final = _park("claim_structural_failed", "removal_unproven")
    assert convertible_park_class(final, admit_structural_claim=True) is None


def test_the_reason_is_an_objection_not_a_shortfall() -> None:
    """Class 2's admission policy is derived from `REASON_CLASS` (`shortfall`/`incidental`), so the
    classification IS the enforcement — a `shortfall` here would silently admit it."""
    assert reason_class("removal_unproven") == "objection"
    assert "removal_unproven" in REASON_CLASS


def test_it_is_in_no_admissible_class_for_the_give_up_arm() -> None:
    from mosaera_core.eligibility import give_up_allowed_reasons

    assert "removal_unproven" not in give_up_allowed_reasons()


def test_it_is_proof_bearing_so_no_clause_can_waive_it() -> None:
    """It fires precisely BECAUSE proof is absent, so a waiver would remove the only evidence
    standing between a removal and every caller it breaks.

    The registry guard caught this during implementation — its own error message names the
    precedent: `validation_not_attempted` went unprotected for six days because the check was
    one-directional.
    """
    assert "removal_unproven" in PROOF_BEARING
    assert "removal_unproven" not in NOT_PROOF_BEARING


# --- slice 4: the same hole, closed the same way ------------------------------------------------


def test_an_unassessed_impact_park_is_refused_with_the_knob_ON() -> None:
    """An unassessed behaviour change must never be auto-shippable, for the reason `removal` has
    its own class: Layer 2 verifies by authoring a BEHAVIOURAL acceptance test and mutating it —
    which is precisely the evidence a behaviour CHANGE invalidates. It would convert a change
    nothing witnesses, against criteria derived from the behaviour being replaced."""
    final = _park("impact_unassessed")
    assert convertible_park_class(final, admit_structural_claim=True) is None
    assert convertible_decline_reason(final, admit_structural_claim=True) != ""
    assert (
        convertible_park_class(
            _park("claim_structural_failed", "impact_unassessed"), admit_structural_claim=True
        )
        is None
    )


def test_the_impact_reason_is_an_objection_and_proof_bearing() -> None:
    assert reason_class("impact_unassessed") == "objection"
    assert "impact_unassessed" in PROOF_BEARING
    assert "impact_unassessed" not in NOT_PROOF_BEARING
    from mosaera_core.eligibility import give_up_allowed_reasons

    assert "impact_unassessed" not in give_up_allowed_reasons()
