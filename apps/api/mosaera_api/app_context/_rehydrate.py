"""Restart recovery: reconstruct a run that parked at a gate and survived a restart.

Rebuilds the ``RunSession`` on the durable checkpointer + original thread_id and
replays to the persisted interrupt, reconstructing the autonomous posture (which
isn't persisted) from the project's Autonomous flag.
"""

from __future__ import annotations

import time
from typing import Any

from mosaera_core.config import Settings

from mosaera_api.app_context._base import AppContextBase
from mosaera_api.app_context._launch import _run_budget, _run_hard_budget
from mosaera_api.runner import TERMINAL_STATUSES, RunSession
from mosaera_api.schemas import RunSubmit


def _rehydrate_posture(
    proj: dict[str, Any] | None, item_id: int | None, task: str
) -> tuple[bool, str]:
    """On restart the per-run mode isn't persisted, so a project run's posture is
    derived from the project's Autonomous flag. Returns (autonomous, item_title)."""
    autonomous = bool(proj and proj.get("autonomous"))
    item_title = task.splitlines()[0][:60] if task else ""
    if proj and item_id is not None:
        it = next((b for b in proj.get("backlog", []) if b.get("id") == item_id), None)
        if it:
            item_title = str(it.get("title") or item_title)
    return autonomous, item_title


class RehydrateMixin(AppContextBase):
    def rehydrate(self, run_id: str, detail: dict[str, Any]) -> RunSession:
        """Reconstruct a RunSession for a run that parked at a gate and survived
        a restart. Reopens the workspace untouched, rebuilds the graph on the
        durable checkpointer + original thread_id, and re-enters the stream so
        LangGraph replays to the persisted interrupt (back to awaiting_approval);
        the human's approval then resumes it. Only reachable with a durable DB."""
        from mosaera_api.factory import default_graph_factory

        project_id = detail.get("project_id")
        item_id = detail.get("item_id")
        hist = self.history
        # The per-run mode isn't persisted, so for a restarted PROJECT run the
        # project's Autonomous flag is authoritative: reconstruct the autonomous
        # posture AND the advance/pause chain so a parked sweep resumes and keeps
        # chaining (not silently demoted to guided). Ad-hoc / non-autonomous → guided.
        task = str(detail.get("task", ""))
        proj = hist.project_detail(project_id) if (project_id and hist is not None) else None
        autonomous, item_title = _rehydrate_posture(proj, item_id, task)
        if project_id:
            # Hold the clone while resuming so a new run can't race it.
            self.reserve_project(project_id)
        try:
            req = RunSubmit(
                repo=str(detail.get("source", "")),
                task=task,
                project_id=project_id,
                item_id=item_id,
                # Thread the reconstructed autonomous flag into the graph REBUILD (#52 red-team).
                # Without it `_verify_overlay` sees req.autonomous=False and strips the oracle
                # posture (tester + coverage + mutation), so a run that PARKED on the oracle could
                # rebuild oracle-less on restart and auto-approve-ship (RunSession already got it).
                autonomous=autonomous,
            )
            graph, config, initial, mem = default_graph_factory(
                req, run_id, checkpointer=self.checkpointer, resume=True
            )

            def _after() -> None:
                if project_id:
                    self.release_project(project_id)
                if not (autonomous and project_id and hist is not None):
                    return
                # Same chain policy as a fresh autonomous launch: advance on clean
                # delivery, clear on a human stop, else surface a pause note.
                if session.status == "completed" and bool((session.final or {}).get("approved")):
                    hist.update_project(project_id, error="")
                    if item_id is not None:
                        self._maybe_open_item_mr(project_id, item_id, run_id)
                    self.advance_project(project_id)
                elif session.status == "cancelled":
                    hist.update_project(project_id, error="")
                elif (
                    session.status == "incomplete"
                    and item_id is not None
                    and self._try_recurate_or_defer(
                        project_id,
                        {"id": item_id, "title": item_title},
                        "autonomous",
                        run_id,
                        session,
                    )
                ):
                    return  # resilient sweep: item deferred/re-curated, the sweep advanced
                else:
                    hist.update_project(
                        project_id, error=f"autonomous paused: item '{item_title}' needs attention"
                    )

            def _on_park() -> None:
                if project_id and hist is not None:
                    hist.update_project(
                        project_id,
                        error=f"autonomous paused: item '{item_title}' awaiting gate approval",
                    )

            session = RunSession(
                run_id,
                graph,
                config,
                initial,
                memory=mem,
                project_id=project_id,
                item_id=item_id,
                on_done=_after,
                auto_approve=autonomous,
                mode="autonomous" if autonomous else "guided",
                on_park=_on_park if autonomous else None,
                max_seconds=Settings.from_env().run_max_seconds,
                resilient=(autonomous and Settings.from_env().resilient_sweep),
                budget=_run_budget(Settings.from_env()),
                hard_budget=_run_hard_budget(Settings.from_env()),
                # Restart recovery: seed the meter from the last persisted spend so a
                # resumed run's budget/hard-cap math continues from real spend, not zero.
                prior_cost=mem.latest_cost(run_id) if mem is not None else None,
            )
            self.register_session(run_id, session)
            session.start()
        except Exception:
            if project_id:
                self.release_project(project_id)
            raise
        # Replay to the persisted interrupt is fast (no model/tool work).
        for _ in range(250):
            if session.status == "awaiting_approval" or session.status in TERMINAL_STATUSES:
                break
            time.sleep(0.02)
        return session
