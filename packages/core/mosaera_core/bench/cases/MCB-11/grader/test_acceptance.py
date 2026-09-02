"""Hidden acceptance suite for MCB-11 (add `*` and `/` with precedence to calc).

Ground truth — never shown to the agent, injected at grade time. Calls the public
`evaluate` as a black box; broader than the seed's visible tests, covering
precedence, left-associativity, float division, and the preserved +/- behaviour.
"""

from __future__ import annotations

import pytest
from calc import evaluate


def test_existing_addition_preserved() -> None:
    assert evaluate("1 + 2 + 3") == 6


def test_existing_subtraction_preserved() -> None:
    assert evaluate("10 - 4 - 1") == 5


def test_existing_mixed_add_sub_preserved() -> None:
    # left-to-right: (1 + 2) - 3 == 0
    assert evaluate("1 + 2 - 3") == 0


def test_mul_binds_tighter_than_add() -> None:
    assert evaluate("2 + 3 * 4") == 14


def test_mul_binds_tighter_than_sub() -> None:
    assert evaluate("10 - 2 * 3") == 4


def test_div_binds_tighter_than_add() -> None:
    assert evaluate("20 / 4 + 1") == 6


def test_two_products_across_a_plus() -> None:
    assert evaluate("2 * 3 + 4 * 5") == 26


def test_division_is_left_associative() -> None:
    assert evaluate("8 / 2 / 2") == 2


def test_division_is_float_division() -> None:
    # 7 / 2 == 3.5, not 3
    assert evaluate("7 / 2") == 3.5


def test_plain_product() -> None:
    assert evaluate("6 * 7") == 42


def test_float_literals() -> None:
    assert evaluate("1.5 + 2.5 * 2") == 6.5


def test_unsupported_operator_still_raises() -> None:
    with pytest.raises(ValueError):
        evaluate("2 % 3")
