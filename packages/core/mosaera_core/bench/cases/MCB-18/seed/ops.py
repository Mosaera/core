"""Apply a list of operations to a copy of a dict."""

from __future__ import annotations


def apply_operations(data: dict, operations: list[dict]) -> dict:
    """Return a new dict with ``operations`` applied to a copy of ``data``.

    Supported actions: ``set`` (key/value), ``delete`` (key), and ``increment``
    (key/amount, adds amount to the stored number). ``data`` is not mutated.
    """
    result = dict(data)
    for op in operations:
        action = op["action"]
        if action == "set":
            result[op["key"]] = op["value"]
        elif action == "delete":
            del result[op["key"]]
        elif action == "increment":
            result[op["key"]] = result[op["key"]] + op["amount"]
    return result
