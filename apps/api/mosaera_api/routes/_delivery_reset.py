"""Diverged-clone recovery (task 4D, F12): the guarded escape hatch for a project clone that has
drifted from its remote and can no longer land a launch.

Split out of ``project_delivery.py`` for the god-file ratchet — this is one endpoint, self
contained, and the split keeps the file under its 500-line ceiling.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_core.config import Settings
from mosaera_core.tools.repo.clone import reset_clone_to_remote

from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import ProjectBusy


def register_clone_reset_route(
    api: APIRouter,
    ctx: AppContext,
    require_admin: Callable[[Request], None],
    _actor: Callable[[AppContext, Request], str],
    _audit_mr: Callable[..., None],
) -> None:
    @api.post("/projects/{project_id}/clone/reset")
    def reset_project_clone(project_id: str, request: Request) -> dict[str, Any]:
        """Force the project's persistent clone back onto `origin/<base>`, discarding any
        local-only commits — the guarded action for the `diverged` case `check_base_drift`
        refuses to touch on its own (a branch cut from a stale, unreconciled tip produces a
        wrong MR diff, so the deterministic check fails closed and leaves recovery to a human).

        Admin-gated (a hard reset discards history) and 409s while a run is active, the same
        mutex pattern `merge_project`'s cherry-pick path uses — this mutates the shared clone.
        """
        require_admin(request)
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        try:
            ctx.reserve_project(project_id)
        except ProjectBusy as exc:
            raise HTTPException(
                status_code=409,
                detail="a run is active on this project; try again after it finishes",
            ) from exc
        try:
            root = Settings.from_env().projects_dir / project_id / "repo"
            outcome = reset_clone_to_remote(root)
        finally:
            ctx.release_project(project_id)
        if not outcome.ok:
            raise HTTPException(status_code=502, detail=outcome.detail or "reset failed")
        # Clear a prior base-drift pause note (`driftNote` in the web client reads this field) —
        # the reset is exactly what resolves it. Any OTHER error is left alone: this endpoint
        # only ever answers for drift, and clobbering an unrelated failure note would hide it.
        if detail.get("error") and "base drift" in str(detail["error"]).lower():
            mem.update_project(project_id, error="")
        _audit_mr(
            ctx,
            project_id,
            f"actor={_actor(ctx, request)}; clone reset to remote ({outcome.detail})",
            event="clone.reset",
        )
        return {"reset": True, "detail": outcome.detail}
