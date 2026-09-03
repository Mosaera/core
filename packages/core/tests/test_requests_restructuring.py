"""The scaffold's red phase asserts decomposition, so it may arm only when decomposition is asked.

Measured on the 0.6.3 sweep (docs/engineering-history/over-park-anatomy-2026-08-30.md): a comment
fix and a version bump both promise "No behaviour changes", both armed `scaffold_if_refactor`, and
received `assert _module_level_functions(_real) > _module_level_functions(_frozen)` — producing
`assert 2 > 2` on trees the hidden grader passed 100%. 4 runs, 15% of every over-park where an
authored assertion refused correct code.

The briefs below are the REAL corpus text, not invented examples, because the defect was invisible
to examples I would have written myself.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mosaera_core.behavior_preservation import is_behavior_preserving, requests_restructuring
from mosaera_core.refactor_scaffold import scaffold_if_refactor

MCB_14 = """# Extract the duplicated validation (Python)

You are working in an existing Python project. `accounts.py` defines two functions,
`create_user(name, age)` and `update_user(name, age)`, that both contain the same block of input
validation, copy-pasted into each.

## Task

Refactor `accounts.py` to remove the duplication: extract the shared validation into a single
helper. Keep the observable behaviour unchanged.
"""

MCB_30 = """# Fix the stale comment on TAX_RATE

The comment above `TAX_RATE` in `ledger.py` says "Returns the tally in cents.", which is left over
from an older version. It should read "The sales tax rate applied by with_tax."

## Acceptance criteria

The comment above `TAX_RATE` reads `# The sales tax rate applied by with_tax.`
No behaviour changes.
"""

MCB_32 = """# Bump the version string

`__version__` in `ledger.py` is `1.4.0`. The release is `1.5.0`; bump the version string.

## Acceptance criteria

`ledger.__version__` is `1.5.0`
No behaviour changes.
"""


@pytest.mark.parametrize("brief", [MCB_30, MCB_32], ids=["comment-fix", "version-bump"])
def test_the_two_briefs_that_broke_are_preserving_but_NOT_decompositions(brief: str) -> None:
    """THE defect, stated as a test. Both predicates must disagree — that disagreement is the whole
    point, and if they ever agree the unmeetable bar comes straight back."""
    assert is_behavior_preserving(brief) is True, "these do promise behaviour preservation"
    assert requests_restructuring(brief) is False, "but neither asks for anything to be broken up"


def test_a_real_refactor_brief_still_arms() -> None:
    """The other half. Declining everywhere would 'fix' over-park by deleting a working control."""
    assert is_behavior_preserving(MCB_14) is True
    assert requests_restructuring(MCB_14) is True


_SEED = (
    "def total(nums, scale=1):\n"
    "    s = 0\n"
    "    for n in nums:\n"
    "        s += n * scale\n"
    "    return s\n"
)
_EXISTING_TEST = "from calc import total\n\ndef test_it():\n    assert total([1, 2, 3]) == 6\n"


def _ws(root: Path) -> Any:
    """A workspace the scaffold CAN author against — a root-level module plus a test that imports it
    with literal inputs. Without this the scaffold bails for its own reasons and every assertion
    below passes whether or not the guard exists."""
    (root / "calc.py").write_text(_SEED, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_calc.py").write_text(_EXISTING_TEST, encoding="utf-8")
    return SimpleNamespace(root=root)


def test_the_fixture_really_can_author__otherwise_everything_below_is_vacuous(
    tmp_path: Path,
) -> None:
    """THE CONTROL, and it is not optional. The first version of these tests passed a `None`
    workspace: it raised, `scaffold_if_refactor`'s bare `except Exception` swallowed it, and `[]`
    came back whether the guard was present or not. All 13 tests passed with the guard deleted.
    This pins that the scaffold DOES author on a decomposition brief, so a `[]` below means the
    guard refused rather than the scaffold merely failing."""
    got = scaffold_if_refactor(
        _ws(tmp_path),
        enabled=True,
        task=MCB_14,
        plan="",
        design="",
        existing_tests=["tests/test_calc.py"],
    )
    assert got, "fixture cannot author at all — the decline tests below would prove nothing"
    assert any("golden" in f for f in got)


@pytest.mark.parametrize("brief", [MCB_30, MCB_32], ids=["comment-fix", "version-bump"])
def test_the_scaffold_now_DECLINES_those_briefs(brief: str, tmp_path: Path) -> None:
    """End to end on a workspace that CAN be authored against: no files, so no decomposition bar."""
    assert (
        scaffold_if_refactor(
            _ws(tmp_path),
            enabled=True,
            task=brief,
            plan="",
            design="",
            existing_tests=["tests/test_calc.py"],
        )
        == []
    )


def test_the_PM_paraphrase_cannot_arm_decomposition(tmp_path: Path) -> None:
    """ADR-0066, applied to the new predicate. `scaffold_if_refactor` already discards plan/design
    for preservation; the decomposition read must not reintroduce the paraphrase channel that
    planted an unmeetable bar on MCB-11."""
    assert requests_restructuring("Bump the version string. No behaviour changes.") is False
    assert (
        scaffold_if_refactor(
            _ws(tmp_path),
            enabled=True,
            task="Bump the version string. No behaviour changes.",
            plan="decompose ledger.py into helper functions",
            design="extract the shared validation into smaller functions",
            existing_tests=["tests/test_calc.py"],
        )
        == []
    ), "a PM paraphrase armed the decomposition bar the brief never asked for"


@pytest.mark.parametrize(
    "task,expected",
    [
        ("Decompose the handler into smaller pieces", True),
        ("Extract the shared validation into a helper", True),
        ("Split it out into separate functions", True),
        ("Make render a short orchestrator", True),
        ("Rename the variable. Keep the observable behaviour unchanged.", False),
        ("Update the docstring. No behaviour changes.", False),
        ("Reorder the imports; identical output.", False),
    ],
)
def test_predicate_is_deny_by_default(task: str, expected: bool) -> None:
    assert requests_restructuring(task) is expected
