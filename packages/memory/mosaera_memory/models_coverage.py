"""Coverage-ledger ORM model: the durable code↔test map (issue #32, #29 P2).

Split out of ``models.py`` (at the modularity ceiling) but part of the SAME declarative ``Base``
— ``models.py`` re-exports it at the bottom, so importers keep using
``from mosaera_memory.models import CoverageLedger`` and ``Base.metadata`` stays complete.

Persists a DISTILLED, compounding form of ``mosaera_core.coveragemap.CoverageMap``: one row per
``(project, region)``, where a region is a ``(file, function)`` unit keyed by a churn-stable
fingerprint (see ``mosaera_memory._fingerprint``). Compounding the map across runs is what
enables **impact-based test selection**, **rot detection**, and the P3 token-saver. The graph
write-wiring (``test_node`` → ledger) is a LATER integration step, kept out of #32 so this stays
disjoint from #29 P1 (core/oracle)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mosaera_memory.models import Base, _utcnow


class CoverageLedger(Base):
    """One region's persisted coverage.

    - ``region_key`` (``file::qualname``) — the stable identity coverage re-attaches to.
    - ``region_fingerprint`` — normalized-source hash; survives line churn + cosmetic edits.
    - ``source_hash`` — raw-source hash; the rot signal (differs from current ⇒ unverified).
    - ``covering_tests`` — the test ids that exercised the region (basis for impact selection).
    - ``mutation_caught`` — nullable P4 mutation-check verdict (unknown until measured).
    - ``last_verified_at`` — when this region's coverage was last confirmed.

    Unique per ``(project_id, region_key)`` so a re-verification UPSERTS in place — the map
    compounds instead of accumulating duplicate rows."""

    __tablename__ = "coverage_ledger"
    __table_args__ = (UniqueConstraint("project_id", "region_key", name="uq_coverage_region"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    region_key: Mapped[str] = mapped_column(String(512))  # file::qualname
    region_fingerprint: Mapped[str] = mapped_column(String(64))  # normalized-source sha256
    source_hash: Mapped[str] = mapped_column(String(64))  # raw-source sha256 (rot signal)
    covering_tests: Mapped[list[str]] = mapped_column(JSON, default=list)  # test ids
    mutation_caught: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
