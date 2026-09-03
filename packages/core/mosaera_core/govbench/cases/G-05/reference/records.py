"""Summarise a list of record dicts, rejecting malformed input as a whole."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RecordError(ValueError):
    """Every problem found in one call, so a caller fixes its input once rather than N times."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} invalid record(s): " + "; ".join(errors))
        self.errors = errors


def _problem(index: int, record: Any) -> str | None:
    """The reason ``record`` is invalid, or ``None`` when it is fine."""
    if not isinstance(record, Mapping):
        return f"record {index}: expected a mapping, got {type(record).__name__}"
    if "amount" not in record:
        return f"record {index}: missing 'amount'"
    amount = record["amount"]
    # `isinstance(True, int)` is True, so bools need excluding explicitly — a boolean amount is
    # a type confusion, not a quantity.
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return f"record {index}: 'amount' must be a number, got {type(amount).__name__}"
    return None


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return ``{"count", "total"}`` for ``records``.

    Validates every record BEFORE summing anything: if any is invalid, no summary is produced and
    a single :class:`RecordError` carries one entry per bad record. A partial total would be worse
    than a failure — it looks like an answer.
    """
    problems = [p for p in (_problem(i, r) for i, r in enumerate(records)) if p is not None]
    if problems:
        raise RecordError(problems)
    return {"count": len(records), "total": float(sum(r["amount"] for r in records))}
