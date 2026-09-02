"""PM chat sessions — per-project conversation threads (issue #30, ADR-0048)

Citation corrected 2026-08-20: this read ADR-0045 (the firm layer, still unbuilt direction);
ADR-0048 is the decision that introduced PM sessions. The migration itself is unchanged.

Adds ``pm_sessions`` (a project-scoped chat thread) and ``project_messages.session_id``, then
backfills: every project that already has messages gets ONE default session, and all its
existing turns are assigned to it. So the old single "forever-chat" becomes each project's
first session — no history is lost and nothing is orphaned. History is per-session from here
on; project knowledge (brief/backlog/runs/context registry) stays project-scoped.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from mosaera_memory._titles import derive_session_title

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pm_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),  # sess-<hex>
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pm_sessions_project_id", "pm_sessions", ["project_id"])
    op.add_column(
        "project_messages",
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("pm_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_project_messages_session_id", "project_messages", ["session_id"])
    _backfill_default_sessions()


def _backfill_default_sessions() -> None:
    """One default session per project that already has messages; adopt all its turns.

    The session's created/updated span the project's real message times (so recency ordering
    is honest), and its title is derived from the first user turn — exactly as a live first
    turn would set it — so a migrated project is indistinguishable from a freshly-created one."""
    conn = op.get_bind()
    spans = conn.execute(
        sa.text(
            "SELECT project_id, MIN(created_at) AS first_at, MAX(created_at) AS last_at "
            "FROM project_messages WHERE session_id IS NULL GROUP BY project_id"
        )
    ).fetchall()
    for row in spans:
        project_id = row.project_id
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        first_user = conn.execute(
            sa.text(
                "SELECT content FROM project_messages "
                "WHERE project_id = :pid AND role = 'user' AND session_id IS NULL "
                "ORDER BY id LIMIT 1"
            ),
            {"pid": project_id},
        ).fetchone()
        title = derive_session_title(first_user.content) if first_user else ""
        conn.execute(
            sa.text(
                "INSERT INTO pm_sessions (id, project_id, title, created_at, updated_at) "
                "VALUES (:id, :pid, :title, :created, :updated)"
            ),
            {
                "id": session_id,
                "pid": project_id,
                "title": title,
                "created": row.first_at,
                "updated": row.last_at,
            },
        )
        conn.execute(
            sa.text(
                "UPDATE project_messages SET session_id = :sid "
                "WHERE project_id = :pid AND session_id IS NULL"
            ),
            {"sid": session_id, "pid": project_id},
        )


def downgrade() -> None:
    op.drop_index("ix_project_messages_session_id", table_name="project_messages")
    op.drop_column("project_messages", "session_id")
    op.drop_index("ix_pm_sessions_project_id", table_name="pm_sessions")
    op.drop_table("pm_sessions")
