"""Apply a list of operations to a copy of a dict, atomically and validated."""

from __future__ import annotations

from numbers import Number


class OperationError(Exception):
    """Raised when one or more operations are invalid.

    Aggregates every problem: ``errors`` is a list with one message per bad op,
    each naming that op's index. When raised, nothing has been applied.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _is_number(value: object) -> bool:
    # bool is a subclass of int — it is not a valid numeric operand here.
    return isinstance(value, Number) and not isinstance(value, bool)


def _validate(data: dict, operations: list[dict]) -> list[str]:
    """Return a list of error messages, one per invalid op (empty if all valid).

    Validation is done against a running *shadow* view of the keys so that an
    ``increment`` after a ``set`` of the same key is judged against the state it
    would actually see — without mutating ``data``.
    """
    errors: list[str] = []
    known_keys = set(data)
    values = dict(data)

    for index, op in enumerate(operations):
        if not isinstance(op, dict) or "action" not in op:
            errors.append(f"op {index}: missing 'action'")
            continue
        action = op["action"]

        if action == "set":
            if "key" not in op:
                errors.append(f"op {index}: 'set' is missing required key 'key'")
                continue
            known_keys.add(op["key"])
            values[op["key"]] = op.get("value")
        elif action == "delete":
            if "key" not in op:
                errors.append(f"op {index}: 'delete' is missing required key 'key'")
                continue
            known_keys.discard(op["key"])
            values.pop(op["key"], None)
        elif action == "increment":
            if "key" not in op:
                errors.append(f"op {index}: 'increment' is missing required key 'key'")
                continue
            key = op["key"]
            amount = op.get("amount")
            if key not in known_keys:
                errors.append(f"op {index}: 'increment' on missing key {key!r}")
                continue
            if not _is_number(values.get(key)):
                errors.append(
                    f"op {index}: 'increment' on key {key!r} whose value is not a number"
                )
                continue
            if not _is_number(amount):
                errors.append(f"op {index}: 'increment' amount is not a number")
                continue
            values[key] = values[key] + amount
        else:
            errors.append(f"op {index}: unknown action {action!r}")

    return errors


def apply_operations(data: dict, operations: list[dict]) -> dict:
    """Return a new dict with ``operations`` applied to a copy of ``data``.

    Two-phase: validate every op first and, if any is invalid, raise
    ``OperationError`` (with an ``errors`` list, one entry per bad op) without
    applying anything. ``data`` is never mutated.
    """
    errors = _validate(data, operations)
    if errors:
        raise OperationError(errors)

    result = dict(data)
    for op in operations:
        action = op["action"]
        if action == "set":
            result[op["key"]] = op["value"]
        elif action == "delete":
            result.pop(op["key"], None)
        elif action == "increment":
            result[op["key"]] = result[op["key"]] + op["amount"]
    return result
