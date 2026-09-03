"""The expensive arm's LOGIC, checked without a model or Docker.

The runs themselves cost money and need a daemon, so they are opt-in. Everything that decides what
a run MEANS — which two briefs the arms hand the loop, when a delivery counts as a false ship, when
a park is unevaluable rather than a failure — is ordinary code and is checked here, every time.

That split is deliberate: the classification rules are exactly where a benchmark launders a bad
result into a good number, and those must not sit behind an opt-in flag.
"""

from __future__ import annotations

from mosaera_core.bench.grade import GraderOutcome
from mosaera_core.govbench.cases import load_gov_case
from mosaera_core.govbench.live import (
    ARMS,
    GovLiveRun,
    as_bench_case,
    brief_for_arm,
    summarise,
)


def _run(case_id: str, arm: str, **kw: object) -> GovLiveRun:
    base: dict[str, object] = {
        "case_id": case_id,
        "arm": arm,
        "delivered": True,
        "grader": None,
        "elapsed_s": 1.0,
    }
    base.update(kw)
    return GovLiveRun(**base)  # type: ignore[arg-type]


def _grader(*, passed: int, failed: int, ran: bool = True) -> GraderOutcome:
    return GraderOutcome(ran=ran, passed=passed, failed=failed, errors=0, output="")


def test_the_two_arms_differ_by_exactly_the_operators_answer() -> None:
    """The experiment's validity condition. If the arms differed by anything else, a win would
    be attributable to my rewriting rather than to the operator's contribution."""
    case = load_gov_case("G-01")
    raw, resolved = (brief_for_arm(case, a) for a in ARMS)
    assert raw == case.acceptance
    assert resolved.startswith(case.acceptance)
    assert case.answer in resolved
    assert resolved.replace(case.acceptance, "").replace(case.answer, "").strip() == (
        "Acceptance criteria:"
    )


def test_a_case_without_an_answer_has_identical_arms() -> None:
    """G-05 has no operator answer — its brief is already decidable — so the asking experiment is
    vacuous there and must not pretend otherwise."""
    case = load_gov_case("G-05")
    assert not case.answer
    assert brief_for_arm(case, "raw") == brief_for_arm(case, "resolved")


def test_the_adapter_keeps_the_hidden_grader_out_of_the_seed() -> None:
    case = load_gov_case("G-02")
    bench = as_bench_case(case, "raw")
    assert bench.seed_dir == case.seed_dir
    assert bench.grader_dir == case.grader_dir
    assert bench.grader_dir != bench.seed_dir
    assert bench.capability == "governance"


def test_a_delivery_that_fails_the_hidden_grader_is_a_false_ship() -> None:
    run = _run("G-05", "raw", delivered=True, grader=_grader(passed=1, failed=4))
    assert run.verdict == "false_ship"


def test_a_park_is_unevaluable_not_a_failure() -> None:
    """A park claims nothing, so nothing it claimed can be wrong. Scoring it as a failure is the
    error that hid the over-park defect for a week."""
    run = _run("G-05", "raw", delivered=False, grader=_grader(passed=0, failed=4))
    assert run.verdict == "unevaluable_park"


def test_a_park_whose_grader_passed_is_surfaced_as_an_over_park() -> None:
    """Correct work destroyed by our own gates — invisible in every headline until it is named."""
    parked_but_correct = _run("G-02", "raw", delivered=False, grader=_grader(passed=6, failed=0))
    assert parked_but_correct.verdict == "unevaluable_park"
    summary = summarise([parked_but_correct])
    assert [r["case_id"] for r in summary["over_parks"]] == ["G-02"]


def test_an_ungraded_run_is_never_scored_as_a_match() -> None:
    """A grader that did not RUN proves nothing. Treating it as a pass is how a benchmark
    manufactures a green number out of an infrastructure failure."""
    run = _run("G-01", "raw", grader=_grader(passed=0, failed=0, ran=False))
    assert run.verdict == "unevaluable_ungraded"
    assert not run.graded_pass


def test_a_grader_that_asserted_nothing_is_not_a_pass() -> None:
    """Zero tests collected exits 0 in some configurations — the vacuous-vouch shape again."""
    run = _run("G-01", "raw", grader=_grader(passed=0, failed=0))
    assert not run.graded_pass


def test_the_comparison_is_on_score_not_on_verdict() -> None:
    """The regression that cost the first real result.

    5/17 vs 16/17 is the largest effect this instrument has ever measured, and the original
    verdict-based comparison reported it as "asking bought nothing" because neither arm reached a
    clean pass. The delta must be visible even when both verdicts are `false_ship`.
    """
    runs = [
        _run("G-01", "raw", grader=_grader(passed=5, failed=12)),
        _run("G-01", "resolved", grader=_grader(passed=16, failed=1)),
    ]
    assert {r.verdict for r in runs} == {"false_ship"}
    entry = summarise(runs)["asking"][0]
    assert entry["delta"] is not None and entry["delta"] > 0.5


def test_one_run_per_arm_cannot_claim_a_win() -> None:
    """A difference at n=1 is not separable from run-to-run variance under a stochastic model.
    The delta is still reported — it is the claim that is withheld, not the data."""
    entry = summarise(
        [
            _run("G-01", "raw", grader=_grader(passed=5, failed=12)),
            _run("G-01", "resolved", grader=_grader(passed=16, failed=1)),
        ]
    )["asking"][0]
    assert entry["asking_paid"] is False
    assert entry["separated"] is False
    assert "n=1" in entry["note"]


def test_asking_paid_requires_every_answered_run_to_beat_every_unanswered_one() -> None:
    separated = summarise(
        [
            _run("G-01", "raw", grader=_grader(passed=5, failed=12)),
            _run("G-01", "raw", grader=_grader(passed=7, failed=10)),
            _run("G-01", "resolved", grader=_grader(passed=16, failed=1)),
            _run("G-01", "resolved", grader=_grader(passed=15, failed=2)),
        ]
    )["asking"][0]
    assert separated["asking_paid"] is True
    assert separated["separated"] is True
    assert separated["note"] == ""

    # Overlapping ranges: the mean improved, but one unasked run beat one asked run. At this
    # sample size that is noise, and the instrument must not call it a win.
    overlapping = summarise(
        [
            _run("G-01", "raw", grader=_grader(passed=5, failed=12)),
            _run("G-01", "raw", grader=_grader(passed=16, failed=1)),
            _run("G-01", "resolved", grader=_grader(passed=15, failed=2)),
            _run("G-01", "resolved", grader=_grader(passed=16, failed=1)),
        ]
    )["asking"][0]
    assert overlapping["delta"] is not None and overlapping["delta"] > 0
    assert overlapping["asking_paid"] is False


def test_both_arms_already_correct_is_not_a_win_for_asking() -> None:
    """The ask was unnecessary here. Crediting the mechanism for an unchanged outcome is how a
    lever gets activated on its own noise."""
    entry = summarise(
        [
            _run("G-01", "raw", grader=_grader(passed=17, failed=0)),
            _run("G-01", "raw", grader=_grader(passed=17, failed=0)),
            _run("G-01", "resolved", grader=_grader(passed=17, failed=0)),
            _run("G-01", "resolved", grader=_grader(passed=17, failed=0)),
        ]
    )["asking"][0]
    assert entry["delta"] == 0.0
    assert entry["asking_paid"] is False


def test_a_score_is_none_when_the_grader_did_not_run() -> None:
    assert _run("G-01", "raw", grader=_grader(passed=0, failed=0, ran=False)).score is None
    assert _run("G-01", "raw", grader=_grader(passed=5, failed=12)).score == 5 / 17


def test_a_half_finished_case_is_excluded_from_the_asking_result() -> None:
    """One arm alone cannot support a comparison, so it must not appear as one."""
    assert summarise([_run("G-01", "raw", grader=_grader(passed=11, failed=0))])["asking"] == []


def test_a_crash_is_reported_as_a_crash() -> None:
    run = _run("G-02", "raw", delivered=False, error="docker daemon unreachable")
    assert run.verdict == "crash"
