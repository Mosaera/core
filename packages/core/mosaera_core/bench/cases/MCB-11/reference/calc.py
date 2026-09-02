"""A tiny space-separated infix expression evaluator.

Supports ``+``, ``-``, ``*`` and ``/`` over integer/float literals with standard
precedence (``*`` and ``/`` bind tighter than ``+`` and ``-``) and left
associativity. Division is float division. There are no parentheses. Any other
operator token raises ``ValueError``.
"""

from __future__ import annotations


def _number(token: str) -> float:
    """Parse a numeric literal token into a float."""
    return float(token)


def evaluate(expr: str) -> float:
    """Evaluate a space-separated infix expression, e.g. ``"2 + 3 * 4"``."""
    tokens = expr.split()
    if not tokens:
        raise ValueError("empty expression")

    # First pass: resolve the tighter-binding * and / left-to-right, collapsing each
    # run of factors into a single value. What remains is an alternating sequence of
    # values and + / - operators.
    values: list[float] = [_number(tokens[0])]
    ops: list[str] = []
    i = 1
    while i < len(tokens):
        op = tokens[i]
        rhs = _number(tokens[i + 1])
        if op == "*":
            values[-1] = values[-1] * rhs
        elif op == "/":
            values[-1] = values[-1] / rhs
        elif op in ("+", "-"):
            ops.append(op)
            values.append(rhs)
        else:
            raise ValueError(f"unsupported operator: {op}")
        i += 2

    # Second pass: apply + and - left-to-right over the collapsed values.
    result = values[0]
    for op, value in zip(ops, values[1:]):
        if op == "+":
            result = result + value
        else:  # "-"
            result = result - value
    return result
