"""Run lifecycle + history routes: submit, list, poll, approve, stream (SSE),
patch/files download, report, open-MR, cancel, delete — plus durable history.

Extracted from ``create_app`` verbatim (Phase 2 router split). All shared run
state and lifecycle helpers come through the injected ``AppContext`` (``ctx``);
the pure diff/report helpers come from the leaf ``mosaera_api.diffs`` module to
avoid an import cycle back through ``app``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from mosaera_connectors import (
    assemble_merge_request,
    is_gitlab_source,
    open_merge_request,
    project_from_source,
)
from mosaera_core.config import Settings
from mosaera_core.sandbox import SandboxUnavailable
from mosaera_memory import SecretKeyError

from mosaera_api._pathsafe import contained_path, safe_segment
from mosaera_api.diffs import _changed_files_from_diff, _mr_report
from mosaera_api.routes.context import AppContext
from mosaera_api.routes.preflight import guard_can_run
from mosaera_api.schemas import ApproveBody, RunSubmit


def _transcript_header(ctx: AppContext, run_id: str) -> dict[str, Any]:
    """Run outcome for a transcript export (durable row first, else the live run)."""
    if ctx.history is not None:
        detail = ctx.history.run_detail(run_id)
        if detail is not None:
            return {
                "run_id": run_id,
                "status": detail.get("status"),
                "termination_reason": detail.get("termination_reason"),
                "task": detail.get("task", ""),
            }
    with ctx.state_lock:
        session = ctx.sessions.get(run_id)
    if session is not None:
        return {
            "run_id": run_id,
            "status": session.status,
            "termination_reason": session.termination_reason,
            "task": session.initial_task,
        }
    return {"run_id": run_id, "status": None, "termination_reason": None, "task": ""}


def _transcript_markdown(header: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """Human-readable transcript for `?format=md` — a readable summary; the JSON
    form carries the complete event payloads for the benchmark harness."""
    lines = [f"# Run transcript — {header['run_id']}", ""]
    if header.get("task"):
        lines += [f"**Task:** {header['task']}", ""]
    if header.get("status"):
        reason = header.get("termination_reason")
        lines += [f"**Status:** {header['status']}" + (f" — {reason}" if reason else ""), ""]
    for e in events:
        data = e.get("data") or {}
        node = e.get("node") or ""
        tag = f"[{node}] " if node else ""
        typ = e.get("type")
        if typ == "activity":
            verb = str(data.get("kind", "")).replace("_", " ")
            suffix = (f" {data['detail']}" if data.get("detail") else "") + (
                f" → {data['result']}" if data.get("result") else ""
            )
            lines.append(f"- {tag}{verb}{suffix}")
        elif typ == "thought":
            text = str(data.get("text", "")).strip()
            if text:
                rows = text.splitlines()
                lines.append(f"> {tag}{rows[0]}")
                lines += [f"> {r}" for r in rows[1:]]
        elif typ == "update":
            lines.append(f"- {tag}completed")
        elif typ == "interrupt":
            lines.append(f"- {tag}reached the delivery gate")
    return "\n".join(lines) + "\n"


def make_runs_router(ctx: AppContext) -> APIRouter:
    api = APIRouter()

    @api.post("/runs", status_code=201)
    def submit_run(req: RunSubmit) -> dict[str, Any]:
        guard_can_run()
        try:
            session = ctx.launch(req)
        except SandboxUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            # e.g. the repo can't be cloned, or the workspace can't be created.
            raise HTTPException(status_code=400, detail=f"could not start run: {exc}") from exc
        return session.snapshot()

    @api.get("/runs")
    def list_runs() -> dict[str, Any]:
        # Active (in-memory) runs, newest first — carries live phase + timing so a
        # project page can show its in-flight run's agent status without opening it.
        with ctx.state_lock:
            live = list(ctx.sessions.values())
        runs = [
            {
                "run_id": s.run_id,
                "status": s.status,
                "task": s.initial_task,
                "phase": s.phase,
                "started_at": s.started_at or None,
                "project_id": s.project_id,
                "item_id": s.item_id,
            }
            for s in live
        ]
        runs.reverse()
        return {"runs": runs}

    @api.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        from mosaera_api.runner._mode import get_mode

        session = ctx.get_session(run_id)
        # ADR-0101: the live interaction mode rides the snapshot the UI polls.
        return {**session.snapshot(), "interaction_mode": get_mode(session)}

    @api.post("/runs/{run_id}/approve")
    def approve_run(run_id: str, body: ApproveBody) -> dict[str, Any]:
        session = ctx.get_session(run_id)
        try:
            session.approve(body.approve, body.feedback, body.authorize_tests, body.option_id)
        except ValueError as exc:
            # An option this gate did not offer: 400, and the park stays answerable. Never an
            # auto-approve — ADR-0082 §5, mitigating the hazard ADR-0080 recorded.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session.snapshot()

    @api.get("/runs/{run_id}/events")
    async def stream_events(run_id: str) -> StreamingResponse:
        # Async SSE: the generator runs natively on the event loop and holds NO anyio threadpool
        # token during idle gaps (the old sync gen via iterate_in_threadpool pinned one worker per
        # open connection, so ~40 idle viewers starved every sync route). See session.aevents.
        session = ctx.get_session(run_id)

        async def agen() -> AsyncIterator[str]:
            async for event in session.aevents():
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"

        return StreamingResponse(agen(), media_type="text/event-stream")

    @api.get("/history")
    def list_history(limit: int = 50) -> dict[str, Any]:
        if ctx.history is None:
            return {"runs": []}
        return {"runs": ctx.history.list_runs(limit=limit)}

    @api.get("/history/{run_id}")
    def history_detail(run_id: str) -> dict[str, Any]:
        detail = ctx.history.run_detail(run_id) if ctx.history is not None else None
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return detail

    @api.get("/runs/{run_id}/transcript")
    def run_transcript(run_id: str, format: str = "json") -> Any:
        """Durable transcript for a run — the fine-grained tool activities, agent
        reasoning, node completions and gate, plus the outcome. For off-platform
        evaluation, debugging and the benchmark harness. `?format=md` renders
        human-readable markdown; the default JSON carries full event payloads."""
        events: list[dict[str, Any]] = []
        if ctx.history is not None:
            events = ctx.history.list_run_events(run_id)
        if not events:
            # DB-less / still-live fallback: reconstruct from the in-memory stream.
            with ctx.state_lock:
                session = ctx.sessions.get(run_id)
            if session is not None:
                events = session.transcript_events()
        header = _transcript_header(ctx, run_id)
        if not events and header["status"] is None:
            raise HTTPException(status_code=404, detail="unknown run")
        if format == "md":
            body = _transcript_markdown(header, events)
            return Response(body, media_type="text/markdown; charset=utf-8")
        return {**header, "events": events}

    @api.get("/runs/{run_id}/patch")
    def download_patch(run_id: str) -> Response:
        return Response(
            ctx.run_diff(run_id),
            media_type="text/x-patch",
            headers={"Content-Disposition": f'attachment; filename="mosaera-{run_id}.patch"'},
        )

    @api.get("/runs/{run_id}/files")
    def changed_files(run_id: str) -> dict[str, list[str]]:
        return {"files": _changed_files_from_diff(ctx.run_diff(run_id))}

    @api.get("/runs/{run_id}/files/{path:path}")
    def download_file(run_id: str, path: str) -> FileResponse:
        # `run_id` is untrusted URL input joined onto a base dir; a `..` segment (reachable
        # as `%2e%2e`) would otherwise anchor `root` OUTSIDE the workspaces dir and this very
        # check would then pass for `.mosaera/settings.json` — leaking the PAT (ADR-0038).
        root = contained_path(Settings.from_env().workspaces_dir, run_id, kind="run id")
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(status_code=400, detail="invalid path")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="file not found (workspace may be cleaned)")
        return FileResponse(target, filename=target.name)

    @api.get("/runs/{run_id}/report")
    def run_report(run_id: str) -> dict[str, str]:
        # Delivered runs write reports_dir/run-{id}.md; cancelled/crashed runs
        # never do, so a 404 here is an honest "no report was recorded".
        safe_segment(run_id, kind="run id")  # keep the id out of the report filename join
        root = Settings.from_env().reports_dir.resolve()
        target = (root / f"run-{run_id}.md").resolve()
        if not target.is_relative_to(root):
            raise HTTPException(status_code=400, detail="invalid run id")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="no report recorded for this run")
        return {"markdown": target.read_text(encoding="utf-8")}

    @api.post("/runs/{run_id}/open-mr")
    def open_mr(run_id: str) -> dict[str, Any]:
        # The authenticated call IS the human approval (ADR-0102): no approval row is
        # fabricated — the audit event below records what happened and who drove it.
        settings = Settings.from_env()
        detail = ctx.history.run_detail(run_id) if ctx.history is not None else None
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown run")
        if not detail["commit_sha"]:
            raise HTTPException(status_code=400, detail="run has no commit to push")
        # Token posture (ADR-0102): a PROJECT run pushes with its project-scoped
        # write_repository token, never the global one; the global token serves only
        # ad-hoc (project-less) runs, which have no other credential home.
        token = settings.gitlab_token
        project_id = detail.get("project_id")
        if project_id:
            if ctx.history is None:
                raise HTTPException(status_code=400, detail="no store to read the project token")
            try:
                token = ctx.history.get_project_token(str(project_id)) or ""
            except SecretKeyError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not token:
                raise HTTPException(
                    status_code=400,
                    detail="this project has no GitLab token; add one in project settings",
                )
        elif not token:
            raise HTTPException(
                status_code=400, detail="GitLab not configured (MOSAERA_GITLAB_TOKEN)"
            )
        source = str(detail["source"])
        if not is_gitlab_source(source, settings.gitlab_url):
            raise HTTPException(
                status_code=400,
                detail="run's source is not on the configured GitLab; remote push targets "
                "GitLab repos you can push to",
            )
        project = project_from_source(source)
        if not project:
            raise HTTPException(status_code=400, detail=f"could not derive project from {source}")
        workspace_root = contained_path(settings.workspaces_dir, run_id, kind="run id")
        if not (workspace_root / ".git").exists():
            raise HTTPException(status_code=409, detail="workspace no longer available; re-run")
        plan = assemble_merge_request(
            detail["task"], run_id, str(detail["branch"]), _mr_report(detail)
        )
        result = open_merge_request(
            workspace_root,
            plan,
            project=project,
            gitlab_url=settings.gitlab_url,
            token=token,
        )
        url = result.url
        if result.opened and not url:
            # A banner without a parseable URL — resolve the real one via read REST
            # (ADR-0102 slice O); empty on lookup failure keeps today's behavior.
            from mosaera_api.delivery import resolve_mr_url

            url = resolve_mr_url(settings, token, project, str(detail["branch"]))
        if ctx.history is not None:
            try:
                ctx.history.add_audit_event(
                    run_id,
                    "mr.opened" if result.opened else "mr.failed",
                    f"actor=endpoint; {url or result.error}",
                )
            except Exception:  # noqa: S110 — audit is best-effort
                pass
        if not result.opened:
            raise HTTPException(status_code=502, detail=result.error or "merge request not opened")
        return {"opened": True, "url": url}

    @api.patch("/runs/{run_id}/mode")
    def set_run_mode(run_id: str, body: dict[str, str]) -> dict[str, str]:
        """ADR-0101: switch a LIVE run's interaction mode (ask / accept / auto).

        Effective at the next write gate; recorded as a mode_change decision + audit.
        The delivery gate keeps the run's launch semantics — no mode skips it. The
        posture/RBAC floor (DIRECTION) will be enforced here when it lands."""
        from mosaera_api.runner._mode import set_mode

        with ctx.state_lock:
            session = ctx.sessions.get(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no live session for this run")
        try:
            previous = set_mode(session, str(body.get("mode", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"run_id": run_id, "mode": str(body.get("mode")), "previous": previous}

    @api.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, str]:
        # Signal the worker and durably mark the run CANCELLED (freeing its
        # backlog item back to todo). The session stays in memory (status
        # cancelling → cancelled) so /runs/{id} keeps telling the truth; the
        # project mutex is freed only by the worker's own on_done once the
        # thread has actually stopped — never here.
        with ctx.state_lock:
            session = ctx.sessions.get(run_id)
        if session is not None:
            session.cancel()
        if ctx.history is not None:
            ctx.history.cancel_run(run_id)
        return {"cancelled": run_id}

    @api.delete("/runs/{run_id}")
    def delete_run(run_id: str) -> dict[str, str]:
        safe_segment(run_id, kind="run id")  # reject a traversal id before we touch anything
        with ctx.state_lock:
            session = ctx.sessions.get(run_id)
        if session is not None and session.status in (
            "pending",
            "running",
            "awaiting_approval",
            "cancelling",
        ):
            raise HTTPException(status_code=409, detail="run is active; wait for it to finish")
        with ctx.state_lock:
            ctx.sessions.pop(run_id, None)
        if ctx.history is not None:
            ctx.history.delete_run(run_id)
        target = contained_path(Settings.from_env().workspaces_dir, run_id, kind="run id")
        shutil.rmtree(target, ignore_errors=True)
        return {"deleted": run_id}

    return api
