"""The existing suite. It asserts the OLD raw-float behaviour, so it MUST fail after the change —
that failure is the point of the item, and telling it apart from "the code is wrong" is what
slice 4 exists to do."""

from __future__ import annotations

import pytest

from pricing.checkout import order_total
from pricing.discount import apply_discount


def test_apply_discount_raw_float() -> None:
    assert apply_discount(10.0, 17) == 8.299999999999999


def test_order_total_uses_the_discount() -> None:
    assert order_total([5.0, 5.0], 17) == 8.299999999999999


def test_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        apply_discount(10.0, 101)
