"""Per-credential API rate limiting + a durable per-user daily run quota (#34, ADR-0050).

A LEAF beside the auth middleware rather than inside it. ``app.py`` holds ``guard_bind`` and the
session/token verification and is near the modularity ceiling; a limiter bolted into it would put
new logic inside the file whose auth path must not be perturbed. So ``app.py`` gains an import and
one call, and everything below is testable on its own.

**Config is SPLIT (#37, ADR-0050 addendum).** The **rate limit stays ENV-ONLY**
(``MOSAERA_RATE_LIMIT_PER_MIN``, ``load_config``): a request-rate limit on the API server is the
infra family ``GENERAL_KNOBS`` documents excluding (ADR-0005), it runs on *every* request so its
config must stay boot-time + free (ADR-0050 §1), and its parse is LOUD on a typo (``SystemExit``,
the ``guard_bind``/``guard_memory`` precedent) — a control you can't read is a failure, not a
suggestion. The **run quota is a UI knob** (``run_quota_per_day`` in ``GENERAL_KNOBS``): it is
run-adjacent and read only on the rare ``POST /api/runs`` path, so ``_live_quota`` re-reads it
(env > stored > default) live — a UI save applies with no restart. See ADR-0050 for the full
argument (its follow-up #1 is what #37 resolves).

**Ordering matters and is counter-intuitive.** Starlette's ``add_middleware`` inserts at position 0,
so the LAST-registered middleware is the OUTERMOST. ``install_rate_limit`` is therefore called
BEFORE ``@app.middleware("http") _authenticate`` is registered, which places this INSIDE it — i.e.
it runs *after* authentication. That is required: everything reaching this module has already been
authenticated, so a client cannot mint fresh buckets with junk credentials.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, NamedTuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mosaera_core.config import Settings
from mosaera_memory import MemoryStore, utc_day

from mosaera_api.auth import SESSION_COOKIE, current_user, hash_token

# The one route that starts a run. Matched literally rather than via a dependency so the whole
# feature stays inside this module + a 2-line app.py wiring (the disjoint-domain constraint of
# #34: routes/ belongs to a sibling session). ``test_run_create_path_still_exists`` asserts the
# app really exposes it, so a future rename fails a test LOUDLY instead of silently un-metering
# the quota.
RUN_CREATE_PATH = "/api/runs"

_WINDOW_SECONDS = 60
# Ceiling on distinct tracked subjects. Bounds the in-process dict against a caller that rotates
# credentials to grow it without limit (see ``_FixedWindow._prune``).
_MAX_TRACKED_SUBJECTS = 10_000

_DEFAULT_PER_MIN = 300  # 5 rps sustained per credential — far above any real SPA, far below a loop
_DEFAULT_QUOTA_PER_DAY = 0  # off: there is no safe universal number (see load_config)
_MAX_SANE = 100_000


class RateLimitConfig(NamedTuple):
    """Resolved env-only limits. ``0`` means "not enforced" for either field."""

    per_min: int
    quota_per_day: int

    @property
    def enabled(self) -> bool:
        return self.per_min > 0 or self.quota_per_day > 0


def _int_env(name: str, default: int) -> int:
    """Parse a bounded non-negative int from the environment, or exit loudly.

    Deliberately NOT lenient. Falling back to the default on a typo would mean an operator who
    set ``MOSAERA_RATE_LIMIT_PER_MIN=1O0`` (letter O) runs at 300 believing they run at 100 — the
    silently-wrong-config class ADR-0035 exists to kill. A limit is a control; an unreadable
    control is a failure, not a suggestion.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"invalid {name}={raw!r} — expected a whole number of "
            f"{'requests per minute' if 'RATE' in name else 'runs per day'} "
            f"(0 disables it)."
        ) from None
    if not 0 <= value <= _MAX_SANE:
        raise SystemExit(
            f"invalid {name}={value} — must be between 0 and {_MAX_SANE} (0 disables)."
        )
    return value


def load_config() -> RateLimitConfig:
    """Read the env-only limits.

    ``MOSAERA_RATE_LIMIT_PER_MIN`` defaults ON (a runaway client is the common failure and the
    default is generous enough that no legitimate caller notices). ``MOSAERA_RUN_QUOTA_PER_DAY``
    defaults OFF: a runs/day cap is a fairness/budget POLICY, and there is no number that is
    right for every deployment — the same reason ``run_max_usd``/``run_max_tokens`` default to
    None. Deny-by-default governs *authorization*; this is not an authorization decision.
    """
    return RateLimitConfig(
        per_min=_int_env("MOSAERA_RATE_LIMIT_PER_MIN", _DEFAULT_PER_MIN),
        quota_per_day=_int_env("MOSAERA_RUN_QUOTA_PER_DAY", _DEFAULT_QUOTA_PER_DAY),
    )


def _live_quota() -> int:
    """The CURRENT daily run-quota limit (env > stored > default), re-read LIVE so a UI settings
    save applies with no restart (#37, ADR-0050 addendum). Read only on the rare ``POST /api/runs``
    path + once at boot — never the interactive hot path (ADR-0050 §1). ``0`` = no cap.

    The env var stays parsed LOUDLY at boot by ``load_config``'s ``_int_env`` (called first in
    ``install_rate_limit``), so a garbage ``MOSAERA_RUN_QUOTA_PER_DAY`` still ``SystemExit``s; a
    *stored* (UI) value parses leniently like every other knob (a typo → the default, which for an
    opt-in, off-by-default policy the operator notices). The request-RATE limit is NOT a knob."""
    return max(0, int(Settings.from_env().run_quota_per_day))


class _FixedWindow:
    """A per-subject fixed-window counter, in process.

    Fixed window (not a token bucket) because it is the cheapest thing that works: one dict
    lookup and no background task, on a path that must not add latency. The known cost is a
    boundary burst — up to 2x the limit across two adjacent windows — which is acceptable for a
    control whose job is stopping a runaway loop, not shaping traffic.

    Ephemeral by design: a restart clears it. The durable half of #34 is the quota; a rate limit
    that forgets on restart is not a meaningful weakening (a restart is not an attacker-reachable
    reset — it costs the operator more than the attacker).
    """

    def __init__(self, max_subjects: int = _MAX_TRACKED_SUBJECTS) -> None:
        self._hits: dict[str, tuple[int, int]] = {}  # subject -> (window index, count)
        self._max = max_subjects

    def check(self, subject: str, limit: int, now: float | None = None) -> int:
        """Count one hit. Returns 0 when allowed, else seconds until the window rolls."""
        clock = time.monotonic() if now is None else now  # monotonic: immune to wall-clock jumps
        window = int(clock // _WINDOW_SECONDS)
        current = self._hits.get(subject)
        if current is None or current[0] != window:
            self._prune(window)
            self._hits[subject] = (window, 1)
            return 0
        _, count = current
        if count >= limit:
            return max(1, int((window + 1) * _WINDOW_SECONDS - clock))
        self._hits[subject] = (window, count + 1)
        return 0

    def _prune(self, window: int) -> None:
        """Bound the dict. Only ever called when admitting a NEW subject, so the common path
        stays a single lookup.

        Without this, a caller that rotates its credential every request grows the dict forever —
        turning a memory-protection control into a memory leak. Dropping stale windows is enough
        in practice; the clear() is the last resort that trades a brief counter reset (all
        subjects get a fresh window) for a hard bound. That trade only triggers under an active
        rotation attack, where the counters were already being evaded.
        """
        if len(self._hits) < self._max:
            return
        self._hits = {s: v for s, v in self._hits.items() if v[0] == window}
        if len(self._hits) >= self._max:
            self._hits.clear()


def subject_for(request: Request, api_token: str) -> str | None:
    """Which bucket this request counts against, or None when it carries no credential.

    NOT an authorization check — ``_authenticate`` already ran and anything here is authorized.
    This only picks a counting key, which is why an unverified cookie is a safe basis: an invalid
    one never reaches this code.

    Cookie first, mirroring ``_authenticate``'s own precedence. It matters: the SPA sends BOTH a
    session cookie and the service token, so keying on the token first would collapse every
    logged-in user into one shared bucket and let one busy tab throttle the whole team.

    Returning None (no credential) is safe: such a request is either about to be 401'd by auth, or
    the instance has no auth configured at all — a dev box, which the auth middleware also leaves
    open. So credential-presence, not a `users_exist` DB probe, is the discriminator; that keeps
    this path free of database calls entirely.
    """
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        # Hash so a live session token never sits in a process-memory dict key (the store holds
        # only hashes for the same reason); truncated because this is a bucket key, not a secret.
        return f"session:{hash_token(raw)[:32]}"
    if api_token:
        header = request.headers.get("Authorization", "")
        header_ok = bool(header) and secrets.compare_digest(header, f"Bearer {api_token}")
        query = request.query_params.get("token", "")
        query_ok = bool(query) and secrets.compare_digest(query, api_token)
        if header_ok or query_ok:
            return "token"  # ONE shared credential = ONE identity = one bucket
    return None


def _seconds_to_utc_midnight(now: datetime | None = None) -> int:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    tomorrow = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow.timestamp() + 86_400) - moment.timestamp()))


def _too_many(detail: str, retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"detail": detail}, status_code=429, headers={"Retry-After": str(retry_after)}
    )


def _quota_subject(request: Request, store: MemoryStore | None) -> str | None:
    """The DURABLE identity for the daily quota, or None when the caller is exempt.

    Unlike the rate limit this resolves the REAL account (one DB read, on run-creation only — a
    rare, expensive action, so it never touches the interactive path). It has to: a per-session
    key would let a user reset their own daily cap by logging in again, which is fine for a rate
    limit but would make a quota decorative.

    Admins are exempt: the quota is fair-share between users, and the operator is not competing
    for their own capacity. Run budgets (``run_max_usd``/``run_max_tokens``) still bound them.
    """
    user = current_user(request, store)
    if user is None:
        return "token"  # the service token: one credential, one bucket
    if user.get("is_admin"):
        return None
    return f"user:{user['id']}"


def install_rate_limit(
    app: FastAPI, *, history: MemoryStore | None, api_token: str
) -> RateLimitConfig:
    """Register the limiter. MUST be called before the auth middleware — see the module docstring.

    Returns the resolved config (for tests/observability). Registers nothing when both limits are
    off, so a disabled limiter costs exactly zero per request.
    """
    config = (
        load_config()
    )  # rate limit: env-only, loud, boot-time (the quota field here is the env value)
    boot_quota = _live_quota()  # env > stored > default — catches a UI-stored quota at boot too
    if boot_quota > 0 and history is None:
        # A configured quota with nowhere to count is a policy that silently does nothing —
        # exactly the class guard_memory refuses to boot on (ADR-0035). Fail loudly instead.
        raise SystemExit(
            f"a daily run quota ({boot_quota}/day) needs durable memory to count against, but no "
            "database is available.\nSet MOSAERA_DB_URL, or clear MOSAERA_RUN_QUOTA_PER_DAY / the "
            "Runs-per-day setting."
        )
    # Register whenever a limit could fire: the rate limit is on, OR a DB exists so the quota can be
    # turned on LIVE from the UI later (its enforcement needs the store). Both off + no DB → nothing
    # to enforce, so register nothing and pay exactly zero per request.
    if config.per_min <= 0 and history is None:
        return config

    window = _FixedWindow()

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next: Callable[..., Any]) -> Any:
        path = request.url.path
        # Same scope as auth: /api only. OPTIONS is a CORS preflight carrying no credential.
        if not path.startswith("/api/") or request.method == "OPTIONS":
            return await call_next(request)
        subject = subject_for(request, api_token)
        if subject is None:
            return await call_next(request)

        if config.per_min > 0:
            retry_after = window.check(subject, config.per_min)
            if retry_after:
                return _too_many(
                    f"rate limit exceeded ({config.per_min} requests/minute) — "
                    f"retry in {retry_after}s",
                    retry_after,
                )

        # The quota meters the EXPENSIVE action (starting a run), not every request — so it can
        # afford to re-read its limit LIVE (env > stored > default) here, applying a UI save with
        # no restart without touching the interactive hot path (ADR-0050 §1, #37).
        if request.method == "POST" and path.rstrip("/") == RUN_CREATE_PATH and history is not None:
            quota_limit = _live_quota()
            quota_subject = _quota_subject(request, history) if quota_limit > 0 else None
            if quota_subject is not None:  # None = quota off, or admin (exempt)
                used = history.try_consume_run_quota(quota_subject, utc_day(), quota_limit)
                if used is None:
                    retry_after = _seconds_to_utc_midnight()
                    return _too_many(
                        f"daily run quota reached ({quota_limit} runs/day) — resets at 00:00 UTC",
                        retry_after,
                    )

        return await call_next(request)

    return config


__all__ = ["RUN_CREATE_PATH", "RateLimitConfig", "install_rate_limit", "load_config", "subject_for"]
