"""Discount arithmetic."""

from __future__ import annotations


def apply_discount(total: float, pct: float) -> float:
    """Apply a percentage discount. Returns a RAW float — the behaviour to change."""
    if pct < 0 or pct > 100:
        raise ValueError(f"percentage out of range: {pct}")
    return total * (1 - pct / 100)
