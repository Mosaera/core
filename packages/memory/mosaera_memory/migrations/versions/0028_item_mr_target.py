"""backlog_items.mr_target: the branch an item's OPEN merge request actually targets.

Until now the target existed only in GitLab, and the product answered "what does this MR
target?" by RECOMPUTING it with `_stacked_target`. That function answers a different
question — "what should a NEW MR target?" — and the two diverge the moment a predecessor
merges, the backlog is reordered, or a predecessor item is deleted.

Measured consequence (2026-08-18, live): item 99 merged, so the recomputed target for
item 100 became `main`; `mosaera/item-99` therefore dropped out of the protected set and
the prune deleted it — while item 100's open MR still pointed at it. GitLab: "The target
branch mosaera/item-99 does not exist." No in-product recovery existed.

Recording it makes branch protection a fact about the MR rather than an inference about
the backlog. Written when the MR opens and refreshed by the /mr-status poll, which already
fetches the full MR JSON (it carries `target_branch`), so the record self-heals.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "backlog_items",
        sa.Column("mr_target", sa.String(length=256), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("backlog_items", "mr_target")
