"""Hidden acceptance suite for MCB-19 (fix the business-days off-by-one).

Ground truth — NEVER shown to the agent, injected into the delivered workspace only
at grade time. Independent of (a superset of) the seed's own test suite, so a run
that merely deletes or weakens the visible tests does not pass here. Imports the
delivered ``bizdays`` module from the workspace cwd. Note: 2024-01-01 is a Monday, so
these ranges exercise the inclusive end that the seed's exclusive range drops.
"""

from __future__ import annotations

from datetime import date

from bizdays import business_days


def test_full_week_ending_on_a_weekday() -> None:
    # Mon Jan 1 .. Fri Jan 5 — the inclusive end (Fri) must be counted.
    assert business_days(date(2024, 1, 1), date(2024, 1, 5)) == 5


def test_single_weekday() -> None:
    # Same weekday for start and end counts as one.
    assert business_days(date(2024, 1, 1), date(2024, 1, 1)) == 1


def test_single_weekend_day() -> None:
    assert business_days(date(2024, 1, 6), date(2024, 1, 6)) == 0


def test_weekend_span() -> None:
    # Sat Jan 6 .. Sun Jan 7 — no weekdays.
    assert business_days(date(2024, 1, 6), date(2024, 1, 7)) == 0


def test_spans_a_weekend_to_next_monday() -> None:
    # Mon Jan 1 .. Mon Jan 8 — five weekdays plus the following Monday.
    assert business_days(date(2024, 1, 1), date(2024, 1, 8)) == 6


def test_end_on_weekend_is_unaffected() -> None:
    # Mon Jan 1 .. Sat Jan 6 — end on a weekend, still five weekdays.
    assert business_days(date(2024, 1, 1), date(2024, 1, 6)) == 5
