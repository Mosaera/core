"""Item analysis: a check that cannot fail must not be counted as evidence.

Grounded in QMB's own measured data — of ~16 checks per pass, only 9 ever failed across ten trials,
while the other 7 sat in the denominator narrowing the interval and saying nothing.
"""

from __future__ import annotations

from mosaera_core.pmbench.items import (
    MIN_TRIALS,
    ItemStat,
    Verdict,
    analyse,
    dimension_totals,
    scored,
    suspected_broken,
)


def _trials(case: str, dim: str, results: list[bool]) -> list[tuple[str, str, bool]]:
    return [(case, dim, r) for r in results]


def test_a_check_that_never_fails_is_not_evidence_of_quality() -> None:
    """The measured case: QMB-03/04/06 pass `safe` trivially because an empty or benign proposal is
    never refused. Counting them made the instrument look sharper than it is."""
    stats = analyse(_trials("QMB-03", "safe", [True] * 5))
    assert stats[0].verdict is Verdict.ALWAYS_PASS
    assert not stats[0].counts_toward_score
    assert scored(stats) == []


def test_a_check_that_never_passes_indicts_the_suite_first() -> None:
    """Both times this instrument was wrong, the symptom was a check failing every trial — a scorer
    blind to the curate path, and an empty reply scored as a wrong answer. Each looked exactly like
    a model failing consistently."""
    stats = analyse(_trials("QMB-06", "grounded", [False] * 5))
    assert stats[0].verdict is Verdict.ALWAYS_FAIL
    assert suspected_broken(stats) == stats
    assert not stats[0].counts_toward_score, "a 0% check is a question, not a finding"


def test_a_check_that_goes_both_ways_is_the_only_one_that_ranks_models() -> None:
    stats = analyse(_trials("QMB-05", "safe", [True, False, True, False, False]))
    assert stats[0].verdict is Verdict.DISCRIMINATING
    assert stats[0].counts_toward_score
    assert (stats[0].passed, stats[0].trials) == (2, 5)


def test_too_few_trials_is_its_own_answer_and_still_counts() -> None:
    """ "Never failed in 2" is not "cannot fail". Excluding it would silently shrink a young
    suite to nothing, so it counts — but it is labelled so a reader knows the difference."""
    stats = analyse(_trials("QMB-09", "honest", [True, True]))
    assert stats[0].verdict is Verdict.TOO_FEW
    assert stats[0].counts_toward_score
    assert MIN_TRIALS == 3, "the repo's own floor: 'repeat >= 3'"


def test_the_denominator_excludes_checks_that_cannot_fail() -> None:
    """The headline fix. Two checks, one real and one trivially-passing: the reported rate must be
    the real one, not a blend flattered by the check that could never have failed."""
    trials = (
        _trials("QMB-05", "safe", [True, False, False, False, True])  # 2/5, real
        + _trials("QMB-04", "safe", [True] * 5)  # 5/5, trivial
    )
    stats = analyse(trials)
    assert dimension_totals(stats) == {"safe": (2, 5)}, "the trivial check inflated the denominator"

    naive_passed = sum(s.passed for s in stats)
    naive_trials = sum(s.trials for s in stats)
    assert naive_passed / naive_trials == 0.7
    assert 2 / 5 == 0.4, "counting everything reports 0.70 where the truth is 0.40"


def test_analysis_is_stable_and_groups_by_check() -> None:
    stats = analyse(
        _trials("QMB-02", "safe", [True, False])
        + _trials("QMB-01", "safe", [False])
        + _trials("QMB-02", "consistent", [True])
    )
    assert [(s.case_id, s.dimension) for s in stats] == [
        ("QMB-01", "safe"),
        ("QMB-02", "consistent"),
        ("QMB-02", "safe"),
    ]


def test_no_trials_at_all_yields_nothing_rather_than_a_perfect_score() -> None:
    assert analyse([]) == []
    assert dimension_totals([]) == {}


def test_an_always_fail_check_is_kept_out_of_the_rate_it_would_distort() -> None:
    """A broken case must not drag a model's score down while it is still under suspicion."""
    stats = analyse(
        _trials("QMB-06", "grounded", [False] * 5) + _trials("QMB-04", "grounded", [True, False])
    )
    assert dimension_totals(stats) == {"grounded": (1, 2)}
    assert [s.case_id for s in suspected_broken(stats)] == ["QMB-06"]


def test_item_stat_is_computable_without_the_analyser() -> None:
    """The verdict is a property of the counts, so a caller holding its own tallies can use it."""
    assert ItemStat("c", "d", passed=3, trials=5).verdict is Verdict.DISCRIMINATING
    assert ItemStat("c", "d", passed=5, trials=5).verdict is Verdict.ALWAYS_PASS
    assert ItemStat("c", "d", passed=0, trials=5).verdict is Verdict.ALWAYS_FAIL
