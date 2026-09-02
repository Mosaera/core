"""Hidden acceptance suite for MCB-32 (version bump)."""

from __future__ import annotations

import ledger
from ledger import subtotal, with_tax


def test_the_version_was_bumped() -> None:
    assert ledger.__version__ == '1.5.0'


def test_behaviour_is_unchanged() -> None:
    assert subtotal([{'amount': 10}, {'amount': 5}]) == 15
    assert with_tax([{'amount': 10}]) == 12.0
