"""Shopping-cart checkout totals."""

from __future__ import annotations

from typing import Any


def checkout_total(cart: list[dict[str, Any]], member: bool = False) -> float:
    """Total for ``cart`` (a list of {name, price, qty}).

    Rules: a line of qty >= 10 gets 10% off; members get a further 5% off the
    subtotal; shipping is free at or above 50 (else 5.00); 8% tax on the discounted
    subtotal. An empty cart costs 0.
    """
    if not cart:
        return 0.0
    subtotal = 0.0
    for item in cart:
        if item["qty"] <= 0:
            raise ValueError("qty must be positive")
        if item["price"] < 0:
            raise ValueError("price must be non-negative")
        line = item["price"] * item["qty"]
        if item["qty"] >= 10:
            line = line * 0.9
        subtotal += line
    if member:
        subtotal = subtotal * 0.95
    if subtotal >= 50:
        shipping = 0.0
    else:
        shipping = 5.0
    tax = subtotal * 0.08
    total = subtotal + tax + shipping
    return round(total, 2)
