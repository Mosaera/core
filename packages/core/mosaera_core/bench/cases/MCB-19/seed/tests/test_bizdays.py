from datetime import date

from bizdays import business_days


def test_full_working_week() -> None:
    # Mon Jan 1 .. Sat Jan 6, 2024 — the end falls on a weekend.
    assert business_days(date(2024, 1, 1), date(2024, 1, 6)) == 5


def test_weekend_only() -> None:
    # Sat Jan 6 .. Sun Jan 7, 2024 — no weekdays.
    assert business_days(date(2024, 1, 6), date(2024, 1, 7)) == 0
