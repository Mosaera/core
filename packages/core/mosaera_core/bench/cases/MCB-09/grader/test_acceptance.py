"""Hidden acceptance suite for MCB-09 (fix the interval-merge bugs).

Ground truth — NEVER shown to the agent, injected into the delivered workspace only
at grade time. Independent of (a superset of) the seed's own test suite, so a run
that merely deletes or weakens the visible tests does not pass here. Imports the
delivered ``intervals`` module from the workspace cwd. Exercises both flaws the seed
hides: unsorted input and touching (non-strictly-overlapping) intervals.
"""

from __future__ import annotations

from intervals import merge


def test_touching_intervals_merge() -> None:
    # end == next start must merge: this is the strict-overlap bug.
    assert merge([(1, 3), (3, 5)]) == [(1, 5)]


def test_unsorted_input_is_sorted_and_merged() -> None:
    # Input arrives out of order: this is the "assumes sorted" bug.
    assert merge([(8, 10), (1, 3), (2, 6)]) == [(1, 6), (8, 10)]


def test_nested_interval_absorbed() -> None:
    assert merge([(1, 10), (2, 5)]) == [(1, 10)]


def test_already_sorted_overlapping() -> None:
    assert merge([(1, 3), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_disjoint_preserved_and_sorted() -> None:
    assert merge([(4, 5), (1, 2)]) == [(1, 2), (4, 5)]


def test_empty() -> None:
    assert merge([]) == []


def test_single_point_interval() -> None:
    assert merge([(5, 5)]) == [(5, 5)]


def test_chain_of_touching_intervals() -> None:
    assert merge([(1, 2), (2, 3), (3, 4)]) == [(1, 4)]
