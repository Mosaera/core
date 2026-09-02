"""Index the foreign-key columns on the hot read paths (perf; no schema/behaviour change).

Postgres does not auto-index foreign keys, so every project/run aggregate that filtered on an
FK (``decisions.run_id``, ``runs.project_id``, the per-run child tables, the message/attachment
link tables) was a sequential scan that degraded super-linearly as history grew. This adds a
plain btree index on each un-indexed FK, matching the ``index=True`` now declared on those ORM
columns — the names are SQLAlchemy's default ``ix_<table>_<column>`` so the model and the DB
agree. ``doctrine_chunks.project_id`` (0008), ``run_events.run_id`` (0006), and
``user_sessions.user_id`` (0007) are already indexed and are intentionally omitted here.

First standalone ``create_index`` migration in this package; safe to run online.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-15 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, column) — the FK columns that lacked an index. Names are the SQLAlchemy
# default for ``index=True`` so create_all and this migration produce identical index names.
_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_runs_project_id", "runs", "project_id"),
    ("ix_runs_item_id", "runs", "item_id"),
    ("ix_backlog_items_project_id", "backlog_items", "project_id"),
    ("ix_decisions_run_id", "decisions", "run_id"),
    ("ix_repo_changes_run_id", "repo_changes", "run_id"),
    ("ix_test_results_run_id", "test_results", "run_id"),
    ("ix_artifacts_run_id", "artifacts", "run_id"),
    ("ix_approvals_run_id", "approvals", "run_id"),
    ("ix_audit_events_run_id", "audit_events", "run_id"),
    ("ix_project_messages_project_id", "project_messages", "project_id"),
    ("ix_latency_samples_project_id", "latency_samples", "project_id"),
    ("ix_latency_samples_run_id", "latency_samples", "run_id"),
    ("ix_attachments_project_id", "attachments", "project_id"),
    ("ix_attachment_derivatives_attachment_id", "attachment_derivatives", "attachment_id"),
    ("ix_project_context_items_project_id", "project_context_items", "project_id"),
    ("ix_message_context_sources_message_id", "message_context_sources", "message_id"),
    ("ix_message_attachments_message_id", "message_attachments", "message_id"),
    ("ix_message_attachments_attachment_id", "message_attachments", "attachment_id"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
