"""Descriptive statistics over lists of numbers.

Every function takes a non-empty list of numbers and raises ``ValueError`` on an
empty input.
"""

from __future__ import annotations

from collections import Counter


def mean(values: list[float]) -> float:
    """The arithmetic mean."""
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """The middle value; for an even count, the average of the two middle values."""
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid]


def mode(values: list[float]) -> float:
    """The most common value; ties break to the smallest."""
    if not values:
        raise ValueError("mode requires at least one value")
    counts = Counter(values)
    top = max(counts.values())
    return min(v for v, c in counts.items() if c == top)
