"""Summary statistics for a list of possibly-messy values."""

from __future__ import annotations

from typing import Any


def _numbers(values: list) -> list[float]:
    """The ``int`` / ``float`` entries of ``values`` (``bool`` and ``None`` excluded)."""
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def summarize(values: list) -> dict[str, Any]:
    """Return ``{count, mean, min, max}`` for the numeric entries of ``values``.

    Non-numeric entries (strings, ``None``, ``bool``) are ignored. When no numeric
    values remain, returns ``{"count": 0, "mean": 0.0, "min": None, "max": None}``.
    Never raises on a well-formed list argument.
    """
    nums = _numbers(values)
    if not nums:
        return {"count": 0, "mean": 0.0, "min": None, "max": None}
    return {
        "count": len(nums),
        "mean": sum(nums) / len(nums),
        "min": min(nums),
        "max": max(nums),
    }
