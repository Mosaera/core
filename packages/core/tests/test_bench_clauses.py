"""The bench's ratified standing decisions must actually be standing — and overridable.

**Why this exists.** ADR-0082 names MCB-05/15 exactly: the briefs say "a short orchestrator" with
no number, ADR-0072 forbids deriving the constant from prose, and the engine's relative fallback
accepted 13 statements where the graders demand ≤6/7. The fix is a ratified clause — and it fixes
BOTH directions because `weave_criteria` puts the number into the brief the agent reads (ledger E5:
delivered 7→18, over-park 8→2, false ships 0). The owner ratified `structural.body_statements=5`
as the bench default on 2026-08-12.

**What can go wrong, and is pinned here:**

- the default silently not applying (this seam had NO test before today — a forgotten env var
  reverting every sweep to the unsound relative check is the silent-vacancy class);
- the default failing clause validation and vanishing (`make_clause` raises on an unregistered
  parameter — a default that cannot validate must fail tests, not disappear);
- the ``none`` sentinel breaking, which would make a no-clause A/B arm inexpressible — before
  default-on, empty meant "none"; after, empty means "default", and that meaning-flip needs a pin.
"""

from __future__ import annotations

import pytest
from mosaera_core.bench._clauses import _RATIFIED_DEFAULT, _bench_clauses
from mosaera_core.clauses import apply_to_constraints
from mosaera_core.structural_spec import extract_structural_constraints


def test_the_ratified_default_applies_when_no_env_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAERA_BENCH_CLAUSES", raising=False)
    clauses = _bench_clauses()
    assert [f"{c.binds}={c.value_num}" for c in clauses] == [_RATIFIED_DEFAULT]
    assert "owner ratification 2026-08-12" in clauses[0].because


def test_the_default_round_trips_into_the_constraint_it_ratifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE POSITIVE CONTROL. A default that validates but never reaches `max_body` would be a
    standing decision that stands for nothing — the constraint must actually tighten."""
    monkeypatch.delenv("MOSAERA_BENCH_CLAUSES", raising=False)
    stated = extract_structural_constraints(
        "Refactor `f` into a short orchestrator that delegates to at least three helpers"
    )
    assert stated is not None, "a refactor sentence must extract a constraint at all"
    assert stated.max_body is None, "the brief leaves the number open — that is the whole point"
    bound = apply_to_constraints(stated, _bench_clauses())
    assert bound is not None
    assert bound.max_body == 5, "the ratified value must bind the open parameter"


def test_env_still_overrides_for_an_ab_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_BENCH_CLAUSES", "structural.body_statements=7")
    clauses = _bench_clauses()
    assert [c.value_num for c in clauses] == [7]
    assert "owner ratification" not in clauses[0].because, (
        "an explicit arm is the arm's decision, not the owner's standing one"
    )


def test_the_none_sentinel_yields_no_clauses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before default-on, an EMPTY env meant "no clauses"; now it means "default". The no-clause
    A/B arm must stay expressible, or the control arm of every future clause experiment dies."""
    monkeypatch.setenv("MOSAERA_BENCH_CLAUSES", "none")
    assert _bench_clauses() == ()


def test_garbage_env_does_not_crash_and_does_not_silently_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit-but-unparseable arm yields NO clauses rather than the default: the operator
    said something; substituting the default would silently measure a posture they did not ask
    for."""
    monkeypatch.setenv("MOSAERA_BENCH_CLAUSES", "structural.body_statements=lots")
    assert _bench_clauses() == ()
