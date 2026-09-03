"""first-run setup-token gate — single-row setup_tokens (ADR-0040)

Holds only the SHA-256 of the random token printed to the startup logs on a fresh instance;
``/auth/setup`` requires it before minting the first admin, and the row is deleted once that
admin exists. Fixed PK (always 1) makes it a single row; insert-if-absent is multi-worker-safe.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-15 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "setup_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),  # always 1
        sa.Column("token_hash", sa.String(length=64), nullable=False),  # sha256 hex
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("setup_tokens")
