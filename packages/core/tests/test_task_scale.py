"""The deterministic task-scale classifier (Approach A).

The dangerous direction is a FALSE TRIVIAL — a behavioural change waved onto a lane that authors no
acceptance test. So most of these drive the deny side, and the accept side is deliberately narrow.
"""

from __future__ import annotations

from mosaera_core.task_scale import (
    added_lines_within_budget,
    classify,
    diff_within_scope,
)

_FILES = ("src/report.py", "src/cli.py", "README.md", "pyproject.toml")


def test_a_comment_fix_scoped_to_one_known_file_takes_the_reduced_lane() -> None:
    s = classify(
        "Fix the stale comment above render_row",
        "Edit the comment in src/report.py; nothing else changes.",
        _FILES,
    )
    assert s.reduced
    assert s.paths == ("src/report.py",)
    assert "src/report.py" in s.reason


def test_a_behaviour_verb_anywhere_forces_the_full_lane() -> None:
    """The deny-by-default term. A brief that mentions a comment AND a real change is a real
    change — the cheap lane must never be reachable by burying the behaviour in a sentence."""
    s = classify(
        "Fix the comment above render_row and add a --quiet flag",
        "Touches src/report.py.",
        _FILES,
    )
    assert not s.reduced
    assert "behaviour change" in s.reason


def test_the_matched_phrase_does_not_disqualify_itself() -> None:
    """`fix a typo` contains `fix`. If the sweep ran over the raw text every non-behavioural shape
    would disqualify itself and the lane would be unreachable — a control that cannot fire."""
    s = classify("Fix a typo in the docstring", "In src/cli.py.", _FILES)
    assert s.reduced, s.reason


def test_an_unrecognised_shape_is_full_not_trivial() -> None:
    s = classify("Make the report faster", "Touch src/report.py.", _FILES)
    assert not s.reduced
    assert "no recognised non-behavioural shape" in s.reason


def test_a_plan_naming_no_REAL_file_certifies_nothing() -> None:
    """The plan is model output. A path it invents cannot certify a scope, so the file list is
    intersected with the actual repo rather than trusted."""
    s = classify("Fix a typo in the comment", "Edit src/does_not_exist.py.", _FILES)
    assert not s.reduced
    assert "no existing file" in s.reason


def test_a_multi_file_change_is_full_even_when_non_behavioural() -> None:
    s = classify(
        "Fix the comments", "Edit src/report.py and src/cli.py to correct the comments.", _FILES
    )
    assert not s.reduced
    assert "spans 2 files" in s.reason


def test_a_diff_that_leaves_the_certified_scope_is_refused() -> None:
    """The classifier PREDICTS; this MEASURES. Being wrong must cost the lane, never correctness."""
    s = classify("Fix a typo in the comment", "In src/report.py.", _FILES)
    assert s.reduced
    assert diff_within_scope(s, ["src/report.py"]) == ""
    why = diff_within_scope(s, ["src/report.py", "src/cli.py"])
    assert "outside the certified scope" in why


def test_scope_is_not_checked_on_the_full_lane() -> None:
    """A full-lane run has no certified scope to leave, so the check must be inert there rather
    than accidentally constraining a normal run."""
    s = classify("Make the report faster", "Touch everything.", _FILES)
    assert diff_within_scope(s, ["a.py", "b.py", "c.py"]) == ""


def test_a_large_diff_in_the_right_file_is_still_refused() -> None:
    """The scope check asks WHERE, this asks HOW MUCH. A 400-line rewrite of the one certified file
    passes the path check and is obviously not a comment fix."""
    big = "\n".join(["+ line"] * 40)
    assert "capped at" in added_lines_within_budget(big)
    assert added_lines_within_budget("+ one comment\n- old comment") == ""


def test_the_diff_header_is_not_counted_as_an_added_line() -> None:
    """`+++ b/file` starts with `+`. Counting it would make every diff one line bigger and the
    budget quietly wrong at the boundary."""
    assert added_lines_within_budget("+++ b/src/report.py\n+ one real line") == ""
