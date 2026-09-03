"""per-item design/architecture artifact

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The PM design stage (#3) produces an architecture per backlog item, reused
    # across runs. server_default="" backfills existing rows.
    op.add_column(
        "backlog_items",
        sa.Column("design", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("backlog_items", "design")
