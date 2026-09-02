"""test_contracts: who owns a delivered test, and its amendment history (ADR-0087 §1-§4).

Project item runs share ONE long-lived clone, so a test delivered by item N lands in item N+1's
integrity baseline indistinguishable from a human's. Nothing in the engine could say otherwise —
`disposition.py` calls every baselined path "a HUMAN/baselined test", which is false on a
project's fourth item. This table is the missing fact.

One append-only versioned row per (project, path, version): version 1 is a delivery, N+1 an
amendment, and the version history IS the amendment record. Rows are written only for paths a run
demonstrably authored or amended — absence means the owner is UNKNOWN, which is the truth and
which the operator surface must say rather than guessing.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "test_contracts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        # NULL = genuinely unknown owner. Never a placeholder for "we didn't look".
        sa.Column("owner_item_id", sa.Integer(), nullable=True),
        sa.Column("owner_run_id", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("criterion", sa.Text(), nullable=False, server_default=""),
        sa.Column("amended_from_version", sa.Integer(), nullable=True),
        sa.Column("authorized_by", sa.String(length=32), nullable=True),
        sa.Column("amend_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "assertion_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        # SET NULL, not CASCADE: losing the run must not erase the fact that the contract exists.
        sa.ForeignKeyConstraint(["owner_run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "path", "version", name="uq_contract_ver"),
    )
    op.create_index("ix_test_contracts_project_id", "test_contracts", ["project_id"])
    op.create_index("ix_test_contracts_path", "test_contracts", ["path"])


def downgrade() -> None:
    op.drop_index("ix_test_contracts_path", table_name="test_contracts")
    op.drop_index("ix_test_contracts_project_id", table_name="test_contracts")
    op.drop_table("test_contracts")
