"""coverage ledger — durable code↔test map for impact selection + rot detection (#29 P2, #32)

Persists a distilled, compounding form of ``mosaera_core.coveragemap.CoverageMap``: one row per
``(project, region)`` where a region is a ``(file, function)`` keyed by a churn-stable fingerprint.
Enables impact-based test SELECTION (changed region → its covering tests), ROT detection (stored
``source_hash`` != current ⇒ unverified), and feeds the P3 token-saver. The graph write-wiring is
a later integration step (kept out of P2 to stay disjoint from #29 P1 core/oracle).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coverage_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("region_key", sa.String(length=512), nullable=False),  # file::qualname
        sa.Column("region_fingerprint", sa.String(length=64), nullable=False),  # normalized hash
        sa.Column("source_hash", sa.String(length=64), nullable=False),  # raw hash (rot signal)
        sa.Column("covering_tests", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("mutation_caught", sa.Boolean(), nullable=True),
        sa.Column(
            "last_verified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # One row per region per project — a re-verification UPSERTS in place (the map compounds).
        sa.UniqueConstraint("project_id", "region_key", name="uq_coverage_region"),
    )
    op.create_index("ix_coverage_ledger_project_id", "coverage_ledger", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_coverage_ledger_project_id", table_name="coverage_ledger")
    op.drop_table("coverage_ledger")
