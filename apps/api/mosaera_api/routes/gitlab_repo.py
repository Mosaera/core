"""Create a project's GitLab repository by authorizing, not by pasting anything (ADR-0125).

The GitLab half of ADR-0120, and deliberately the same flow so the two forges behave alike:
authorize → create → **push the project's existing history** → repoint → connect. Same state
machinery (hashed, single-use, TTL, bound to admin + project + provider), same push-before-repoint
ordering, same server-derived name.

Two differences, both because the providers differ rather than because the flows do:

- **No second application.** GitLab's `api` scope — the one ADR-0104's connect already asks for —
  can create a project. GitHub needed a separate OAuth App because its App tokens are refused by
  the equivalent endpoint (ADR-0120 Amendment 2).
- **Created private.** `clone.py` injects a credential for the configured GitLab host, so a
  private GitLab project clones and its runs start. GitHub is public-only because that injection
  does not exist for it yet. Each provider gets the most private option it can actually deliver.

And one thing the GitLab flow can finish that GitHub cannot: because ADR-0104 already mints a
project access token from the same grant, the project ends **connected and credentialed** in the
same request — no installation step to go and do.
"""

from __future__ import annotations

import hashlib
import secrets
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import detect_delivery_provider, project_from_source
from mosaera_connectors import gitlab_write as glw
from mosaera_core.config import Settings
from starlette.responses import RedirectResponse

from mosaera_api.auth import current_user
from mosaera_api.routes.github_repo import repo_name_for

if TYPE_CHECKING:
    from mosaera_api.routes.context import AppContext

_PROVIDER = "gitlab-create"
_STATE_TTL = timedelta(minutes=10)
_TOKEN_DAYS = 364  # GitLab caps a project access token at 365 days; stay just under


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.base_url}/oauth/gitlab/create/callback"


def _configured(settings: Settings) -> bool:
    return bool(
        settings.gitlab_oauth_client_id
        and settings.gitlab_oauth_client_secret
        and settings.base_url
        and settings.gitlab_url
    )


def _on_a_forge(settings: Settings, detail: dict) -> bool:
    """Whether this project already lives on a forge. A local path is a source but not a
    repository — the case creation exists for."""
    source = str(detail.get("source_repo") or "").strip()
    if not source:
        return False
    return detect_delivery_provider(source, settings.gitlab_url) in ("gitlab", "github")


def _fail(project_id: str | None, reason: str) -> RedirectResponse:
    """A FIXED internal literal — no part of the target comes from the request, which is what
    keeps this from being an open redirect. Nothing is stored on any failure path."""
    target = f"/projects/{project_id}/settings?pane=integration&" if project_id else "/projects?"
    return RedirectResponse(f"{target}repo_error={urllib.parse.quote(reason)}", status_code=302)


def make_gitlab_repo_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    @api.get("/gitlab/repo/status")
    def gitlab_repo_status(request: Request) -> dict[str, object]:
        settings = Settings.from_env()
        user = current_user(request, ctx.history)
        return {
            "configured": _configured(settings),
            "is_admin": bool(user and user.get("is_admin")),
            "host": urllib.parse.urlparse(settings.gitlab_url).netloc or settings.gitlab_url,
        }

    @api.get("/oauth/gitlab/create/start")
    def gitlab_create_start(project_id: str, request: Request) -> RedirectResponse:
        require_admin(request)
        settings = Settings.from_env()
        if not _configured(settings):
            raise HTTPException(
                status_code=400,
                detail="GitLab is not set up on this instance yet — choose an instance and "
                "register an OAuth application in Settings → Git → GitLab.",
            )
        user = current_user(request, ctx.history)
        if user is None or not user.get("id"):
            raise HTTPException(
                status_code=400, detail="creating a repository requires a logged-in admin session"
            )
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if _on_a_forge(settings, detail):
            # Same control as the GitHub path: creation is only for a project that has no
            # repository yet. Without it this would repoint a WORKING project at a new empty one.
            raise HTTPException(
                status_code=400,
                detail="this project already has a repository; creation is only for a project "
                "whose source is not yet on GitHub or GitLab",
            )

        state = secrets.token_urlsafe(32)
        mem.mint_oauth_state(
            _hash_state(state),
            int(user["id"]),
            project_id,
            _PROVIDER,
            datetime.now(UTC) + _STATE_TTL,
        )
        query = urllib.parse.urlencode(
            {
                "client_id": settings.gitlab_oauth_client_id,
                "redirect_uri": _redirect_uri(settings),
                "response_type": "code",
                "state": state,
                "scope": "api",  # creates the project AND mints its access token
            }
        )
        return RedirectResponse(f"{settings.gitlab_url}/oauth/authorize?{query}", status_code=302)

    return api


def handle_gitlab_create_callback(ctx: AppContext, request: Request) -> RedirectResponse:
    """Pre-auth top-level callback: the spent state plus a live-session re-check authorize it."""
    settings = Settings.from_env()
    params = request.query_params
    if params.get("error"):
        return _fail(None, f"gitlab: {params.get('error')}")
    code, state = params.get("code"), params.get("state")
    if not code or not state:
        return _fail(None, "missing code or state")

    mem = ctx.history
    if mem is None:
        return _fail(None, "server has no store")
    # Spent FIRST, and provider-scoped so a connect state can never be spent here.
    binding = mem.spend_oauth_state(_hash_state(state), _PROVIDER, datetime.now(UTC))
    if binding is None:
        return _fail(None, "invalid or expired state")
    project_id = str(binding["project_id"])

    user = current_user(request, ctx.history)
    if (
        user is None
        or not user.get("is_admin")
        or int(user.get("id") or 0) != int(binding["user_id"])
    ):
        return _fail(project_id, "session does not match the initiating admin")

    if not _configured(settings):
        return _fail(project_id, "GitLab is not set up on this instance")
    detail = mem.project_detail(project_id)
    if detail is None:
        return _fail(project_id, "unknown project")
    if _on_a_forge(settings, detail):
        # Re-checked: a state minted while the project had no repository could be spent after one
        # was set. Checking only at start leaves that window open.
        return _fail(project_id, "this project already has a repository")

    token, err = glw.exchange_oauth_code(
        settings.gitlab_url,
        client_id=str(settings.gitlab_oauth_client_id),
        client_secret=str(settings.gitlab_oauth_client_secret),
        code=code,
        redirect_uri=_redirect_uri(settings),
    )
    if err or not token:
        return _fail(project_id, f"authorization failed: {err or 'no token'}")

    # Server-derived name; nothing from the redirect reaches this call.
    name = repo_name_for(str(detail.get("name") or ""), project_id)
    created, err = glw.create_project(settings.gitlab_url, token, name)
    if err or not created:
        return _fail(project_id, f"could not create the repository: {err or 'no repository'}")

    http_url = str(created.get("http_url_to_repo") or created.get("web_url") or "")
    full_path = str(created.get("path_with_namespace") or "")

    # Push BEFORE repointing. An empty repository that a project points at is worse than no
    # repository — the next run clones nothing — so this fails closed: the project keeps its
    # working source and the operator is told the repository exists but is empty.
    working = settings.projects_dir / project_id / "repo"
    if full_path and working.is_dir():
        _branch, push_err = glw.push_existing_project(
            Path(working), gitlab_url=settings.gitlab_url, project_path=full_path, token=token
        )
        if push_err:
            return _fail(
                project_id,
                f"created {full_path} but could not push this project into it ({push_err}). "
                "The project still points at its current source; the empty repository is on "
                "GitLab and can be deleted there.",
            )

    mem.update_project(project_id, source_repo=http_url)

    # Finish credentialed. The same grant that created the project mints its scoped access token
    # (ADR-0104), so the project ends ready to deliver rather than with a connect step to go and
    # do. A mint failure is not a failure of the publish — the repository exists and the code is
    # in it — so it degrades to connecting manually.
    project_path = full_path or project_from_source(http_url) or ""
    if project_path:
        minted, mint_err = glw.create_project_access_token(
            settings.gitlab_url,
            token,
            project_path,
            name=f"mosaera-connect-{project_id}",
            scopes=["write_repository", "api"],
            expires_at=(date.today() + timedelta(days=_TOKEN_DAYS)).isoformat(),
        )
        if minted and not mint_err:
            mem.update_project(project_id, gitlab_token=minted, gitlab_api_token=minted)
    _audit(ctx, project_id, user, http_url)

    return RedirectResponse(
        f"/projects/{project_id}/settings?pane=integration&repo=created", status_code=302
    )


def _audit(ctx: AppContext, project_id: str, user: dict, url: str) -> None:
    """Best-effort audit against the project's newest run — the anchor every delivery route uses.
    Never fails the flow."""
    if ctx.history is None:
        return
    try:
        pdetail = ctx.history.project_detail(project_id)
        runs = (pdetail or {}).get("runs") or []
        if runs:
            ctx.history.add_audit_event(
                str(runs[0]["id"]),
                "project.gitlab_repo_created",
                f"actor=user:{user.get('username')}; created {url} (private)",
            )
    except Exception:  # noqa: S110 — audit is best-effort, never blocks the flow
        pass
