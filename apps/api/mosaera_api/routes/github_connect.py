"""Connect a project to its GitHub App installation (ADR-0114).

Deliberately NOT the shape `routes/oauth.py` uses for GitLab, and the difference is the whole
security argument. GitLab's flow redirects to the provider and reads the result; GitHub's
equivalent redirect carries an `installation_id` that GitHub itself documents as forgeable —
"Bad actors can hit this URL with a spoofed ``installation_id``, so you should not rely on the
validity of the ``installation_id`` parameter."

So there is no redirect to trust here, and therefore no state to mint, no callback outside
`/api`, no client secret, and no code exchange. Connect is a plain admin-gated POST: the server
signs an App JWT and asks GitHub which installation owns *this project's own* `source_repo`.
Every input to that question is already server-side. There is nothing for an attacker to
supply, so the vector that made ADR-0104's machinery necessary does not exist.

Admin-gated because it writes a credential-bearing record, the same tier as any project token
write.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_core.config import Settings

from mosaera_api import github_delivery as ghd
from mosaera_api.auth import current_user

if TYPE_CHECKING:
    from mosaera_api.routes.context import AppContext


def _audit(ctx: AppContext, project_id: str, actor: str, detail: str) -> None:
    """Best-effort audit against the project's newest run — the anchor the delivery routes and
    `oauth._audit_connect` both use. Never fails the request."""
    if ctx.history is None:
        return
    try:
        pdetail = ctx.history.project_detail(project_id)
        runs = (pdetail or {}).get("runs") or []
        if runs:
            ctx.history.add_audit_event(
                str(runs[0]["id"]), "project.github_connected", f"actor={actor}; {detail}"
            )
    except Exception:  # noqa: S110 — audit is best-effort, never blocks the connect
        pass


def make_github_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    @api.get("/github/status")
    def github_status(request: Request) -> dict[str, Any]:
        """Whether this instance can deliver to GitHub at all, and where to install the App.

        Mirrors `/oauth/gitlab/status`: the UI needs to know whether to offer Connect before
        offering it, rather than presenting a control that fails on press.
        """
        settings = Settings.from_env()
        user = current_user(request, ctx.history)
        return {
            "configured": ghd.app_configured(settings),
            "is_admin": bool(user and user.get("is_admin")),
            "install_url": ghd.install_url(settings),
        }

    @api.get("/github/installations")
    def github_installations(request: Request) -> dict[str, Any]:
        """Where the App is installed, for the Git settings panel.

        Admin-gated — unlike `/github/status`, which answers in booleans, this names the
        accounts the App can reach, which is organisation information rather than a
        capability bit.

        It is a *listing*, not an authorization: nothing it returns is ever spent. Delivery
        still asks GitHub which installation owns the project's own `source_repo` (see the
        module docstring), so the forgeable-id argument is untouched by this endpoint's
        existence.

        An App installed nowhere is `installations: []` with no error — the ordinary first-run
        answer, which the panel renders as "install it" rather than as a failure.
        """
        require_admin(request)
        settings = Settings.from_env()
        if not ghd.app_configured(settings):
            return {"configured": False, "installations": [], "install_url": "", "error": None}
        rows, err = ghd.list_installations(settings)
        return {
            "configured": True,
            "installations": rows,
            "install_url": ghd.install_url(settings),
            "error": err,
        }

    @api.post("/projects/{project_id}/github/connect")
    def github_connect(project_id: str, request: Request) -> dict[str, Any]:
        """Resolve and record which installation can reach this project's repository.

        Writes a credential-bearing record, so it is admin-gated. It asks GitHub rather than
        believing anything in the request — see the module docstring.
        """
        require_admin(request)
        settings = Settings.from_env()
        if not ghd.app_configured(settings):
            raise HTTPException(
                status_code=400,
                detail="GitHub delivery is not configured on this instance "
                "(MOSAERA_GITHUB_APP_ID / MOSAERA_GITHUB_APP_PRIVATE_KEY).",
            )
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if not ghd.is_github_project(settings, detail):
            raise HTTPException(
                status_code=400, detail="this project's source is not a GitHub repository"
            )
        owner_repo = ghd.owner_repo_from_source(str(detail["source_repo"]))
        if not owner_repo:
            raise HTTPException(
                status_code=400, detail="could not derive owner/repo from the project source"
            )
        # Always re-resolve on an explicit Connect: the operator is asking whether it works
        # NOW, and answering from a cached id would be the second-origin defect — reporting a
        # stored value as proof of an access we have not confirmed.
        ident, err = ghd.resolve_installation(mem, settings, project_id, owner_repo)
        if ident is None:
            link = ghd.install_url(settings)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"the Mosaera GitHub App is not installed on {owner_repo}"
                    + (f" — install it at {link}" if link else "")
                    + f" ({err})"
                ),
            )
        user = current_user(request, ctx.history)
        actor = f"user:{user['username']}" if user and user.get("username") else "endpoint"
        _audit(ctx, project_id, actor, f"installation {ident} for {owner_repo}")
        return {"connected": True, "owner_repo": owner_repo}

    return api
