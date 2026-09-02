"""Run seal columns (#63 Ledger view).

Three nullable columns on `runs`: `finished_at` (stamped on every terminal transition),
`engine_version` (the mosaera_core version that PRODUCED the run — stamped at finalize,
never back-filled), and `receipt_id` (deterministic sha256 over run_id + commit_sha +
engine_version + the receipt JSON — minted only when a receipt decision exists). NULL is
the honest "pre-0020 row / never finalized / no receipt" state; the UI must never proxy
a live value for a NULL stamp.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("engine_version", sa.String(32), nullable=True))
    op.add_column("runs", sa.Column("receipt_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "receipt_id")
    op.drop_column("runs", "engine_version")
    op.drop_column("runs", "finished_at")
