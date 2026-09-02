"""A tiny space-separated infix expression evaluator.

Supports addition and subtraction over integer/float literals, evaluated strictly
left-to-right. Any other operator token raises ``ValueError``.
"""

from __future__ import annotations


def _number(token: str) -> float:
    """Parse a numeric literal token into a float."""
    return float(token)


def evaluate(expr: str) -> float:
    """Evaluate a space-separated infix expression, e.g. ``"1 + 2 - 3"``."""
    tokens = expr.split()
    if not tokens:
        raise ValueError("empty expression")

    result = _number(tokens[0])
    i = 1
    while i < len(tokens):
        op = tokens[i]
        rhs = _number(tokens[i + 1])
        if op == "+":
            result = result + rhs
        elif op == "-":
            result = result - rhs
        else:
            raise ValueError(f"unsupported operator: {op}")
        i += 2
    return result
