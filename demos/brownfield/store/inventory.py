"""A tiny inventory ledger — the existing, working code the brief extends.

Deliberately small and CORRECT so the run starts from green in-scope tests; the
demo is about the ROOT-level invariant test (test_invariants.py, outside tests/)
that whole-suite validation now discovers.
"""

from __future__ import annotations


class Inventory:
    def __init__(self) -> None:
        self._stock: dict[str, int] = {}

    def add_item(self, name: str, qty: int) -> None:
        """Add ``qty`` units of ``name`` to stock."""
        self._stock[name] = self._stock.get(name, 0) + qty

    def quantity(self, name: str) -> int:
        """Units of ``name`` currently in stock (0 if unknown)."""
        return self._stock.get(name, 0)

    def total_count(self) -> int:
        """Total units across every item."""
        return sum(self._stock.values())
