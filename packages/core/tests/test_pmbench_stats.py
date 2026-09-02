"""The first statistics code in this repo, checked against numbers the repo already published.

Every expected value below was computed by hand in `docs/engineering-history/` and acted on at the
time. Testing against those rather than against a textbook means a disagreement indicts the code,
not the record — and it keeps the new arithmetic continuous with the decisions already made from it.
"""

from __future__ import annotations

import math

from mosaera_core.pmbench.stats import (
    discordant_needed,
    mcnemar_exact,
    se_difference,
    wilson,
)


def test_wilson_reproduces_the_published_false_ship_bound() -> None:
    """`rebaseline-2026-08-05.md:33`: "false_ship 1/72 = 1.4%, 95% Wilson upper bound ~= 7.5%".

    That bound was the argument for a gate decision, so the code had better agree with it."""
    ci = wilson(1, 72)
    assert ci is not None
    assert abs(ci.hi - 0.075) < 0.002, f"published upper bound was ~7.5%, got {ci.hi:.3%}"
    assert ci.lo >= 0.0


def test_wilson_stays_inside_zero_and_one_where_the_normal_interval_would_not() -> None:
    """The reason for Wilson rather than the normal approximation: QMB's most common observation is
    "0 failures in 5", where p +/- z*sqrt(p(1-p)/n) collapses to a zero-width interval at 0.0 and
    would report certainty from five trials.

    Note this tests the FORMULA's bounds, not the clamp in the code — Wilson is bounded within
    [0, 1] analytically, so the clamp can never bind and nothing can mutation-cover it. It is
    float-error defence, and saying so is better than a test that appears to check it."""
    perfect = wilson(5, 5)
    assert perfect is not None
    assert perfect.hi == 1.0
    assert perfect.lo < 1.0, "five successes is not proof of a perfect model"
    assert perfect.lo > 0.4

    none_at_all = wilson(0, 5)
    assert none_at_all is not None
    assert none_at_all.lo == 0.0 and none_at_all.hi > 0.4


def test_wilson_is_none_when_nothing_was_measured() -> None:
    """Consistent with the scorer: an unasserted dimension has no rate, not a perfect one."""
    assert wilson(0, 0) is None


def test_se_difference_reproduces_the_mutation_ab_noise_floor() -> None:
    """`mutation-veto-ab-2026-08-11.md:30-34`: A=39/125, B=38/125, "SE=5.8pp".

    This is the division that would have cancelled a 5.5-hour sweep before it ran."""
    se = se_difference(39, 125, 38, 125)
    assert se is not None
    assert abs(se - 0.058) < 0.001, f"published SE was 5.8pp, got {se:.4f}"

    diff = 39 / 125 - 38 / 125
    assert abs(diff / se - 0.14) < 0.02, "published: 0.14 standard errors"
    assert abs(2 * se - 0.117) < 0.002, "published: resolvable only above ~2 SE = 11.7pp"


def test_mcnemar_ignores_concordant_trials() -> None:
    """The whole economy of a paired design. Trials both models get right, or both get wrong, say
    nothing about which is better — so they must not move the p-value."""
    assert mcnemar_exact(10, 2) == mcnemar_exact(10, 2)
    # A closed form anyone can check: 2 * P(X <= 2 | n=12, p=0.5) = 2 * (1+12+66)/4096.
    assert abs(mcnemar_exact(10, 2) - 2 * 79 / 4096) < 1e-12


def test_mcnemar_says_nothing_when_the_arms_never_disagreed() -> None:
    """Zero discordant pairs is not evidence of equality; it is absence of evidence. p=1.0 is the
    honest encoding — the comparison simply has nothing to go on."""
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_is_symmetric_and_two_sided() -> None:
    assert mcnemar_exact(9, 1) == mcnemar_exact(1, 9)
    assert mcnemar_exact(6, 6) == 1.0
    assert mcnemar_exact(9, 1) < 0.05 < mcnemar_exact(6, 4)


def test_the_exact_test_is_used_because_the_counts_are_small() -> None:
    """At the counts a paired QMB run produces, the chi-square approximation is optimistic and the
    two tests genuinely disagree. 7-vs-1: the uncorrected statistic (b-c)^2/(b+c) = 4.5 clears 3.84
    and calls it significant; the exact p is 2 * (1+8)/256 = 0.070 and does not. The exact test is
    the conservative one, which is why a suite that will report "model A beats model B" uses it."""
    chi_sq = (7 - 1) ** 2 / 8
    assert chi_sq > 3.84, "chi-square would call this significant"
    assert mcnemar_exact(7, 1) > 0.05, "the exact test does not — and it is the one we trust"
    assert abs(mcnemar_exact(7, 1) - 2 * 9 / 256) < 1e-12


def test_power_is_computable_before_a_sweep_runs() -> None:
    """Pre-registration, per `over-park-attribution-2026-08-11.md:85-90`. A 3:1 lean needs roughly a
    dozen discordant trials; a near-even one needs far more, which is the number to print BEFORE
    spending GPU hours."""
    strong = discordant_needed(lean=0.75)
    weak = discordant_needed(lean=0.60)
    assert 8 <= strong <= 20, strong
    assert weak > strong * 3, "a slight lean must be shown to be expensive up front"
    b = round(strong * 0.75)
    assert mcnemar_exact(b, strong - b) <= 0.05


def test_binom_cdf_matches_math_comb_directly() -> None:
    """The one hand-rolled primitive, checked against an independent expansion."""
    from mosaera_core.pmbench.stats import _binom_cdf

    expect = sum(math.comb(10, i) for i in range(4)) / 2**10
    assert abs(_binom_cdf(3, 10) - expect) < 1e-12


def test_the_cdf_survives_the_sizes_a_power_search_reaches() -> None:
    """Found by running it: the obvious `comb(n, i) * p**i` form raises OverflowError, because
    `math.comb` returns an exact int far past float range long before the power search stops. The
    log-space form is not a micro-optimisation — the direct one cannot produce an answer at all."""
    from mosaera_core.pmbench.stats import _binom_cdf

    assert 0.0 <= _binom_cdf(750, 1500) <= 1.0
    assert abs(_binom_cdf(750, 1500) - 0.5) < 0.02, "a fair coin is near even at the midpoint"
    assert _binom_cdf(1500, 1500) == 1.0
    assert _binom_cdf(-1, 10) == 0.0

    # And the whole reason it matters: a near-even lean must return a number, not raise.
    assert discordant_needed(lean=0.52) > 100
