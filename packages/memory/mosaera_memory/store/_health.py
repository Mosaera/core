"""Suite-health store: the last measured verdict for a project, keyed by the tree it measured.

Persistence ONLY for ``ProjectSuiteHealth``. Methods are ``suite_``-prefixed so they never collide
across the mixins composed into ``MemoryStore`` (the ``CharterMixin`` convention).

Two invariants live here rather than in the callers:

- **A verdict is never returned for a different tree.** ``suite_health`` takes the tree hash the
  caller cares about and returns ``None`` on a mismatch, so a stale verdict cannot be read as a
  current one by a caller that forgot to compare. Bazel's rule — an action is indexed by a digest
  of its inputs — expressed at the boundary.
- **The verdict vocabulary is closed** (``SUITE_VERDICTS``): deny-by-default, so a typo can never
  persist as a verdict nothing understands. In particular an unreadable validator is recorded
  ``unknown`` and never ``failed`` — reporting a repository broken on the strength of output that
  could not be parsed would make the control fire on its own blindness.
"""

from __future__ import annotations

from typing import Any

from mosaera_memory.models_health import SUITE_VERDICTS, ProjectSuiteHealth
from mosaera_memory.store._base import StoreBase, _iso


class HealthMixin(StoreBase):
    def suite_health(self, project_id: str, tree_hash: str | None = None) -> dict[str, Any] | None:
        """The recorded verdict, or ``None`` when there is none FOR THIS TREE.

        Pass ``tree_hash`` to ask the only question worth asking at run start — "do I already know
        the answer for the tree in front of me?" — and get ``None`` when the answer belongs to a
        different tree. Omit it to read the last verdict whatever its tree (for display, where
        staleness is information rather than a hazard).
        """
        with self.session() as s:
            row = s.get(ProjectSuiteHealth, project_id)
            if row is None:
                return None
            if tree_hash is not None and row.tree_hash != tree_hash:
                return None
            return {
                "project_id": row.project_id,
                "tree_hash": row.tree_hash,
                "verdict": row.verdict,
                "failing": list(row.failing or []),
                "run_id": row.run_id,
                "measured_at": _iso(row.measured_at),
            }

    def record_suite_health(
        self,
        project_id: str,
        *,
        tree_hash: str,
        verdict: str,
        failing: list[str] | None = None,
        run_id: str | None = None,
    ) -> bool:
        """Upsert the project's verdict. False when the verdict is not one we understand.

        Called at the MOMENT of measurement, not at run end — ``persist_run`` is only reached from
        ``deliver_node``, so a cancelled run, a crash, a resilient-sweep give-up or an unanswered
        park would otherwise record nothing, and those are the runs whose knowledge matters most.
        """
        if verdict not in SUITE_VERDICTS or not tree_hash:
            return False
        with self.session() as s, s.begin():
            row = s.get(ProjectSuiteHealth, project_id)
            if row is None:
                row = ProjectSuiteHealth(project_id=project_id)
                s.add(row)
            row.tree_hash = tree_hash
            row.verdict = verdict
            row.failing = list(failing or [])
            row.run_id = run_id
            return True
