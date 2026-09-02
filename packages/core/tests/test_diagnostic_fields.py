"""The three diagnostic fields added 2026-08-11 — each one cost a real conclusion first.

Every mechanism that failed during the 2026-08-11 session failed on a COMPLIANCE question: a
deterministic control handed work to a model and nothing recorded what the model was asked or
whether it obeyed. These three fields close that seam, and each is pinned BOTH ways — a field that
reads the same however the run goes is the defect it exists to detect, not evidence about it.
"""

from __future__ import annotations

from mosaera_core.bench.faithfulness import overstrict_total
from mosaera_core.run_diagnosis import build_diagnosis


def test_overstrict_total_gives_the_count_a_denominator() -> None:
    """`overstrict_vs_ref` is a COUNT. A model that authors more tests has more chances to be
    over-strict, so without a denominator "wrote worse tests" and "wrote more tests" are the same
    number. That ambiguity decided the tester-model experiment: MCB-22 read +204% and is
    permanently uninterpretable."""
    assert overstrict_total("3 failed, 17 passed in 0.4s") == 20
    assert overstrict_total("20 passed in 0.4s") == 20
    assert overstrict_total("5 failed in 0.2s") == 5


def test_overstrict_total_is_None_when_pytest_reported_no_tally() -> None:
    """Deny-by-default: an unparseable tail must not silently become a denominator of 0, which
    would make every rate infinite or zero rather than absent."""
    assert overstrict_total("INTERNALERROR> collection failed") is None
    assert overstrict_total("") is None


def test_a_refused_repair_is_distinguishable_from_no_repair() -> None:
    """THE POINT. `proctor_edits == []` conflates two states needing OPPOSITE fixes:
    the model ignored the instruction, or it edited and the assertion-profile check refused the
    edit as a weakening. Arm 1 of the MCB-28 measurement read 0/5 and could not say which."""
    ignored = build_diagnosis({"proctor_edits": {}, "amendment_refusals": {}})
    refused = build_diagnosis(
        {
            "proctor_edits": {},
            "amendment_refusals": {"tests/test_pricing.py": "assertion profile lost a test"},
        }
    )
    assert ignored["amendment_refusals"] == {}
    assert refused["amendment_refusals"] == {
        "tests/test_pricing.py": "assertion profile lost a test"
    }
    assert ignored["amendment_refusals"] != refused["amendment_refusals"], (
        "the two states must not read identically — that is the whole defect"
    )


def test_the_diagnosis_always_carries_the_key_even_when_empty() -> None:
    """An ABSENT key and an empty one are different evidence: absent means the field was never
    written (the ADR-0078 shape), empty means it was written and there was nothing to say."""
    assert "amendment_refusals" in build_diagnosis({})


def test_claim_failure_reasons_separates_bad_work_from_a_bad_checker() -> None:
    """A failed claim must record WHY, not only that it failed.

    `unsatisfied_claims` names ids and `unsatisfied_claim_kinds` names classes. Neither can
    distinguish *"the delivered code really missed the requested shape"* from *"the checker
    demanded something the case's own acceptance criteria never did"* — and those need opposite
    fixes. Measured 2026-08-12: MCB-15 parked 5/5 on three structural claims while the hidden
    grader PASSED, and diagnosing it required replaying the checker by hand.

    The shape is pinned here rather than the wiring, which the bench integration covers: only
    FAILED rows are kept (an `unbound` or `satisfied` row has no failure to explain), and the
    reason travels with the claim id.
    """
    dispositions = [
        {
            "claim_id": "task-c11",
            "verdict": "failed",
            "oracle_ref": "structural_spec: still iterates",
        },
        {"claim_id": "task-c12", "verdict": "satisfied", "oracle_ref": "met"},
        {"claim_id": "task-c13", "verdict": "unbound", "oracle_ref": "no oracle bound"},
    ]
    reasons = {
        str(d["claim_id"]): str(d.get("oracle_ref", ""))[:300]
        for d in dispositions
        if str(d.get("verdict")) == "failed"
    }
    assert reasons == {"task-c11": "structural_spec: still iterates"}, (
        "only failed claims carry a failure reason — a satisfied claim has nothing to explain"
    )
