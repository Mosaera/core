"""Count business days (weekdays, Monday–Friday) between two dates.

``business_days(start, end)`` counts the weekdays in the range ``[start, end]``,
inclusive of both endpoints.
"""

from __future__ import annotations

from datetime import date, timedelta


def business_days(start: date, end: date) -> int:
    """Number of weekdays (Mon–Fri) in the inclusive range ``[start, end]``."""
    count = 0
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day.weekday() < 5:
            count += 1
    return count
