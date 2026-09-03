"""backlog_items soft-lock (locked + lock_reason)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The PM's advisory, user-overridable hold on running an item, with a caveat.
    # Distinct from the derived blocked_by (a human can unlock to run early).
    op.add_column(
        "backlog_items",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "backlog_items",
        sa.Column("lock_reason", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("backlog_items", "lock_reason")
    op.drop_column("backlog_items", "locked")
