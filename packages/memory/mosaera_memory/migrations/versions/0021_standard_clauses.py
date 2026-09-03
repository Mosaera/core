"""Ratified derived clauses (ADR-0082 tier 2).

One table: an operator decision recorded once so it is inherited rather than re-litigated. The
constraints here are not belt-and-braces — each closes a way the original defect returns:

- the value is a number or absent, never prose (a re-derivable value is the defect itself);
- a condition is all three columns or none (a half-condition would silently never fire);
- ONE live clause per (scope, standard, parameter). Note the COALESCE in the unique index:
  Postgres treats NULLs as distinct, so a plain `project_id` index would happily admit two
  contradictory live repo-scoped clauses on the same parameter — which is precisely the
  two-readers-two-numbers failure this whole arc exists to kill.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standard_clauses",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("standard_id", sa.String(length=120), nullable=False),
        sa.Column("binds", sa.String(length=120), nullable=False),
        sa.Column("value_kind", sa.String(length=16), nullable=False),
        sa.Column("value_num", sa.Integer(), nullable=True),
        sa.Column("when_param", sa.String(length=60), nullable=True),
        sa.Column("when_op", sa.String(length=2), nullable=True),
        sa.Column("when_num", sa.Integer(), nullable=True),
        sa.Column("because", sa.Text(), nullable=False, server_default=""),
        sa.Column("author", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("ratified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "value_kind IN ('advisory', 'number', 'unbounded')", name="ck_clause_value_kind"
        ),
        # A numeric clause has a number; a non-numeric one has none. Both directions, so a value
        # can neither go missing nor be silently ignored.
        sa.CheckConstraint(
            "(value_kind = 'number') = (value_num IS NOT NULL)", name="ck_clause_value_present"
        ),
        sa.CheckConstraint(
            "(when_param IS NULL) = (when_num IS NULL) "
            "AND (when_param IS NULL) = (when_op IS NULL)",
            name="ck_clause_condition_complete",
        ),
    )
    op.create_index("ix_standard_clauses_project_id", "standard_clauses", ["project_id"])
    op.create_index("ix_standard_clauses_superseded_at", "standard_clauses", ["superseded_at"])
    # The load-bearing one. COALESCE, not the bare column: repo-scoped clauses carry a NULL
    # project_id, and NULLs are distinct in a unique index, so the bare version would enforce
    # nothing at all for exactly the rows that apply everywhere.
    op.create_index(
        "uq_standard_clauses_live",
        "standard_clauses",
        [sa.text("COALESCE(project_id, '')"), "standard_id", "binds"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
        sqlite_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_standard_clauses_live", table_name="standard_clauses")
    op.drop_index("ix_standard_clauses_superseded_at", table_name="standard_clauses")
    op.drop_index("ix_standard_clauses_project_id", table_name="standard_clauses")
    op.drop_table("standard_clauses")
