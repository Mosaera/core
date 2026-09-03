"""Interactive-latency samples (#22) — split from models.py when the god-file ratchet
fired (504 lines): a standalone, self-contained model family (the models_auth/chat/coverage
precedent). Registered on Base.metadata via the bottom re-export in models.py."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow


class LatencySample(Base):
    """One timing sample for an interactive (human-blocking) code path — e.g. a
    synchronous PM chat turn. Powers the p50/p95 "interactive latency" governance
    metric (#22): perceived latency is a feature, so we measure the paths a human
    actually waits on. Best-effort — recording a sample never breaks the path."""

    __tablename__ = "latency_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # run_id is nullable: most interactive paths (PM chat) are not inside a run.
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(64))  # e.g. "pm_chat"
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
