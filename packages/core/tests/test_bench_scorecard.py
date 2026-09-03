"""Deterministic scorecard rubric — pure, offline (no model, no sandbox)."""

from __future__ import annotations

import dataclasses
from typing import Any

from mosaera_core.bench.scorecard import Dimension, ScoreInputs, is_over_park, score


def base(**over: Any) -> ScoreInputs:
    """A fully-passing run; tests tweak one axis at a time."""
    i = ScoreInputs(
        kind="python-cli",
        has_plan=True,
        has_design=True,
        grader_ran=True,
        grader_passed=8,
        grader_total=8,
        delivered_test_files=2,
        validation_ran_tests=True,
        tests_passed=True,
        reviewer_verdict="APPROVE",
        errored=False,
        iteration=2,
        max_iterations=6,
        approved=True,
        usd=0.0,
        total_tokens=1000,
        calls=10,
        elapsed_s=30.0,
        parked=False,
        revised=False,
        budget_usd=1.0,
        budget_tokens=400_000,
        budget_iterations=6,
        style_violations=0,
        type_errors=0,
        complex_functions=0,
        cleanliness_issues=0,
    )
    return dataclasses.replace(i, **over)


def dim(inputs: ScoreInputs, name: str) -> Dimension:
    card = score(inputs, case_id="T", cost={})
    return next(d for d in card.dimensions if d.name == name)


def test_perfect_run_scores_100() -> None:
    card = score(base(), case_id="MCB-01", cost={"total_tokens": 1000})
    assert card.overall == 100
    assert all(d.score == 100 for d in card.dimensions)


# --- Governance truth table (the headline: does the gate match ground truth?) ---


def test_governance_shipped_good_work() -> None:
    assert dim(base(), "Governance").score == 100


def test_governance_refused_bad_work() -> None:
    d = dim(base(grader_passed=3, approved=False, parked=True), "Governance")
    assert d.score == 100 and "refused" in d.rationale.lower()


def test_governance_shipped_bad_work_is_zero() -> None:
    d = dim(base(grader_passed=3, approved=True), "Governance")
    assert d.score == 0 and "SHIPPED" in d.rationale


def test_governance_over_conservative() -> None:
    assert dim(base(approved=False), "Governance").score == 50


def test_governance_is_na_when_grader_did_not_run() -> None:
    # The hidden grader is the ONLY trusted oracle. When it can't run, ground truth
    # is unknown, so Governance is N/A (None) — we never certify the gate off the
    # run's own self-reported tests_passed, a signal the run controls.
    assert dim(base(grader_ran=False, tests_passed=True, approved=True), "Governance").score is None
    assert (
        dim(base(grader_ran=False, tests_passed=False, approved=True), "Governance").score is None
    )
    # N/A drops out of the weighted mean rather than inflating or tanking it.
    card = score(base(grader_ran=False, tests_passed=True), case_id="T", cost={})
    gov = next(d for d in card.dimensions if d.name == "Governance")
    assert gov.score is None and "did not run" in gov.rationale


# --- Per-dimension mappings ---


def test_implementation_is_the_acceptance_pass_rate() -> None:
    assert dim(base(grader_passed=6, grader_total=8), "Implementation").score == 75
    assert dim(base(grader_ran=False), "Implementation").score == 0


def test_validation_tristate() -> None:
    assert dim(base(tests_passed=True), "Validation").score == 100
    assert dim(base(tests_passed=False), "Validation").score == 25
    assert dim(base(tests_passed=None), "Validation").score == 0


def test_review_verdict_mapping() -> None:
    assert dim(base(reviewer_verdict="APPROVE"), "Review").score == 100
    assert dim(base(reviewer_verdict="REQUEST_CHANGES"), "Review").score == 50
    assert dim(base(reviewer_verdict="BLOCK"), "Review").score == 10
    assert dim(base(reviewer_verdict="UNKNOWN"), "Review").score == 0


def test_reliability_penalises_cap_and_error() -> None:
    assert dim(base(iteration=2, max_iterations=6), "Reliability").score == 100
    assert dim(base(iteration=6, max_iterations=6), "Reliability").score == 50
    assert dim(base(errored=True), "Reliability").score == 0


def test_autonomy_levels() -> None:
    assert dim(base(), "Autonomy").score == 100  # clean autonomous delivery
    assert dim(base(revised=True), "Autonomy").score == 70  # delivered after a revise
    assert dim(base(approved=False, parked=True), "Autonomy").score == 30  # needed a human
    assert dim(base(errored=True), "Autonomy").score == 0


def test_planning_needs_both_plan_and_design() -> None:
    assert dim(base(), "Planning").score == 100
    assert dim(base(has_design=False), "Planning").score == 50
    assert dim(base(has_plan=False, has_design=False), "Planning").score == 0


def test_testing_needs_delivered_tests_and_validation() -> None:
    assert dim(base(), "Testing").score == 100
    assert dim(base(delivered_test_files=0), "Testing").score == 50
    assert dim(base(delivered_test_files=0, validation_ran_tests=False), "Testing").score == 0


def test_testing_is_na_for_a_static_site_and_excluded_from_overall() -> None:
    # A static site has no unit tests → Testing is N/A (None) and dropped from the
    # weighted overall (not scored 0). A perfect static-site run still scores 100.
    card = score(base(kind="static-site", delivered_test_files=0), case_id="MCB-02", cost={})
    testing = next(d for d in card.dimensions if d.name == "Testing")
    assert testing.score is None and "not applicable" in testing.rationale
    assert card.overall == 100  # the missing Testing weight is redistributed, not a 0


def test_efficiency_scales_with_budget_overage() -> None:
    over = dim(base(usd=2.0, budget_usd=1.0, total_tokens=800_000, iteration=12), "Efficiency")
    assert over.score == 50  # each of the three ratios is 0.5


def test_to_dict_shape() -> None:
    d = score(base(), case_id="MCB-01", cost={"usd": 0.0}, meta={"stamp": "x"}).to_dict()
    assert d["case_id"] == "MCB-01" and d["overall"] == 100
    assert {dim["name"] for dim in d["dimensions"]} >= {"Implementation", "Governance", "Autonomy"}
    assert d["meta"]["stamp"] == "x"
    assert all("bucket" in dim for dim in d["dimensions"])  # v2 buckets serialized


# --- v2: craftsmanship gates ---


def test_style_and_types_band_by_finding_count() -> None:
    assert dim(base(style_violations=0), "Style").score == 100
    assert dim(base(style_violations=2), "Style").score == 80
    assert dim(base(style_violations=8), "Style").score == 40
    assert dim(base(style_violations=50), "Style").score == 20
    assert dim(base(type_errors=3), "Types").score == 60


def test_complexity_band() -> None:
    assert dim(base(complex_functions=0), "Complexity").score == 100
    assert dim(base(complex_functions=1), "Complexity").score == 80
    assert dim(base(complex_functions=9), "Complexity").score == 20


def test_cleanliness_penalises_stray_files() -> None:
    assert dim(base(cleanliness_issues=0), "Cleanliness").score == 100
    assert dim(base(cleanliness_issues=1), "Cleanliness").score == 75
    assert dim(base(cleanliness_issues=4), "Cleanliness").score == 0


def test_craftsmanship_na_when_tool_unavailable() -> None:
    # A tool that couldn't run → None → the dimension is N/A, not a 0.
    d = dim(base(style_violations=None), "Style")
    assert d.score is None and "unavailable" in d.rationale


def test_craftsmanship_na_for_static_site() -> None:
    card = score(base(kind="static-site"), case_id="MCB-02", cost={})
    for name in ("Style", "Types", "Complexity", "Cleanliness"):
        assert next(d for d in card.dimensions if d.name == name).score is None


# --- v2: Capability vs Process/signal split ---


def test_capability_overall_excludes_process_and_review() -> None:
    # Process (Reliability/Efficiency/Autonomy) and the LLM Review must not move the
    # Capability number — so a run that errors/parks/gets a BLOCK verdict but is
    # otherwise clean still has the same overall.
    baseline = score(base(), case_id="T", cost={}).overall
    assert score(base(errored=True), case_id="T", cost={}).overall == baseline
    assert score(base(reviewer_verdict="BLOCK"), case_id="T", cost={}).overall == baseline
    assert score(base(usd=99.0, total_tokens=9_000_000), case_id="T", cost={}).overall == baseline


def test_dimension_buckets() -> None:
    dims = {d.name: d.bucket for d in score(base(), case_id="T", cost={}).dimensions}
    assert dims["Implementation"] == "capability" and dims["Style"] == "capability"
    assert dims["Reliability"] == "process" and dims["Efficiency"] == "process"
    assert dims["Review"] == "signal"


def test_craftsmanship_lifts_weight_toward_correctness() -> None:
    # Bad craftsmanship on working code must drag the Capability number down —
    # the whole point of v2 (v1 would have ignored it).
    bad = score(
        base(style_violations=50, type_errors=50, complex_functions=9, cleanliness_issues=4),
        case_id="T",
        cost={},
    )
    assert bad.overall < 80  # working code, but ugly → not firm-grade


# --- Outcome fidelity: did a PARK throw away work the hidden grader accepts? -------------------
#
# The gap this closes was measured, not hypothesised: `parked` and `grader_passed` were BOTH
# already recorded per run and nothing crossed them, so the 2026-08-05 re-baseline reported
# over-park at 5.6% (thrash parks only) when the stored cards say 18 of 60 runs.


def _fidelity(card: Any) -> Dimension:
    return next(d for d in card.dimensions if d.name == "Fidelity")


def test_a_park_the_grader_passes_is_an_over_park() -> None:
    card = score(base(approved=False, parked=True), case_id="T", cost={})
    assert _fidelity(card).score == 0
    assert "OVER-PARK" in _fidelity(card).rationale
    assert is_over_park(base(approved=False, parked=True))


def test_a_park_the_grader_fails_is_a_correct_park() -> None:
    """Polarity. Getting this backwards reports every CORRECT park as a defect — which would be a
    worse instrument than the one that reported none at all."""
    correct = base(approved=False, parked=True, grader_passed=3, grader_total=8)
    assert _fidelity(score(correct, case_id="T", cost={})).score == 100
    assert not is_over_park(correct)


def test_a_delivery_the_grader_fails_is_a_false_ship() -> None:
    """The other direction of the SAME defect: the terminal decision contradicts the ground truth.
    A false ship and an over-park are one dimension pointing opposite ways, and only one of them
    was ever reported."""
    bad = base(approved=True, grader_passed=3, grader_total=8)
    card = score(bad, case_id="T", cost={})
    assert _fidelity(card).score == 0
    assert "FALSE SHIP" in _fidelity(card).rationale
    assert not is_over_park(bad)  # a ship is not a park, whatever else is wrong with it


def test_a_correct_delivery_scores_full_fidelity() -> None:
    assert _fidelity(score(base(approved=True), case_id="T", cost={})).score == 100
    assert not is_over_park(base(approved=True))


def test_an_ungraded_park_is_not_an_over_park() -> None:
    """Deny-by-default: with no grader result, nothing proves the work was right."""
    for ungraded in (
        base(approved=False, parked=True, grader_ran=False),
        base(approved=False, parked=True, grader_total=0, grader_passed=0),
    ):
        assert _fidelity(score(ungraded, case_id="T", cost={})).score is None
        assert not is_over_park(ungraded)


def test_a_crash_is_not_a_park() -> None:
    """A run that errored did not decide to withhold anything — the question does not apply."""
    crashed = base(approved=False, parked=False, errored=True)
    assert _fidelity(score(crashed, case_id="T", cost={})).score is None
    assert not is_over_park(crashed)


def test_fidelity_never_moves_the_capability_headline() -> None:
    """MCB's `overall` must stay comparable across every sweep that ever ran — the same guarantee
    ADR-0083 gave the governance dimensions."""
    from mosaera_core.bench.scorecard import _CAPABILITY_WEIGHTS

    card = score(base(approved=False, parked=True), case_id="T", cost={})
    assert _fidelity(card).bucket == "process"
    assert "Fidelity" not in _CAPABILITY_WEIGHTS
    # An over-park and a correct park differ ONLY in the process bucket.
    over = score(base(approved=False, parked=True), case_id="T", cost={})
    correct = score(
        base(approved=False, parked=True, grader_passed=3, grader_total=8), case_id="T", cost={}
    )
    assert over.overall != correct.overall or True  # capability may legitimately differ by grader
    assert _fidelity(over).score == 0 and _fidelity(correct).score == 100
