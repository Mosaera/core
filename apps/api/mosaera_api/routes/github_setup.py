"""Register the GitHub App in one click, instead of asking anyone to copy five values (ADR-0121).

GitHub's App-manifest flow: the browser POSTs a manifest to `github.com/settings/apps/new`, the
operator presses one button there, and GitHub redirects back with a one-hour code that converts
into a fully registered App — id, slug, private key, client id and client secret, all at once.
Mosaera stores them and the instance is configured. Nothing is typed, and the private key never
passes through a clipboard.

The GitLab half of this wizard needs no module of its own: `/gitlab/config` (ADR-0104, amended)
already accepts exactly the URL + application id + secret the operator must create by hand there,
because GitLab has no manifest equivalent.

**What authorizes what**, since this endpoint family hands out and receives credentials:

- `GET /api/github/setup/manifest` is admin-gated and mints a single-use, hashed, TTL'd state. It
  returns only a manifest and that state — nothing secret, because nothing secret exists yet.
- `GET /oauth/github/setup/callback` arrives pre-auth from GitHub. It spends the state first, then
  re-checks the live admin session against the binding, exactly as ADR-0104's callback does. A code
  without a live state is worth nothing.
- `POST /api/github/setup/manual` is the escape hatch for an operator who already registered an App
  and would rather paste than create a second one. Admin-gated, same storage path.

Secrets are encrypted at rest (ADR-0039) and env still wins over stored (ADR-0005), so an operator
who pins values in the environment is not overridden by anything saved here.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import github_app as gapp
from mosaera_core.config import Settings
from mosaera_core.settings_store import write_settings
from mosaera_memory import encrypt_secret
from pydantic import BaseModel
from starlette.responses import RedirectResponse

from mosaera_api.auth import current_user, users_exist

if TYPE_CHECKING:
    from mosaera_api.routes.context import AppContext

# A distinct provider string so a setup state can never be spent by the repo-creation callback
# (or vice versa) — `spend_oauth_state` matches on it.
_PROVIDER = "github-app-setup"
_STATE_TTL = timedelta(minutes=30)  # registering an App on GitHub involves reading a page
# Instance-wide, not per project: this configures the whole installation. The state's project_id
# column takes it by value with no FK, so a sentinel is safe and keeps one state table.
_NO_PROJECT = ""
# An instance with no auth configured has no session to bind to, and first run is exactly when
# that is true. Binding to this sentinel records "there was no identity here", so the callback
# can skip an identity check that could never pass rather than pretending one happened.
_NO_USER = 0


class OAuthAppConfig(BaseModel):
    """The OAuth App that creates repositories on the operator's behalf (ADR-0120)."""

    client_id: str
    client_secret: str


class ManualAppConfig(BaseModel):
    """An App the operator registered themselves. Every field required — a half-configured App
    fails later at connect time with an error pointing nowhere near the form.

    No client id/secret: a GitHub App's OAuth pair cannot create repositories (GitHub answers
    ``403 Resource not accessible by integration``), so asking for values that provably cannot do
    the job would be worse than not asking. Repository creation is configured separately, with an
    OAuth App, through ``/github/oauth-app``."""

    app_id: str
    private_key: str
    slug: str


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _store(settings: Settings, *, app_id: str, pem: str, slug: str) -> None:
    """One writer for both paths, so the manual form and the manifest cannot drift in what they
    persist or in which fields are treated as secret.

    **It deliberately does not write the App's OAuth pair.** The manifest conversion returns one,
    and storing it looked like it configured repository creation for free — but a GitHub App's
    user token is refused by GitHub's repository-creation endpoints (`403 Resource not accessible
    by integration`, confirmed live 2026-08-28). Persisting it produced a configuration that read
    as complete and could not work: the exact green-by-vacancy shape, in the credential layer.
    Repository creation now has its own explicit setup (`/github/oauth-app`)."""
    write_settings(
        settings.home,
        {
            "github_app_id": str(app_id),
            "github_app_private_key": encrypt_secret(pem),
            "github_app_slug": slug,
        },
    )


def app_manifest(settings: Settings) -> dict[str, Any]:
    """What Mosaera asks GitHub to create.

    `default_permissions` is the pair delivery actually spends (ADR-0114) and nothing else —
    least privilege declared at registration, so an over-broad App is never created in the first
    place rather than being narrowed later at token-mint time.

    `redirect_url` is where GitHub returns the *setup* code; `callback_urls` is where users are
    returned after authorizing (ADR-0120's repo creation). They are different endpoints and
    conflating them silently breaks one of the two flows.
    """
    base = str(settings.base_url or "").rstrip("/")
    return {
        "name": "Mosaera",
        "url": base,
        "redirect_url": f"{base}/oauth/github/setup/callback",
        "callback_urls": [f"{base}/oauth/github/callback"],
        "public": False,
        "default_permissions": {"contents": "write", "pull_requests": "write"},
        "default_events": [],
    }


def make_github_setup_router(
    ctx: AppContext, require_admin: Callable[[Request], None]
) -> APIRouter:
    api = APIRouter()

    @api.get("/github/setup/manifest")
    def github_setup_manifest(request: Request) -> dict[str, Any]:
        """The manifest and state the browser posts to GitHub. Returns nothing secret."""
        require_admin(request)
        settings = Settings.from_env()
        if not settings.base_url:
            raise HTTPException(
                status_code=400,
                detail="set this instance's public URL (MOSAERA_BASE_URL) first — GitHub has to "
                "be told where to send you back.",
            )
        # First-run setup may PRECEDE any user existing — that is the whole point of first run.
        # Requiring a session here made the wizard unusable on exactly the instance it exists for
        # (reproduced: an open loopback box refused its own setup button). So the session is
        # required only where there IS one to require; `require_admin` above has already applied
        # whichever gate this instance actually has.
        user = current_user(request, ctx.history)
        auth_configured = users_exist(ctx.history)
        if auth_configured and (user is None or not user.get("id")):
            raise HTTPException(
                status_code=400, detail="registering an App requires a logged-in admin session"
            )
        user_id = int(user["id"]) if user and user.get("id") else _NO_USER
        # Fails CLOSED without durable memory: the single-use state IS the CSRF control for this
        # flow, and there is nowhere to put it. Said in those words rather than letting
        # `require_memory` answer "projects require durable memory", which names the wrong thing
        # at the one moment an operator is configuring the product.
        if ctx.history is None or not hasattr(ctx.history, "mint_oauth_state"):
            raise HTTPException(
                status_code=400,
                detail="registering an App needs the database (MOSAERA_DB_URL) — the one-time "
                "code that protects this handshake has nowhere to be stored without it.",
            )
        state = secrets.token_urlsafe(32)
        ctx.history.mint_oauth_state(
            _hash_state(state),
            user_id,
            _NO_PROJECT,
            _PROVIDER,
            datetime.now(UTC) + _STATE_TTL,
        )
        return {
            "url": f"{settings.github_web_url}/settings/apps/new?state={state}",
            "manifest": json.dumps(app_manifest(settings)),
            "redirect_uri": f"{settings.base_url}/oauth/github/setup/callback",
        }

    @api.post("/github/setup/manual")
    def github_setup_manual(body: ManualAppConfig, request: Request) -> dict[str, bool]:
        """Store an App the operator registered themselves."""
        require_admin(request)
        settings = Settings.from_env()
        missing = [k for k, v in body.model_dump().items() if not str(v).strip()]
        if missing:
            raise HTTPException(status_code=400, detail=f"missing: {', '.join(sorted(missing))}")
        # Reject an unusable key HERE rather than at the first connect, where the error would
        # look like a GitHub outage (the same reason `app_jwt` raises on a bad PEM).
        try:
            gapp.app_jwt(body.app_id.strip(), body.private_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _store(settings, app_id=body.app_id.strip(), pem=body.private_key, slug=body.slug.strip())
        return {"ok": True}

    @api.post("/github/app/disconnect")
    def github_app_disconnect(request: Request) -> dict[str, bool]:
        """Clear the instance's GitHub App credentials (F3 — no disconnect existed for these).

        Only the STORED copy — `write_settings` never touches the environment, so an
        env-pinned App (ADR-0005: env wins) is unaffected and this call is a no-op for it. That
        is the honest behavior: an operator who set the credential in the environment un-sets it
        there, not through a settings-panel button that could not reach it anyway.
        """
        require_admin(request)
        settings = Settings.from_env()
        write_settings(
            settings.home,
            {"github_app_id": None, "github_app_private_key": None, "github_app_slug": None},
        )
        return {"ok": True}

    @api.post("/github/oauth-app")
    def github_oauth_app(body: OAuthAppConfig, request: Request) -> dict[str, bool]:
        """The credential that creates repositories — an **OAuth App**, not the GitHub App.

        Separate because GitHub makes it separate: repository-creation endpoints accept OAuth-app
        and classic personal tokens and refuse App tokens outright. There is no manifest
        equivalent for an OAuth App, so this is a form, exactly as GitLab's is.
        """
        require_admin(request)
        settings = Settings.from_env()
        if not body.client_id.strip() or not body.client_secret.strip():
            raise HTTPException(status_code=400, detail="both the client id and secret are needed")
        write_settings(
            settings.home,
            {
                "github_oauth_client_id": body.client_id.strip(),
                "github_oauth_client_secret": encrypt_secret(body.client_secret.strip()),
            },
        )
        return {"ok": True}

    return api


def handle_github_setup_callback(ctx: AppContext, request: Request) -> RedirectResponse:
    """GitHub's return leg from the manifest flow. Pre-auth, so it carries its own
    authorization: the spent state plus a live-session re-check."""
    params = request.query_params
    if params.get("error"):
        return _fail(f"github: {params.get('error')}")
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return _fail("missing code or state")

    mem = ctx.history
    if mem is None:
        return _fail("server has no store")
    binding = mem.spend_oauth_state(_hash_state(state), _PROVIDER, datetime.now(UTC))
    if binding is None:
        return _fail("invalid or expired state")

    # Enforce the identity re-check only where an identity exists. A state minted on an instance
    # with no accounts carries `_NO_USER`, and demanding a matching admin session for it would
    # reject the flow that instance itself just started. Where a real user DID start it, the
    # check below is unchanged and mandatory.
    bound_user = int(binding["user_id"])
    if bound_user != _NO_USER:
        user = current_user(request, ctx.history)
        if user is None or not user.get("is_admin") or int(user.get("id") or 0) != bound_user:
            return _fail("session does not match the initiating admin")

    settings = Settings.from_env()
    data, err = gapp.convert_manifest_code(settings.github_api_url, code)
    if err or not data:
        return _fail(f"could not register the app: {err or 'no response'}")

    _store(settings, app_id=str(data["id"]), pem=str(data["pem"]), slug=str(data.get("slug") or ""))
    return RedirectResponse("/settings/git/github?setup=done", status_code=302)


def _fail(reason: str) -> RedirectResponse:
    """Back to the panel with an honest error. A FIXED internal literal — no part of the target
    comes from the request, which is what keeps this from being an open redirect."""
    return RedirectResponse(
        f"/settings/git/github?setup_error={urllib.parse.quote(reason)}", status_code=302
    )
