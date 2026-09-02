"""GitLab OAuth "Connect" (ADR-0104): provision a project's tokens by authorizing with the
configured GitLab instead of pasting a PAT.

Two surfaces, deliberately asymmetric in trust:

- ``GET /api/oauth/gitlab/start`` — under ``/api``, admin-gated, initiated from a logged-in
  browser session. Mints a single-use, hashed, bound state and 302s to the provider.
- ``GET /oauth/callback`` — a TOP-LEVEL route (registered in ``app.py``, NOT under ``/api``), so
  it arrives pre-auth from the provider. It carries its OWN authorization: it spends the state
  (single-use / TTL / bound to the initiating admin + project) AND re-checks the live session
  (``SameSite=Lax`` lets the cookie ride the redirect). Any failure redirects with an honest error
  and stores nothing.

Every endpoint DERIVES its host from ``settings.gitlab_url`` — self-hosted first, gitlab.com never
hardcoded. The client secret is ``env OR stored-encrypted`` (ADR-0104 amendment — UI-settable like
the global token, env wins) and sent server-to-server only in the token exchange.
"""

from __future__ import annotations

import hashlib
import secrets
import urllib.parse
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import gitlab_write as glw
from mosaera_connectors import is_gitlab_source, project_from_source
from mosaera_core.config import Settings
from starlette.responses import RedirectResponse

from mosaera_api.auth import current_user

if TYPE_CHECKING:
    from mosaera_api.routes.context import AppContext

_PROVIDER = "gitlab"
_STATE_TTL = timedelta(minutes=10)  # an authorize round-trip is seconds; 10 min is generous slack
_TOKEN_DAYS = 364  # GitLab caps a project access token at 365 days; stay just under


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _redirect_uri(settings: Settings) -> str:
    # The EXACT redirect_uri sent in BOTH the authorize step and the token exchange (GitLab
    # requires them to match). Derived from base_url, so self-hosted works unchanged.
    return f"{settings.base_url}/oauth/callback"


def _oauth_configured(settings: Settings) -> bool:
    return bool(
        settings.gitlab_oauth_client_id
        and settings.gitlab_oauth_client_secret
        and settings.base_url
    )


def _fail_redirect(project_id: str | None, reason: str) -> RedirectResponse:
    """Fail-safe: land the operator back on the project's Integration pane (or the project list if
    we never resolved a project) with an honest, url-safe error. Nothing is stored on any failure
    path.

    The target is a FIXED INTERNAL literal built from a project id we resolved ourselves — no part
    of it comes from the request. That is what makes this not an open redirect; keep it that way."""
    target = f"/projects/{project_id}/settings?pane=integration&" if project_id else "/projects?"
    return RedirectResponse(f"{target}oauth_error={urllib.parse.quote(reason)}", status_code=302)


def make_oauth_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    @api.get("/oauth/gitlab/status")
    def gitlab_oauth_status(request: Request) -> dict[str, object]:
        # Tells the UI whether to offer "Connect with GitLab": it needs the instance to be OAuth-
        # configured AND the caller to be a logged-in admin (the start endpoint requires both).
        # ``host`` is shown on the button so the operator sees WHICH GitLab they're authorizing
        # against — the self-hosted instance from gitlab_url, never assumed to be gitlab.com.
        settings = Settings.from_env()
        user = current_user(request, ctx.history)
        return {
            "configured": _oauth_configured(settings),
            "is_admin": bool(user and user.get("is_admin")),
            "host": urllib.parse.urlparse(settings.gitlab_url).netloc or settings.gitlab_url,
        }

    @api.get("/oauth/gitlab/start")
    def gitlab_oauth_start(project_id: str, request: Request) -> RedirectResponse:
        # Admin-gated AND session-bound: the OAuth flow is inherently a browser handshake, so it
        # requires a logged-in admin whose id the state binds to (the callback re-checks it). A
        # header-only admin (service token) has no session to ride the redirect — refuse honestly.
        require_admin(request)
        settings = Settings.from_env()
        if not _oauth_configured(settings):
            raise HTTPException(
                status_code=400,
                detail="GitLab OAuth is not configured on this instance "
                "(MOSAERA_GITLAB_OAUTH_CLIENT_ID / _SECRET / MOSAERA_BASE_URL). "
                "Use the manual token fields instead.",
            )
        user = current_user(request, ctx.history)
        if user is None or not user.get("id"):
            raise HTTPException(
                status_code=400, detail="Connect requires a logged-in admin session"
            )
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if not is_gitlab_source(str(detail["source_repo"]), settings.gitlab_url):
            raise HTTPException(
                status_code=400,
                detail="project source is not on the configured GitLab; OAuth targets only it",
            )
        state = secrets.token_urlsafe(32)  # 256-bit; only its SHA-256 is stored
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
                "scope": "api",  # needed to mint a project access token on the operator's behalf
            }
        )
        return RedirectResponse(f"{settings.gitlab_url}/oauth/authorize?{query}", status_code=302)

    return api


def handle_gitlab_callback(ctx: AppContext, request: Request) -> RedirectResponse:
    """The pre-auth top-level callback. Registered directly on the app (outside ``/api``) so the
    provider can reach it; authorization is the spent state + a live-session re-check. Every failure
    path redirects with an honest error and stores nothing."""
    settings = Settings.from_env()
    params = request.query_params
    if params.get("error"):
        # The provider denied consent (or errored) — nothing to spend, land back honestly.
        return _fail_redirect(None, f"provider: {params.get('error')}")
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return _fail_redirect(None, "missing code or state")

    mem = ctx.history
    if mem is None:
        return _fail_redirect(None, "server has no store")

    # Spend the state FIRST (single-use / TTL / provider-bound). A replay or an expired/forged
    # state finds nothing and dies here — before any code is exchanged.
    binding = mem.spend_oauth_state(_hash_state(state), _PROVIDER, datetime.now(UTC))
    if binding is None:
        return _fail_redirect(None, "invalid or expired state")
    project_id = str(binding["project_id"])
    bound_user_id = int(binding["user_id"])

    # Re-check the LIVE session: the current user must be an admin AND the same admin who started
    # the flow. The Lax session cookie rides the top-level redirect; if it doesn't resolve (or a
    # different user holds it), refuse — the state binding alone is not trusted to authorize a mint.
    user = current_user(request, ctx.history)
    if user is None or not user.get("is_admin") or int(user.get("id") or 0) != bound_user_id:
        return _fail_redirect(project_id, "session does not match the initiating admin")

    if not _oauth_configured(settings):
        return _fail_redirect(project_id, "OAuth is not configured")
    detail = mem.project_detail(project_id)
    if detail is None:
        return _fail_redirect(project_id, "unknown project")
    source = str(detail["source_repo"])
    gl_project = (
        project_from_source(source) if is_gitlab_source(source, settings.gitlab_url) else None
    )
    if not gl_project:
        return _fail_redirect(project_id, "project is not on the configured GitLab")

    # Exchange the code for a short-lived user token (client secret server-to-server), then mint the
    # durable project token and DISCARD the user token — no per-user grant is persisted.
    access_token, err = glw.exchange_oauth_code(
        settings.gitlab_url,
        client_id=str(settings.gitlab_oauth_client_id),
        client_secret=str(settings.gitlab_oauth_client_secret),
        code=code,
        redirect_uri=_redirect_uri(settings),
    )
    if err or not access_token:
        return _fail_redirect(project_id, f"code exchange failed: {err or 'no token'}")

    expires_at = (date.today() + timedelta(days=_TOKEN_DAYS)).isoformat()
    minted, err = glw.create_project_access_token(
        settings.gitlab_url,
        access_token,
        gl_project,
        name=f"mosaera-connect-{project_id}",
        scopes=["write_repository", "api"],
        expires_at=expires_at,
    )
    # The user token has done its job whether or not the mint succeeded — it is never stored.
    if err or not minted:
        return _fail_redirect(project_id, f"could not mint project token: {err or 'no token'}")

    # One token, both roles (git transport + REST metadata) — populates the whole ADR-0103 model.
    mem.update_project(project_id, gitlab_token=minted, gitlab_api_token=minted)
    _audit_connect(ctx, project_id, user)
    # Same fixed-internal-literal rule as _fail_redirect: `pane=integration` lands the operator on
    # the pane that shows the result, instead of the settings root (which opened on General).
    return RedirectResponse(
        f"/projects/{project_id}/settings?pane=integration&oauth=connected", status_code=302
    )


def _audit_connect(ctx: AppContext, project_id: str, user: dict) -> None:
    """Best-effort audit of the credential provisioning against the project's newest run (the same
    anchor the delivery routes use). Never fails the flow."""
    if ctx.history is None:
        return
    try:
        pdetail = ctx.history.project_detail(project_id)
        runs = (pdetail or {}).get("runs") or []
        if runs:
            ctx.history.add_audit_event(
                str(runs[0]["id"]),
                "project.oauth_connected",
                f"actor=user:{user.get('username')}; provisioned project token via GitLab OAuth",
            )
    except Exception:  # noqa: S110 — audit is best-effort, never blocks the connect
        pass
