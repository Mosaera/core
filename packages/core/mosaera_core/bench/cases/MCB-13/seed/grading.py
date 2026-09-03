"""Map a numeric score to a letter grade."""

from __future__ import annotations


def grade_letter(score: int) -> str:
    """Return the letter grade for ``score`` (0-100).

    Bands: >= 90 "A", >= 80 "B", >= 70 "C", >= 60 "D", otherwise "F".
    """
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"
