"""Merge overlapping or touching integer intervals.

``merge`` takes a list of ``(start, end)`` tuples and returns the sorted list of
merged intervals. Two intervals merge when they overlap or *touch* (the end of one
equals the start of the next).
"""

from __future__ import annotations


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or touching intervals into a sorted list."""
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start < merged[-1][1]:
            last_start, last_end = merged[-1]
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
