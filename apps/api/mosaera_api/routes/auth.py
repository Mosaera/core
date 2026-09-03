"""Multi-user login: login/logout, session identity, and admin user management (capped seats).

Sessions ride an HttpOnly cookie; the middleware in ``app.py`` accepts a valid session OR the
shared service token. ``/auth/status`` and ``/auth/login`` are the only endpoints the middleware
leaves open, so the SPA can decide "sign in" before anyone is authenticated. User accounts require
a database — without one the endpoints report ``users_supported: false`` and no-op.

THERE IS NO ACCOUNT-CREATION ROUTE HERE FOR AN EMPTY INSTANCE (ADR-0116). The first administrator
is created by `mosaera-setup`, in a terminal, against the database directly. `POST /auth/setup` and
its one-time token (ADR-0040) are gone with it: the browser half of setup was the reason an
unauthenticated endpoint had to exist at all, and CWE-1188 is now closed by there being no such
endpoint rather than by a token guarding one. `MOSAERA_INITIAL_ADMIN_*` remains for orchestrated
deploys, and `POST /auth/users` still refuses to create the FIRST account.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from mosaera_memory import MemoryStore

from mosaera_api.auth import (
    _DUMMY_HASH,
    SESSION_COOKIE,
    SESSION_TTL,
    cookie_secure,
    current_user,
    hash_password,
    hash_token,
    login_subject,
    new_session_token,
    normalize_username,
    session_expiry,
    validate_credentials,
    verify_password,
)
from mosaera_api.loginguard import backoff_seconds, load_backoff_config, verify_slot
from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import CreateUserBody, CredentialsBody

_MAX_USERS = 5

# 1-in-N admitted logins also sweeps stale backoff buckets. Probabilistic rather than
# every-request: any submitted username makes a bucket, so a spray of random usernames grows the
# table without limit — but sweeping on every request would add a second unauthenticated write to
# an open endpoint. Probability decouples the sweep rate from the attack rate while still scaling
# with it (the `ratelimit.py` prune-only-on-a-new-subject precedent). See ADR-0051.
_PRUNE_ODDS = 100


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


def make_auth_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()
    # Resolved ONCE, at app build — not per request. A malformed value must refuse to BOOT
    # (`guard_bind`/`guard_memory`'s precedent), not 500 the login endpoint on first use, which is
    # the inverted-failure version of the same mistake ADR-0035 exists to prevent.
    backoff = load_backoff_config()

    def _issue_session(response: Response, store: MemoryStore, user_id: int) -> None:
        token = new_session_token()
        store.create_session(hash_token(token), user_id, session_expiry())
        _set_session(response, token)

    @api.get("/auth/status")
    def auth_status(request: Request) -> dict[str, Any]:
        """What the SPA needs to decide setup vs login vs app. Open (no auth)."""
        store = ctx.history
        supported = store is not None
        # A store that opened at boot but has since DIED must not 500 the one endpoint the
        # SPA needs to bootstrap — and must not read as "no users", which would advertise
        # `needs_setup: true` to an attacker while dropping auth_required. Fail CLOSED, in
        # step with `users_exist` (ADR-0035). Note the discriminator is the store's
        # CAPABILITY: a store with no `count_users` simply has no account tier (a fake, or a
        # build without the users table) — that is an answer, not a failure.
        degraded = False
        count = 0
        counter = getattr(store, "count_users", None) if store is not None else None
        if counter is not None:
            try:
                count = counter()
            except Exception:
                degraded = True
        token_set = bool(os.environ.get("MOSAERA_API_TOKEN", "").strip())
        return {
            "users_supported": supported,
            # An instance with a database and no accounts. The SPA can no longer ACT on this —
            # there is no browser route to create one — but it still says so, because "sign in to
            # an instance that has no accounts" deserves a sentence naming `mosaera-setup` rather
            # than a login form that can never succeed.
            "needs_setup": supported and not degraded and count == 0,
            "auth_required": token_set or count > 0 or degraded,
            "user": current_user(request, store),
        }

    def _retry_after(store: MemoryStore, subject: str, config: Any) -> int:
        """Seconds until this subject may try again. Never 0 — a `Retry-After: 0` just invites the
        hot retry loop the backoff exists to stop.

        Read-only and best-effort: the admission decision was already made atomically by the claim.
        If the bucket can't be read we fall back to the base delay rather than guess low.
        """
        read = getattr(store, "get_login_backoff", None)
        record = read(subject) if read is not None else None
        if not record:
            return max(1, config.base_seconds)
        elapsed = (datetime.now(UTC) - record["last_attempt_at"]).total_seconds()
        return max(1, int(backoff_seconds(int(record["attempts"]), config) - elapsed))

    def _maybe_prune_backoff(store: MemoryStore, config: Any) -> None:
        """Opportunistically sweep stale backoff buckets (see `_PRUNE_ODDS`)."""
        prune = getattr(store, "prune_login_backoff", None)
        if prune is None or not config.enabled or secrets.randbelow(_PRUNE_ODDS) != 0:
            return
        cutoff = datetime.now(UTC) - timedelta(seconds=config.reset_seconds)
        prune(cutoff)

    @api.post("/auth/login")
    def auth_login(body: CredentialsBody, response: Response) -> dict[str, Any]:
        """Authenticate, behind a per-account backoff (#38, ADR-0051).

        Every branch below is ordered so that an unknown username is indistinguishable from a real
        one — same status, same work. That is the whole point: backoff necessarily branches on
        account state, so without equalization a 429 would mean "this account exists", handing over
        a cleaner enumeration oracle than the timing leak this also closes.
        """
        store = ctx.history
        if store is None:
            raise HTTPException(503, "user accounts require a database")

        # ONE normalization, used for BOTH the bucket and the lookup. Deriving the key separately
        # from `body.username` is how the two drift apart, and either direction of drift is a
        # bypass (see `normalize_username`).
        username = normalize_username(body.username)
        subject = login_subject(username)

        claim = getattr(store, "claim_login_attempt", None)
        if backoff.enabled and claim is not None:
            spent = claim(
                subject,
                threshold=backoff.threshold,
                base_seconds=backoff.base_seconds,
                max_seconds=backoff.max_seconds,
                reset_seconds=backoff.reset_seconds,
            )
            if spent is None:
                # Backed off. Nothing else runs: no session sweep, no lookup, no scrypt — so this
                # path is equally cheap for a real account and a fictional one.
                raise HTTPException(
                    429,
                    "too many failed sign-in attempts — try again later",
                    headers={"Retry-After": str(_retry_after(store, subject, backoff))},
                )

        # Below the gate, so a refused attempt never pays for this.
        store.prune_sessions(datetime.now(UTC))
        _maybe_prune_backoff(store, backoff)

        creds = store.get_user_credentials(username)
        with verify_slot() as slot:
            if not slot:
                # Every verification slot is busy — refuse rather than queue (queueing would hold
                # an anyio worker and stall every other sync endpoint, which is the DoS itself).
                raise HTTPException(
                    503,
                    "sign-in is busy — try again shortly",
                    headers={"Retry-After": "1"},
                )
            # NOT `creds is not None and verify_password(...)`: `and` short-circuits, so that shape
            # skips ~130ms of scrypt whenever the account doesn't exist — a ~100x timing gap
            # readable in ONE request. Verifying against a dummy hash costs exactly the same and
            # can never match (ADR-0051).
            verified = verify_password(
                body.password, str(creds["password_hash"]) if creds else _DUMMY_HASH
            )
        if creds is None or not verified:
            raise HTTPException(401, "invalid username or password")

        clear = getattr(store, "clear_login_failures", None)
        if clear is not None:
            clear(subject)  # a success ends the streak
        _issue_session(response, store, int(creds["id"]))
        return {"user": {k: creds[k] for k in ("id", "username", "is_admin")}}

    @api.post("/auth/logout")
    def auth_logout(request: Request, response: Response) -> dict[str, bool]:
        store = ctx.history
        raw = request.cookies.get(SESSION_COOKIE)
        if store is not None and raw:
            store.delete_session(hash_token(raw))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @api.get("/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        user = current_user(request, ctx.history)
        if user is None:
            raise HTTPException(401, "not authenticated")
        return {"user": user}

    @api.get("/auth/users")
    def list_users(request: Request) -> dict[str, Any]:
        require_admin(request)
        store = ctx.history
        return {"users": store.list_users() if store is not None else [], "max_users": _MAX_USERS}

    @api.post("/auth/users", status_code=201)
    def create_user(body: CreateUserBody, request: Request) -> dict[str, Any]:
        require_admin(request)
        store = ctx.history
        if store is None:
            raise HTTPException(503, "user accounts require a database")
        # Defence in depth (ADR-0040 / finding A1): the FIRST account must come through the
        # token-gated /auth/setup, never here. On a loopback-behind-a-proxy instance with no
        # MOSAERA_API_TOKEN the admin gate degrades to the (proxy-unreliable) localhost check,
        # so without this a proxied client could mint the first admin via /auth/users and skip
        # the setup token entirely. Once an account exists, admin auth is genuinely enforced.
        if store.count_users() == 0:
            raise HTTPException(
                403, "create the first admin via first-run setup with the setup token, not here"
            )
        err = validate_credentials(body.username, body.password)
        if err:
            raise HTTPException(400, err)
        try:
            user = store.create_user(
                body.username,
                hash_password(body.password),
                is_admin=body.is_admin,
                max_users=_MAX_USERS,
            )
        except ValueError as exc:
            reason = str(exc)
            msg = (
                f"user limit reached ({_MAX_USERS} max)"
                if reason == "user_limit"
                else "that username is taken"
            )
            raise HTTPException(409, msg) from exc
        return {"user": user}

    @api.delete("/auth/users/{user_id}/lockout")
    def clear_user_lockout(user_id: int, request: Request) -> dict[str, bool]:
        """Clear an account's login backoff (#38, ADR-0051).

        Per-account backoff is a deliberate trade: it throttles guessing, and in exchange anyone
        who knows a username can keep that account locked out by failing against it. This is the
        recovery path for a locked-out MEMBER. An admin is never dependent on it — a locked-out
        operator still reaches `/api/*` with `MOSAERA_API_TOKEN`/`MOSAERA_ADMIN_TOKEN`, which
        bypass `/auth/login` entirely.

        Admin-gated, though it is worth being precise about what it can do: it deletes a counter.
        It cannot grant access, weaken a password, or mint a session — the blast radius of a bug
        here is that someone gets their normal number of attempts back.
        """
        require_admin(request)
        store = ctx.history
        if store is None:
            raise HTTPException(503, "user accounts require a database")
        target = store.get_user(user_id)
        if target is None:
            raise HTTPException(404, "no such user")
        clear = getattr(store, "clear_login_failures", None)
        if clear is not None:
            clear(login_subject(normalize_username(str(target["username"]))))
        return {"ok": True}

    @api.delete("/auth/users/{user_id}")
    def delete_user(user_id: int, request: Request) -> dict[str, bool]:
        require_admin(request)
        store = ctx.history
        if store is None:
            raise HTTPException(503, "user accounts require a database")
        target = store.get_user(user_id)
        if target is None:
            raise HTTPException(404, "no such user")
        # Never orphan the instance: refuse to remove the last admin.
        if target["is_admin"] and store.count_admins() <= 1:
            raise HTTPException(409, "can't remove the last admin")
        store.delete_user(user_id)
        return {"ok": True}

    return api
