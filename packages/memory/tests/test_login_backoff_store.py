"""Login-backoff store: atomic check-and-claim (#38, ADR-0051).

Skipped unless MOSAERA_TEST_DB_URL points at a reachable database — the point of these tests is the
real Postgres UPSERT semantics (atomicity, the conditional WHERE, the overflow clamps), none of
which an in-memory fake could demonstrate.

Time is injected (`now=`) rather than slept, so the whole escalation ladder is exercised
deterministically in milliseconds.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from mosaera_memory import LOGIN_BACKOFF_EXP_CAP, MemoryStore
from mosaera_memory.models_auth import LoginBackoff
from sqlalchemy import select

# The policy under test. threshold=5 → five attempts admitted, the sixth backs off for 30s,
# doubling to a 900s ceiling; a 3600s idle starts the streak over.
_POLICY = {"threshold": 5, "base_seconds": 30, "max_seconds": 900, "reset_seconds": 3600}
_T0 = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)


# Read at import: the repo-root autouse fixture strips MOSAERA_* per test.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")

# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
pytestmark = pytest.mark.requires_db


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


@pytest.fixture
def subject() -> str:
    return uuid.uuid4().hex  # isolated per test; no cleanup needed


def _claim(store: MemoryStore, subject: str, at: datetime, **over: int) -> int | None:
    return store.claim_login_attempt(subject, **{**_POLICY, **over}, now=at)


def _force(store: MemoryStore, subject: str, *, attempts: int, at: datetime) -> None:
    """Plant a bucket state directly — reaching it through the API would take `attempts` calls."""
    with store.session() as s, s.begin():
        row = s.scalar(select(LoginBackoff).where(LoginBackoff.subject_hash == subject))
        assert row is not None
        row.attempts = attempts
        row.last_attempt_at = at


def test_attempts_below_the_threshold_are_all_admitted(store: MemoryStore, subject: str) -> None:
    assert [_claim(store, subject, _T0) for _ in range(5)] == [1, 2, 3, 4, 5]


def test_the_attempt_after_the_threshold_is_refused(store: MemoryStore, subject: str) -> None:
    for _ in range(5):
        _claim(store, subject, _T0)
    assert _claim(store, subject, _T0) is None


def test_a_refused_claim_consumes_nothing(store: MemoryStore, subject: str) -> None:
    """A hammering attacker must not be able to extend their own lock, and the counter must keep
    meaning "attempts spent" rather than "requests sent"."""
    for _ in range(5):
        _claim(store, subject, _T0)
    for _ in range(10):
        assert _claim(store, subject, _T0) is None
    record = store.get_login_backoff(subject)
    assert record is not None
    assert record["attempts"] == 5  # unmoved by the 10 refusals
    assert record["last_attempt_at"] == _T0


def test_the_lock_lifts_after_the_backoff_elapses(store: MemoryStore, subject: str) -> None:
    for _ in range(5):
        _claim(store, subject, _T0)
    assert _claim(store, subject, _T0 + timedelta(seconds=29)) is None  # a second early
    assert _claim(store, subject, _T0 + timedelta(seconds=30)) == 6  # base_seconds later


def test_the_backoff_escalates(store: MemoryStore, subject: str) -> None:
    """5 attempts → 30s → 60s → 120s: each further failure costs double."""
    at = _T0
    for _ in range(5):
        _claim(store, subject, at)
    for expected_wait, expected_attempts in ((30, 6), (60, 7), (120, 8)):
        assert _claim(store, subject, at + timedelta(seconds=expected_wait - 1)) is None
        at = at + timedelta(seconds=expected_wait)
        assert _claim(store, subject, at) == expected_attempts


def test_the_backoff_is_capped(store: MemoryStore, subject: str) -> None:
    _claim(store, subject, _T0)
    _force(store, subject, attempts=20, at=_T0)  # deep into the ladder
    assert _claim(store, subject, _T0 + timedelta(seconds=899)) is None
    assert _claim(store, subject, _T0 + timedelta(seconds=900)) is not None  # max_seconds ceiling


def test_an_idle_streak_resets(store: MemoryStore, subject: str) -> None:
    for _ in range(5):
        _claim(store, subject, _T0)
    assert _claim(store, subject, _T0 + timedelta(seconds=3600)) == 1  # a fresh streak, not a 6th


def test_a_saturated_counter_does_not_overflow_the_schedule(
    store: MemoryStore, subject: str
) -> None:
    """The clamp that stops an attacker turning POST /auth/login into a 500.

    SQL's LEAST does not short-circuit — it evaluates both arms — so an unclamped
    power(2, attempts - threshold) overflows `double precision` once the counter climbs, and the
    statement raises. This asserts the claim still executes at a saturated counter.
    """
    _claim(store, subject, _T0)
    _force(store, subject, attempts=10_000, at=_T0)  # far past LOGIN_BACKOFF_EXP_CAP
    assert _claim(store, subject, _T0 + timedelta(seconds=1)) is None  # refused, not exploded
    admitted = _claim(store, subject, _T0 + timedelta(seconds=901))  # past the capped ceiling
    assert admitted is not None


def test_the_counter_stops_at_its_cap(store: MemoryStore, subject: str) -> None:
    _claim(store, subject, _T0)
    _force(store, subject, attempts=50, at=_T0)
    assert _claim(store, subject, _T0 + timedelta(seconds=900), attempts_cap=50) == 50


def test_concurrent_claims_cannot_exceed_the_threshold(store: MemoryStore, subject: str) -> None:
    """THE reason the slot is claimed before the password is checked.

    Verification is ~130ms of scrypt. Read-count → compare → verify → increment leaves a 130ms
    window in which every concurrent request reads the same under-threshold count and gets a guess:
    the threshold would bound sequential ROUNDS, not guesses, and a caller with N connections would
    buy N guesses per window. One conditional UPSERT makes check-and-claim a single atomic step, so
    exactly `threshold` of 40 racing callers win.
    """
    with ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(lambda _: _claim(store, subject, _T0), range(40)))

    admitted = [r for r in results if r is not None]
    assert len(admitted) == _POLICY["threshold"]
    assert sorted(admitted) == [1, 2, 3, 4, 5]  # each winner took a distinct, gapless slot


def test_clear_ends_the_streak(store: MemoryStore, subject: str) -> None:
    for _ in range(5):
        _claim(store, subject, _T0)
    assert _claim(store, subject, _T0) is None
    store.clear_login_failures(subject)
    assert _claim(store, subject, _T0) == 1  # a success wipes the bucket entirely


def test_unknown_subject_has_no_bucket(store: MemoryStore, subject: str) -> None:
    assert store.get_login_backoff(subject) is None


def test_a_disabled_threshold_never_reaches_the_database(store: MemoryStore, subject: str) -> None:
    with pytest.raises(ValueError):
        _claim(store, subject, _T0, threshold=0)


def test_prune_removes_only_stale_buckets_and_honours_its_limit(store: MemoryStore) -> None:
    fresh, stale = uuid.uuid4().hex, uuid.uuid4().hex
    _claim(store, fresh, _T0)
    _claim(store, stale, _T0 - timedelta(hours=5))
    removed = store.prune_login_backoff(_T0 - timedelta(hours=1))
    assert removed >= 1
    assert store.get_login_backoff(stale) is None
    assert store.get_login_backoff(fresh) is not None  # untouched

    many = [uuid.uuid4().hex for _ in range(5)]
    for m in many:
        _claim(store, m, _T0 - timedelta(hours=5))
    assert store.prune_login_backoff(_T0 - timedelta(hours=1), limit=2) == 2  # bounded


def test_exp_cap_is_the_one_shared_constant() -> None:
    """The API mirrors this schedule for Retry-After; the clamp must come from one place so the
    two cannot drift (see mosaera_api.loginguard.backoff_seconds)."""
    assert LOGIN_BACKOFF_EXP_CAP == 32


def test_prune_sessions_still_counts_after_the_set_based_rewrite(store: MemoryStore) -> None:
    """Regression on the N+1 → single-DELETE change: it runs on every (unauthenticated) login."""
    user = store.create_user(f"prune-{uuid.uuid4().hex[:8]}", "x", max_users=999)
    try:
        store.create_session("expired-" + uuid.uuid4().hex, int(user["id"]), _T0)
        store.create_session("live-" + uuid.uuid4().hex, int(user["id"]), _T0 + timedelta(days=1))
        assert store.prune_sessions(_T0 + timedelta(hours=1)) == 1  # only the expired one
        assert store.prune_sessions(_T0 + timedelta(hours=1)) == 0  # idempotent
    finally:
        store.delete_user(int(user["id"]))
