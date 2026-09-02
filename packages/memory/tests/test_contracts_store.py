"""The test-contract registry (ADR-0087 §1-§4) — offline validators + DB-gated round-trips.

Two layers, the ``test_claims_store.py`` template: validators raise BEFORE any session opens
(provable against an unreachable URL), and the round-trips need MOSAERA_TEST_DB_URL.

The property this table exists to protect is NOT "we store rows". It is **never invent
ownership**: a project's fourth item inherits every earlier item's tests in one long-lived clone,
and `disposition.py` calls all of them "a HUMAN/baselined test". A registry that guessed an owner
would make that false statement authoritative and put it in front of an operator being asked to
authorize an amendment.
"""

from __future__ import annotations

import os
import uuid

import pytest
from mosaera_memory import MemoryStore

_OFFLINE_URL = "postgresql://u:p@127.0.0.1:1/nope"

_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
requires_db = pytest.mark.requires_db


def _offline_store() -> MemoryStore:
    return MemoryStore.from_url(_OFFLINE_URL)


# --- validators: refuse before any session opens -----------------------------------------------


def test_unknown_provenance_is_refused_offline() -> None:
    with pytest.raises(ValueError, match="provenance"):
        _offline_store().record_test_contract("p", "tests/t.py", provenance="invented")


def test_a_non_human_authority_is_refused_offline() -> None:
    """ADR-0087 §5's load-bearing constraint, re-pinned at the storage boundary: only a HUMAN
    authorizes an amendment. The Proctor writes the content; it never grants the permission."""
    with pytest.raises(ValueError, match="authority"):
        _offline_store().record_test_contract(
            "p", "tests/t.py", provenance="amended", authorized_by="autonomous"
        )
    with pytest.raises(ValueError, match="authority"):
        _offline_store().record_test_contract(
            "p", "tests/t.py", provenance="amended", authorized_by="proctor"
        )


def test_an_empty_path_is_refused_offline() -> None:
    with pytest.raises(ValueError, match="path"):
        _offline_store().record_test_contract("p", "   ", provenance="delivered")


# --- round-trips -------------------------------------------------------------------------------


def _store() -> MemoryStore:
    s = MemoryStore.from_url(str(_DB_URL))
    s.init()
    return s


def _project(s: MemoryStore) -> str:
    pid = f"proj-contract-{uuid.uuid4().hex[:8]}"
    s.create_project(pid, "ContractTest", "file:///tmp/x", "goal")
    return pid


@requires_db
def test_a_delivery_then_an_amendment_reads_as_a_history() -> None:
    s = _store()
    pid = _project(s)
    v1 = s.record_test_contract(
        pid, "tests/t.py", provenance="delivered", owner_item_id=42, content_hash="h1"
    )
    v2 = s.record_test_contract(
        pid,
        "tests/t.py",
        provenance="amended",
        content_hash="h2",
        authorized_by="human",
        amend_reason="requirement changed",
    )
    assert (v1, v2) == (1, 2)
    hist = s.test_contract_history(pid, "tests/t.py")
    assert [h["version"] for h in hist] == [1, 2]
    assert [h["amended_from_version"] for h in hist] == [None, 1]
    assert hist[1]["authorized_by"] == "human"
    assert hist[1]["amend_reason"] == "requirement changed"


@requires_db
def test_an_amendment_inherits_the_original_owner() -> None:
    """An amendment changes a bar's CONTENT, not whose bar it is. Losing the owner here would
    blank the one fact the operator most needs — "authored for item #42" — at exactly the moment
    they are asked to judge an amendment to it."""
    s = _store()
    pid = _project(s)
    s.record_test_contract(
        pid,
        "tests/t.py",
        provenance="delivered",
        owner_item_id=42,
        content_hash="h1",
        criterion="the summary prints two lines",
    )
    s.record_test_contract(
        pid, "tests/t.py", provenance="amended", content_hash="h2", authorized_by="human"
    )
    cur = s.latest_test_contracts(pid, ["tests/t.py"])["tests/t.py"]
    assert cur["owner_item_id"] == 42
    assert cur["criterion"] == "the summary prints two lines"


@requires_db
def test_re_delivering_identical_content_is_not_a_new_version() -> None:
    """Otherwise the history fills with noise and "how often is this bar amended?" — the question
    ADR-0087's Consequences section wants to answer — becomes unanswerable."""
    s = _store()
    pid = _project(s)
    assert s.record_test_contract(pid, "tests/t.py", provenance="delivered", content_hash="h1") == 1
    assert (
        s.record_test_contract(pid, "tests/t.py", provenance="delivered", content_hash="h1") is None
    )
    assert [h["version"] for h in s.test_contract_history(pid, "tests/t.py")] == [1]


@requires_db
def test_an_unregistered_path_is_ABSENT_not_a_stub() -> None:
    """THE rule. A path with no row means we do not know who wrote it — the truth for every
    human-authored test in a brownfield repo. Returning a stub is how an invented owner reaches
    an operator's screen."""
    s = _store()
    pid = _project(s)
    s.record_test_contract(pid, "tests/known.py", provenance="delivered", owner_item_id=7)
    got = s.latest_test_contracts(pid, ["tests/known.py", "tests/never_seen.py"])
    assert set(got) == {"tests/known.py"}


@requires_db
def test_contracts_are_scoped_to_their_project() -> None:
    s = _store()
    a, b = _project(s), _project(s)
    s.record_test_contract(a, "tests/t.py", provenance="delivered", owner_item_id=1)
    assert s.latest_test_contracts(b, ["tests/t.py"]) == {}


@requires_db
def test_the_assertion_profile_round_trips() -> None:
    """Stored so a weakening is auditable ACROSS runs — the in-run check only ever compares one
    run's before/after, and cannot answer "has this bar eroded over five items?"."""
    s = _store()
    pid = _project(s)
    s.record_test_contract(
        pid,
        "tests/t.py",
        provenance="delivered",
        content_hash="h1",
        assertion_profile={"test_totals": 3, "TestC.test_m": 1},
    )
    cur = s.latest_test_contracts(pid, ["tests/t.py"])["tests/t.py"]
    assert cur["assertion_profile"] == {"test_totals": 3, "TestC.test_m": 1}


@requires_db
def test_no_paths_asks_nothing() -> None:
    s = _store()
    assert s.latest_test_contracts(_project(s), []) == {}
