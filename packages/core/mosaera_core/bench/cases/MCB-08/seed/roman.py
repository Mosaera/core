"""Convert integers to Roman numerals.

``to_roman(n)`` returns the Roman-numeral string for ``1 <= n <= 3999``.
"""

from __future__ import annotations

# Symbol values, largest first. (Additive only.)
_VALUES = [
    (1000, "M"),
    (500, "D"),
    (100, "C"),
    (50, "L"),
    (10, "X"),
    (5, "V"),
    (1, "I"),
]


def to_roman(n: int) -> str:
    """Return the Roman numeral for ``n`` (1..3999)."""
    if not 1 <= n <= 3999:
        raise ValueError("to_roman requires 1 <= n <= 3999")
    result = []
    for value, symbol in _VALUES:
        while n >= value:
            result.append(symbol)
            n -= value
    return "".join(result)
