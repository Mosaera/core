"""Password hashing + session helpers for multi-user login.

Deliberately dependency-free: password hashing uses stdlib ``hashlib.scrypt``
(memory-hard) so there's no native build (argon2/bcrypt) to fight on Windows/WSL.
Only the SHA-256 of a session token is ever stored, so a database leak can't be
replayed as a live session. Sessions ride an HttpOnly cookie (see routes/auth.py).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request
    from mosaera_memory import MemoryStore

SESSION_COOKIE = "mosaera_session"
SESSION_TTL = timedelta(days=14)

# scrypt cost params (n must be a power of two). N=2**14 is a sane interactive-login
# cost; r/p standard. Encoded into the hash so params can evolve without a migration.
#
# ⚠ If you bump these, re-read ADR-0051. `_DUMMY_HASH` below equalizes login timing by hashing at
# THESE params, but existing users carry the params encoded in their stored hash. The moment the
# two diverge, an unknown username (new, dearer params) becomes measurably SLOWER than a real one
# (old, cheaper params) — the enumeration oracle re-opens, inverted. It cannot be fixed in general
# (you can't know an unknown user's params), so a bump needs a rehash-on-login migration first.
_N, _R, _P = 2**14, 8, 1
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
_MIN_PASSWORD = 8

# The longest username we'll even look at. `CredentialsBody.username` is an unbounded `str`, so
# without this a 10MB login body would be stripped, SHA-256'd and shipped to Postgres. Generous
# next to `_USERNAME_RE`'s 64 so it only ever catches abuse, never a real (if invalid) attempt.
_MAX_USERNAME = 256

# A stored-hash shape that no password matches, used to equalize login timing for an unknown
# username (ADR-0051). Deliberately NOT built with `hash_password`: `verify_password` below parses
# `scheme$n$r$p$salt$hash`, recomputes scrypt from those params and compares — it never checks the
# stored digest is a genuine scrypt output. So random bytes verify at *identical* cost (measured:
# 132.4ms vs 131.8ms, ratio 1.004) while costing nothing to construct, which keeps 130ms of scrypt
# out of every process start and every test that imports this module. `dklen` follows from the hex
# length, so 32 bytes matches a real hash exactly.
_DUMMY_HASH = (
    f"scrypt${_N}${_R}${_P}${secrets.token_bytes(16).hex()}${secrets.token_bytes(32).hex()}"
)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(hash_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def normalize_username(raw: str) -> str:
    """The canonical form of a submitted username — the ONE identity both the account lookup and
    the backoff bucket must agree on.

    **This must stay byte-identical to ``AuthMixin.get_user_credentials``' normalization
    (``.strip()``, case-SENSITIVE).** Both deviations are exploitable, in opposite directions:

    - *Coarser* (e.g. ``.casefold()``) is a backoff BYPASS. ``users.username`` is case-sensitively
      unique, so ``admin`` and ``Admin`` are two accounts that can coexist. Folding them into one
      bucket means — because a successful login DELETES the bucket — whoever holds ``Admin`` clears
      the real admin's failure counter at will, simply by logging into their own account.
    - *Finer* (no strip) is also a bypass: ``admin``, ``admin `` and ``admin\\t`` all resolve to the
      same account but would land in different buckets, so an attacker gets a fresh allowance per
      whitespace variant, forever.

    The length cap only ever trips abuse (`_USERNAME_RE` allows 64); it exists because the request
    schema does not bound the field at all.
    """
    return raw.strip()[:_MAX_USERNAME]


def login_subject(normalized_username: str) -> str:
    """The backoff bucket key for a normalized username.

    Hashed so the durable table can never hold the passwords people periodically type into the
    username box, and to match the standing discipline: sessions and setup tokens are stored as
    SHA-256 for the same reason. Pass the output of ``normalize_username``, never a raw body field.
    """
    return hash_token(normalized_username)


def validate_credentials(username: str, password: str) -> str | None:
    """Return a human error message if the username/password are unacceptable, else
    None. Kept liberal (self-hosted small team) but non-trivial."""
    if not _USERNAME_RE.match(username.strip()):
        return "username must be 3-64 chars: letters, digits, dot, dash, underscore"
    if len(password) < _MIN_PASSWORD:
        return f"password must be at least {_MIN_PASSWORD} characters"
    return None


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + SESSION_TTL


def cookie_secure() -> bool:
    """Whether to mark the session cookie Secure (HTTPS-only). Off by default so the
    common loopback/LAN http deploy works; set MOSAERA_COOKIE_SECURE=1 behind TLS."""
    return os.environ.get("MOSAERA_COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes")


def users_exist(store: MemoryStore | None) -> bool:
    """Whether any account exists — the signal that turns auth enforcement on.

    Three states, and they are NOT the same (ADR-0035). The old code collapsed the last two
    into ``False``, which is how a database outage silently switched authentication off:

    1. **No store.** → False. Either no DB is configured (a legitimate, chosen mode), or the
       operator explicitly opted into ``MOSAERA_ALLOW_DEGRADED_MEMORY`` — ``guard_memory``
       refuses to boot otherwise.
    2. **A store that does not support accounts at all** (no ``count_users``: a duck-typed
       test fake, or a build without the users table). → False. There is no account tier
       here to enforce; this is a *capability* answer, not a failure.
    3. **A store that supports accounts but ERRORS when we ask.** → **True: fail CLOSED.**
       A database that dies mid-flight must not switch authentication off. The accounts
       guarding this API do not cease to exist because we momentarily cannot read them, so
       callers get a 401 rather than the whole API falling open.

    The discriminator is the store's CAPABILITY, not whether the call threw — which is why
    this checks for the method rather than catching everything.
    """
    if store is None:
        return False
    counter = getattr(store, "count_users", None)
    if counter is None:
        return False
    try:
        return bool(counter() > 0)
    except Exception:
        return True


def current_user(request: Request, store: MemoryStore | None) -> dict[str, Any] | None:
    """The logged-in account for a request (from its session cookie), or None. Only
    touches the DB when a cookie is actually present, so credential-less requests
    cost nothing."""
    if store is None:
        return None
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return store.session_user(hash_token(raw), datetime.now(UTC))
    except Exception:
        return None
