"""The design cache gets a key (ADR-0084 §3).

``design_node`` stores a design on the backlog item and reuses it verbatim on later runs. The only
invalidation test was ``not feedback`` — which is not a key, it is the absence of one. Measured
2026-08-06: an item's design authored on 08-05 said the launcher must use
``from src.budget_tracker.cli import main``; the operator corrected exactly that at a write gate on
08-06, and the run was still served the old design and wrote the forbidden import. Operator
corrections land in ``corrections``, not ``feedback``, so correcting the very thing the design
mandates did not invalidate it.

One nullable column holding a fingerprint of the design's real inputs (the item's acceptance, the
plan, and the run's corrections). Reuse only on an exact match.

NULL means STALE, deliberately, and is the reason this is nullable rather than back-filled: every
pre-0023 row was authored against inputs nobody recorded, so its freshness is unknown and
deny-by-default says regenerate once. This mirrors the recon map's rule — a NULL dimension
fingerprint is unknown freshness, therefore stale — which is the precedent ADR-0084 cites.

A short opaque hash, not JSON: nothing reads its parts, it is only ever compared for equality.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("backlog_items", sa.Column("design_key", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("backlog_items", "design_key")
