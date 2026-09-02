"""Project-history reads — the raw material for the project-memory queries.

Read-only by construction: every method here SELECTs. The ledgers this reads are written
elsewhere (``_runs``, ``_backlog``, ``_contracts``) and this module never touches them, so a
history question can never perturb the history it is asking about.

Why plain SQL and not a retrieval model: the questions are exact ("how many runs ended
`under_specified`", "which open items depend on #83") over a known schema with real identifiers.
Aggregate counts have one correct answer, and a citable count that is occasionally wrong is worse
than no count at all — see ``mosaera_core.project_memory`` for the measured argument.

Method names embed ``history`` so they cannot collide across the composed mixins.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mosaera_memory.models import BacklogItem, Run, backlog_item_dependencies
from mosaera_memory.store._base import StoreBase, _iso

# Statuses that mean "this item is not finished" — the open set the PM reasons about.
OPEN_STATUSES: frozenset[str] = frozenset(
    {"todo", "in_progress", "in_review", "blocked", "deferred"}
)


# Named columns, never `select(Run)` / `select(BacklogItem)`. Loading the whole entity couples a
# history question to every column those tables will ever have: a database one migration behind
# (or ahead) raises UndefinedColumn on a field this module does not read and never needed. Asking
# only for what it uses also keeps the read narrow, which is the right posture for a module whose
# whole contract is that it observes without disturbing.
_RUN_COLS = (
    Run.id,
    Run.item_id,
    Run.status,
    Run.termination_reason,
    Run.diagnosis,
    Run.iterations,
    Run.created_at,
)
_ITEM_COLS = (BacklogItem.id, BacklogItem.title, BacklogItem.status, BacklogItem.acceptance)


class HistoryMixin(StoreBase):
    def history_runs(self, project_id: str) -> list[dict[str, Any]]:
        """Every run this project has ever produced, oldest first.

        Deliberately unfiltered: a project's failures are the half worth reading, and the
        cross-run digest (``project_history``) already filters to APPROVED, so filtering here
        too would leave the failure record unreachable from anywhere.
        """
        with self.session() as s:
            rows = s.execute(
                select(*_RUN_COLS)
                .where(Run.project_id == project_id)
                .order_by(Run.created_at, Run.id)
            ).all()
            return [
                {
                    "run_id": rid,
                    "item_id": item_id,
                    "status": status,
                    "termination_reason": reason,
                    # NULL for a pre-0022 row, a run in flight, or a terminal path that never
                    # reached the diagnosis write.
                    "diagnosis": dict(diagnosis or {}),
                    "iterations": iterations,
                    "created_at": _iso(created),
                }
                for rid, item_id, status, reason, diagnosis, iterations, created in rows
            ]

    def history_items(self, project_id: str) -> list[dict[str, Any]]:
        """Backlog items with their dependency edges, for the blocked-work questions."""
        with self.session() as s:
            items = s.execute(
                select(*_ITEM_COLS)
                .where(BacklogItem.project_id == project_id)
                .order_by(BacklogItem.position, BacklogItem.id)
            ).all()
            ids = [i[0] for i in items]
            edges: dict[int, list[int]] = {i: [] for i in ids}
            if ids:
                # Read the edge table directly rather than walking the ORM relationship: one
                # query instead of N, and the caller only needs ids.
                for item_id, dep_id in s.execute(
                    select(
                        backlog_item_dependencies.c.item_id,
                        backlog_item_dependencies.c.depends_on_id,
                    ).where(backlog_item_dependencies.c.item_id.in_(ids))
                ).all():
                    edges.setdefault(item_id, []).append(dep_id)
            return [
                {
                    "item_id": iid,
                    "title": title,
                    "status": status,
                    "acceptance": acceptance or "",
                    "depends_on": sorted(edges.get(iid, [])),
                }
                for iid, title, status, acceptance in items
            ]

    def history_run_item_ids(self, project_id: str) -> list[int]:
        """Distinct item ids appearing in this project's run history.

        Separate from ``history_items`` on purpose: runs outlive the items they ran against
        (a recurated or deleted item leaves its runs behind), so comparing the two sets is how
        the caller detects history that can no longer be explained.
        """
        with self.session() as s:
            return sorted(
                {
                    r
                    for (r,) in s.execute(
                        select(Run.item_id)
                        .where(Run.project_id == project_id, Run.item_id.is_not(None))
                        .distinct()
                    ).all()
                    if r is not None
                }
            )
