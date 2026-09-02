"""backlog_items per-item branch + mr_url (ADR-0021, revertable per-item MRs)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-item stacked-MR delivery: each item carries its own branch (`mosaera/item-<id>`)
    # and the URL of the MR opened for it — mirrors Project.branch/mr_url one level down.
    op.add_column(
        "backlog_items",
        sa.Column("branch", sa.String(length=256), nullable=False, server_default=""),
    )
    op.add_column(
        "backlog_items",
        sa.Column("mr_url", sa.String(length=1024), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("backlog_items", "mr_url")
    op.drop_column("backlog_items", "branch")
