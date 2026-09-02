"""The design cache key (ADR-0084 §3, migration 0023).

The cache's only invalidation test used to be `not feedback`, which is not a key but the absence of
one. Measured 2026-08-06: an operator corrected a design's instruction at a write gate and the next
run was served that same design anyway — corrections land in `corrections`, not `feedback`.
"""

from __future__ import annotations

from typing import Any, cast

from mosaera_core.graph._design_cache import design_cache_key
from mosaera_core.graph.state import RunState


def _state(**kw: Any) -> RunState:
    """A RunState literal for the key — cast because these tests only ever set the keys it reads."""
    return cast(RunState, {"task": "T", "corrections": [], **kw})


def test_identical_inputs_produce_the_same_key() -> None:
    # The property that justifies caching at all: unchanged inputs → reuse → no model call.
    assert design_cache_key(_state(), "PLAN") == design_cache_key(_state(), "PLAN")


def test_a_changed_task_invalidates() -> None:
    # `task` carries the woven acceptance criteria (build_run_task), so this covers a changed
    # acceptance AND a newly ratified clause.
    assert design_cache_key(_state(task="T2"), "PLAN") != design_cache_key(_state(), "PLAN")


def test_a_changed_plan_invalidates() -> None:
    assert design_cache_key(_state(), "PLAN_2") != design_cache_key(_state(), "PLAN")


def test_a_correction_invalidates() -> None:
    # THE case that broke: a design authored before the operator said "never the src. prefix"
    # must not be reused after they said it.
    corrected = _state(corrections=["never the src. prefix"])
    assert design_cache_key(corrected, "PLAN") != design_cache_key(_state(), "PLAN")


def test_each_further_correction_invalidates_again() -> None:
    one = _state(corrections=["a"])
    two = _state(corrections=["a", "b"])
    assert design_cache_key(one, "PLAN") != design_cache_key(two, "PLAN")


def test_absent_corrections_key_is_treated_as_none() -> None:
    # A run that never had a correction must not differ from one whose list is empty, or every
    # pre-corrections run would regenerate spuriously.
    assert design_cache_key(cast(RunState, {"task": "T"}), "PLAN") == design_cache_key(
        _state(), "PLAN"
    )


def test_the_key_is_a_short_opaque_hash() -> None:
    # Stored in a VARCHAR(64) column and only ever compared for equality.
    key = design_cache_key(_state(), "PLAN")
    assert len(key) == 64 and key.isalnum()


def test_field_boundaries_are_not_ambiguous() -> None:
    # Concatenation must not let a task ending in a plan's prefix collide with the reverse split.
    assert design_cache_key(_state(task="AB"), "C") != design_cache_key(_state(task="A"), "BC")
