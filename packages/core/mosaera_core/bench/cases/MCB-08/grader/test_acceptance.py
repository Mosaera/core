"""Hidden acceptance suite for MCB-08 (add subtractive Roman notation).

Ground truth — NEVER shown to the agent, injected into the delivered workspace only
at grade time. Independent of (a superset of) the seed's own test suite, so a run
that merely deletes or weakens the visible tests does not pass here. Imports the
delivered ``roman`` module from the workspace cwd.
"""

from __future__ import annotations

import pytest
from roman import to_roman


def test_additive_values_still_work() -> None:
    assert to_roman(1) == "I"
    assert to_roman(3) == "III"
    assert to_roman(10) == "X"
    assert to_roman(30) == "XXX"


def test_subtractive_ones() -> None:
    assert to_roman(4) == "IV"
    assert to_roman(9) == "IX"


def test_subtractive_tens() -> None:
    assert to_roman(40) == "XL"
    assert to_roman(90) == "XC"


def test_subtractive_hundreds() -> None:
    assert to_roman(400) == "CD"
    assert to_roman(900) == "CM"


def test_composite_values() -> None:
    assert to_roman(2024) == "MMXXIV"
    assert to_roman(3999) == "MMMCMXCIX"
    assert to_roman(1994) == "MCMXCIV"


def test_out_of_range_raises() -> None:
    for bad in (0, -1, 4000):
        with pytest.raises(ValueError):
            to_roman(bad)
