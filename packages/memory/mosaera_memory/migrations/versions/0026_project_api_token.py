"""projects.gitlab_api_token: an optional api-scoped credential for REST metadata (ADR-0103).

MRs are created via git push-options over the `write_repository` token today, which cannot
carry a faithful multi-line body, cannot edit an MR, and cannot list branches. Those need the
GitLab REST API → the `api` scope. This column holds an OPTIONAL, per-project, encrypted
`api`-scoped token used ONLY by operator-initiated REST metadata calls — never git transport
(that stays on `gitlab_token`) and never the autonomous sweep. Write-only like `gitlab_token`.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("gitlab_api_token", sa.String(length=512), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("projects", "gitlab_api_token")
