"""Hidden acceptance suite for MCB-31 (docstring wording)."""

from __future__ import annotations

from ledger import subtotal, with_tax


def test_the_docstring_was_corrected() -> None:
    assert subtotal.__doc__ == 'Return the sum of the row amounts.'


def test_behaviour_is_unchanged() -> None:
    assert subtotal([{'amount': 10}, {'amount': 5}]) == 15
    assert with_tax([{'amount': 10}]) == 12.0
