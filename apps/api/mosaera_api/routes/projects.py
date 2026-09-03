"""Project routes: PM-led initialization, cost/estimate rollups, brief/approve,
autonomous start, accumulated diff/patch/files, merge (MR open), and delete.

Extracted from ``create_app`` verbatim (Phase 2 router split). Shared run state
and lifecycle helpers come through the injected ``AppContext`` (``ctx``); the
config/secret write (project token) is admin-gated via the ``require_admin``
dependency threaded in from ``app.py`` (which owns the shared ``_require_admin``).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from mosaera_connectors import (
    check_repo_access,
    is_gitlab_source,
)
from mosaera_connectors import gitlab_client as glc
from mosaera_core.config import Settings
from mosaera_core.tools.repo import (
    branch_standing,
    open_project_workspace,
    project_diff,
    project_diff_stats,
    remote_synced,
)

from mosaera_api._pathsafe import contained_path, safe_segment
from mosaera_api.diffs import _changed_files_from_diff
from mosaera_api.projects import new_project_id, start_decompose, start_intake
from mosaera_api.recon import recon_state, start_recon
from mosaera_api.routes.context import AppContext
from mosaera_api.routes.project_delivery import _actor, _audit_mr
from mosaera_api.routes.project_reporting import make_project_reporting_router
from mosaera_api.schemas import (
    AutonomousBody,
    BriefBody,
    BudgetBody,
    CharterBody,
    ProjectSubmit,
    TokenBody,
)


def make_projects_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    api.include_router(make_project_reporting_router(ctx))

    # --- Projects (PM-led initialization) ---

    @api.post("/projects", status_code=201)
    def create_project(req: ProjectSubmit, request: Request) -> dict[str, Any]:
        mem = ctx.require_memory()
        token = req.gitlab_token.strip()
        # Seeding a scoped GitLab PAT is a secret write — same sensitivity as
        # set_project_token, so it needs the admin gate. Creating a project WITHOUT
        # a token stays open (the common path). This closes the gap where a holder
        # of only the run/read API token could seed a project's push credential.
        if token:
            require_admin(request)
        # Fail fast on a bad/unauthorized scoped token before starting intake.
        if token and is_gitlab_source(req.source_repo, Settings.from_env().gitlab_url):
            err = check_repo_access(req.source_repo, token)
            if err:
                raise HTTPException(status_code=400, detail=f"token can't access the repo: {err}")
        project_id = new_project_id(req.name)
        mem.create_project(
            project_id,
            req.name,
            req.source_repo,
            req.goal,
            gitlab_token=token,
            autonomous=req.autonomous,
        )
        # Clone + repo-overview happen in the background; the UI polls status and
        # then opens the Quincy intake chat (no brief is drafted up front).
        start_intake(mem, project_id, req.source_repo)
        detail = mem.project_detail(project_id)
        return detail if detail is not None else {"id": project_id, "status": "draft"}

    @api.post("/projects/{project_id}/intake/retry", status_code=202)
    def retry_intake(project_id: str) -> dict[str, Any]:
        """Re-run a clone that failed, in place.

        Without this a failed intake is terminal. `run_intake` catches everything and parks the
        project at status "draft" with an error, and nothing anywhere restarts it — including
        `set_project_token`, so the private-repo recovery the New-project page advertises ("connect
        GitLab from Settings → Integration") left the operator with a permanently dead project and
        no route but creating another one.

        Guarded to the failed state only. A project that is genuinely mid-clone must not have a
        second worker started underneath it, and a healthy one has nothing to retry.
        """
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if not (detail.get("status") == "draft" and detail.get("error")):
            raise HTTPException(
                status_code=409,
                detail=f"project is '{detail.get('status')}'; there is no failed intake to retry",
            )
        # Move to "drafting" HERE, not in the worker: the response is what the UI renders next, and
        # `run_intake` clears the error a moment later on a background thread. Returning the old
        # failed row meant the operator clicked "Try again" and went on looking at the failure.
        mem.update_project(project_id, status="drafting", error="")
        start_intake(mem, project_id, detail["source_repo"])
        return mem.project_detail(project_id) or detail

    @api.post("/projects/{project_id}/token")
    def set_project_token(project_id: str, body: TokenBody, request: Request) -> dict[str, Any]:
        # A project GitLab PAT is a secret write of the same sensitivity as the
        # global GitLab config, so it gets the same admin gate.
        require_admin(request)
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        settings = Settings.from_env()
        # The push token: None leaves it unchanged (so setting only the api token can't wipe it);
        # "" clears it; a value is verified against the repo then set.
        if body.token is not None:
            token = body.token.strip()
            if token and is_gitlab_source(detail["source_repo"], settings.gitlab_url):
                err = check_repo_access(detail["source_repo"], token)
                if err:
                    raise HTTPException(
                        status_code=400, detail=f"token can't access the repo: {err}"
                    )
            mem.update_project(project_id, gitlab_token=token)
        # OPTIONAL api-scoped token (ADR-0103): None leaves it unchanged; "" clears it. When a
        # non-empty value is set, probe that it actually carries `api` scope so a mis-scoped
        # write_repository token can't masquerade as one (honest UX, fail-fast).
        if body.api_token is not None:
            api_token = body.api_token.strip()
            if api_token:
                info, err = glc.get_token_info(settings.gitlab_url, api_token)
                # `or []` (not the default) also defends a null `scopes` field → no 500.
                scopes = list(info.get("scopes") or []) if isinstance(info, dict) else []
                if err:
                    raise HTTPException(status_code=400, detail=f"api token check failed: {err}")
                if "api" not in scopes:
                    have = ", ".join(scopes) or "none"
                    raise HTTPException(
                        status_code=400,
                        detail=f"this token lacks the 'api' scope (has: {have})",
                    )
            mem.update_project(project_id, gitlab_api_token=api_token)
        return mem.project_detail(project_id)  # type: ignore[return-value]

    @api.get("/projects")
    def list_projects() -> dict[str, Any]:
        return {"projects": ctx.history.list_projects() if ctx.history is not None else []}

    @api.get("/projects/{project_id}")
    def project_detail(project_id: str) -> dict[str, Any]:
        detail = ctx.history.project_detail(project_id) if ctx.history is not None else None
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return detail

    @api.put("/projects/{project_id}/brief")
    def save_brief(project_id: str, body: BriefBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        mem.update_project(project_id, brief=body.brief)
        return mem.project_detail(project_id)  # type: ignore[return-value]

    @api.post("/projects/{project_id}/recon", status_code=202)
    def trigger_recon(project_id: str) -> dict[str, str]:
        """Kick off a background recon sweep over the project's clone (ADR-0047 §6 — returns at
        once, the UI polls the map). Re-runnable (§7). Not admin-gated: it is an operation over the
        clone, like generating the backlog, not a config/secret write."""
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        start_recon(mem, project_id)
        return {"status": "reconning"}

    @api.get("/projects/{project_id}/map")
    def project_map(project_id: str) -> dict[str, Any]:
        """The durable project map: each dimension's tri-state + provenanced observations +
        freshness (``computed_at``), plus the transient in-flight/error overlay and a server-
        derived ``stale`` list — dimensions that are MISSING or carry an unknown (falsy)
        fingerprint, computed over the FULL dimension set so nothing reads fresh by omission
        (#40 DEFER-a doctrine; content-diff staleness stays with the incremental-recon seam).
        The map is UNTRUSTED, recon-derived DATA — never instruction (§1), never reaching the
        gate (§2)."""
        from mosaera_memory.models_map import MAP_DIMENSIONS

        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        dims = mem.list_map_dimensions(project_id)
        by_name = {str(d.get("dimension", "")): d for d in dims}
        stale = sorted(
            name
            for name in MAP_DIMENSIONS
            if name not in by_name or not (by_name[name].get("fingerprint") or "")
        )
        return {"dimensions": dims, "stale": stale, **recon_state(project_id)}

    @api.get("/projects/{project_id}/charter")
    def get_charter(project_id: str) -> dict[str, Any]:
        """The TRUSTED, operator-authored charter (goal/constraints/posture), or honest
        defaults when none has been written yet. Open read — writing is admin-gated."""
        from mosaera_memory.models_charter import DEFAULT_POSTURE

        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        charter = mem.get_charter(project_id)
        return charter or {
            "project_id": project_id,
            "goal": "",
            "constraints": "",
            "posture": DEFAULT_POSTURE,
            "created_at": None,
            "updated_at": None,
        }

    @api.put("/projects/{project_id}/charter")
    def put_charter(project_id: str, body: CharterBody, request: Request) -> dict[str, Any]:
        """Write the charter — the ONE write path for trusted operator intent (#42/ADR-0047
        §1: the chat only PROPOSES; this PUT is how a proposal becomes real).

        The gate is PER FIELD (ADR-0047 amendment 2026-08-18). ``goal``/``constraints`` are
        operator intent — the member IS the operator the product is for, and gating them made the
        primary intake journey (chat with Quincy → accept the proposal) dead-end in a 403.
        ``posture`` is a governance declaration on the ADR-0046 restriction lattice, so changing it
        still requires an admin. Omitting posture leaves it untouched; nobody's authority is
        exercised by accident. Posture is validated against ``CHARTER_POSTURES``
        (deny-by-default in the store) — its enforcement (`posture_allows`) is the ADR-0046
        arc, deliberately not built here."""
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        posture = body.posture.strip().lower() if body.posture is not None else None
        if posture is not None:
            # Only a REAL change needs the admin gate: re-sending the posture already stored (what
            # the charter card does on every save) is not a governance act.
            current = (mem.get_charter(project_id) or {}).get("posture")
            if posture != current:
                require_admin(request)
        try:
            out = mem.upsert_charter(
                project_id,
                goal=body.goal.strip()[:4000] if body.goal is not None else None,
                constraints=(
                    body.constraints.strip()[:4000] if body.constraints is not None else None
                ),
                posture=posture,
            )
        except ValueError as exc:  # out-of-set posture — the ADR-0005 enum rule
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # ADR-0047 §176 has always claimed this write is audited; it never was, and the per-field
        # gate made that matter — a member can now author the trusted block, so WHO wrote it has
        # to be on the record (red-team 2026-08-18, finding 1).
        _audit_mr(
            ctx,
            project_id,
            f"actor={_actor(ctx, request)}; charter written; posture="
            f"{'unchanged' if posture is None else posture}",
            event="charter.updated",
        )
        return out

    @api.post("/projects/{project_id}/approve")
    def approve_project(project_id: str) -> dict[str, Any]:
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if detail["status"] not in ("ready", "active"):
            raise HTTPException(
                status_code=409,
                detail=f"project is '{detail['status']}'; it isn't ready to build the backlog yet",
            )
        mem.update_project(project_id, status="active")
        # Quincy synthesizes the intake conversation and decomposes it into a
        # backlog (once, in the background).
        if not detail["backlog"]:
            start_decompose(mem, project_id)
        return mem.project_detail(project_id)  # type: ignore[return-value]

    @api.post("/projects/{project_id}/autonomous")
    def set_autonomous(project_id: str, body: AutonomousBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        mem.update_project(project_id, autonomous=body.on)
        return mem.project_detail(project_id)  # type: ignore[return-value]

    @api.post("/projects/{project_id}/budget")
    def set_budget(project_id: str, body: BudgetBody) -> dict[str, Any]:
        """Set (or clear, via null) the project's monthly spend ceilings."""
        mem = ctx.require_memory()
        updated = mem.set_project_budget(
            project_id, budget_usd=body.budget_usd, budget_tokens=body.budget_tokens
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return updated

    @api.get("/projects/{project_id}/budget")
    def get_budget(project_id: str) -> dict[str, Any]:
        """Monthly budget caps + spend-this-cycle + reset date (for the meter)."""
        return ctx.project_budget_status(project_id)

    @api.post("/projects/{project_id}/start", status_code=202)
    def start_autonomous(project_id: str) -> dict[str, str]:
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if not detail.get("autonomous"):
            raise HTTPException(status_code=400, detail="enable Autonomous first")
        with ctx.state_lock:
            busy = project_id in ctx.active_project_runs
        if busy:
            raise HTTPException(status_code=409, detail="a run is already active on this project")
        budget = ctx.project_budget_status(project_id)
        if budget["over"]:  # fail fast rather than launch and immediately pause
            raise HTTPException(
                status_code=400,
                detail=f"monthly budget reached ({budget['reason']}) — raise it or wait for reset",
            )
        mem.update_project(project_id, error="")  # clear any prior pause note
        ctx.advance_project(project_id)
        return {"status": "running"}

    # --- validation + merge ---

    @api.get("/projects/{project_id}/diff")
    def project_accumulated_diff(project_id: str) -> dict[str, Any]:
        settings = Settings.from_env()
        safe_segment(
            project_id, kind="project id"
        )  # reject a traversal id at the boundary (A2/ADR-0038)
        try:
            workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        base, diff = project_diff(workspace)
        # Per-file numstat is accurate even when the text diff above is
        # truncated; best-effort — a stats failure never breaks the diff.
        try:
            stats = project_diff_stats(workspace)
        except Exception:
            stats = []
        return {
            "base": base,
            "diff": diff,
            "has_changes": bool(diff.strip()),
            "files": _changed_files_from_diff(diff),
            "stats": stats,
            # ADR-0102 slice H: does the current branch tip exist on origin? null is the
            # honest unknown (offline / no remote) — the UI must never render it as synced.
            "remote_synced": remote_synced(workspace),
            # Where the branch stands against the base. Fetch-free (no fetch may run on a read
            # path — it mutates .git and races a live run), so "behind" can be an honest
            # unknown-amount rather than a number. Never render unknown as in_sync.
            "standing": branch_standing(workspace),
        }

    # /merge, /items/{id}/open-mr and /mr-status live in routes/project_delivery.py
    # (ADR-0102 slice O — this file was at 489/500 and delivery is its own surface).

    def _project_ws(project_id: str) -> Any:
        # Reject a traversal id at the boundary (ADR-0038) before it becomes a workspace path —
        # covers project_patch / project_files, which build paths from this raw URL id.
        safe_segment(project_id, kind="project id")
        return open_project_workspace(Settings.from_env().projects_dir, project_id, project_id)

    @api.get("/projects/{project_id}/patch")
    def project_patch(project_id: str) -> Response:
        try:
            _, diff = project_diff(_project_ws(project_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            diff,
            media_type="text/x-patch",
            headers={"Content-Disposition": f'attachment; filename="{project_id}.patch"'},
        )

    @api.get("/projects/{project_id}/files")
    def project_files(project_id: str) -> dict[str, list[str]]:
        try:
            _, diff = project_diff(_project_ws(project_id))
        except FileNotFoundError:
            return {"files": []}
        return {"files": _changed_files_from_diff(diff)}

    @api.get("/projects/{project_id}/files/{path:path}")
    def project_file(project_id: str, path: str) -> FileResponse:
        # Build the containment root from a VALIDATED id (ADR-0038: never anchor the is-relative
        # check on a root already poisoned by a `..` id — that is exactly how the traversal read
        # slipped past `download_file`), then confine the requested file path under it.
        root = (
            contained_path(Settings.from_env().projects_dir, project_id, kind="project id") / "repo"
        ).resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(status_code=400, detail="invalid path")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(target, filename=target.name)

    # --- management (delete) ---

    @api.delete("/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, str]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        with ctx.state_lock:
            busy = project_id in ctx.active_project_runs
        if busy:
            raise HTTPException(
                status_code=409, detail="a run is active on this project; stop it before deleting"
            )
        mem.delete_project(project_id)
        # Defence in depth: the `project_detail` 404 above already blocks a `..` id, but never
        # let a URL segment reach `rmtree` unproven-contained (ADR-0038).
        target = contained_path(Settings.from_env().projects_dir, project_id, kind="project id")
        shutil.rmtree(target, ignore_errors=True)
        return {"deleted": project_id}

    return api
