"""Intake clarification on backlog items (ADR-0080 §1).

One nullable JSON column: the OPEN clarification request Quincy raised on this item —
`{claim_text, why_unbindable, proposals: [str], status: open|resolved, asked_at}`. One request
per item (ADR-0080's batching/fatigue rule); resolving clears or marks it. Validation lives at
the store write boundary, never in the DB.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "backlog_items",
        sa.Column("clarification", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("backlog_items", "clarification")
