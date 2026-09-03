"""message_steps: what Quincy looked up on a turn.

Sibling of ``message_proposals`` (0031) in every respect — same parent, same CASCADE — so a turn
keeps the record of its own lookups and a reload does not lose it.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "message_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("project_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("arg", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_message_steps_message_id", "message_steps", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_steps_message_id", table_name="message_steps")
    op.drop_table("message_steps")
