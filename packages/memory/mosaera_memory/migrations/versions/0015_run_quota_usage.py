"""run quota usage — durable per-subject daily run counter (#34, ADR-0050)

One row per ``(subject, day)``: how many runs a caller has started on a UTC calendar day.
``subject`` is an opaque API-owned string (``user:<id>`` | ``token``) rather than a ``users.id``
FK, because the shared service token (ADR-0004) is a legitimate caller with no user row.

The unique constraint is load-bearing, not just hygiene: it is the conflict target the atomic
check-and-consume UPSERTs against (``QuotaMixin.try_consume_run_quota``), which is what stops a
read-then-write race from admitting ``limit + 1`` runs.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_quota_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("subject", sa.String(length=80), nullable=False),  # user:<id> | token
        sa.Column("day", sa.String(length=10), nullable=False),  # UTC YYYY-MM-DD
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # The atomic-consume conflict target — named so the UPSERT can cite it explicitly.
        sa.UniqueConstraint("subject", "day", name="uq_run_quota_subject_day"),
    )
    # Today's bucket for a subject is the only read pattern; the unique constraint already
    # indexes (subject, day), so no additional index is warranted.


def downgrade() -> None:
    op.drop_table("run_quota_usage")
