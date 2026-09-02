"""Evaluate a calc AST against a variable environment."""

from __future__ import annotations

from calc.parser import Assign, BinOp, Num, Var


class EvalError(ValueError):
    """Raised when an AST cannot be evaluated (bad op, division by zero, unbound name)."""


def evaluate(node: object, env: dict[str, int] | None = None) -> int:
    if env is None:
        env = {}
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Var):
        if node.name not in env:
            raise EvalError(f"undefined variable {node.name!r}")
        return env[node.name]
    if isinstance(node, BinOp):
        left = evaluate(node.left, env)
        right = evaluate(node.right, env)
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


def evaluate_program(statements: list[object], env: dict[str, int] | None = None) -> int:
    """Evaluate statements left to right against a shared env; return the last value."""
    if env is None:
        env = {}
    result = 0
    for stmt in statements:
        if isinstance(stmt, Assign):
            result = evaluate(stmt.expr, env)
            env[stmt.name] = result
        else:
            result = evaluate(stmt, env)
    return result
