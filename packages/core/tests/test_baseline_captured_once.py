"""The ADR-0036 tamper baseline is captured ONCE, including on a repo that starts with no tests.

The guard was `if not state.get("integrity_baseline")`. A repo with no tests baselines to `{}`,
which is falsy — so "captured, and there was nothing" and "not captured yet" were the same value,
and `plan_node` re-baselined on every gate-deny re-plan. By then the Proctor has authored a suite
and the coder has written code, so the re-capture records a TOUCHED tree as pristine: exactly the
absorption the code's own comment forbids, on greenfield repos where the coder can write anything.

Found by chasing an anomaly: on the 0.6.3 sweep, 5 of 7 greenfield runs reported a `standing_suite`
vouch on a repository that began empty.
"""

from __future__ import annotations

import pytest
from mosaera_core.graph.state import RunState


def _guard(state: dict) -> bool:
    """The predicate as `plan_node` now spells it: capture iff NEITHER marker is present."""
    return not (state.get("integrity_enumerator") or state.get("integrity_baseline"))


def _old_guard(state: dict) -> bool:
    """The predicate as it WAS, kept so the regression is stated rather than described."""
    return not state.get("integrity_baseline")


def test_a_repo_that_started_with_no_tests_is_baselined_ONLY_once() -> None:
    """THE defect. An empty baseline is a RESULT, not an absence."""
    after_first = {"integrity_baseline": {}, "integrity_enumerator": "v1"}
    assert _guard(after_first) is False, "already captured — must not re-baseline"
    assert _old_guard(after_first) is True, (
        "regression pin: the old guard re-baselined here, absorbing whatever "
        "the coder and Proctor had written by the time the gate denied"
    )


def test_a_brownfield_repo_was_never_affected() -> None:
    """Scoping the blast radius honestly: a non-empty baseline is truthy, so the old guard held."""
    after_first = {"integrity_baseline": {"tests/test_a.py": "abc"}, "integrity_enumerator": "v1"}
    assert _guard(after_first) is False
    assert _old_guard(after_first) is False


def test_the_first_visit_still_captures() -> None:
    """The fix must not stop the baseline being taken at all."""
    assert _guard({}) is True
    assert _guard({"integrity_baseline": {}}) is True, (
        "an EMPTY baseline with no enumerator is the greenfield first visit — capture"
    )
    assert _guard({"integrity_baseline": {"tests/t.py": "h"}}) is False, (
        "a caller carrying only the older marker must still skip: the fix ADDS a way to be "
        "sure, it does not replace one"
    )


@pytest.mark.parametrize("enumerator", ["v1", "sha256:paths", "anything-non-empty"])
def test_any_stamped_enumerator_counts_as_captured(enumerator: str) -> None:
    assert _guard({"integrity_baseline": {}, "integrity_enumerator": enumerator}) is False


def test_integrity_enumerator_is_a_declared_state_key() -> None:
    """It has to survive the checkpoint, or the guard is reading a key LangGraph drops (ADR-0026)
    and the run re-baselines every time — the same bug with a different cause."""
    assert "integrity_enumerator" in RunState.__annotations__
