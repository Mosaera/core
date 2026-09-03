"""Run quota: the durable per-subject daily run counter — atomic check-and-consume (#34).

This mixin owns persistence ONLY. *Who* a subject is (a logged-in account vs. the shared
service token) and *whether* a quota applies at all are the API's decisions
(``apps/api/mosaera_api/ratelimit.py``); handing the subject string in keeps ``memory`` a leaf.
Methods are ``run_quota``-prefixed so they never collide across the mixins composed into
``MemoryStore`` (the convention ``CoverageMixin`` follows).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mosaera_memory.models import RunQuotaUsage
from mosaera_memory.store._base import StoreBase


def utc_day(now: datetime | None = None) -> str:
    """Today's quota bucket key — the UTC calendar day as ``YYYY-MM-DD``.

    Lives here (not in the API) so the bucket key and the column that stores it can never
    drift apart. Injectable ``now`` so a test can pin the day without pinning a clock.
    """
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%d")


class QuotaMixin(StoreBase):
    def try_consume_run_quota(self, subject: str, day: str, limit: int) -> int | None:
        """Consume one run from ``subject``'s ``day`` bucket iff they are under ``limit``.

        Returns the new count when consumed, or **None** when the bucket is already at/over
        the limit (in which case *nothing* is consumed — a refused attempt must not inflate
        the counter, or a client that retries would push its own bucket up forever).

        **Why one statement.** The obvious implementation — read the count, compare, write
        count+1 — is a read-then-write race: two concurrent submits both observe ``count <
        limit`` and both proceed, admitting ``limit + 1``. Postgres' conditional
        ``ON CONFLICT ... DO UPDATE ... WHERE`` makes the *check* and the *consume* a single
        atomic step, so the cap holds under concurrency without a lock or a compensating
        decrement. The insert arm covers the first run of a day; the update arm covers the
        rest; a conflicting row that fails the ``WHERE`` returns no row at all — which is
        precisely the "over quota" signal.

        ``limit`` must be positive; callers skip this entirely when the quota is disabled.
        """
        if limit <= 0:  # defensive: a disabled quota must never reach the DB
            raise ValueError("try_consume_run_quota requires a positive limit")
        now = datetime.now(UTC)
        stmt = (
            pg_insert(RunQuotaUsage)
            .values(subject=subject, day=day, count=1, created_at=now, updated_at=now)
            .on_conflict_do_update(
                constraint="uq_run_quota_subject_day",
                set_={"count": RunQuotaUsage.__table__.c.count + 1, "updated_at": now},
                # The atomic gate: only bump a bucket that is still under the cap.
                where=RunQuotaUsage.__table__.c.count < limit,
            )
            .returning(RunQuotaUsage.__table__.c.count)
        )
        with self.session() as s, s.begin():
            return s.execute(stmt).scalar_one_or_none()

    def run_quota_used(self, subject: str, day: str) -> int:
        """How many runs ``subject`` has started on ``day`` (0 when it has no bucket).

        Read-only — for tests and future surfacing. Never use this to decide admission:
        that check must be the atomic consume above.
        """
        stmt = select(RunQuotaUsage.count).where(
            RunQuotaUsage.subject == subject, RunQuotaUsage.day == day
        )
        with self.session() as s:
            return int(s.scalar(stmt) or 0)
