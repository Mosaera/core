"""Intake-clarification store (ADR-0080, Wave 3) — offline validators + DB round-trip."""

from __future__ import annotations

import os
import uuid

import pytest
from mosaera_memory import MemoryStore

_OFFLINE_URL = "postgresql://u:p@127.0.0.1:1/nope"


# Read at import: the repo-root autouse fixture strips MOSAERA_* per test.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")

# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_db = pytest.mark.requires_db


def test_empty_claim_text_rejected_offline() -> None:
    with pytest.raises(ValueError, match="claim_text"):
        MemoryStore.from_url(_OFFLINE_URL).set_item_clarification(
            1,
            claim_text="",
            why_unbindable="",
            proposals=["p"],
            axis="checkability",
            proposal_kind="acceptance",
        )


def test_no_proposals_rejected_offline() -> None:
    with pytest.raises(ValueError, match="proposal"):
        MemoryStore.from_url(_OFFLINE_URL).set_item_clarification(
            1,
            claim_text="x",
            why_unbindable="",
            proposals=["", "  "],
            axis="checkability",
            proposal_kind="acceptance",
        )


@requires_db
def test_clarification_round_trip_and_resolution() -> None:
    store = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    store.init()
    pid = f"clar-{uuid.uuid4().hex[:10]}"
    store.create_project(pid, "P", "src")
    try:
        iid = store.add_backlog_item(pid, "wiring", "", "wired up nicely", 0)
        store.set_item_clarification(
            iid,
            claim_text="wired up nicely",
            why_unbindable="no behaviour",
            proposals=["p1", "p2"],
            axis="checkability",
            proposal_kind="acceptance",
        )
        open_req = store.item_clarification(iid)
        assert open_req is not None and open_req["proposals"] == ["p1", "p2"]
        # summary carries it
        row = store.get_backlog_item(iid)
        assert row is not None and row["clarification"]["status"] == "open"
        # a NEW request replaces the old (one per item — the batching rule)
        store.set_item_clarification(
            iid,
            claim_text="still vague",
            why_unbindable="",
            proposals=["p3"],
            axis="checkability",
            proposal_kind="acceptance",
        )
        assert store.item_clarification(iid)["proposals"] == ["p3"]  # type: ignore[index]
        store.resolve_item_clarification(iid, status="resolved", resolution="tags survive restart")
        assert store.item_clarification(iid) is None  # the launch gate sees no OPEN ask
        row = store.get_backlog_item(iid)
        assert row is not None
        assert row["clarification"] is None  # open-only field unchanged for existing UI
        # The exchange is RETAINED (#63 ledger): ask + answer + when.
        record = row["clarification_record"]
        assert record["status"] == "resolved"
        assert record["resolution"] == "tags survive restart"
        assert record["claim_text"] == "still vague"
        assert record["resolved_at"]
    finally:
        store.delete_project(pid)


@requires_db
def test_dismissed_clarification_retained_without_resolution() -> None:
    store = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    store.init()
    pid = f"clar-{uuid.uuid4().hex[:10]}"
    store.create_project(pid, "P", "src")
    try:
        iid = store.add_backlog_item(pid, "w", "", "vague", 0)
        store.set_item_clarification(
            iid,
            claim_text="vague",
            why_unbindable="",
            proposals=["p"],
            axis="checkability",
            proposal_kind="acceptance",
        )
        store.resolve_item_clarification(iid, status="dismissed")
        row = store.get_backlog_item(iid)
        assert row is not None and row["clarification"] is None
        assert row["clarification_record"]["status"] == "dismissed"
        assert row["clarification_record"]["resolution"] == ""
    finally:
        store.delete_project(pid)


def test_resolve_rejects_unknown_status_offline() -> None:
    # An enumerable, never free text — validated before any session opens.
    with pytest.raises(ValueError, match="status"):
        MemoryStore.from_url(_OFFLINE_URL).resolve_item_clarification(1, status="closed")
