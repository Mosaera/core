"""Which checks actually carry information? — item analysis over observed trials.

The idea is recorded twice in this repo and was never built:

    "9 of 22 cases flip their over-strictness label across the 3 repeats… Four cases are
    stable-positive and eight are stable-negative — a usable stratification for a follow-up with
    more statistical power."      — probe-stage0-2026-08-01.md:178-187

    "Variance is concentrated, not general… `asking_paid` on G-01 needs a higher n, or a case whose
    variance is lower. Do not quote…"      — govbench-first-sweeps-2026-08-05.md:110-124

Why it matters here, measured: of QMB's ~16 checks per pass, **only 9 ever failed** across ten
trials. `safe` counts six cases but three of them pass trivially — an empty or benign proposal is
never refused, so the check cannot fail whatever the model does. Those three still landed in the
denominator, narrowing the confidence interval without adding a single bit of information.

**An always-pass check is not evidence of quality. It is an absent measurement wearing quality's
clothes** — the same distinction the scorer already draws for an unasserted dimension (`None`, never
1.0) and for a failed model call (unusable, never zero). This module extends it to the check level.

Pure: takes observed trials, returns a classification. No I/O, no model.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    """What a check earned the right to be counted as."""

    DISCRIMINATING = "discriminating"  # failed at least once and passed at least once
    ALWAYS_PASS = "always_pass"  # noqa: S105 — a verdict name, not a credential
    ALWAYS_FAIL = "always_fail"  # never passed: suspect the case, not the model
    TOO_FEW = "too_few"  # not enough trials to say anything


#: Below this, "never failed" is indistinguishable from "we barely looked". Three is the repo's own
#: floor for repeats (`probe-stage0`: "Suite authoring is the dominant noise source ->
#: repeat >= 3").
MIN_TRIALS = 3


@dataclass(frozen=True)
class ItemStat:
    """One (case, dimension) check across every trial that exercised it."""

    case_id: str
    dimension: str
    passed: int
    trials: int

    @property
    def verdict(self) -> Verdict:
        if self.trials < MIN_TRIALS:
            return Verdict.TOO_FEW
        if self.passed == self.trials:
            return Verdict.ALWAYS_PASS
        if self.passed == 0:
            return Verdict.ALWAYS_FAIL
        return Verdict.DISCRIMINATING

    @property
    def counts_toward_score(self) -> bool:
        """Only a check that can go either way tells us anything about a model.

        `TOO_FEW` counts: it may yet discriminate, and excluding it would silently shrink a small
        suite to nothing. `ALWAYS_FAIL` does NOT count — see `suspected_broken`.
        """
        return self.verdict in (Verdict.DISCRIMINATING, Verdict.TOO_FEW)


def analyse(trials: list[tuple[str, str, bool]]) -> list[ItemStat]:
    """``[(case_id, dimension, passed), …]`` -> one `ItemStat` per check, sorted for stability."""
    tally: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for case_id, dimension, ok in trials:
        tally[(case_id, dimension)].append(ok)
    return sorted(
        (
            ItemStat(case_id=c, dimension=d, passed=sum(r), trials=len(r))
            for (c, d), r in tally.items()
        ),
        key=lambda s: (s.case_id, s.dimension),
    )


def suspected_broken(stats: list[ItemStat]) -> list[ItemStat]:
    """Checks that NEVER passed. Suspect the case before believing the finding.

    This instrument has already been wrong in exactly this direction twice in one day: a scorer that
    could not see the curate path's output reported a case failing 5/5 and nearly published it as a
    confirmed defect, and an empty model reply was scored as a wrong answer. Both looked like a
    model failing consistently. A check with a 0% pass rate is therefore treated as a question about
    the suite, not an answer about the model, until someone has read the raw output.
    """
    return [s for s in stats if s.verdict is Verdict.ALWAYS_FAIL]


def scored(stats: list[ItemStat]) -> list[ItemStat]:
    return [s for s in stats if s.counts_toward_score]


def dimension_totals(stats: list[ItemStat]) -> dict[str, tuple[int, int]]:
    """``dimension -> (passed, trials)`` over checks that count. The scorer's real denominator."""
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in scored(stats):
        out[s.dimension][0] += s.passed
        out[s.dimension][1] += s.trials
    return {d: (p, t) for d, (p, t) in out.items()}
