"""Splitting a reason cannot change what SHIPS — proven exhaustively, not argued (ADR-0092).

ADR-0090 called a replay analysis mandatory before the `unsatisfied_claim` split, on the theory
that the gate-stall breaker fingerprints `sorted(set(reasons))`. The real hazard turned out to be
elsewhere: the breaker compares within a run only, so a split changes the hash value and not the
equality relation. What genuinely could flip a park into a ship is **suppression** — emitting FEWER
reasons — because `_resolve` has two branches keyed on exact reason sets.

ADR-0092 therefore splits and never suppresses, and this file is the proof of that claim rather
than its restatement. `evaluate_gate` has exactly four ship-or-revise predicates, every one a
POSITIVE test against a fixed literal:

    not reasons                              -> approve
    core == ["reviewer_unknown"] (+evidence)  -> approve
    set(reasons) == {"reviewer_requested_changes"} -> deny_with_feedback
    action = "deliver" if not reasons else "require_human"

Emitting k>=1 reasons exactly where the old code emitted 1 leaves `bool(reasons)` invariant and can
only GROW the list, so all four are pointwise invariant. The sweep below asserts that over the full
input cross-product against a faithful model of the pre-split gate — including the surjection
(every new reason collapses back to exactly the old one), which is what makes "the split is a
refinement" a checked fact.

This ships as a permanent test, not a one-off script: the audit is a property of *this* gate's
source, not a law, and the next reason must land under a proof someone re-ran.
"""

from __future__ import annotations

import itertools
from typing import Any

from mosaera_policies.gate import (
    UNCLASSIFIED_CLAIM_REASON,
    autonomous_resolution,
    evaluate_gate,
)

# Every new reason collapses back to the single string the pre-split gate emitted.
_COLLAPSE = {
    "claim_behavioral_failed": UNCLASSIFIED_CLAIM_REASON,
    "claim_structural_failed": UNCLASSIFIED_CLAIM_REASON,
    "claim_integrity_failed": UNCLASSIFIED_CLAIM_REASON,
}

_CLASS_POWERSET = [
    list(combo)
    for size in range(4)
    for combo in itertools.combinations(("behavioral", "structural", "integrity"), size)
]


def _cells() -> list[dict[str, Any]]:
    """The full input cross-product. Kept explicit so a new gate input is a visible edit here."""
    cells = []
    for tests_passed, verdict, strength, classes in itertools.product(
        (True, False, None),
        ("APPROVE", "REQUEST_CHANGES", "BLOCK", "CONFLICT", ""),
        ("suite", "shallow", "none", "unknown"),
        _CLASS_POWERSET,
    ):
        # `scan_attempted` (ADR-0107) and `scan_fresh`/`review_fresh` (ADR-0108) are HERE because
        # the docstring above requires it and both ADRs skipped it — ADR-0108 went as far as
        # claiming in its Consequences that this edit had been made. Red team, 2026-08-21.
        # "disabled" joins the status axis in the same pass: it is the operator opt-out, and the
        # first cut of the staleness rule minted `security_stale` for it.
        for (
            findings,
            tampered,
            vetoed,
            oracle_ok,
            security,
            iteration,
            attempted,
            scan_fresh,
            review_fresh,
        ) in itertools.product(
            (0, 1),
            (False, True),
            (False, True),
            (False, True),
            ("clean", "unavailable", "disabled"),
            (0, 3),
            (True, False),
            (True, False),
            (True, False),
        ):
            cells.append(
                {
                    "tests_passed": tests_passed,
                    "reviewer_verdict": verdict,
                    "findings_count": findings,
                    "iteration": iteration,
                    "max_iterations": 3,
                    "oracle_verified": oracle_ok,
                    "validation_strength": strength,
                    "tests_tampered": tampered,
                    "critic_vetoed": vetoed,
                    "security_status": security,
                    "scan_attempted": attempted,
                    "scan_fresh": scan_fresh,
                    "review_fresh": review_fresh,
                    "claims_failed": ["c1"] if classes else [],
                    "claims_failed_classes": classes,
                }
            )
    return cells


def test_the_split_changes_no_permission_anywhere_in_the_input_space() -> None:
    """The load-bearing assertion of ADR-0092, over the whole cross-product.

    `old` is the pre-split gate modelled faithfully: identical inputs, but the claim evidence
    reduced to the single legacy reason — which is exactly what passing ids WITHOUT classes still
    does, so the model is the real code path rather than a reimplementation.
    """
    cells = _cells()
    assert len(cells) > 5_000, f"the sweep collapsed to {len(cells)} cells — it is not exhaustive"

    for cell in cells:
        new = evaluate_gate(**cell)
        old = evaluate_gate(**{**cell, "claims_failed_classes": []})

        assert bool(new.reasons) == bool(old.reasons), f"emptiness changed: {cell}"
        assert new.action == old.action, f"action changed: {cell}"
        assert autonomous_resolution(new) == autonomous_resolution(old), f"resolution: {cell}"
        # The refinement property: collapsing every new reason reproduces the old set exactly.
        assert {_COLLAPSE.get(r, r) for r in new.reasons} == set(old.reasons), f"surjection: {cell}"


def test_a_claim_reason_can_never_be_the_sole_blocker_that_ships() -> None:
    """The two `_resolve` allowlist branches are unreachable from any claim reason.

    Stated directly as well as swept, because it is the sentence an operator would want: no
    combination of failed-claim classes makes the gate approve or auto-revise.
    """
    for classes in _CLASS_POWERSET[1:]:
        decision = evaluate_gate(
            tests_passed=True,
            reviewer_verdict="APPROVE",
            findings_count=0,
            iteration=0,
            max_iterations=3,
            oracle_verified=True,
            validation_strength="suite",
            claims_failed=["c1"],
            claims_failed_classes=classes,
        )
        assert autonomous_resolution(decision) == "park", classes
        assert decision.action == "require_human", classes


def test_suppression_is_what_would_have_been_dangerous() -> None:
    """Why ADR-0092 never drops a reason, demonstrated rather than asserted.

    Had the split suppressed the behavioural reason when `validation_failed` was present, this
    otherwise-identical run would have gone from a park to an APPROVAL — the exact failure the
    no-suppression rule exists to make impossible.
    """
    parked = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="",
        findings_count=0,
        iteration=0,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
        claims_failed=["c1"],
        claims_failed_classes=["behavioral"],
    )
    assert autonomous_resolution(parked) == "park"

    # The same run with the claim evidence suppressed: silence becomes the SOLE reason...
    suppressed = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="",
        findings_count=0,
        iteration=0,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
    )
    assert autonomous_resolution(suppressed) == "approve"  # ...and it ships.
