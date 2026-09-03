"""`message_proposals` (0031): what Quincy proposed on a turn, and why it must outlive the response.

Its own module rather than more lines in `test_store.py`, which is a grandfathered file on the
shrink-only ratchet — the rule being "shrink them, or split them, but do not raise the recorded
size".
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
def test_message_proposals_survive_a_reload(store: MemoryStore) -> None:
    """The defect this table exists for: a PM turn's proposal lived only in the POST response, so
    a refresh destroyed it — and the stored reply had already been stripped down to
    "Here's what I'd suggest.", leaving a sentence with nothing under it."""
    from mosaera_memory.models import Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    mid = store.add_message(pid, "pm", "Here's what I'd suggest.")
    store.add_message_proposals(
        mid,
        [
            {"kind": "changeset", "payload": [{"op": "enhance", "id": 7}]},
            {"kind": "charter", "payload": {"goal": "ship it"}},
        ],
    )

    row = store.list_messages(pid)[-1]
    kinds = {p["kind"]: p["payload"] for p in row["proposals"]}
    assert kinds["changeset"] == [{"op": "enhance", "id": 7}]
    assert kinds["charter"] == {"goal": "ship it"}
    assert row["id"] == mid  # the card can anchor to the turn that produced it

    # Resolved proposals leave the live read: a card the operator already handled must not come
    # back on every reload, or they learn to ignore cards.
    pid_of = {p["kind"]: p["id"] for p in row["proposals"]}
    assert store.set_proposal_status(pid_of["changeset"], "accepted") is True
    assert [p["kind"] for p in store.list_messages(pid)[-1]["proposals"]] == ["charter"]

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))


@requires_db
def test_an_empty_or_unknown_proposal_is_not_stored(store: MemoryStore) -> None:
    """A row the UI cannot draw is worse than no row — it would restore a BLANK card under a reply
    whose text was already stripped of the proposal."""
    from mosaera_memory.models import Project

    pid = f"proj-test-{uuid.uuid4().hex[:8]}"
    store.create_project(pid, "P", "src")
    mid = store.add_message(pid, "pm", "reply")
    store.add_message_proposals(
        mid,
        [
            {"kind": "changeset", "payload": []},  # nothing proposed
            {"kind": "charter", "payload": None},
            {"kind": "wat", "payload": {"a": 1}},  # unknown kind
        ],
    )
    assert store.list_messages(pid)[-1]["proposals"] == []
    assert store.set_proposal_status(999_999, "accepted") is False  # unknown id
    assert store.set_proposal_status(1, "banana") is False  # unknown status

    with store.session() as s, s.begin():
        s.delete(s.get(Project, pid))
