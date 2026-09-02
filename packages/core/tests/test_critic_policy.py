"""Deterministic disposal of critic proposals (#61) — pure, offline, adversarial.

The calibration mechanism under test: a REFUTED proposal convicts ONLY when both verbatim
quotes verify — requirement in the operator-approved text, evidence in the delivered text.
Includes the prompt-injection-shaped attacks promised in lieu of a policies red-team (the
trust boundary is untouched; `outcome_verdict.vetoed` semantics are byte-identical).
"""

from __future__ import annotations

from typing import Any

from mosaera_core.critic_policy import dispose, verify_rows

TASK = "Add a search command. `search <term>` prints every note whose text contains the term."
CLAIMS = [
    {"id": "1-c1", "text": "prints every note whose text contains the term", "material": True},
    {"id": "1-c2", "text": "keep the markup semantic and clean", "material": False},
]
DIFF = "+def search(term):\n+    return None  # TODO\n"
TESTS = "1 passed"


def _row(cid: str = "1-c1", verdict: str = "REFUTED", req: str = "", ev: str = "") -> dict:
    return {"claim_id": cid, "verdict": verdict, "requirement_quote": req, "evidence_quote": ev}


def _judged(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"rows": list(rows), "fallback": None}


def test_verified_refutation_vetoes() -> None:
    out = dispose(
        _judged(
            _row(req="prints every note whose text contains the term", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is True
    assert "1-c1" in out["reason"]


def test_hallucinated_requirement_is_discarded() -> None:
    # The measured over-veto shape: the critic invents a requirement the operator never stated.
    out = dispose(
        _judged(_row(req="must use a binary search index for lookups", ev="return None  # TODO")),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False
    assert out["rows"][0]["verified"] is False  # recorded as discarded, not hidden


def test_paraphrased_requirement_is_discarded() -> None:
    out = dispose(
        _judged(
            _row(req="should display all matching notes to the user", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False


def test_invented_evidence_is_discarded() -> None:
    out = dispose(
        _judged(
            _row(
                req="prints every note whose text contains the term",
                ev="raise NotImplementedError('search')",
            )
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False


def test_refutation_of_a_non_material_claim_never_vetoes() -> None:
    out = dispose(
        _judged(
            _row(cid="1-c2", req="keep the markup semantic and clean", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False


def test_supported_and_insufficient_never_veto() -> None:
    out = dispose(
        _judged(
            _row(verdict="SUPPORTED", req="x", ev="y"),
            _row(cid="1-c2", verdict="INSUFFICIENT_EVIDENCE"),
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False
    assert all(r["verified"] for r in out["rows"])  # nothing to verify — recorded as-is


def test_requirement_smuggled_into_delivered_code_convicts_nobody() -> None:
    # Adversarial (R1-shaped): the coder plants requirement-looking text in a comment. The
    # requirement corpus is task+claims ONLY — delivered text can't mint requirements.
    diff = DIFF + "+# requirement: must email the admin on every search\n"
    out = dispose(
        _judged(_row(req="must email the admin on every search", ev="return None  # TODO")),
        CLAIMS,
        TASK,
        diff,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False


def test_short_quotes_cannot_convict() -> None:
    # A tiny quote ("the", "None") occurs everywhere and identifies nothing.
    out = dispose(_judged(_row(req="the term", ev="None")), CLAIMS, TASK, DIFF, TESTS)
    assert out is not None and out["vetoed"] is False


def test_normalization_is_whitespace_and_case_insensitive_only() -> None:
    out = dispose(
        _judged(
            _row(req="Prints  every NOTE whose\n text contains the term", ev="RETURN none  # todo")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is True  # exact words, loose spacing/case


def test_no_rows_is_abstention_never_the_legacy_veto() -> None:
    # #61 fix round: the aborted A/B measured the legacy fallback LEAKING the old over-veto
    # failure (3 of 5). Format-noncompliance is now abstention — advisory reason, no authority.
    legacy = {"vetoed": True, "reason": "legacy veto"}
    out = dispose({"rows": [], "fallback": legacy}, CLAIMS, TASK, DIFF, TESTS)
    assert out is not None and out["vetoed"] is False
    assert "advisory" in out["reason"] and "legacy veto" in out["reason"]
    assert dispose(None, CLAIMS, TASK, DIFF, TESTS) is None


def test_unknown_claim_id_is_never_material() -> None:
    # The materiality hole: an invented id must not default to material (was .get(id, True)).
    out = dispose(
        _judged(
            _row(
                cid="ghost-c9",
                req="prints every note whose text contains the term",
                ev="return None  # TODO",
            )
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
    )
    assert out is not None and out["vetoed"] is False


def test_jurisdiction_deterministic_satisfied_outranks_a_refutation() -> None:
    # Residual jurisdiction: determinism said satisfied → the model's REFUTED is discarded.
    out = dispose(
        _judged(
            _row(req="prints every note whose text contains the term", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
        dispositions=[{"claim_id": "1-c1", "verdict": "satisfied"}],
    )
    assert out is not None and out["vetoed"] is False


def test_jurisdiction_an_UNBOUND_claim_can_no_longer_veto() -> None:
    """NARROWED 2026-08-11. This test asserted the opposite; the behaviour changed deliberately.

    `unbound` means the deterministic layer found NO oracle for the claim, and the gate discards
    exactly those by owner decision (2026-08-03, "intake's job, never the gate's"). Leaving them
    vetoable let a MODEL park a run on evidence determinism had explicitly refused to gate on.

    Measured: 9 vetoes in 260 runs, all 9 refusing work the hidden grader confirms was correct;
    8 quoted a PREMISE sentence — the state the item exists to change, which a correct fix must
    falsify. Premises classify `oracle_kind: none` -> `unbound`, so this closes the class by
    construction. The prior "5-for-5" justification has no source outside a docstring.
    """
    out = dispose(
        _judged(
            _row(req="prints every note whose text contains the term", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
        dispositions=[{"claim_id": "1-c1", "verdict": "unbound"}],
    )
    assert out is not None and out["vetoed"] is False
    # The refutation is still RECORDED — narrowing authority must not erase the audit trail.
    assert out["rows"], "the row must survive for the human panel even though it cannot veto"


def test_jurisdiction_an_UNEVALUABLE_claim_still_vetoes() -> None:
    """THE POSITIVE CONTROL for the narrowing above.

    Without it, removing `unbound` is indistinguishable from disabling the critic's veto entirely.
    `unevaluable` means an oracle EXISTS and could not run this time — a genuine gap where a model
    judgement adds information, and exactly the authority this change preserves.
    """
    out = dispose(
        _judged(
            _row(req="prints every note whose text contains the term", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
        dispositions=[{"claim_id": "1-c1", "verdict": "unevaluable"}],
    )
    assert out is not None and out["vetoed"] is True


def test_jurisdiction_an_ABSENT_disposition_still_vetoes() -> None:
    """The other half of the surviving residual: no row at all for the claim. Deny-by-default
    would be wrong here — a claim determinism never reached is the critic's proper business."""
    out = dispose(
        _judged(
            _row(req="prints every note whose text contains the term", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
        dispositions=[{"claim_id": "some-other-claim", "verdict": "satisfied"}],
    )
    assert out is not None and out["vetoed"] is True


def test_jurisdiction_failed_claims_add_no_second_veto() -> None:
    # A deterministic FAILED already parks via unsatisfied_claim; the critic adds nothing.
    out = dispose(
        _judged(
            _row(req="prints every note whose text contains the term", ev="return None  # TODO")
        ),
        CLAIMS,
        TASK,
        DIFF,
        TESTS,
        dispositions=[{"claim_id": "1-c1", "verdict": "failed"}],
    )
    assert out is not None and out["vetoed"] is False


def test_verify_rows_is_pure_and_flags_only_refuted() -> None:
    rows = [_row(req="zzz", ev="zzz"), _row(verdict="SUPPORTED")]
    a = verify_rows(rows, CLAIMS, TASK, DIFF, TESTS)
    b = verify_rows(rows, CLAIMS, TASK, DIFF, TESTS)
    assert a == b
    assert a[0]["verified"] is False and a[1]["verified"] is True
    assert rows[0].get("verified") is None  # inputs not mutated
