"""Run-quota store: atomic check-and-consume (#34, ADR-0050).

Skipped unless MOSAERA_TEST_DB_URL points at a reachable database — the whole point of these
tests is the real Postgres UPSERT semantics, which an in-memory fake could not demonstrate.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from mosaera_memory import MemoryStore, utc_day

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
    return f"user:{uuid.uuid4().hex[:8]}"  # isolated per test; no cleanup needed


def test_utc_day_is_a_calendar_day_string() -> None:
    assert utc_day(datetime(2026, 7, 17, 23, 59, tzinfo=UTC)) == "2026-07-17"
    assert utc_day(datetime(2026, 7, 18, 0, 0, tzinfo=UTC)) == "2026-07-18"


def test_consume_counts_up_then_refuses_at_the_limit(store: MemoryStore, subject: str) -> None:
    day = utc_day()
    assert store.try_consume_run_quota(subject, day, 3) == 1
    assert store.try_consume_run_quota(subject, day, 3) == 2
    assert store.try_consume_run_quota(subject, day, 3) == 3
    assert store.try_consume_run_quota(subject, day, 3) is None  # 4th refused
    assert store.run_quota_used(subject, day) == 3


def test_a_refused_attempt_consumes_nothing(store: MemoryStore, subject: str) -> None:
    """A client that retries past its cap must not inflate its own counter — otherwise the
    recorded usage stops meaning "runs started"."""
    day = utc_day()
    store.try_consume_run_quota(subject, day, 1)
    for _ in range(5):
        assert store.try_consume_run_quota(subject, day, 1) is None
    assert store.run_quota_used(subject, day) == 1


def test_buckets_are_per_day_and_per_subject(store: MemoryStore, subject: str) -> None:
    store.try_consume_run_quota(subject, "2026-07-17", 1)
    assert store.try_consume_run_quota(subject, "2026-07-17", 1) is None
    assert store.try_consume_run_quota(subject, "2026-07-18", 1) == 1  # tomorrow: fresh
    assert store.try_consume_run_quota(f"{subject}-other", "2026-07-17", 1) == 1  # other subject


def test_unused_subject_reports_zero(store: MemoryStore, subject: str) -> None:
    assert store.run_quota_used(subject, utc_day()) == 0


def test_a_disabled_quota_never_reaches_the_database(store: MemoryStore, subject: str) -> None:
    with pytest.raises(ValueError):
        store.try_consume_run_quota(subject, utc_day(), 0)


def test_concurrent_consumes_cannot_exceed_the_limit(store: MemoryStore, subject: str) -> None:
    """The reason this is one statement rather than read-compare-write.

    Twenty threads race for a limit of 5. A read-then-write counter lets several observe
    ``count < limit`` before any writes and admit more than 5; the conditional ON CONFLICT makes
    the check and the consume a single atomic step, so exactly 5 win.
    """
    day = utc_day()
    limit = 5
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(
            pool.map(lambda _: store.try_consume_run_quota(subject, day, limit), range(20))
        )

    granted = [r for r in results if r is not None]
    assert len(granted) == limit
    assert sorted(granted) == [1, 2, 3, 4, 5]  # each winner got a distinct, gapless count
    assert store.run_quota_used(subject, day) == limit
