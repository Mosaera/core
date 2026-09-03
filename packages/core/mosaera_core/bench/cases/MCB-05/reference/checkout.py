"""Shopping-cart checkout totals."""

from __future__ import annotations

from typing import Any


def _line_total(item: dict[str, Any]) -> float:
    """One cart line, with a 10% discount for a bulk quantity (>= 10)."""
    if item["qty"] <= 0:
        raise ValueError("qty must be positive")
    if item["price"] < 0:
        raise ValueError("price must be non-negative")
    line = item["price"] * item["qty"]
    if item["qty"] >= 10:
        line = line * 0.9
    return line


def _subtotal(cart: list[dict[str, Any]]) -> float:
    return sum(_line_total(item) for item in cart)


def _apply_member_discount(subtotal: float, member: bool) -> float:
    return subtotal * 0.95 if member else subtotal


def _shipping(subtotal: float) -> float:
    return 0.0 if subtotal >= 50 else 5.0


def _tax(subtotal: float) -> float:
    return subtotal * 0.08


def checkout_total(cart: list[dict[str, Any]], member: bool = False) -> float:
    """Total for ``cart`` (a list of {name, price, qty}).

    Rules: a line of qty >= 10 gets 10% off; members get a further 5% off the
    subtotal; shipping is free at or above 50 (else 5.00); 8% tax on the discounted
    subtotal. An empty cart costs 0.
    """
    if not cart:
        return 0.0
    subtotal = _apply_member_discount(_subtotal(cart), member)
    total = subtotal + _tax(subtotal) + _shipping(subtotal)
    return round(total, 2)
