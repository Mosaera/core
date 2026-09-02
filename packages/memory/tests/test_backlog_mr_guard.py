"""Regression from the 2026-08-18 red team: a backlog row that owns a live merge request may not
be deleted, because that row is the only record of what the MR targets (migration 0028) and branch
protection reads it. Its own file so the ratchet on test_store.py is not paid for with thinner
assertions."""

from __future__ import annotations

import os
import uuid

import pytest
from mosaera_memory import MemoryStore
from test_store import _drop_project

# Same shape as test_store.py's — a five-line fixture is cheaper to restate than to hoist into a
# shared conftest, which would be a refactor of test infrastructure this regression does not need.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
requires_db = pytest.mark.requires_db


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


@requires_db
def test_delete_backlog_item_refuses_while_its_merge_request_is_open(store: MemoryStore) -> None:
    """Red-team 2026-08-18 finding 5.

    The row is the ONLY record of what an item's MR targets (0028), and branch protection reads
    it. Deleting the row silently unprotects that branch and orphans a live MR — and this is
    reachable from an LLM-proposed curation changeset an operator accepts, not just a direct call.
    """
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "del-mr", "src")
    try:
        item = store.add_backlog_item(pid, "has an open MR", position=0)
        store.update_backlog_item(
            item,
            branch="mosaera/item-x",
            mr_url="https://gl/x/-/merge_requests/9",
            mr_state="opened",
            mr_target="mosaera/item-w",
        )
        with pytest.raises(ValueError, match="merge request is open"):
            store.delete_backlog_item(item)

        # Merged is terminal — that one may go.
        store.update_backlog_item(item, mr_state="merged")
        store.delete_backlog_item(item)
        assert all(i["id"] != item for i in store.list_backlog_items(pid))
    finally:
        _drop_project(store, pid)


@requires_db
def test_split_and_merge_refuse_while_a_merge_request_is_open(store: MemoryStore) -> None:
    """The delete guard closed one door of three. `split_backlog_item` deletes the PARENT row and
    `merge_backlog_items` deletes every SOURCE row, neither with an MR check — so the same
    orphaning was reachable through two other operations, both of which an operator can trigger
    by accepting an LLM-proposed curation changeset.
    """
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "split-mr", "src")
    try:
        live = store.add_backlog_item(pid, "owns a live MR", position=0)
        other = store.add_backlog_item(pid, "ordinary", position=1)
        store.update_backlog_item(
            live,
            branch="mosaera/item-live",
            mr_url="https://gl/x/-/merge_requests/9",
            mr_state="opened",
            mr_target="main",
        )
        # split deletes the parent
        with pytest.raises(ValueError, match="merge request is open"):
            store.split_backlog_item(live, [{"title": "a"}, {"title": "b"}])
        # merge deletes the sources — the live item as a SOURCE is what gets destroyed
        with pytest.raises(ValueError, match="merge request is open"):
            store.merge_backlog_items(other, [live])
        # Both rows survived the refusals.
        assert {i["id"] for i in store.list_backlog_items(pid)} == {live, other}

        # Merged is terminal — the same operations then go through.
        store.update_backlog_item(live, mr_state="merged")
        store.merge_backlog_items(other, [live])
        assert {i["id"] for i in store.list_backlog_items(pid)} == {other}
    finally:
        _drop_project(store, pid)


@requires_db
def test_clear_todo_backlog_keeps_an_item_whose_merge_request_is_live(store: MemoryStore) -> None:
    """The fourth row-deleting door. `todo` does not imply "no merge request": a cancelled,
    timed-out, or crashed run resets its item to `todo` while `branch`/`mr_url` persist, so
    "Generate backlog" could delete a row that owned a live MR — orphaning it and destroying the
    record branch protection reads."""
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "clear-todo-mr", "src")
    try:
        live = store.add_backlog_item(pid, "todo, but owns a live MR", position=0)
        plain = store.add_backlog_item(pid, "ordinary todo", position=1)
        store.update_backlog_item(
            live,
            status="todo",  # exactly what a cancelled/crashed run leaves behind
            branch="mosaera/item-live",
            mr_url="https://gl/x/-/merge_requests/9",
            mr_state="opened",
            mr_target="main",
        )
        kept = store.clear_todo_backlog(pid)
        assert kept == 1
        assert {i["id"] for i in store.list_backlog_items(pid)} == {live}
        assert plain not in {i["id"] for i in store.list_backlog_items(pid)}

        # Merged is terminal — then the regenerate may take it.
        store.update_backlog_item(live, mr_state="merged")
        assert store.clear_todo_backlog(pid) == 0
        assert store.list_backlog_items(pid) == []
    finally:
        _drop_project(store, pid)
