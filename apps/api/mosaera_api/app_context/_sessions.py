"""Session registry + project-run mutex.

Registers live ``RunSession``s (with bounded retention) and holds the per-project
clone mutex that serializes work on a project's persistent clone.
"""

from __future__ import annotations

from mosaera_api.app_context._base import AppContextBase
from mosaera_api.runner import TERMINAL_STATUSES, RunSession
from mosaera_api.schemas import ProjectBusy

# Bounded in-memory session retention (finished sessions beyond this are
# evicted, oldest first; durable history serves them). Monkeypatchable in tests.
_MAX_SESSIONS = 100


class SessionsMixin(AppContextBase):
    def reserve_project(self, project_id: str) -> None:
        """Atomically claim a project's clone for one run (closes the TOCTOU
        between the old membership check and the add across slow graph builds)."""
        with self.state_lock:
            if project_id in self.active_project_runs:
                raise ProjectBusy(project_id)
            self.active_project_runs.add(project_id)

    def release_project(self, project_id: str) -> None:
        with self.state_lock:
            self.active_project_runs.discard(project_id)

    def register_session(self, run_id: str, session: RunSession) -> None:
        with self.state_lock:
            self.sessions[run_id] = session
            self.reap_sessions()

    def reap_sessions(self) -> None:
        # Bounded retention (call with state_lock held): evict oldest FINISHED
        # sessions beyond the cap; live sessions are never evicted. Durable
        # history (/api/history/:id) serves everything reaped.
        if len(self.sessions) <= _MAX_SESSIONS:
            return
        finished = [
            rid
            for rid, s in self.sessions.items()  # insertion order = launch order
            if s.status in TERMINAL_STATUSES  # incl. `incomplete` — else these leak (finding H-1)
        ]
        for rid in finished[: len(self.sessions) - _MAX_SESSIONS]:
            self.sessions.pop(rid, None)
