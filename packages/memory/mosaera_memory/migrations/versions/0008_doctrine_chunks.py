"""doctrine_chunks — the trusted planning corpus the PM follows

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Global (scope='global', project_id NULL) or per-project (scope='project')
    # planning doctrine the PM follows. The embedding column is the seam for later
    # semantic retrieval (similar_doctrine); no ANN index yet (as with artifacts).
    op.create_table(
        "doctrine_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("source", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="reference"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("doctrine_chunks")
