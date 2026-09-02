"""Map a numeric score to a letter grade."""

from __future__ import annotations

# Ordered high-to-low: the first band whose threshold the score meets wins.
_BANDS: list[tuple[int, str]] = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
]


def grade_letter(score: int) -> str:
    """Return the letter grade for ``score`` (0-100).

    Bands: >= 90 "A", >= 80 "B", >= 70 "C", >= 60 "D", otherwise "F".
    """
    for threshold, letter in _BANDS:
        if score >= threshold:
            return letter
    return "F"
