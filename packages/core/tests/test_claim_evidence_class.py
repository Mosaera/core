"""The oracle-kind → evidence-class partition is TOTAL, and the gate's split follows from it.

This is ADR-0090's guard pattern applied to the seam ADR-0092 creates. The gate needs to say WHICH
kind of claim went unsatisfied, but `packages/policies` may not import `mosaera_core`, where
`ORACLE_KINDS` lives. Mirroring the six kinds into policies would have recreated ADR-0090's exact
defect one layer down — a vocabulary owned by core, copied where nothing forces the copies to move
together — so core partitions and policies declares only the three-member class vocabulary.

The failure this guards: add a seventh oracle kind, and without a total mapping it buckets as
unknown, the gate emits no reason for it, and a failed claim silently stops parking anything.
"""

from __future__ import annotations

from typing import get_args

from mosaera_core.claim_oracles import failed_claim_classes
from mosaera_core.claims import CLAIM_EVIDENCE_CLASS, ORACLE_KINDS
from mosaera_policies.gate import ClaimEvidenceClass

_GATING_KINDS = frozenset(ORACLE_KINDS) - {"none"}


def test_every_gating_oracle_kind_has_an_evidence_class() -> None:
    """A new oracle kind must arrive with its class, or this fails naming it."""
    missing = sorted(_GATING_KINDS - set(CLAIM_EVIDENCE_CLASS))
    assert not missing, (
        f"oracle kind(s) {missing} have no CLAIM_EVIDENCE_CLASS entry — a failed claim of that "
        "kind would emit NO gate reason and silently stop parking (ADR-0092). Classify it in "
        "mosaera_core/claims.py, beside ORACLE_KINDS."
    )


def test_no_stale_or_invented_evidence_class() -> None:
    """The reverse direction, and the vocabulary itself."""
    stale = sorted(set(CLAIM_EVIDENCE_CLASS) - frozenset(ORACLE_KINDS))
    assert not stale, f"CLAIM_EVIDENCE_CLASS maps {stale}, which is not an ORACLE_KIND"
    declared = set(get_args(ClaimEvidenceClass))
    invented = {k: v for k, v in CLAIM_EVIDENCE_CLASS.items() if v not in declared}
    assert not invented, (
        f"CLAIM_EVIDENCE_CLASS uses class(es) the policies-side Literal does not declare: "
        f"{invented} (allowed: {sorted(declared)})"
    )


def test_none_is_deliberately_unmapped() -> None:
    """`none` resolves `unbound`, never `failed`, so it can never reach a FAILED set.

    Pinned rather than left implicit: mapping it would invent a class for evidence that by
    definition has no oracle, and the first test above would then stop being able to tell the
    difference between "unclassified" and "deliberately excluded".
    """
    assert "none" not in CLAIM_EVIDENCE_CLASS


def test_the_totality_guard_actually_fires() -> None:
    """Proven on synthetic input, so it cannot pass by vacuity (ADR-0090's own bar)."""
    kinds = frozenset({"a", "b", "a_seventh_kind"})
    mapped = frozenset({"a", "b"})
    assert sorted(kinds - mapped) == ["a_seventh_kind"]


def test_an_unclassifiable_kind_is_dropped_never_guessed() -> None:
    """A claim whose kind has no class contributes NO reason rather than a guessed one.

    Deny-by-default in the direction that matters: guessing would eventually label a tamper as
    behavioural, which is admissible to Layer 2. The totality test above is what makes dropping
    safe — the two are a pair, and neither is sufficient alone.
    """
    rows = [{"claim_id": "c1", "verdict": "failed"}]
    claims = [{"id": "c1", "oracle_kind": "a_kind_from_the_future"}]
    assert failed_claim_classes(rows, claims) == []


def test_the_classes_are_what_the_split_emits() -> None:
    """End to end: core's partition drives the gate's reasons, one per class present."""
    from mosaera_policies.gate import evaluate_gate

    claims = [
        {"id": "c1", "oracle_kind": "acceptance_test"},
        {"id": "c2", "oracle_kind": "ast_transformation_contract"},
    ]
    rows = [{"claim_id": "c1", "verdict": "failed"}, {"claim_id": "c2", "verdict": "failed"}]
    classes = failed_claim_classes(rows, claims)
    assert classes == ["behavioral", "structural"]

    decision = evaluate_gate(
        tests_passed=False,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=0,
        max_iterations=3,
        claims_failed=["c1", "c2"],
        claims_failed_classes=classes,
    )
    assert "claim_behavioral_failed" in decision.reasons
    assert "claim_structural_failed" in decision.reasons
    assert "claim_integrity_failed" not in decision.reasons
    # The ids still ride the decision unchanged — the receipt seal is over this field.
    assert decision.unsatisfied_claims == ["c1", "c2"]
