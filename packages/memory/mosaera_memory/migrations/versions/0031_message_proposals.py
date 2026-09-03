"""message_proposals: what Quincy proposed on a turn, stored beside the turn.

A PM turn produces two things the operator can act on — a backlog ``changeset`` and a
``charter_proposal`` — and neither was persisted. ``pm_turn`` returned them to the client, which
held them in React state, so a page refresh destroyed them. The transcript that survived was worse
than empty: the agent strips the proposal out of the reply before storing it and substitutes
"Here's what I'd suggest.", so a reloaded conversation kept a sentence with nothing under it.

One row per proposal per message, CASCADE on the message — the ``message_context_sources`` shape,
which already hangs per-turn evidence off ``project_messages`` and batch-loads it in
``list_messages``.

``status`` is what stops a card the operator already handled from returning on every reload; the
live read returns only ``open``, mirroring ``clarification`` vs ``clarification_record``.

Nothing here grants authority. Applying a changeset still runs the validator and the
delivered-work guard; a charter still requires the operator's admin-gated PUT (ADR-0047 §1). This
table records what was SAID, and nothing reads it to decide anything.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "message_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("project_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_message_proposals_message_id", "message_proposals", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_proposals_message_id", table_name="message_proposals")
    op.drop_table("message_proposals")
