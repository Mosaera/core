"""Convert integers to Roman numerals.

``to_roman(n)`` returns the Roman-numeral string for ``1 <= n <= 3999``.
"""

from __future__ import annotations

# Symbol values, largest first, including the subtractive pairs (CM, CD, XC, ...).
_VALUES = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
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
