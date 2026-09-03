"""FastAPI app: submit runs, stream progress (SSE), resolve approval gates over HTTP.

The app is built around a ``graph_factory`` seam so tests can inject a fake graph
and exercise the full submit -> stream -> approve -> done cycle offline. The
default factory (``mosaera_api.factory.default_graph_factory``) wires the real
orchestrator exactly like the CLI.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mosaera_core import __version__ as _ENGINE_VERSION
from mosaera_core.config import Settings
from mosaera_memory import MemoryStore

from mosaera_api.apikey_auth import authenticate_api_key
from mosaera_api.auth import current_user, users_exist
from mosaera_api.initial_admin import seed_initial_admin
from mosaera_api.ratelimit import install_rate_limit
from mosaera_api.routes.auth import make_auth_router
from mosaera_api.routes.backlog import make_backlog_router
from mosaera_api.routes.context import AppContext, GraphFactory
from mosaera_api.routes.github_connect import make_github_router
from mosaera_api.routes.github_repo import (
    handle_github_repo_callback,
    make_github_repo_router,
)
from mosaera_api.routes.github_setup import (
    handle_github_setup_callback,
    make_github_setup_router,
)
from mosaera_api.routes.gitlab_repo import (
    handle_gitlab_create_callback,
    make_gitlab_repo_router,
)
from mosaera_api.routes.keys import make_keys_router
from mosaera_api.routes.messages import make_messages_router
from mosaera_api.routes.oauth import handle_gitlab_callback, make_oauth_router
from mosaera_api.routes.onboarding import make_onboarding_router
from mosaera_api.routes.preflight import make_preflight_router
from mosaera_api.routes.project_delivery import make_project_delivery_router
from mosaera_api.routes.projects import make_projects_router
from mosaera_api.routes.runs import make_runs_router
from mosaera_api.routes.sessions import make_sessions_router
from mosaera_api.routes.settings import make_settings_router
from mosaera_api.routes.standards import make_standards_router
from mosaera_api.routes.voice import make_voice_router
from mosaera_api.schemas import (
    ApproveBody,
    RunSubmit,
)
from mosaera_api.security_headers import install_security_headers

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# The bind guard lives in its own module (see `bind_guard`); imported here so
# `mosaera_api.app.guard_bind` and the helpers keep resolving for `__main__` and the tests.
from mosaera_api.bind_guard import (  # noqa: E402
    _cli_bind_host,
    guard_bind,
)

__all__ = ["create_app", "guard_bind", "guard_memory"]


def guard_memory(history: Any, reason: str) -> None:
    """Refuse to start when a database is CONFIGURED but unreachable.

    Silently degrading here is a trust-killer for a product whose pitch is durable memory
    (ADR-0035). A configured-but-dead DB previously left the API running with: no run
    history; parked runs unrehydratable (the in-process saver has no memory of them);
    project endpoints 400-ing with "set MOSAERA_DB_URL" — which IS set; and, worst,
    **auth enforcement failing open**, because `users_exist` reads an unreachable store as
    "no users exist". None of it was logged.

    So fail closed, matching ``guard_bind``'s precedent above and the CLI, which already
    raises loudly on this exact condition. ``MOSAERA_ALLOW_DEGRADED_MEMORY=1`` is the
    escape hatch for an operator who genuinely wants a history-less API — it degrades
    LOUDLY, as a choice, which is the difference that matters.
    """
    if not Settings.from_env().db_url or history is not None:
        return  # no DB configured (a legitimate mode), or the store opened fine
    if _env_flag("MOSAERA_ALLOW_DEGRADED_MEMORY"):
        print(
            f"  WARNING: durable memory is UNAVAILABLE ({reason or 'unknown'}) and "
            "MOSAERA_ALLOW_DEGRADED_MEMORY is set — running degraded: no run history, "
            "parked runs will NOT survive a restart, and user-account auth is NOT enforced."
        )
        return
    raise SystemExit(
        f"refusing to start: MOSAERA_DB_URL is set but the database is unreachable "
        f"({reason or 'unknown error'}).\nRuns would lose their history, parked runs would "
        "not survive a restart, and user-account auth would NOT be enforced.\nFix the "
        "database, unset MOSAERA_DB_URL to run without durable memory, or set "
        "MOSAERA_ALLOW_DEGRADED_MEMORY=1 to accept the risk."
    )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _require_local_config(request: Request) -> None:
    """Gate a sensitive config/secret mutation (GitLab tokens, pricing) to
    localhost, unless MOSAERA_ALLOW_REMOTE_CONFIG is set. This is defense-in-depth
    on top of the API token: it keeps 'reconfigure the server / write a credential'
    off the network even when 'run tasks' is exposed.

    CAVEAT: ``request.client.host`` is the direct socket peer. Behind a reverse
    proxy (the recommended exposed topology) every client appears as the proxy's
    address (usually 127.0.0.1), so this reads as same-host for everyone — it is a
    same-host guard, NOT an authorization boundary in a proxied deploy. X-Forwarded
    -For is deliberately NOT trusted (a direct attacker can't spoof local).
    """
    host = request.client.host if request.client else ""
    allow_remote = os.environ.get("MOSAERA_ALLOW_REMOTE_CONFIG", "0") in ("1", "true", "yes")
    if host not in _LOCAL_HOSTS and not allow_remote:
        raise HTTPException(
            status_code=403,
            detail="config changes are allowed only from localhost; set "
            "MOSAERA_ALLOW_REMOTE_CONFIG=1 to override",
        )


def _require_admin(request: Request) -> None:
    """Authorize a config/secret write against the ADMIN capability.

    Two-tier auth: the API token grants run/read; the admin token
    (``MOSAERA_ADMIN_TOKEN``, sent as the ``X-Mosaera-Admin`` header) grants
    'reconfigure the server / write a credential'. This is proxy-agnostic — unlike
    the localhost gate it does not depend on the socket peer address (finding #4).

    Secure-by-default: with an admin token set, it is required (constant-time
    compare). With no admin token but the instance token-protected (exposed), we
    refuse — the localhost gate is unreliable behind a proxy. On plain loopback dev
    (no API token) we fall back to the same-host gate so nothing changes locally.
    """
    admin_token = os.environ.get("MOSAERA_ADMIN_TOKEN", "").strip()
    if admin_token:
        provided = request.headers.get("X-Mosaera-Admin", "")
        if not (provided and secrets.compare_digest(provided, admin_token)):
            raise HTTPException(status_code=403, detail="admin token required for this action")
        return
    if os.environ.get("MOSAERA_API_TOKEN", "").strip():
        raise HTTPException(
            status_code=403,
            detail="set MOSAERA_ADMIN_TOKEN to change config on a token-protected instance",
        )
    # AN API KEY IS NEVER ADMIN (ADR-0127), and this is the line that makes that true rather
    # than merely intended. The two tiers above detect exposure by reading the ENVIRONMENT — a
    # token set means "this instance is reachable, demand the admin token". A per-user API key is
    # a credential that env cannot see, so a token-less instance behind a reverse proxy read as a
    # developer laptop: `current_user` is None for a key, which SKIPS the explicit non-admin
    # refusal in `_require_admin_ctx` and lands here, where every proxied request presents as
    # 127.0.0.1. Any user could mint their own key and create an administrator with it.
    #
    # Guarded here, below the admin-token tier, so the rule reads exactly as ADR-0127 states it:
    # a key holder may still perform an admin write by ALSO presenting MOSAERA_ADMIN_TOKEN, and
    # may never do so on the strength of the key alone.
    if getattr(request.state, "api_key", None) is not None:
        raise HTTPException(
            status_code=403,
            detail="an API key is never admin; this action needs an admin session or "
            "MOSAERA_ADMIN_TOKEN",
        )
    _require_local_config(request)


def _warn_if_stale_dist(dist: Path, index: Path) -> None:
    """Dev convenience: warn when the web SOURCE is newer than the built bundle.

    A stale ``dist/`` is the classic reason freshly-added UI doesn't appear at the
    served origin (the API serves the pre-built bundle, not the source). Skipped in
    a deployed wheel, where ``src/`` isn't present to compare against."""
    src = dist.parent / "src"
    if not src.is_dir():
        return
    try:
        built = index.stat().st_mtime
        newest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0.0)
    except OSError:
        return
    if newest > built:
        print(
            "  WARNING: the web bundle (apps/web/dist) is OLDER than apps/web/src — "
            "freshly-changed UI won't appear at this origin. Rebuild it with "
            "`npm --prefix apps/web run build` (or `make up`)."
        )


def create_app(
    graph_factory: GraphFactory | None = None,
    memory: MemoryStore | None = None,
    web_dist: str | Path | None = None,
) -> FastAPI:
    # Enforce the bind-safety invariant here too, not just in main(): a
    # --factory / gunicorn entrypoint constructs the app directly and skips main().
    # Prefer the server's own most-exposed --host/--bind/UVICORN_HOST bind (the REAL bind for
    # that path) over MOSAERA_API_HOST, so `uvicorn app:create_app --factory --host 0.0.0.0`
    # OR `UVICORN_HOST=0.0.0.0` with no MOSAERA_API_HOST can't slip past the guard (TM-0002).
    guard_bind(
        _cli_bind_host() or os.environ.get("MOSAERA_API_HOST") or "127.0.0.1",
        os.environ.get("MOSAERA_API_TOKEN", ""),
        os.environ.get("MOSAERA_SANDBOX", "docker"),
    )
    # ADR-0055: the engine version is the single source of truth — the OpenAPI doc must not
    # carry a second, hand-maintained one (this sat at 0.1.0 through two releases).
    app = FastAPI(title="Mosaera API", version=_ENGINE_VERSION)
    # Shared run machinery (state + lifecycle helpers) lives in AppContext; the
    # still-inline endpoints below reach it through the local aliases bound after
    # the middleware. One ctx per app: it builds the lock, session table, project
    # mutex, rehydration set, durable history, and the server-lifetime checkpointer.
    ctx = AppContext(memory=memory, graph_factory=graph_factory)
    guard_memory(ctx.history, ctx.memory_error)
    history = ctx.history

    # A fresh process has no live runs, so any run still marked RUNNING in durable
    # memory was interrupted (e.g. a restart) — finalize it so it isn't stuck.
    # AWAITING_APPROVAL rows are left alone: they parked at a gate and rehydrate.
    if history is not None:
        try:
            history.finalize_orphans()
            # Same for projects stranded mid-intake/decompose (no thread survives).
            history.finalize_orphan_projects()
        except Exception:  # noqa: S110 — best-effort startup cleanup
            pass

    # An orchestrated deploy with no terminal can pre-provision its administrator from the
    # environment (ADR-0116). There is no token path any more, and no browser route that creates an
    # account: on an empty instance the first admin comes from `mosaera-setup` or from here.
    seed_initial_admin(history)

    # Auth: a request to /api is authorized by EITHER a logged-in user SESSION
    # (HttpOnly cookie) OR the shared service token (MOSAERA_API_TOKEN, as Bearer
    # or ?token= for header-less transports like SSE). Enforced only when auth is
    # CONFIGURED — a token is set OR user accounts exist — so an unconfigured
    # loopback dev box stays open. /healthz and the SPA shell (/, /assets) are not
    # under /api so they always load; the auth bootstrap routes are exempted below.
    api_token = os.environ.get("MOSAERA_API_TOKEN", "").strip()
    # The only /api paths the middleware leaves open — the SPA must reach these before anyone is
    # authenticated (ADR-0004 §5): probe state, and log in. `/auth/setup` and `/auth/setup/check`
    # were the other two, and their removal is the whole of the CWE-1188 fix: the first-admin race
    # needed an unauthenticated endpoint that MINTS AN ADMIN, and there is no longer one.
    _open_api_paths = frozenset({"/api/auth/status", "/api/auth/login"})

    # Per-credential rate limit + daily run quota (#34, ADR-0050). Registered HERE, *before* the
    # auth middleware below, which is what places it INSIDE auth — Starlette's add_middleware
    # inserts at position 0, so the last registered is the outermost. It must run AFTER auth so
    # every request it meters is already authenticated. Self-contained in ratelimit.py; the auth
    # path below is untouched.
    install_rate_limit(app, history=history, api_token=api_token)

    # Registered before CORS below so CORS stays the outermost layer and still
    # answers preflight OPTIONS (which carry no Authorization header).
    @app.middleware("http")
    async def _authenticate(request: Request, call_next: Callable[..., Any]) -> Any:
        path = request.url.path
        if not path.startswith("/api/") or request.method == "OPTIONS":
            return await call_next(request)
        if path in _open_api_paths:
            return await call_next(request)
        # 1) A logged-in user session (DB lookup only when a cookie is present).
        if current_user(request, history) is not None:
            return await call_next(request)
        # 2) The shared service token (constant-time; header or query param).
        if api_token:
            header = request.headers.get("Authorization", "")
            header_ok = bool(header) and secrets.compare_digest(header, f"Bearer {api_token}")
            qp = request.query_params.get("token", "")
            query_ok = bool(qp) and secrets.compare_digest(qp, api_token)
            if header_ok or query_ok:
                return await call_next(request)
        # 2b) A per-user API key (ADR-0127). It sets NO session user, so it authenticates
        # without ever being admin -- the argument is in `apikey_auth`.
        if authenticate_api_key(request, history):
            return await call_next(request)
        # 3) No valid credential — reject IFF auth is configured; else open (dev).
        auth_required = bool(api_token) or users_exist(history)
        if auth_required:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    def _require_admin_ctx(request: Request) -> None:
        """Admin gate for config/secret/user writes: a logged-in ADMIN passes; a
        logged-in non-admin is refused; with no session we fall back to the service
        tiers (admin token / loopback) via the module-level ``_require_admin``."""
        user = current_user(request, history)
        if user is not None:
            if user.get("is_admin"):
                return
            raise HTTPException(status_code=403, detail="admin privileges required")
        _require_admin(request)

    origins = [
        o.strip()
        for o in os.environ.get("MOSAERA_API_CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Registered LAST, which makes it the OUTERMOST layer (same ordering rule ratelimit.py
    # documents: registration inserts at position 0, so the last one wins the outside). That
    # matters: a 401 from the auth middleware, a 429 from the rate limiter and a 500 from an
    # exception handler all short-circuit the inner stack, and every one of them still has to
    # carry the CSP. See security_headers.py for why the policy is what it is.
    install_security_headers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # Report the durable-memory state, not a bare literal. This used to answer "ok" with
        # a dead database behind it, which is exactly the lie a health check exists to catch
        # — and the one an orchestrator would happily keep routing traffic to (ADR-0035).
        if not Settings.from_env().db_url:
            return {"status": "ok", "memory": "none"}  # no DB configured — a chosen mode
        if history is None:
            return {"status": "degraded", "memory": "unavailable"}
        return {"status": "ok", "memory": "postgres"}

    # All app endpoints live under /api so the top-level paths (/runs/:id,
    # /history/:id, ...) belong to the SPA's client-side router and resolve to
    # index.html on a full page load — no JSON-vs-UI collision.
    api = APIRouter(prefix="/api")

    # Extracted per-domain routers (Phase 2 split). Included into `api` so they
    # inherit the /api prefix; assembled here, defined in mosaera_api.routes.*.
    api.include_router(make_auth_router(ctx, _require_admin_ctx))
    # ADR-0127. Session-only by construction: a key cannot issue or revoke a key.
    api.include_router(make_keys_router(ctx))
    api.include_router(make_settings_router(_require_admin_ctx))
    api.include_router(make_voice_router())
    api.include_router(make_runs_router(ctx))
    api.include_router(make_preflight_router())
    api.include_router(make_backlog_router(ctx))
    api.include_router(make_standards_router(ctx, _require_admin_ctx))
    api.include_router(make_messages_router(ctx))
    api.include_router(make_sessions_router(ctx))
    api.include_router(make_projects_router(ctx, _require_admin_ctx))
    api.include_router(make_onboarding_router(ctx, _require_admin_ctx))
    api.include_router(make_project_delivery_router(ctx, _require_admin_ctx))
    api.include_router(make_oauth_router(ctx, _require_admin_ctx))
    # ADR-0114 — GitHub connect needs no pre-auth callback (nothing from a redirect is
    # trusted), so unlike the GitLab OAuth router it lives entirely under /api.
    api.include_router(make_github_router(ctx, _require_admin_ctx))
    api.include_router(make_github_repo_router(ctx, _require_admin_ctx))
    api.include_router(make_github_setup_router(ctx, _require_admin_ctx))
    api.include_router(make_gitlab_repo_router(ctx, _require_admin_ctx))

    app.include_router(api)

    # The OAuth callback (ADR-0104) is a TOP-LEVEL route, NOT under /api: it arrives pre-auth from
    # GitLab with ?code&state, so the /api auth middleware must not 401 it — it carries its own
    # authorization (spent single-use state + a live-session re-check inside the handler). Declared
    # before the SPA catch-all below so that catch-all can't swallow it.
    @app.get("/oauth/callback")
    def oauth_callback(request: Request) -> Any:
        return handle_gitlab_callback(ctx, request)

    # GitHub repo creation (ADR-0120) gets its OWN callback path rather than sharing the one
    # above: the state is spent per-provider, so the handler must know which provider it is
    # before it can spend anything. A separate path answers that from the URL instead of
    # guessing, and leaves the GitLab callback untouched.
    @app.get("/oauth/github/callback")
    def github_repo_callback(request: Request) -> Any:
        return handle_github_repo_callback(ctx, request)

    # GitHub's return leg from the App-manifest registration (ADR-0121). Distinct from the
    # user-authorization callback above: they carry different codes, spend different states, and
    # the manifest declares BOTH to GitHub, so conflating them would break one flow silently.
    @app.get("/oauth/github/setup/callback")
    def github_setup_callback(request: Request) -> Any:
        return handle_github_setup_callback(ctx, request)

    # GitLab project creation (ADR-0126) gets its own callback for the same reason the GitHub
    # ones do: state is spent per-provider, so the handler must know which flow it is before it
    # can spend anything. ADR-0104's connect callback is untouched.
    @app.get("/oauth/gitlab/create/callback")
    def gitlab_create_callback(request: Request) -> Any:
        return handle_gitlab_create_callback(ctx, request)

    # Serve the built SPA (if present) from the same origin. Registered last so API
    # routes win; a catch-all returns index.html for client-side routes.
    dist = Path(web_dist or os.environ.get("MOSAERA_WEB_DIST", "apps/web/dist"))
    index = dist / "index.html"
    if index.is_file():
        _warn_if_stale_dist(dist, index)
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        dist_root = dist.resolve()

        # An unknown /api path is a 404 for EVERY verb (#129 follow-up). The SPA catch-all below
        # is GET-only, so a POST/PUT/DELETE to a path no real route claimed used to fall through to
        # Starlette's method check against it and return 405 — "wrong verb" about a path that does
        # not exist. Registered HERE, after every real router and before the catch-all, so
        # first-match-wins keeps real API routes ahead of it.
        #
        # Invisible in CI for the same reason the GET half was: `make ci` runs `build` AFTER `test`,
        # so with no `dist` neither handler is registered and the test that asserts this cannot
        # fire. It reproduces the moment a bundle exists — which is every deployed instance.
        @app.api_route(
            "/api/{full_path:path}",
            methods=["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        )
        # `-> None` rather than `NoReturn`: it always raises, but FastAPI inspects the
        # annotation to build a response model and cannot handle NoReturn (every request
        # to the route errored). None is the closest honest thing it accepts.
        def unknown_api_route(full_path: str) -> None:
            raise HTTPException(status_code=404, detail="unknown API route")

        @app.get("/{full_path:path}")
        def spa(full_path: str) -> FileResponse:
            # An unknown /api path is a 404, never the SPA. This catch-all is registered last so
            # real API routes win — but a path that matched NONE of them still landed here and was
            # answered with index.html and a 200, so a client could not tell a typo'd endpoint from
            # a working one. It reads as success and returns HTML to something expecting JSON.
            #
            # Invisible until now because `make ci` runs `build` AFTER `test`: with no `dist` in
            # CI this handler is never even registered, so the test that asserts this (which has
            # existed all along) could not fire there. Green-by-vacancy, on the API's own 404.
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="unknown API route")
            # Confine to dist like every other file handler — Starlette's :path
            # converter does not strip `..`, so resolve then check containment.
            candidate = (dist_root / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist_root):
                return FileResponse(candidate)
            return FileResponse(index)

    app.state.sessions = ctx.sessions
    return app


__all__ = ["ApproveBody", "RunSubmit", "create_app"]
