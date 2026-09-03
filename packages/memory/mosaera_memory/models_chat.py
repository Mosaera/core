"""PM chat session ORM model: per-project conversation threads (issue #30).

Split out of ``models.py`` (which is at the modularity ceiling) but part of the SAME
declarative ``Base`` — ``models.py`` re-exports this at its bottom, so importers keep using
``from mosaera_memory.models import PmSession`` unchanged and ``Base.metadata`` stays complete.

A session groups a project's chat turns into an isolated thread: **history is per-session**,
while project knowledge (brief, backlog, runs, the context registry) stays shared across a
project's sessions. This lets Quincy front many parallel conversations without one bleeding
into another (ADR-0048; this cited ADR-0045 until 2026-08-20 — that ADR is the FIRM layer, which
remains unbuilt direction, while ADR-0048 is the decision that actually introduced PM sessions)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow


class PmSession(Base):
    """One PM (Quincy) conversation thread within a project.

    ``title`` is auto-derived from the first user turn (empty until then; the UI shows a
    generic label meanwhile). Archiving is soft — ``archived_at`` set hides the session from
    the active switcher but never deletes its transcript. ``updated_at`` is bumped on every
    new turn so the session list orders by recency."""

    __tablename__ = "pm_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sess-<hex>
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
