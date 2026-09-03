"""Authenticating a request by a per-user API key (ADR-0127).

Lives beside `app.py` rather than in it because the authority argument belongs with the code that
makes it, and `app.py` sits at its size ceiling.

**The whole security property is what this does NOT do.** It resolves a key to its owner and
records attribution; it never sets a session user. `current_user()` therefore stays None for the
rest of the request, `_require_admin_ctx` falls through to the service tier, and an admin-gated
write still demands MOSAERA_ADMIN_TOKEN. That is how ADR-0004's "the token is not admin" stays
true for a credential a human can mint from a browser: an admin's own key cannot rewrite config or
secrets, so a leaked one cannot either.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from mosaera_api.auth import hash_token


def presented_credential(request: Request) -> str:
    """The bearer credential on a request, from `Authorization: Bearer` or `?token=`.

    Both spellings, because the shared service token has always accepted both and a key that
    worked in one place but not the other would be a trap. The query form exists for SSE and
    `<img>`, which cannot set headers.
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.query_params.get("token", "").strip()


def authenticate_api_key(request: Request, store: Any) -> bool:
    """True when a live API key authenticated this request; False leaves the decision to callers.

    Looked up BY HASH -- a single indexed query, never a scan comparing every stored key, so an
    unknown key costs what a known one costs.

    `request.state.api_key` carries ATTRIBUTION without AUTHORITY: who called, never what they may
    do. Nothing downstream should read it as permission.
    """
    if store is None:
        return False
    presented = presented_credential(request)
    if not presented:
        return False
    hashed = hash_token(presented)
    owner = store.api_key_owner(hashed)
    if owner is None:
        return False
    request.state.api_key = owner
    with suppress(Exception):
        # Best-effort: a failed usage stamp must never refuse an otherwise valid credential.
        store.touch_api_key(hashed, datetime.now(UTC))
    return True
