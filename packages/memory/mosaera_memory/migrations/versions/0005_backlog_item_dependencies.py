"""backlog item dependency edges

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A self-referential many-to-many so a backlog item can depend on other items.
    # Both FKs CASCADE so deleting an item removes its edges in either direction.
    op.create_table(
        "backlog_item_dependencies",
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("backlog_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_id",
            sa.Integer(),
            sa.ForeignKey("backlog_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("backlog_item_dependencies")
