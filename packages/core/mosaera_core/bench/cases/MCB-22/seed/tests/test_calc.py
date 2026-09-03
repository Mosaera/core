"""The seed's own tests — arithmetic evaluation. Context for the agent."""

from __future__ import annotations

from calc.evaluator import evaluate
from calc.parser import parse
from calc.tokens import tokenize


def _ev(source: str) -> int:
    return evaluate(parse(tokenize(source)))


def test_addition() -> None:
    assert _ev("2 + 3") == 5


def test_precedence() -> None:
    assert _ev("2 + 3 * 4") == 14


def test_parentheses() -> None:
    assert _ev("(2 + 3) * 4") == 20


def test_subtraction_and_division() -> None:
    assert _ev("10 - 4") == 6
    assert _ev("12 / 3") == 4
