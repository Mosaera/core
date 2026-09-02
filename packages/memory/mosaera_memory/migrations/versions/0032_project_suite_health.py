"""project_suite_health: is the suite green, and for WHICH tree.

`tests_passed` was a point-in-time fact in a LangGraph channel that nothing invalidated, so the
tree a run COMMITTED was not necessarily the tree that passed — `hygiene`'s autofix writes to the
working tree after validation and routes on without re-testing, and the give-up diversion reaches
the gate carrying a verdict from before the coder's last writes. Nothing ran after `commit_all`.

Because item branches are cut at the clone's current tip, a red commit is inherited by every later
item, and the run-start baseline then reports those failures as "already failing" — blaming nobody
and making the red permanent.

Keying the verdict by `tree_hash` fixes both directions at once: it can be REUSED when the tree is
unchanged (no suite run at all — Bazel's model, and the same idea as this codebase's own
tree-hash-keyed evidence cache, ADR-0003) and it INVALIDATES itself the moment the tree moves.

One row per project, upserted at the moment of measurement rather than at run end: `persist_run` is
only reached from `deliver_node`, so a cancelled run, a crash, a resilient-sweep give-up or an
unanswered park would otherwise record nothing — and those are the runs whose knowledge matters
most.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "project_suite_health",
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tree_hash", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("failing", sa.JSON(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("project_suite_health")
