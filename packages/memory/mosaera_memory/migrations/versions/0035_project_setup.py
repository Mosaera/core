"""project setup: the onboarding decisions that decide whether a run can succeed (#121).

Three columns, each closing a gap the alpha-outsider audit named.

``default_run_mode`` — the run mode (ADR-0012; plain names amended by ADR-0101) was per-launch
only, defaulting to ``guided`` in the route, so a project's intended supervision level lived
nowhere and had to be re-picked from memory at every launch. Recorded per project, it seeds the
launch control and stays overridable per run. It is NOT the charter's ADR-0046 posture — that is a
governance declaration on a restriction lattice and keeps its own column in ``project_charters``.

``test_cmd`` — an operator test command is one of the four independence legs ``evaluate_oracle``
accepts, and `RunSubmit.test_cmd` has always been wired through to ``build_graph``. Nothing outside
the CLI's ``--test-cmd`` could set it, so the leg was unreachable from the product and a greenfield
project's every run parked on ``oracle_unverified``.

``setup_completed_at`` — so the onboarding card can collapse once answered instead of nagging. NULL
means "never answered", which is the honest reading for every project that predates this.

All three are nullable / server-defaulted: an existing project keeps today's behaviour exactly
(``guided``, no test command, an unanswered card).

RENUMBERED ON LANDING (2026-08-24). Authored as `0033` chaining `0032`, which by landing time
THREE files claimed: `0033_message_steps` upstream, `0033_project_github_installation` on the #120
branch, and this one. The filenames differ, so git merges all of them with no conflict and Alembic
silently acquires multiple heads — a break no offline test catches, since the drift guard is
DB-gated. Landed third, after #120's `0034`. `scripts/check_migration_chain.py` (added by #120) is
what makes that failure loud.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "default_run_mode",
            sa.String(length=16),
            nullable=False,
            server_default="guided",
        ),
    )
    op.add_column(
        "projects",
        sa.Column("test_cmd", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "projects",
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "setup_completed_at")
    op.drop_column("projects", "test_cmd")
    op.drop_column("projects", "default_run_mode")
