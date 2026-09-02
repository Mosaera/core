"""The run diagnosis — how a run ended, structured (#75).

One nullable JSON column on ``runs``. Until now a finished run kept ``termination_reason``: 80
characters, and nothing else. The benchmark kept the outcome bucket, the park cause, the gate
reasons, the vouch diagnosis and the stall evidence — which is why the benchmark found defects the
product never surfaced, and why every failure observed through the UI was an anecdote with nothing
to answer "did this recur?" three days later.

JSON rather than columns, deliberately: the record is DIAGNOSTIC, not a queried contract. Its shape
follows the engine's own vocabulary (new stop channels, new gate reasons) and pinning that to DDL
would mean a migration every time the engine learns a new way to stop — the friction that keeps
instrumentation from being added at all. Nothing joins on it; the queried facts (status,
validation_status, termination_reason) keep their columns.

NULL is honest and stays honest: a pre-0022 row, a run still in flight, or a run whose terminal
path never reached the diagnosis. It is never back-filled from a live engine — the same rule the
run seal (0020) follows.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("diagnosis", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "diagnosis")
