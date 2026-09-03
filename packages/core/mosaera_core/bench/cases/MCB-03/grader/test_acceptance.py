"""Hidden acceptance suite for MCB-03 (fix the median bug).

Ground truth — NEVER shown to the agent, injected into the delivered workspace only
at grade time. Independent of (a superset of) the seed's own test suite, so a run
that merely deletes or weakens the visible failing test does not pass here. Imports
the delivered ``metrics`` package from the workspace cwd.
"""

from __future__ import annotations

import pytest
from metrics.stats import mean, median, mode


def test_mean_basic() -> None:
    assert mean([1, 2, 3, 4]) == 2.5
    assert mean([5]) == 5


def test_median_odd_length() -> None:
    assert median([3, 1, 2]) == 2
    assert median([9]) == 9


def test_median_even_length_is_average_of_middles() -> None:
    assert median([1, 2, 3, 4]) == 2.5
    assert median([10, 20]) == 15


def test_median_even_length_unsorted() -> None:
    assert median([4, 1, 3, 2]) == 2.5


def test_mode_most_common() -> None:
    assert mode([1, 1, 2, 3]) == 1


def test_mode_ties_break_to_smallest() -> None:
    assert mode([2, 2, 1, 1, 3]) == 1


def test_empty_inputs_raise() -> None:
    for fn in (mean, median, mode):
        with pytest.raises(ValueError):
            fn([])
