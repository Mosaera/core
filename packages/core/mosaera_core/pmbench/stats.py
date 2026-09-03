"""The arithmetic a benchmark needs to say "A beats B" — and to refuse when it cannot.

**This is the first statistics code in the repository.** Until now `statistics` was imported twice,
for `mean` only, and every interval in `docs/engineering-history/` was computed by hand. So each
function here is tested against a number this project already published and acted on, rather than
against a textbook: if the code disagrees with the arithmetic the repo trusted, the code is wrong.

Pure: no I/O, no settings, no model. Small on purpose — a benchmark that grows its own statistics
library is a benchmark nobody audits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 95%. Two-sided. Everything here is reported at one confidence level because a suite that varies
#: it per call invites picking the level that makes a result look decisive.
_Z = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    @property
    def width(self) -> float:
        return self.hi - self.lo


def wilson(successes: int, trials: int, z: float = _Z) -> Interval | None:
    """95% Wilson score interval for a proportion. ``None`` when there is nothing to bound.

    Wilson rather than the normal approximation because QMB's rates sit near 0 and 1, where the
    normal interval famously runs past them and reports impossible bounds — and "0 failures in 5"
    is exactly the shape this suite produces most often.
    """
    if trials <= 0:
        return None
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    # The clamp is float-error defence only and is deliberately NOT mutation-covered: Wilson is
    # bounded within [0, 1] analytically, so no input can make it bind. It exists so a rounding
    # artefact can never print an interval hi of 1.0000000000000002 in a report.
    return Interval(max(0.0, centre - half), min(1.0, centre + half))


def se_difference(s_a: int, n_a: int, s_b: int, n_b: int) -> float | None:
    """Standard error of the difference between two independent proportions.

    The number the mutation A/B needed and did not compute until afterwards: *"The binomial SE at
    n=125 and p≈0.31 is 5.8pp. Anyone could have divided one by the other BEFORE spending 5.5 hours
    of GPU time."* Exposed so a QMB sweep can be sized in advance rather than explained afterwards.
    """
    if n_a <= 0 or n_b <= 0:
        return None
    p_a, p_b = s_a / n_a, s_b / n_b
    return math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)


def _binom_cdf(k: int, n: int, p: float = 0.5) -> float:
    """P(X <= k) for X ~ Binomial(n, p), computed in LOG space.

    The obvious form — ``comb(n, i) * p**i * (1-p)**(n-i)`` — overflows: `math.comb` returns an
    exact int, and at the n a power calculation reaches (thousands) that int is far past the range
    of a float, so the multiplication raises rather than returning a small number. Found by
    `discordant_needed` searching upward for a near-even lean.
    """
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    log_p, log_q = math.log(p), math.log1p(-p)
    total = 0.0
    for i in range(k + 1):
        log_pmf = (
            math.lgamma(n + 1)
            - math.lgamma(i + 1)
            - math.lgamma(n - i + 1)
            + i * log_p
            + (n - i) * log_q
        )
        total += math.exp(log_pmf)
    return min(1.0, total)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for paired binary outcomes.

    ``b`` and ``c`` are the DISCORDANT counts: trials A passed and B failed, and the reverse.
    Concordant trials are deliberately ignored — that is the entire reason a paired design costs
    less. Cases both models get right, or both get wrong, carry no information about which is
    better, and including them is what made the unpaired 125-vs-125 comparison blind to a 7-run
    effect (`mutation-veto-ab-2026-08-11.md`).

    Exact (binomial) rather than the chi-square approximation because QMB's discordant counts are
    small by design — around 12 to 39 — which is exactly where the approximation misleads.
    """
    n = b + c
    if n == 0:
        return 1.0  # the arms never disagreed; there is nothing to test
    return min(1.0, 2 * _binom_cdf(min(b, c), n))


def discordant_needed(lean: float = 0.75, alpha: float = 0.05) -> int:
    """Smallest discordant count whose most-favourable split would reach significance.

    Pre-registration, not post-hoc explanation: the repo's rule is that *"power was computed before
    running… so a small result reads as underpowered, never as no effect"*. Call this before a
    sweep, print it, and a null result afterwards is honest instead of ambiguous.
    """
    n = 1
    # Bounded: past a few thousand discordant trials the answer is "this design cannot show it",
    # and a caller reading 2000 has the same information as one reading 40000.
    while n < 2_000:
        b = round(n * lean)
        if mcnemar_exact(b, n - b) <= alpha:
            return n
        n += 1
    return n
