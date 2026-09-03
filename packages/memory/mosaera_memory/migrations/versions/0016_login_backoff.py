"""login backoff — per-account failed-login throttle (#38, ADR-0051)

One row per ``subject_hash``: how many login attempts a subject has spent, and when. The subject is
the SHA-256 of the *submitted* username (normalized ``.strip()``), not a ``users.id`` FK — unknown
usernames must back off identically to real accounts, or the 429 becomes a username-enumeration
oracle. Most subjects therefore have no corresponding ``users`` row, and the value is hashed so a
durable table can't capture passwords typed into the username box.

The unique constraint is load-bearing, not hygiene: it is the conflict target the atomic
check-and-claim UPSERTs against (``AuthMixin.claim_login_attempt``), which is what lets the slot be
claimed BEFORE ~130ms of scrypt — otherwise concurrent requests all observe "under the threshold"
and the threshold bounds rounds instead of guesses.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_backoff",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),  # sha256 hex
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # The atomic-claim conflict target — named so the UPSERT can cite it explicitly.
        sa.UniqueConstraint("subject_hash", name="uq_login_backoff_subject"),
    )
    # The prune's range predicate. Unlike the run-quota table (bounded by the seat cap), these
    # buckets are attacker-controlled: any submitted username makes one, so they need sweeping.
    op.create_index("ix_login_backoff_last_attempt_at", "login_backoff", ["last_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_login_backoff_last_attempt_at", table_name="login_backoff")
    op.drop_table("login_backoff")
