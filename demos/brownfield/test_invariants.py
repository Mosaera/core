"""ROOT-level cross-cutting invariants — deliberately OUTSIDE tests/.

This is the whole point of the brownfield demo (ADR-0054 / #45): the old
validation ran only ``pytest tests`` and would SKIP this file, so a naive change
that violates the "quantity never goes negative" invariant would ship green.
Whole-suite discovery (``pytest -q --import-mode=importlib`` from the root) now
RUNS it, so the regression is caught → ``validation_failed`` → honest park.

It encodes the brief's feature (``remove_item``) AND its safety invariant, so a
naive ``self._stock[name] -= qty`` implementation (which lets a quantity go
negative) fails here even though the in-scope tests/ suite stays green.
"""

import pytest

from store.inventory import Inventory


def test_remove_reduces_quantity() -> None:
    inv = Inventory()
    inv.add_item("apple", 5)
    inv.remove_item("apple", 2)
    assert inv.quantity("apple") == 3


def test_remove_never_leaves_a_negative_quantity() -> None:
    inv = Inventory()
    inv.add_item("apple", 1)
    # Removing more than is in stock must NOT leave a negative quantity — either
    # raise, or clamp at zero. A naive `-= qty` violates this.
    with pytest.raises(ValueError):
        inv.remove_item("apple", 5)
    assert inv.quantity("apple") >= 0
    assert inv.total_count() >= 0
