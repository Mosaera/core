"""projects.repo_overview_key: the clone HEAD the cached repo overview was built from.

``repo_overview`` is the file listing (plus README) that gives Quincy his only view of the
codebase. It was written in exactly ONE place — ``run_intake``, at project creation — and never
again, while the project clone at ``projects_dir/<id>/repo`` advances on every approved delivery
(``nodes_deliver`` commits into it). A cache with no invalidation key is not a cache; it is a
snapshot that silently becomes a lie.

Measured consequence (2026-08-19, live): on the LedgerCLI project the only commit on ``main`` is
Mosaera's own ``chore: initialize project``, timestamped the same second the project row was
created; every real file arrived a month later on the work branch. Quincy was therefore planning a
22-file Python package while looking at a generated README, and produced items that read as
reasoning failures but are simply what a model writes with no repository in view — one asking to
create ``src/budget_tracker/__init__.py`` (which already exists), another naming ``tempfile`` and
``os`` as unused imports (they are used). The second cost a full run: the Proctor encoded the false
premise as an acceptance test and the coder correctly refused it.

The key is the clone's HEAD sha rather than ``Workspace.tree_hash``. tree_hash was designed as
exactly this memo key (#23 / ADR-0003) but stats every entry in the tree, and the staleness CHECK
runs on the interactive chat path where it must be O(1). The clone gains content only through
``commit_all`` at deliver and is ``reset --hard`` at run start, so committed state is the truth;
comparing HEAD can over-refresh but never under-refresh.

Empty means "never keyed" and forces a rebuild, so every project predating this migration
self-heals on its next PM turn without a backfill.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("repo_overview_key", sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("projects", "repo_overview_key")
