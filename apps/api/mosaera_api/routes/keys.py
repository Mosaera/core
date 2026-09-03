"""Per-user API keys: issue, list, revoke (ADR-0127).

A key is a long-lived, revocable, attributed credential for headless callers — CI, a CLI, a
script. It exists because `MOSAERA_API_TOKEN` is one shared secret with no revocation and no
attribution: everyone holding it is indistinguishable, and rotating it breaks every consumer at
once. That token stays (ADR-0004 kept it deliberately as a *service* credential); this is additive.

**Two properties carry the security of this module, and both are structural rather than checked.**

*A key is never admin.* Authentication in `app._authenticate` sets no session user, so
`current_user()` stays None and `_require_admin_ctx` falls through to the service tier. An admin's
own key cannot rewrite config or secrets — so neither can a leaked one. Nothing in this file needs
to enforce that, and nothing in this file may undo it.

*A key cannot mint a key.* Every endpoint here requires a logged-in SESSION, refusing a request
authenticated by a key. ADR-0116 deleted this repo's previous credential-issuing endpoint because
an unauthenticated path to a credential is CWE-1188; the lesson generalises — a credential that can
issue credentials is self-propagating, and a leak becomes permanent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_memory import MemoryStore

from mosaera_api.auth import current_user, hash_token, new_session_token
from mosaera_api.routes.context import AppContext

#: Cap per user. Not a security boundary — a bound on accidental accumulation, so a forgotten
#: script cannot grow the table without limit and an operator's list stays readable enough that
#: revoking the right one is easy.
_MAX_KEYS_PER_USER = 20


def _session_user(
    request: Request, store: MemoryStore | None
) -> tuple[dict[str, Any], MemoryStore]:
    """The logged-in account, or refuse.

    THE GUARD OF THIS MODULE. `current_user` reads the session cookie only, so a request
    authenticated by an API key returns None here and is refused — which is what stops a key
    issuing another key. A change that makes this accept `request.state.api_key` would make a
    leaked credential self-renewing; the test suite pins that it does not.

    Returns the store alongside the user so callers narrow the Optional here rather than
    re-asserting it at every call site.
    """
    if store is None:
        raise HTTPException(status_code=503, detail="user accounts require a database")
    user = current_user(request, store)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="sign in to manage API keys — a key cannot issue or revoke keys",
        )
    return user, store


def make_keys_router(ctx: AppContext) -> APIRouter:
    # The parent router already carries `/api`, so this prefix is relative to it (`/api/keys`).
    router = APIRouter(prefix="/keys", tags=["keys"])

    @router.post("")
    def create_key(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Issue a key. The plaintext is returned ONCE and is not recoverable afterwards."""
        user, store = _session_user(request, ctx.history)
        name = str(body.get("name") or "").strip()[:64]
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        live = [k for k in store.list_api_keys(int(user["id"])) if not k["revoked"]]
        if len(live) >= _MAX_KEYS_PER_USER:
            raise HTTPException(
                status_code=409,
                detail=f"at most {_MAX_KEYS_PER_USER} live keys — revoke one first",
            )
        # Same generator as a session token: 32 bytes from `secrets`, urlsafe. Only its hash is
        # stored, so this return value is the single moment the key exists in readable form.
        secret = new_session_token()
        row = store.create_api_key(hash_token(secret), int(user["id"]), name)
        return {**row, "key": secret}

    @router.get("")
    def list_keys(request: Request) -> dict[str, Any]:
        user, store = _session_user(request, ctx.history)
        return {"keys": store.list_api_keys(int(user["id"]))}

    @router.delete("/{key_id}")
    def revoke_key(request: Request, key_id: int) -> dict[str, Any]:
        """Revoke one of the caller's OWN keys; effective on the next request.

        Ownership is enforced in the store's query rather than checked here, so forgetting the
        check in a future route cannot revoke someone else's credential.
        """
        user, store = _session_user(request, ctx.history)
        if not store.revoke_api_key(key_id, int(user["id"]), datetime.now(UTC)):
            raise HTTPException(status_code=404, detail="no such live key")
        return {"revoked": True}

    return router
