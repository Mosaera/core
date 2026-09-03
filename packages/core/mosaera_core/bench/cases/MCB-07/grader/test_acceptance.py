"""Hidden acceptance suite for MCB-07 (fix the pagination off-by-one bug).

Ground truth — NEVER shown to the agent, injected into the delivered workspace only
at grade time. Independent of (a superset of) the seed's own test suite, so a run
that merely deletes or weakens the visible tests does not pass here. Imports the
delivered ``pager`` module from the workspace cwd.
"""

from __future__ import annotations

from pager import paginate


def test_first_page_starts_at_the_beginning() -> None:
    assert paginate([1, 2, 3, 4, 5, 6, 7], 1, 3) == [1, 2, 3]


def test_middle_page() -> None:
    assert paginate([1, 2, 3, 4, 5, 6, 7], 2, 3) == [4, 5, 6]


def test_last_partial_page() -> None:
    assert paginate([1, 2, 3, 4, 5, 6, 7], 3, 3) == [7]


def test_page_just_past_the_end_is_empty() -> None:
    assert paginate([1, 2, 3, 4, 5, 6, 7], 4, 3) == []


def test_page_zero_is_empty() -> None:
    assert paginate([1, 2, 3, 4, 5, 6, 7], 0, 3) == []


def test_per_page_at_least_length_returns_all_on_page_one() -> None:
    assert paginate([1, 2, 3], 1, 3) == [1, 2, 3]
    assert paginate([1, 2, 3], 1, 10) == [1, 2, 3]


def test_per_page_below_one_is_empty() -> None:
    assert paginate([1, 2, 3], 1, 0) == []
    assert paginate([1, 2, 3], 1, -2) == []


def test_empty_items_is_empty() -> None:
    assert paginate([], 1, 3) == []
