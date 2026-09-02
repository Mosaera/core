"""Claim schema + derivation (ADR-0079 Wave 1) — pure, offline."""

from __future__ import annotations

import pytest
from mosaera_core.bench.cases import available_cases, load_case
from mosaera_core.claims import (
    SCHEMA_VERSION,
    Claim,
    claims_as_dicts,
    claims_from_acceptance,
    classify_sentence,
)
from mosaera_core.spec_lint import checkability, checkability_findings


def test_claim_schema_roundtrip_and_version() -> None:
    c = Claim("1-c1", 1, "returns the sorted list", "ENTAILED", "acceptance_test")
    d = c.as_dict()
    assert d["schema_version"] == SCHEMA_VERSION == 1
    assert d["material"] is True and d["predicate"] == ""


def test_claim_rejects_unknown_provenance_and_kind() -> None:
    with pytest.raises(ValueError):
        Claim("x", 1, "t", "GUESSED", "acceptance_test")
    with pytest.raises(ValueError):
        Claim("x", 1, "t", "ENTAILED", "vibes")


# ── classification against REAL brief language ───────────────────────────────
def test_structural_phrasing_classifies_as_transformation_contract() -> None:
    # MCB-05's actual acceptance sentence — the historical false-ship class.
    kind, material = classify_sentence(
        "checkout_total should read as a short orchestrator that delegates "
        "to at least three helper functions"
    )
    assert kind == "ast_transformation_contract" and material


def test_behavioural_phrasing_classifies_as_acceptance_test() -> None:
    # MCB-06-shaped: an error contract a test can independently assert.
    kind, material = classify_sentence("raises ConfigError when the file does not exist")
    assert kind == "acceptance_test" and material


def test_tests_unmodified_beats_behavioural() -> None:
    # The bugfix-case invariant — already enforced end-to-end by the tamper guard.
    kind, material = classify_sentence(
        "Do not delete, skip, or weaken any test to make the suite pass"
    )
    assert kind == "tests_unmodified" and material


def test_quality_soft_phrasing_is_non_material() -> None:
    kind, material = classify_sentence("keep the markup semantic and the CSS clean")
    assert kind == "none" and not material


def test_unmatched_hard_sentence_is_material_with_no_oracle() -> None:
    # Deny-by-default: an unclassifiable hard requirement is a PARKED claim, not a dropped one.
    kind, material = classify_sentence("the dashboard feels fast on slow connections")
    assert kind == "none" and material


def test_derivation_is_entailed_and_ordered() -> None:
    claims = claims_from_acceptance(7, "returns 3 for page one. Do not modify any tests.")
    assert [c.id for c in claims] == ["7-c1", "7-c2"]
    assert all(c.provenance == "ENTAILED" for c in claims)
    assert claims[0].oracle_kind == "acceptance_test"
    assert claims[1].oracle_kind == "tests_unmodified"


def test_empty_acceptance_yields_no_claims() -> None:
    assert claims_from_acceptance(1, "") == []
    assert claims_as_dicts([]) == []


# ── checkability verdicts (spec_lint extension) ──────────────────────────────
def _item(item_id: int, acceptance: str, status: str = "todo") -> dict:
    return {"id": item_id, "title": f"item {item_id}", "acceptance": acceptance, "status": status}


def test_checkable_item() -> None:
    v = checkability([_item(1, "search prints matching notes in id order and exits 0")])
    assert v == {1: "CHECKABLE"}


def test_under_specified_item_fires_the_finding() -> None:
    # The liveness proof for this wave's own control (ADR-0081 applied to ADR-0079): the
    # verdict CAN fire, and produces the finding the existing re-curate loop consumes.
    items = [_item(2, "the module is imported and everything is wired together nicely")]
    assert checkability(items)[2] == "UNDER_SPECIFIED"
    findings = checkability_findings(items)
    assert len(findings) == 1 and findings[0].rule == "under_specified"
    assert "#2" in findings[0].detail


def test_empty_acceptance_is_under_specified() -> None:
    assert checkability([_item(3, "")])[3] == "UNDER_SPECIFIED"


def test_partially_checkable_item() -> None:
    v = checkability([_item(4, "returns the merged list. The dashboard feels fast on Mars.")])
    assert v == {4: "PARTIALLY_CHECKABLE"}


def test_settled_items_are_not_judged() -> None:
    assert checkability([_item(5, "", status="delivered")]) == {}


def test_checkable_item_produces_no_finding() -> None:
    assert checkability_findings([_item(6, "prints the id of the new task")]) == []


# ── report rendering (the wave's one read-only consumer) ─────────────────────
def _write(tmp_path, state: dict) -> str:
    from mosaera_core.report import write_report

    path = write_report(
        tmp_path,
        "run-1",
        source="local",
        branch="main",
        workspace_root=tmp_path,
        state=state,
    )
    return path.read_text(encoding="utf-8")


def test_report_renders_claims_section_when_present(tmp_path) -> None:
    claims = claims_as_dicts(
        claims_from_acceptance(9, "returns the sorted list. keep the code clean.")
    )
    text = _write(tmp_path, {"task": "t", "claims": claims})
    assert "## Acceptance claims" in text
    assert "[ENTAILED → acceptance_test]" in text
    assert "*(quality-soft, non-gating)*" in text


def test_report_is_unchanged_without_claims(tmp_path) -> None:
    # ADR-0079 decision 6: absent claims ⇒ pre-claims rendering, byte-for-byte.
    assert "## Acceptance claims" not in _write(tmp_path, {"task": "t"})


# ── consistency with the hand-annotated checkability analysis ────────────────
def test_no_mcb_brief_is_under_specified() -> None:
    """brief-checkability-2026-08-02: all 24 briefs are materially checkable. The deterministic
    derivation must agree — every brief yields at least one bound material claim. (Run against
    the full brief text; a finer per-field check comes when briefs carry structured acceptance.)"""
    for cid in available_cases():
        claims = claims_from_acceptance(None, load_case(cid).brief)
        bound = [c for c in claims if c.material and c.oracle_kind != "none"]
        assert bound, f"{cid}: derivation found no bound material claim — contradicts the analysis"
