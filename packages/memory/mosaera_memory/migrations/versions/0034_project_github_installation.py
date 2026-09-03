"""project github installation id (ADR-0114)

Which GitHub App installation can reach this project's repository.

Deliberately NOT encrypted, unlike every neighbouring credential column (`gitlab_token`,
`gitlab_api_token`). An installation id is an identifier, not a credential: it grants nothing
on its own, and the value that does — a 1-hour installation access token scoped to the single
repository — is minted immediately before each delivery and never persisted.

It is a CACHE of a fact GitHub owns (the repo → installation mapping), not a second source of
truth for it. A stored id is re-resolved when it stops working rather than being reported as a
working connection; treating it as proof of access would be the "second origin" defect class.

RENUMBERED ON LANDING (2026-08-24). This was authored as `0033` chaining `0032`, and by the time
it merged there were THREE files claiming `0033`: `0033_message_steps` had landed upstream, and the
#121 branch carried `0033_project_setup`. The filenames differ, so git merges all of them without a
conflict and Alembic silently ends up with multiple HEADS — a break no offline test catches (the
drift guard is DB-gated). Landed as `0034` after upstream's `0033`; #121 follows as `0035`.
`scripts/check_migration_chain.py`, added here, is what makes that failure loud instead of silent.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "github_installation_id", sa.String(length=32), nullable=False, server_default=""
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "github_installation_id")
