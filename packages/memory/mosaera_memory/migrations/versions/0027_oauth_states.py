"""oauth_states: single-use, hashed, bound state for the GitLab OAuth "Connect" flow (ADR-0104).

One row per in-flight OAuth handshake. Holds only the SHA-256 of a random ``state`` (plaintext
never stored), is single-use (the callback spends it with an atomic DELETE ... RETURNING), carries
a short TTL, and binds the initiating admin (``user_id``) + selected ``project_id`` + ``provider``.
That binding is the CSRF defense AND the authorization: a callback can only provision the project
the admin selected, for that admin. Nothing here is a durable credential — the OAuth grant is
discarded once the project token is minted, so there is no per-user token table.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_states_state_hash", "oauth_states", ["state_hash"], unique=True)
    op.create_index("ix_oauth_states_user_id", "oauth_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_states_state_hash", table_name="oauth_states")
    op.drop_index("ix_oauth_states_user_id", table_name="oauth_states")
    op.drop_table("oauth_states")
