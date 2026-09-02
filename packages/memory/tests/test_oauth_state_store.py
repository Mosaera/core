"""OAuth "Connect" state store (ADR-0104): the atomic single-use spend + TTL + binding.

Skipped unless MOSAERA_TEST_DB_URL points at a reachable database — the point is the real Postgres
DELETE ... RETURNING semantics (single-use under concurrency, provider matching), which an
in-memory fake could not demonstrate. Time is injected (`now=`) so expiry is exercised without
sleeping.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from mosaera_memory import MemoryStore

_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")
pytestmark = pytest.mark.requires_db
_T0 = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def store() -> Iterator[MemoryStore]:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    yield s
    # DESTRUCTIVE teardown (a test DB only): users carry a hard seat cap, so leaving the admins
    # these tests mint would trip other suites' cap assertions. Deleting the users cascades to
    # their oauth_states (the user_id FK is ON DELETE CASCADE). Mirrors test_auth's teardown.
    for u in s.list_users():
        s.delete_user(int(u["id"]))


def _admin(store: MemoryStore) -> int:
    # A high seat cap so a single test file that mints several admins never self-trips the limit.
    u = store.create_user(f"admin-{uuid.uuid4().hex[:8]}", "hash", is_admin=True, max_users=10_000)
    return int(u["id"])


def _hash() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex  # a 64-char stand-in for the SHA-256 hex


def test_mint_then_spend_returns_the_binding_exactly_once(store: MemoryStore) -> None:
    uid = _admin(store)
    h = _hash()
    store.mint_oauth_state(h, uid, "p1", "gitlab", _T0 + timedelta(minutes=10))
    first = store.spend_oauth_state(h, "gitlab", _T0 + timedelta(minutes=1))
    assert first == {"user_id": uid, "project_id": "p1", "provider": "gitlab"}
    # SINGLE-USE: a replay finds nothing (the row was deleted by the winning spend).
    assert store.spend_oauth_state(h, "gitlab", _T0 + timedelta(minutes=1)) is None


def test_expired_state_does_not_authorize(store: MemoryStore) -> None:
    uid = _admin(store)
    h = _hash()
    store.mint_oauth_state(h, uid, "p1", "gitlab", _T0 + timedelta(minutes=10))
    # Spent AFTER its TTL → None (and the row is gone, so it can't be retried either).
    assert store.spend_oauth_state(h, "gitlab", _T0 + timedelta(minutes=20)) is None
    assert store.spend_oauth_state(h, "gitlab", _T0 + timedelta(minutes=1)) is None


def test_provider_must_match(store: MemoryStore) -> None:
    uid = _admin(store)
    h = _hash()
    store.mint_oauth_state(h, uid, "p1", "gitlab", _T0 + timedelta(minutes=10))
    # A state minted for gitlab can't be spent as another provider; the gitlab spend still works.
    assert store.spend_oauth_state(h, "github", _T0 + timedelta(minutes=1)) is None
    assert store.spend_oauth_state(h, "gitlab", _T0 + timedelta(minutes=1)) is not None


def test_concurrent_spend_admits_exactly_one_winner(store: MemoryStore) -> None:
    uid = _admin(store)
    h = _hash()
    store.mint_oauth_state(h, uid, "p1", "gitlab", _T0 + timedelta(minutes=10))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: store.spend_oauth_state(h, "gitlab", _T0 + timedelta(minutes=1)), range(8)
            )
        )
    winners = [r for r in results if r is not None]
    assert len(winners) == 1  # DELETE ... RETURNING row-locks — exactly one caller wins


def test_sweep_removes_only_expired_states(store: MemoryStore) -> None:
    uid = _admin(store)
    live, dead = _hash(), _hash()
    store.mint_oauth_state(live, uid, "p1", "gitlab", _T0 + timedelta(minutes=30))
    store.mint_oauth_state(dead, uid, "p1", "gitlab", _T0 + timedelta(minutes=1))
    removed = store.sweep_expired_oauth_states(_T0 + timedelta(minutes=10))
    assert removed == 1
    assert store.spend_oauth_state(dead, "gitlab", _T0 + timedelta(minutes=1)) is None  # swept
    assert store.spend_oauth_state(live, "gitlab", _T0 + timedelta(minutes=20)) is not None  # kept
