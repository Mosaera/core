"""Hidden acceptance suite for MCB-13 (refactor grade_letter to a table).

Ground truth — never shown to the agent, injected at grade time. Two kinds of
check:

- **behavioural** — the refactor must not change any output; these pass on the
  original ladder too (a refactor preserves behaviour), and
- **structural** — ``grade_letter`` must be table/data-driven, so its body holds at
  most one ``if`` (the single threshold comparison inside the loop) instead of the
  chained ``if/elif`` ladder. This FAILS on the original ladder, so a run that
  changes nothing cannot pass.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from grading import grade_letter

# --- behavioural: outputs are unchanged by the refactor ---


@pytest.mark.parametrize(
    ("score", "letter"),
    [
        (100, "A"),
        (95, "A"),
        (90, "A"),
        (89, "B"),
        (85, "B"),
        (80, "B"),
        (75, "C"),
        (70, "C"),
        (65, "D"),
        (60, "D"),
        (59, "F"),
        (0, "F"),
    ],
)
def test_grade_letter_mapping(score: int, letter: str) -> None:
    assert grade_letter(score) == letter


# --- structural: the ladder was genuinely replaced by a table-driven loop ---


def _grade_letter_ast() -> ast.FunctionDef:
    src = textwrap.dedent(inspect.getsource(grade_letter))
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_grade_letter_has_no_if_elif_ladder() -> None:
    fn = _grade_letter_ast()
    if_count = sum(1 for node in ast.walk(fn) if isinstance(node, ast.If))
    assert if_count <= 1, (
        f"grade_letter should be table/data-driven with at most one `if`, but "
        f"found {if_count} `if` nodes — replace the if/elif ladder with a loop "
        f"over a list of (threshold, letter) bands"
    )
