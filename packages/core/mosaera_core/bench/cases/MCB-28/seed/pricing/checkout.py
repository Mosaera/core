"""The live consumer — proves the change has a blast radius."""

from __future__ import annotations

from pricing.discount import apply_discount


def order_total(items: list[float], pct: float) -> float:
    return apply_discount(sum(items), pct)
