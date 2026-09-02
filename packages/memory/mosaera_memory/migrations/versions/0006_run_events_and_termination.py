"""run_events transcript + runs.termination_reason

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Why a run ended without delivering (honest terminal state); NULL for a clean
    # delivery or a human decision.
    op.add_column("runs", sa.Column("termination_reason", sa.String(length=80), nullable=True))

    # Durable, append-only transcript: the fine-grained progress (tool activities,
    # agent reasoning, node completions, gate) that otherwise lives only in the
    # in-memory SSE stream. Powers the transcript export/API + benchmark harness.
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("node", sa.String(length=32), nullable=True),
        sa.Column("ts", sa.BigInteger(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_column("runs", "termination_reason")
