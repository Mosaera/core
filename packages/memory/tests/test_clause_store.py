"""Clause persistence (ADR-0082 tier 2) — shape rules and append-only supersession.

Policy (may this clause exist at all?) is NOT tested here, because it is deliberately not enforced
here: `memory` is a leaf and cannot import `mosaera_policies`. That check lives in
`mosaera_core.clauses` — see `packages/core/tests/test_clauses.py`.
"""

from __future__ import annotations

import os
import uuid

import pytest
from mosaera_memory import MemoryStore

_OFFLINE_URL = "postgresql://u:p@127.0.0.1:1/nope"
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
requires_db = pytest.mark.requires_db

_BASE: dict = {
    "project_id": None,
    "standard_id": "standards/house-style",
    "binds": "structural.body_statements",
    "value_kind": "number",
    "value_num": 5,
    "because": "correctness over line count",
    "author": "operator",
}


def _insert(store: MemoryStore, clause_id: str, **over: object) -> dict:
    return store.clause_insert(clause_id, **{**_BASE, **over})  # type: ignore[arg-type]


# --- shape rules: rejected before any session opens, so they need no database ---


def test_the_value_is_a_number_or_absent_never_both_and_never_neither() -> None:
    """The defect this arc exists for was a value that had to be re-derived from prose.

    A numeric clause with no number, and an advisory one carrying a stray number, are both
    incoherent — and a stray number would be silently ignored, which is the worse failure.
    """
    store = MemoryStore.from_url(_OFFLINE_URL)
    with pytest.raises(ValueError, match="carries an integer value"):
        _insert(store, "cl-x", value_kind="number", value_num=None)
    with pytest.raises(ValueError, match="carries an integer value"):
        _insert(store, "cl-x", value_kind="advisory", value_num=5)
    with pytest.raises(ValueError, match="unknown clause value kind"):
        _insert(store, "cl-x", value_kind="a handful", value_num=None)


def test_a_condition_is_all_or_nothing() -> None:
    # A half-stated condition would silently never fire, which is worse than a rejected one.
    store = MemoryStore.from_url(_OFFLINE_URL)
    with pytest.raises(ValueError, match="all of parameter"):
        _insert(store, "cl-x", when_param="module_lines")
    with pytest.raises(ValueError, match="all of parameter"):
        _insert(store, "cl-x", when_param="module_lines", when_op="<")


def test_a_clause_must_cite_and_bind() -> None:
    store = MemoryStore.from_url(_OFFLINE_URL)
    with pytest.raises(ValueError, match="must cite a standard"):
        _insert(store, "cl-x", standard_id="")
    with pytest.raises(ValueError, match="must cite a standard"):
        _insert(store, "cl-x", binds="")


# --- persistence ---


@requires_db
def test_clause_round_trip_supersession_and_scoping() -> None:
    store = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    store.init()
    p1 = f"cl-{uuid.uuid4().hex[:10]}"
    p2 = f"cl-{uuid.uuid4().hex[:10]}"
    store.create_project(p1, "P1", "src")
    store.create_project(p2, "P2", "src")
    prefix = uuid.uuid4().hex[:8]
    try:
        # A repo-scoped clause is stored ONCE and read by every project — a per-project copy
        # would drift, and a drifted copy of a standing decision is the defect returning.
        _insert(store, f"{prefix}-repo", project_id=None, value_num=5)
        for project in (p1, p2):
            ids = {c["id"] for c in store.clause_list(project)}
            assert f"{prefix}-repo" in ids

        # A project clause is scoped to its project and does NOT supersede the repo one.
        _insert(store, f"{prefix}-p1", project_id=p1, value_num=8)
        assert {c["id"] for c in store.clause_list(p1)} >= {f"{prefix}-repo", f"{prefix}-p1"}
        assert f"{prefix}-p1" not in {c["id"] for c in store.clause_list(p2)}

        # The NULL-project_id trap, executed. Postgres treats NULLs as distinct in a unique
        # index, so a live-row index over the bare column would enforce nothing for exactly the
        # rows that apply everywhere — leaving two live contradictory clauses on one parameter,
        # which is the two-readers-two-numbers failure this arc exists to kill.
        _insert(store, f"{prefix}-repo2", project_id=None, value_num=6)
        repo_live = [
            c["id"]
            for c in store.clause_list(p2)
            if c["binds"] == "structural.body_statements" and c["project_id"] is None
        ]
        assert repo_live == [f"{prefix}-repo2"], "a second repo clause must supersede the first"

        # Append-only: the superseded row survives, so "why is it 6 now?" stays answerable.
        history = [c for c in store.clause_list(p2, include_superseded=True) if prefix in c["id"]]
        superseded = [c for c in history if c["id"] == f"{prefix}-repo"]
        assert superseded and superseded[0]["superseded_at"] is not None
    finally:
        store.delete_project(p1)
        store.delete_project(p2)
