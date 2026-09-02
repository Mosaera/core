"""onboarding map + charter — the durable project map and operator charter (#40, ADR-0047)

Three tables, two trust levels (ADR-0047 §1):

- ``project_charters`` — the TRUSTED, operator-authored intent (goal + constraints + posture). One
  row per project (``project_id`` is the PK). Edited, never recomputed (§7).
- ``project_map_dimensions`` — the UNTRUSTED, recon-derived map, one row per (project, dimension):
  tri-state ``status`` (finding/clean/unavailable, §5) + a per-dimension ``fingerprint`` (NULL ⇒
  unknown ⇒ stale, §4) + a loud ``unavailable_reason``.
- ``project_map_observations`` — provenanced facts under a dimension. ``provenance`` (source
  LOCATION) is NOT NULL — the map records observations about the repo, never bare claims (§1); a
  gitleaks finding stores its location, never the secret value.

The map must never reach the gate (§2) — enforced structurally by the layer guard, not this schema.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TRUSTED: the operator charter — one row per project (project_id is the PK).
    op.create_table(
        "project_charters",
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("goal", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("constraints", sa.Text(), nullable=False, server_default=sa.text("''")),
        # free | business | regulated (ADR-0046); validated in the store, not by a DB CHECK.
        sa.Column(
            "posture", sa.String(length=16), nullable=False, server_default=sa.text("'business'")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # UNTRUSTED: the recon map — one row per (project, dimension), the map compounds via upsert.
    op.create_table(
        "project_map_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(length=32), nullable=False),  # one of MAP_DIMENSIONS
        sa.Column("status", sa.String(length=16), nullable=False),  # finding|clean|unavailable
        # NULL fingerprint = unknown freshness ⇒ stale (deny-by-default, §4).
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("unavailable_reason", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "dimension", name="uq_map_dimension"),
    )
    op.create_index(
        "ix_project_map_dimensions_project_id", "project_map_dimensions", ["project_id"]
    )

    # Provenanced facts under a dimension — provenance (source location) is REQUIRED (§1).
    op.create_table(
        "project_map_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "dimension_id",
            sa.Integer(),
            sa.ForeignKey("project_map_dimensions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Source LOCATION only — never a secret value (gitleaks records where, not what).
        sa.Column("provenance", sa.String(length=512), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "severity", sa.String(length=16), nullable=False, server_default=sa.text("'info'")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_project_map_observations_dimension_id",
        "project_map_observations",
        ["dimension_id"],
    )


def downgrade() -> None:
    # FK-safe order: observations → dimensions → charter.
    op.drop_index("ix_project_map_observations_dimension_id", table_name="project_map_observations")
    op.drop_table("project_map_observations")
    op.drop_index("ix_project_map_dimensions_project_id", table_name="project_map_dimensions")
    op.drop_table("project_map_dimensions")
    op.drop_table("project_charters")
