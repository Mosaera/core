"""Claim-ledger store (ADR-0079 Wave 2) — offline validators + DB-gated round-trips.

Two layers, the test_onboarding_store.py template: validators raise BEFORE any session opens
(provable against an unreachable URL), and the round-trips need MOSAERA_TEST_DB_URL.
"""

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


def _offline_store() -> MemoryStore:
    return MemoryStore.from_url(_OFFLINE_URL)


def _row(**over: object) -> dict:
    row = {
        "claim_id": "1-c1",
        "item_id": 1,
        "text": "returns the sorted list",
        "provenance": "ENTAILED",
        "oracle_kind": "acceptance_test",
        "predicate": "",
        "material": True,
        "verdict": "satisfied",
        "oracle_ref": "validation pipeline passed",
        "schema_version": 1,
    }
    row.update(over)
    return row


# ── offline: validators fire before any session opens ────────────────────────
def test_unknown_provenance_rejected_offline() -> None:
    with pytest.raises(ValueError, match="provenance"):
        _offline_store().add_run_claims("r1", [_row(provenance="GUESSED")])


def test_unknown_oracle_kind_rejected_offline() -> None:
    with pytest.raises(ValueError, match="oracle_kind"):
        _offline_store().add_run_claims("r1", [_row(oracle_kind="vibes")])


def test_unknown_verdict_rejected_offline() -> None:
    with pytest.raises(ValueError, match="verdict"):
        _offline_store().add_run_claims("r1", [_row(verdict="probably")])


def test_empty_claim_id_rejected_offline() -> None:
    with pytest.raises(ValueError, match="claim_id"):
        _offline_store().add_run_claims("r1", [_row(claim_id="")])


def test_one_bad_row_rejects_the_whole_batch_offline() -> None:
    # No half-written ledger: validation is all-before-any-write.
    with pytest.raises(ValueError, match="row 1"):
        _offline_store().add_run_claims("r1", [_row(), _row(verdict="nope")])


def test_vocabularies_match_core() -> None:
    # Memory is a strict leaf and cannot import core at runtime — but TESTS can, so the
    # re-declared vocabularies can never drift silently.
    from mosaera_core.claim_oracles import VERDICTS
    from mosaera_core.claims import ORACLE_KINDS, PROVENANCES
    from mosaera_memory.models_claims import (
        CLAIM_ORACLE_KINDS,
        CLAIM_PROVENANCES,
        CLAIM_VERDICTS,
    )

    assert CLAIM_PROVENANCES == set(PROVENANCES)
    assert CLAIM_ORACLE_KINDS == set(ORACLE_KINDS)
    assert CLAIM_VERDICTS == set(VERDICTS)


# ── DB-gated round-trips ─────────────────────────────────────────────────────
@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


@requires_db
def test_round_trip_and_order(store: MemoryStore) -> None:
    run_id = f"claims-{uuid.uuid4().hex[:10]}"
    store.ensure_run(run_id, source="test", branch="main", task="t")
    store.add_run_claims(
        run_id,
        [_row(), _row(claim_id="1-c2", verdict="failed", oracle_ref="data_driven_single_if")],
    )
    rows = store.list_run_claims(run_id)
    assert [r["claim_id"] for r in rows] == ["1-c1", "1-c2"]
    assert rows[1]["verdict"] == "failed"
    assert rows[0]["provenance"] == "ENTAILED" and rows[0]["schema_version"] == 1


@requires_db
def test_empty_batch_is_a_noop(store: MemoryStore) -> None:
    run_id = f"claims-{uuid.uuid4().hex[:10]}"
    store.ensure_run(run_id, source="test", branch="main", task="t")
    store.add_run_claims(run_id, [])
    assert store.list_run_claims(run_id) == []


@requires_db
def test_run_detail_includes_the_claim_ledger(store: MemoryStore) -> None:
    # The ledger rides run_detail (no separate endpoint) — the receipt UI always
    # wants per-claim verdicts with the decisions. Absent claims ⇒ an empty list.
    run_id = f"claims-{uuid.uuid4().hex[:10]}"
    store.ensure_run(run_id, source="test", branch="main", task="t")
    detail = store.run_detail(run_id)
    assert detail is not None and detail["claims"] == []
    store.add_run_claims(run_id, [_row()])
    detail = store.run_detail(run_id)
    assert detail is not None
    assert [c["claim_id"] for c in detail["claims"]] == ["1-c1"]
    assert detail["claims"][0]["verdict"] == "satisfied"
