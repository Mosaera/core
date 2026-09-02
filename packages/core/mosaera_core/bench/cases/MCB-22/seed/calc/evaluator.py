"""Evaluate a calc AST to an integer."""

from __future__ import annotations

from calc.parser import BinOp, Num


class EvalError(ValueError):
    """Raised when an AST cannot be evaluated (e.g. division by zero)."""


def evaluate(node: object) -> int:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, BinOp):
        left = evaluate(node.left)
        right = evaluate(node.right)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise EvalError("division by zero")
            return left // right
    raise EvalError("cannot evaluate expression")
