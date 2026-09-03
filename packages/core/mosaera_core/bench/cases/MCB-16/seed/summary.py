"""Summary statistics for a list of numbers."""

from __future__ import annotations

from typing import Any


def summarize(values: list) -> dict[str, Any]:
    """Return ``{count, mean, min, max}`` for ``values``.

    ``mean`` is the arithmetic mean; ``min`` / ``max`` are the extremes.
    """
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }
