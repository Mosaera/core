"""Hidden acceptance suite for MCB-16 (harden the numeric summary).

Ground truth — never shown to the agent, injected at grade time. Imports the
delivered module from the workspace cwd and asserts messy input is tolerated
(non-numeric entries ignored, empty result set guarded) instead of raising.
"""

from __future__ import annotations

from summary import summarize


def test_clean_numeric_list_unchanged() -> None:
    assert summarize([1, 2, 3]) == {"count": 3, "mean": 2.0, "min": 1, "max": 3}


def test_empty_list_is_guarded() -> None:
    assert summarize([]) == {"count": 0, "mean": 0.0, "min": None, "max": None}


def test_non_numeric_entries_ignored() -> None:
    assert summarize([1, 2, "x", 3, None]) == {"count": 3, "mean": 2.0, "min": 1, "max": 3}


def test_bool_is_not_a_number() -> None:
    assert summarize([True, 1, 2]) == {"count": 2, "mean": 1.5, "min": 1, "max": 2}


def test_all_non_numeric_is_empty_result() -> None:
    assert summarize(["a", "b"]) == {"count": 0, "mean": 0.0, "min": None, "max": None}


def test_floats_are_counted() -> None:
    result = summarize([1.5, 2.5, "skip", None])
    assert result["count"] == 2
    assert result["mean"] == 2.0
    assert result["min"] == 1.5
    assert result["max"] == 2.5
