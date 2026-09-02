"""Summarise a list of record dicts."""

from __future__ import annotations

from typing import Any


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return ``{"count", "total"}`` for ``records``.

    Each record is a mapping with an ``amount``. Malformed input is not handled — a bad record
    raises whatever the arithmetic raises, part-way through.
    """
    total = 0.0
    for record in records:
        total += record["amount"]
    return {"count": len(records), "total": total}
