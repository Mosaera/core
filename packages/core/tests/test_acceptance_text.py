"""A model-authored acceptance keeps its criterion-per-line shape at every WRITE boundary.

The defect these pin, observed live 2026-08-05: Quincy emits ``acceptance`` as a JSON array often
enough that a bare ``str()`` stored the Python repr — ``['crit 1', 'crit 2']``, brackets and quotes
included — as one newline-free blob. Every reader splits on newlines, so the entire chain then saw
exactly ONE criterion: the UI count, the claims minted for the gate, the task handed to the coder
and the Proctor, the checkability verdict, and the criteria count fed back to Quincy (which is why
asking him to emit separate criteria could not fix it — he was told he already had).

The assertions deliberately check for repr characters rather than only counting lines: a future
regression that stores ``"['a', 'b']"`` would still split to one line, and a line-count assertion
alone would pass on the two-element case by coincidence.
"""

from __future__ import annotations

import pytest
from mosaera_core.claims import claims_from_acceptance
from mosaera_core.spec_lint import checkability
from mosaera_core.task_spec import acceptance_text, build_run_task

CRITERIA = [
    "Running `budget add 12.34 food` appends a row to the CSV file.",
    "An invalid amount exits non-zero with a message on stderr.",
]


def _has_repr_noise(text: str) -> bool:
    """A stored acceptance must never carry Python list syntax."""
    return any(token in text for token in ("['", "']", "', '", '["', '"]'))


def test_a_list_becomes_one_criterion_per_line() -> None:
    assert acceptance_text(CRITERIA) == "\n".join(CRITERIA)
    assert not _has_repr_noise(acceptance_text(CRITERIA))


def test_a_string_is_untouched() -> None:
    """No-op for every payload that was already the right shape — this is the common case."""
    already_correct = "\n".join(CRITERIA)
    assert acceptance_text(already_correct) == already_correct


@pytest.mark.parametrize("value", [None, "", [], ["  ", ""]])
def test_empty_shapes_collapse_to_empty(value: object) -> None:
    assert acceptance_text(value) == ""


def test_blank_entries_are_dropped_not_rendered_as_blank_lines() -> None:
    """A blank line would read downstream as a criterion boundary and mint an empty claim."""
    assert acceptance_text(["a", "   ", "b"]) == "a\nb"


def test_a_non_string_scalar_still_stringifies() -> None:
    """Joined, not rejected: the content may be right and only the shape wrong."""
    assert acceptance_text(12) == "12"


def test_the_repr_is_what_broke_the_criteria_count() -> None:
    """The regression itself, stated as a test: ``str(list)`` yields ONE unusable criterion."""
    repr_blob = str(CRITERIA)
    assert len(repr_blob.splitlines()) == 1
    assert _has_repr_noise(repr_blob)
    assert len(acceptance_text(CRITERIA).splitlines()) == len(CRITERIA)


def test_claims_are_minted_per_criterion_not_per_blob() -> None:
    """The consequence that reaches the gate: claim ids must track real criteria.

    Minted from the repr, claims split on sentence punctuation instead and carry stray bracket and
    quote characters, so per-criterion attribution at the gate is wrong.
    """
    good = claims_from_acceptance(1, acceptance_text(CRITERIA))
    assert len(good) == len(CRITERIA)
    assert not any(_has_repr_noise(claim.text) for claim in good)


def test_the_task_handed_to_the_coder_carries_clean_criteria() -> None:
    """``build_run_task`` is what the coder and the Proctor actually read."""
    item = {"id": 1, "title": "Add", "description": "d", "acceptance": acceptance_text(CRITERIA)}
    task, claims = build_run_task(item)
    assert not _has_repr_noise(task)
    assert len(claims) == len(CRITERIA)


def test_checkability_sees_the_criteria_not_one_blob() -> None:
    """The verdict surfaced in the UI and consumed by the intake gate."""
    item = {"id": 1, "title": "Add", "acceptance": acceptance_text(CRITERIA), "status": "todo"}
    assert checkability([item])[1] != "UNDER_SPECIFIED"
