"""Shared infrastructure + module-level helpers for the AppContext package.

``AppContextBase`` holds the ``AppContext`` constructor, the shared mutable
run-state attributes, and the small lifecycle helpers that don't belong to a
single concern (``factory``, ``require_memory``, ``_safe_audit``, ``get_session``,
``run_diff``). The focused per-concern mixins inherit it for their shared state
and for typing.

Lock discipline is preserved verbatim: ``state_lock`` guards ``sessions`` +
``active_project_runs`` (+ ``rehydrating``); every read-of-many and all writes
take it. Worker ``on_done`` callbacks mutate from their own threads.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from mosaera_core.config import Settings
from mosaera_core.tools.repo.workspace import Workspace
from mosaera_memory import MemoryStore

from mosaera_api._pathsafe import contained_path
from mosaera_api.runner import RunSession
from mosaera_api.schemas import ProjectBusy, RunSubmit

# (request, run_id) -> (graph, config, initial, memory)
GraphFactory = Callable[["RunSubmit", str], tuple[Any, dict[str, Any], dict[str, Any] | None, Any]]


def _default_memory() -> tuple[MemoryStore | None, str]:
    """The durable store, plus WHY it is absent when it is.

    Two very different states used to collapse into a bare ``None``: "no database is
    configured" (a legitimate, chosen mode) and "a database IS configured but we cannot
    reach it" (a failure). Only the caller can tell them apart, and only if we hand back
    the reason (ADR-0035).
    """
    url = Settings.from_env().db_url
    if not url:
        return None, ""
    return MemoryStore.open_or_reason(url)


def _build_checkpointer(history: MemoryStore | None) -> Any:
    """A server-lifetime LangGraph checkpointer. With a database, a pooled
    PostgresSaver makes run state durable across restarts (concurrency-safe via
    the pool); otherwise an in-process saver (no cross-restart resume). Owned for
    the process lifetime — never closed here; the process exit reclaims it."""
    from langgraph.checkpoint.memory import InMemorySaver

    url = Settings.from_env().db_url
    if not url:
        return InMemorySaver()  # no DB configured — an in-process saver is the honest mode
    if history is None:
        # A DB IS configured but unreachable. `create_app` normally refuses to boot here;
        # we only get this far under the explicit MOSAERA_ALLOW_DEGRADED_MEMORY opt-in. Say
        # the same thing the `except` below says — this branch used to short-circuit ahead
        # of it and return silently, so the one warning the operator needed never printed.
        print(
            "  WARNING: durable checkpointer unavailable (no database); parked runs "
            "will not survive an API restart. Using an in-process saver."
        )
        return InMemorySaver()
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            url,
            max_size=8,
            open=True,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        # row_factory=dict_row (above) gives dict rows at runtime; the pool's
        # generic param just isn't inferred through kwargs.
        saver = PostgresSaver(pool)  # type: ignore[arg-type]
        saver.setup()  # create checkpoint tables if absent
        return saver
    except Exception as exc:
        print(
            f"  WARNING: durable checkpointer unavailable ({exc}); parked runs "
            "will not survive an API restart. Using an in-process saver."
        )
        return InMemorySaver()


class AppContextBase:
    """The shared run machinery: state + the cross-concern lifecycle helpers,
    extracted from ``create_app`` verbatim. One instance per app; endpoints alias
    its methods. The per-concern mixins inherit this for shared state + typing."""

    def __init__(
        self,
        memory: MemoryStore | None = None,
        graph_factory: GraphFactory | None = None,
    ) -> None:
        self.graph_factory = graph_factory
        # Guards sessions + active_project_runs: sync handlers run concurrently in
        # the anyio threadpool, and worker on_done callbacks mutate from their own
        # threads. One lock, always taken for both reads-of-many and all writes.
        self.state_lock = threading.Lock()
        self.sessions: dict[str, RunSession] = {}
        # Why the durable store is absent, when a DB was configured but unreachable ("" when
        # there is no DB configured, or when the store opened fine). create_app reads this to
        # refuse boot with an actionable message instead of degrading in silence (ADR-0035).
        self.memory_error = ""
        if memory is not None:
            self.history: MemoryStore | None = memory
        else:
            self.history, self.memory_error = _default_memory()

        # Server-lifetime checkpointer: with a database, graph state is durable, so a
        # run parked at a human gate survives a restart and can be rehydrated (below).
        # A connection pool keeps it safe for concurrent runs; falls back to an
        # in-process saver (no cross-restart resume) when there's no DB.
        self.checkpointer = _build_checkpointer(self.history)

        # Project ids with an in-flight run — serialize work on a project's clone.
        self.active_project_runs: set[str] = set()
        # Runs currently being rehydrated (restart recovery). Guards the get-or-
        # rehydrate for AD-HOC parked runs, which — unlike project runs — have no
        # project reservation, so two concurrent requests could otherwise resume the
        # same thread_id into two workers.
        self.rehydrating: set[str] = set()

    def factory(self) -> GraphFactory:
        if self.graph_factory is not None:
            return self.graph_factory
        from mosaera_api.factory import default_graph_factory

        # Bind the server-lifetime checkpointer so every run's state is durable.
        return functools.partial(default_graph_factory, checkpointer=self.checkpointer)

    def _safe_audit(self, run_id: str, event: str, detail: str) -> None:
        try:
            if self.history is not None:
                self.history.add_audit_event(run_id, event, detail)
        except Exception:  # noqa: S110 — audit is best-effort, never fatal
            pass

    def _safe(self, fn: Callable[[], Any]) -> None:
        """Run a best-effort side effect. Sibling of `_safe_audit`, same rule: a write whose only
        job is to make something VISIBLE must never be able to fail the decision it describes."""
        try:
            fn()
        except Exception:  # noqa: S110 — visibility is best-effort, never fatal
            pass

    def record_withheld_ask(self, run_id: str, item: Mapping[str, Any], withheld: str) -> None:
        """Make a SUPPRESSED question visible (`Unsuppressible Ask`, ADR-0107).

        The arm raises a clarification when the producer hits a bar it cannot meet; several
        exclusions can withhold it. That withholding used to be one audit row, which the activity
        log rendered as a muted lifecycle line matching no vocabulary map — so the operator whose
        question was withheld never learned one existed. Recorded ✓, visible ✗, which made a MUST
        invariant false in the half that matters.

        Two DURABLE surfaces plus one best-effort: the audit row (the fact), and a run decision the
        run detail renders as an amber callout (the `capability_limit` shape). The project note is
        a courtesy only — on the autonomous sweep `_try_recurate_or_defer` clears it
        (`update_project(pid, error="")`) or `_launch`'s pause note overwrites it, so it is
        GUARANTEED clobbered on the main path this runs on. Red team R3 caught the first draft of
        this docstring claiming three independent surfaces; it was not true, and a comment that
        overstates its own guarantee is the defect this arc keeps paying for.

        Lives here rather than beside the arm only because `_escalation.py` is at its size ceiling.
        """
        note = f"a question was withheld: {withheld}"
        self._safe_audit(run_id, "escalate-arm.suppressed", f"{withheld} rode the park")
        hist = self.history
        if hist is None:
            return
        self._safe(lambda: hist.add_decision(run_id, "ask_withheld", note))
        pid = str(item.get("project_id") or "")
        if pid:
            self._safe(lambda: hist.update_project(pid, error=note))

    def get_session(self, run_id: str) -> RunSession:
        # Claim the run atomically: if it's live return it; if another request is
        # already rehydrating it, treat as busy (the poll retries and finds the
        # session once registered) — this closes the ad-hoc double-resume race.
        with self.state_lock:
            session = self.sessions.get(run_id)
            if session is not None:
                return session
            if run_id in self.rehydrating:
                raise HTTPException(status_code=409, detail="run is being restored; retry shortly")
            self.rehydrating.add(run_id)
        try:
            # A run parked at a gate may have survived a restart.
            detail = self.history.run_detail(run_id) if self.history is not None else None
            if detail is not None and detail.get("status") == "AWAITING_APPROVAL":
                try:
                    return self.rehydrate(run_id, detail)
                except ProjectBusy as exc:
                    raise HTTPException(
                        status_code=409, detail="a run is already active on this project"
                    ) from exc
            raise HTTPException(status_code=404, detail="unknown run")
        finally:
            with self.state_lock:
                self.rehydrating.discard(run_id)

    def run_diff(self, run_id: str) -> str:
        """The run's diff — from the durable record, else recovered from its workspace.

        ``repo_changes`` is written by ``persist_run``, which only ``deliver`` reaches. A run that
        was cancelled or hit a budget cap therefore has NO row, even after dozens of approved
        writes — while its workspace sits intact on disk, because nothing cleans it up on cancel.
        Without the fallback the product offers a "download patch" control that cannot work and
        claims to keep work it does not surface: the code was recoverable only by shelling onto
        the host. ``/runs/{id}/files`` routes through here too, so the listing was 404ing while
        individual files remained downloadable — you could fetch a changed file only if you
        already knew its path.

        The stored diff still wins when present: it is what was actually sealed and delivered,
        whereas the workspace can have drifted since.
        """
        detail = self.history.run_detail(run_id) if self.history is not None else None
        if detail and detail["repo_changes"]:
            return str(detail["repo_changes"][0]["diff"])
        recovered = self._workspace_diff(run_id)
        if recovered is None:
            raise HTTPException(status_code=404, detail="no changes recorded for this run")
        return recovered

    def _workspace_diff(self, run_id: str) -> str | None:
        """A live read-only diff of the run's workspace, or None if it isn't recoverable.

        Read-only by construction (``diff_readonly`` stages into a throwaway index) — a GET must
        not mutate a workspace an operator may still be inspecting. Returns None rather than
        raising so the caller keeps the honest 404 for a genuinely absent workspace.
        """
        try:
            root = contained_path(Settings.from_env().workspaces_dir, run_id, kind="run id")
        except (HTTPException, ValueError):
            return None
        if not (root / ".git").is_dir():
            return None
        try:
            return Workspace(root=root, run_id=run_id, branch="").diff_readonly() or None
        except Exception:
            return None

    def require_memory(self) -> MemoryStore:
        if self.history is None:
            raise HTTPException(
                status_code=400,
                detail="projects require durable memory — set MOSAERA_DB_URL",
            )
        return self.history

    if TYPE_CHECKING:
        # Type-only declarations of the sibling-mixin methods that the cross-concern
        # helpers above (and the mixins) call via ``self``. They are defined at
        # runtime by the concrete mixins composed into ``AppContext`` — these stubs
        # only give mypy the shared surface so each mixin type-checks in isolation.
        def reserve_project(self, project_id: str) -> None: ...
        def release_project(self, project_id: str) -> None: ...
        def register_session(self, run_id: str, session: RunSession) -> None: ...
        def advance_project(self, project_id: str) -> None: ...
        def project_budget_status(self, project_id: str) -> dict[str, Any]: ...
        def rehydrate(self, run_id: str, detail: dict[str, Any]) -> RunSession: ...
        def _maybe_open_project_mr(self, project_id: str, detail: dict[str, Any]) -> None: ...
        def _maybe_open_item_mr(self, project_id: str, item_id: int, run_id: str) -> None: ...
        def _try_recurate_or_defer(
            self, project_id: str, item: dict[str, Any], mode: str, run_id: str, session: RunSession
        ) -> bool: ...
        def _try_model_escalation(
            self,
            project_id: str,
            item: dict[str, Any],
            chain: bool,
            mode: str,
            run_id: str,
            session: RunSession,
            used_settings: Settings,
            escalation_attempt: int,
        ) -> bool: ...
        def _note_escalation_outcome(
            self,
            project_id: str,
            run_id: str,
            session: RunSession,
            role: str,
            attempt: int,
        ) -> None: ...
        def _try_close_named_gap(
            self,
            project_id: str,
            item: dict[str, Any],
            mode: str,
            run_id: str,
            session: RunSession,
            used_settings: Settings,
        ) -> bool: ...
        def _try_escalate_arm(
            self,
            item: dict[str, Any],
            run_id: str,
            session: RunSession,
            used_settings: Settings,
        ) -> bool: ...
        def launch_item(
            self,
            project_id: str,
            item: dict[str, Any],
            *,
            mode: str = "guided",
            chain: bool = False,
            max_iterations: int | None = None,
            budget_tokens: int | None = None,
            budget_usd: float | None = None,
            cost_mode: str | None = None,
            override: bool = False,
            escalation_settings: Settings | None = None,
            escalation_attempt: int = 0,
            escalation_role: str = "",
        ) -> RunSession: ...
