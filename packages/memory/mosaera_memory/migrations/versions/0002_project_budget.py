"""project monthly budget columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-project monthly spend ceilings; NULL = no cap.
    op.add_column("projects", sa.Column("budget_usd", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("budget_tokens", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "budget_tokens")
    op.drop_column("projects", "budget_usd")
