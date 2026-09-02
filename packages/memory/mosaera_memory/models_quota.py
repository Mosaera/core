"""Run-quota ORM model: the durable per-subject daily run counter (issue #34, ADR-0050).

Split out of ``models.py`` (which is at the modularity ceiling) but part of the SAME declarative
``Base`` — ``models.py`` re-exports it at the bottom, so importers keep using
``from mosaera_memory.models import RunQuotaUsage`` and ``Base.metadata`` stays complete
(the pattern ``models_auth`` / ``models_coverage`` already established).

Two deliberate shape choices, both about representing the API's real callers:

- **``subject`` is an opaque string, not a ``users.id`` FK.** The shared service token
  (ADR-0004) is a legitimate caller with **no user row**, so a FK could not represent it at
  all. The subject vocabulary is owned by the API (``apps/api/mosaera_api/ratelimit.py``):
  ``user:<id>`` for a logged-in account, ``token`` for the service token. Keeping the
  vocabulary out of the schema is also what keeps ``memory`` a leaf — it stores counters and
  knows nothing about how identity is decided.
- **``day`` is a UTC ``YYYY-MM-DD`` string, not a ``Date``.** The bucket identity *is* the
  calendar-day string, so storing it verbatim removes any dependence on the server/session
  timezone for what "today" means — the quota resets at UTC midnight everywhere, and a test
  can pin a day without pinning a clock.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow


class RunQuotaUsage(Base):
    """One ``(subject, day)`` bucket: how many runs that caller has started today.

    Rows accumulate one per active subject per day; they are small and self-expiring in
    relevance (nothing reads yesterday's bucket), so there is no sweeper — see ADR-0050 for
    the retention note.
    """

    __tablename__ = "run_quota_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ``user:<id>`` | ``token`` — the API's subject vocabulary (see module docstring).
    subject: Mapped[str] = mapped_column(String(80), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # UTC YYYY-MM-DD
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # One bucket per subject per day — the uniqueness the atomic consume UPSERTs against.
    __table_args__ = (UniqueConstraint("subject", "day", name="uq_run_quota_subject_day"),)
