"""projects.mr_source: the branch the project's OPEN merge request actually sources from.

0028 recorded an *item* MR's target because protection was RECOMPUTING it. The same defect
sat one level up, unnoticed: ``open_project_mr`` opens the project MR from
``workspace.branch`` — whatever the shared clone happens to be checked out on, which after an
item run is ``mosaera/item-<id>`` — while ``_project_mr_branches`` protected
``projects.branch`` (the intake clone branch, written once at creation) and
``mosaera/combined-<id>``. Neither is necessarily the real source.

Measured consequence (2026-08-18, live): project MR !4 on the ledger-demo project sourced from
``mosaera/item-102`` while ``projects.branch`` was ``mosaera/project-proj-ledger-demo-149ba9``.
Item 102's backlog row was empty, so ``_protected_branches`` did not cover it either — the
branch a live MR depended on was protected by NOTHING, and an admin delete would have orphaned
the merge request. No in-product recovery exists for a project MR (``retarget`` repoints an
item MR's target; nothing repoints a project MR's source).

Recording it makes protection a fact about the MR rather than an inference about the clone's
checkout state. Written when the MR opens and refreshed by the /mr-status poll, which already
fetches the full MR JSON (it carries ``source_branch``), so the record self-heals for MRs
opened before this migration existed.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("mr_source", sa.String(length=256), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("projects", "mr_source")
