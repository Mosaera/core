"""api_keys: a revocable, attributed credential for headless callers (ADR-0127).

Before this the only headless credential was `MOSAERA_API_TOKEN` — one shared secret, env-only,
with no revocation, no attribution and no rotation. Everyone holding it was indistinguishable from
everyone else, and changing it meant an env edit plus a restart for every consumer at once.
ADR-0004 kept that token deliberately as a *service* credential and it stays; this is additive.

The table mirrors `user_sessions`, which already gets the important part right: only the SHA-256 of
the credential is stored, so a database leak cannot be replayed as live access.

Three deliberate divergences from that table:

- **No `expires_at`.** A login session times out because a browser walked away. A CI job does not,
  and a credential that silently stops working at 3am is worse than one an operator revokes on
  purpose. `revoked_at` is the intended end of life.
- **`revoked_at` rather than a row delete.** `audit_events.run_id` is a NON-NULLABLE foreign key to
  `runs.id`, so there is no non-run audit channel and issuance cannot be recorded there without
  inventing a synthetic run. This row therefore IS the audit record — hard-deleting it would erase
  the history of a credential that once had access (*Capability through Auditability*).
- **`last_used_at`.** Sessions do not track use; a long-lived key must, or an operator cannot tell
  a live integration from an abandoned one before revoking. Written coarsely (only when already
  stale) so authenticating does not cost a write per request.

`name` is an operator label ("ci", "laptop") and carries no authority. Authority is fixed by the
authentication path, not by anything in this table: a key authenticates and is never admin.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # sha256 hex of the issued key. UNIQUE both to prevent a collision silently granting two
        # users the same credential and because authentication looks the row up BY this column —
        # a single indexed lookup, never a scan-and-compare over every stored key.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_token_hash", "api_keys", ["token_hash"], unique=True)
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_token_hash", table_name="api_keys")
    op.drop_table("api_keys")
