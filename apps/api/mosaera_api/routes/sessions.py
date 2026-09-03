"""PM chat session routes: list / create / rename / archive a project's conversation threads.

A session scopes chat HISTORY (issue #30). Project knowledge (brief/backlog/runs/context
registry) stays project-scoped and shared across sessions — so switching sessions changes the
conversation, not what Quincy knows about the project. Message read/write themselves live in
``routes/messages.py`` (session-scoped via ``?session_id=`` / the message body)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import SessionCreateBody, SessionPatchBody


def make_sessions_router(ctx: AppContext) -> APIRouter:
    api = APIRouter()

    def _require_project(mem: Any, project_id: str) -> None:
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")

    def _require_session(mem: Any, project_id: str, session_id: str) -> dict[str, Any]:
        # A session is always addressed under its project — a mismatched pair 404s so one
        # project can never read or mutate another's threads.
        sess = mem.get_pm_session(session_id)
        if sess is None or sess["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="unknown session")
        return sess

    @api.get("/projects/{project_id}/sessions")
    def list_sessions(project_id: str, include_archived: bool = False) -> dict[str, Any]:
        mem = ctx.require_memory()
        _require_project(mem, project_id)
        return {
            "sessions": mem.list_pm_sessions(project_id, include_archived=include_archived),
        }

    @api.post("/projects/{project_id}/sessions", status_code=201)
    def create_session(project_id: str, body: SessionCreateBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        _require_project(mem, project_id)
        session_id = mem.create_pm_session(project_id, title=body.title.strip()[:256])
        created = mem.get_pm_session(session_id)
        if created is None:  # pragma: no cover — just-created row must exist
            raise HTTPException(status_code=500, detail="session create failed")
        return created

    @api.patch("/projects/{project_id}/sessions/{session_id}")
    def patch_session(project_id: str, session_id: str, body: SessionPatchBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        _require_project(mem, project_id)
        _require_session(mem, project_id, session_id)
        if body.title is not None:
            mem.rename_pm_session(session_id, body.title.strip()[:256])
        if body.archived is not None:
            mem.set_pm_session_archived(session_id, body.archived)
        updated = mem.get_pm_session(session_id)
        if updated is None:  # pragma: no cover — existence checked above
            raise HTTPException(status_code=404, detail="unknown session")
        return updated

    return api
