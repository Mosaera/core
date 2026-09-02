"""`project_suite_health` (0032): the suite verdict, keyed by the tree it measured.

Its own module rather than more lines in `test_store.py`, which is a grandfathered file on the
shrink-only ratchet.
"""

from __future__ import annotations

import os
import uuid

import pytest
from mosaera_memory import MemoryStore

_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
requires_db = pytest.mark.requires_db


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


@requires_db
def test_a_verdict_is_never_returned_for_a_different_tree(store: MemoryStore) -> None:
    """The guard that makes reuse safe. A verdict is a fact about a specific tree; handing it back
    for another one is how a run would 'inherit' a green that describes a repository state that no
    longer exists — which is the bug this table exists to close, not to reproduce."""
    from mosaera_memory.models import Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")

    assert store.record_suite_health(pid, tree_hash="tree-aaa", verdict="pass", run_id="r1") is True
    assert store.suite_health(pid, "tree-aaa")["verdict"] == "pass"  # type: ignore[index]
    assert store.suite_health(pid, "tree-bbb") is None  # the repo moved → no answer
    shown = store.suite_health(pid)  # display read: staleness is information, not a hazard
    assert shown is not None and shown["tree_hash"] == "tree-aaa"

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))


@requires_db
def test_the_verdict_vocabulary_is_closed(store: MemoryStore) -> None:
    """Deny-by-default at the persistence boundary: a typo can never become a verdict nothing
    understands (ADR-0005's rule, applied where the value lands)."""
    from mosaera_memory.models import Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")

    assert store.record_suite_health(pid, tree_hash="t", verdict="green") is False
    assert store.record_suite_health(pid, tree_hash="", verdict="pass") is False
    assert store.suite_health(pid) is None

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))


@requires_db
def test_the_failing_set_survives_for_the_next_run(store: MemoryStore) -> None:
    """The next run needs WHICH tests were failing, not just that some were — that is what lets it
    tell "already broken" from "you broke it"."""
    from mosaera_memory.models import Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    store.record_suite_health(
        pid, tree_hash="t1", verdict="failed", failing=["tests/a.py::x"], run_id="r1"
    )

    row = store.suite_health(pid, "t1")
    assert row is not None and row["failing"] == ["tests/a.py::x"] and row["run_id"] == "r1"

    # A later measurement REPLACES it — one row per project, always the latest tree.
    store.record_suite_health(pid, tree_hash="t2", verdict="pass", run_id="r2")
    assert store.suite_health(pid, "t1") is None
    assert store.suite_health(pid, "t2")["verdict"] == "pass"  # type: ignore[index]

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))
