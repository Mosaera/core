"""Discount arithmetic."""

from __future__ import annotations


def apply_discount(total: float, pct: float) -> float:
    """Apply a percentage discount, rounded to whole cents."""
    if pct < 0 or pct > 100:
        raise ValueError(f"percentage out of range: {pct}")
    return round(total * (1 - pct / 100), 2)
