"""Charter store: the TRUSTED, operator-authored project intent — read + upsert (#40, ADR-0047).

Persistence ONLY for ``ProjectCharter``. Modeled on ``CoverageMixin`` (#32); methods are
``charter_``-prefixed so they never collide across the mixins composed into ``MemoryStore``.

Two invariants live here, both structural rather than merely documented:

- **Edited, never recomputed (§7).** There is exactly one writer — ``upsert_charter`` — and it takes
  operator-supplied fields. No method derives the charter from the map (that would be the §1
  violation: promoting untrusted repo content to operator intent). Recon has no path to this table.
- **Posture is validated at the boundary (ADR-0046 / ADR-0005).** ``charter_set`` rejects any
  posture outside ``CHARTER_POSTURES`` — deny-by-default, so a typo can never persist an invalid
  autonomy tier. Whether the *caller* is allowed to write (admin-gating) is enforced at the route
  (#42); this layer guarantees the value is well-formed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mosaera_memory.models_charter import CHARTER_POSTURES, DEFAULT_POSTURE, ProjectCharter
from mosaera_memory.store._base import StoreBase, _iso


def _charter_summary(row: ProjectCharter) -> dict[str, Any]:
    return {
        "project_id": row.project_id,
        "goal": row.goal,
        "constraints": row.constraints,
        "posture": row.posture,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


class CharterMixin(StoreBase):
    def get_charter(self, project_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(ProjectCharter, project_id)
            return _charter_summary(row) if row is not None else None

    def upsert_charter(
        self,
        project_id: str,
        *,
        goal: str | None = None,
        constraints: str | None = None,
        posture: str | None = None,
    ) -> dict[str, Any]:
        """Create or replace a project's charter (idempotent per ``project_id``). Operator intent
        only — never called by recon (§1/§7). ``posture`` must be one of ``CHARTER_POSTURES`` or
        this raises ``ValueError`` (deny-by-default; the route is responsible for admin-gating the
        write). Returns the stored summary.

        ``posture=None`` means **leave the existing posture untouched** (``DEFAULT_POSTURE`` only
        when creating the row). Posture is a governance declaration on a different authority than
        goal/constraints — ADR-0047 amendment 2026-08-18 lets a member author intent while posture
        stays admin-only — so the write needs a sentinel that a defaulting kwarg cannot express: a
        member's save must never silently reset it. Nothing enforces posture today, so a silent
        reset would be caught by no gate and no test."""
        if posture is not None and posture not in CHARTER_POSTURES:
            raise ValueError(
                f"unknown posture {posture!r}; expected one of {sorted(CHARTER_POSTURES)}"
            )
        now = datetime.now(UTC)
        with self.session() as s, s.begin():
            row = s.get(ProjectCharter, project_id)
            if row is None:
                posture = posture or DEFAULT_POSTURE
                s.add(
                    ProjectCharter(
                        project_id=project_id,
                        goal=goal or "",
                        constraints=constraints or "",
                        posture=posture,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                if goal is not None:
                    row.goal = goal
                if constraints is not None:
                    row.constraints = constraints
                if posture is not None:
                    row.posture = posture
                posture = row.posture  # echo what is actually stored, not what was asked
                row.updated_at = now
        return self.get_charter(project_id) or {
            "project_id": project_id,
            "goal": goal or "",
            "constraints": constraints or "",
            "posture": posture,
        }
