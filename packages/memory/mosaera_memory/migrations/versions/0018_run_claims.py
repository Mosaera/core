"""The claim ledger (ADR-0079): per-run acceptance claims + evaluated dispositions.

One row per claim per run: the claim as launched (text, provenance, oracle binding — derived
from the item's operator-approved acceptance) plus the verdict the run's oracles produced.
`provenance` is NOT NULL and store-validated (the map-observation "no bare claims" precedent);
enumerable columns are Strings validated at the write boundary, never DB CHECKs. Rows cascade
with their run.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # (item_id, claim_id) is the cross-run claim identity; claims are re-derived per run.
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=sa.text("''")),
        # one of ENTAILED|REPOSITORY_INVARIANT|INFERRED — validated in the store
        sa.Column("provenance", sa.String(length=32), nullable=False),
        # one of the core oracle-kind vocabulary — validated in the store
        sa.Column("oracle_kind", sa.String(length=32), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("material", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # one of satisfied|failed|unbound|unevaluable — validated in the store
        sa.Column("verdict", sa.String(length=16), nullable=False),
        # Evidence POINTER (a location/name, never a value)
        sa.Column(
            "oracle_ref", sa.String(length=512), nullable=False, server_default=sa.text("''")
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_run_claims_run_id", "run_claims", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_claims_run_id", table_name="run_claims")
    op.drop_table("run_claims")
