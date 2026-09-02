"""backlog_items.mr_state: the item MR's last-polled state (ADR-0102 slice O).

Item MRs (ADR-0021) stored a `mr_url` that nothing ever polled, so an item merged on
GitLab still read as in_review forever. This column records what the poll saw
("" | opened | merged | closed). It is deliberately NOT a fifth value on `status` —
the autonomous sweep's completeness logic consumes that enum and a new member would
silently break it.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "backlog_items",
        sa.Column("mr_state", sa.String(length=16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("backlog_items", "mr_state")
