"""Hidden acceptance suite for MCB-28 (round discounted prices to whole cents).

Ground truth — never shown to the agent, injected at grade time. A MODIFY case grades three things,
and the third is what makes it a modify case rather than a feature case:

  * the NEW behaviour holds;
  * the behaviour that was NOT asked to change is untouched (the ValueError path);
  * the live CONSUMER still works — a behaviour change that silently breaks its caller is the
    Hyrum's-Law failure the slice exists to surface.
"""

from __future__ import annotations

import pytest
from pricing.checkout import order_total
from pricing.discount import apply_discount


def test_the_new_behaviour_holds() -> None:
    assert apply_discount(10.0, 17) == 8.3


def test_an_exact_value_is_unharmed_by_rounding() -> None:
    assert apply_discount(19.99, 10) == 17.99


def test_rounding_is_to_two_decimals_not_to_int() -> None:
    """Guards the plausible over-correction: `round(x)` instead of `round(x, 2)`."""
    assert apply_discount(19.99, 15) == 16.99


def test_the_unchanged_behaviour_is_still_unchanged() -> None:
    for bad in (-1, 101):
        with pytest.raises(ValueError):
            apply_discount(10.0, bad)


def test_the_live_consumer_still_works() -> None:
    """`order_total` is the caller that depended on the old behaviour. It must keep working, and
    it must now see rounded totals — the blast radius, graded."""
    assert order_total([5.0, 5.0], 17) == 8.3
    assert order_total([9.99, 10.0], 10) == 17.99
