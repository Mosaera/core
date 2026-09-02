"""Login protection: per-account backoff policy + a bound on concurrent password verification.

Two controls guarding `POST /auth/login`, which `#34`'s rate limiter cannot reach — that route is
middleware-exempt and *pre-credential*, so `subject_for` finds no credential and skips it
(ADR-0050 named this as the open gap; ADR-0051 closes it).

A leaf on purpose: it imports nothing from `auth.py`, so `auth.py` may import *this* without a
cycle. (`ratelimit.py` already imports `auth.py`, which is why reusing its `_int_env` is impossible
rather than merely untidy — and why the ~15-line fork below is scheduled, not permanent.)

**Config is ENV-ONLY**, consistent with `#34`/ADR-0005: API-infra knobs (bind/port/tokens/db) stay
out of `GENERAL_KNOBS`. Values are bounded and a bad one is LOUD (`SystemExit`, the
`guard_bind`/`guard_memory` precedent) — a control you cannot read is a failure, not a suggestion.

Unlike the run quota (a fairness policy → default off), backoff defaults **ON**: it is an
authorization-adjacent security control, so deny-by-default applies.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from mosaera_memory import LOGIN_BACKOFF_EXP_CAP

_DEFAULT_THRESHOLD = 5  # failures before any backoff applies (0 disables the control)
_DEFAULT_BASE_SECONDS = 30  # the first lock, doubling from there
_DEFAULT_MAX_SECONDS = 900  # 15 min ceiling per lock
_DEFAULT_RESET_SECONDS = 3600  # idle this long and the streak starts over
_DEFAULT_VERIFY_SLOTS = 8  # concurrent scrypt verifications allowed
_MAX_SANE = 100_000


class LoginBackoffConfig(NamedTuple):
    """Resolved env-only backoff policy. ``threshold == 0`` disables the control entirely."""

    threshold: int
    base_seconds: int
    max_seconds: int
    reset_seconds: int

    @property
    def enabled(self) -> bool:
        return self.threshold > 0


def _int_env(
    name: str, default: int, *, unit: str, minimum: int = 0, maximum: int = _MAX_SANE
) -> int:
    """Parse a bounded int from the environment, or exit loudly.

    Deliberately not lenient: silently falling back to the default on a typo would run the control
    at a setting the operator does not believe is in force (ADR-0035's silently-wrong-config class).

    Forked from `ratelimit.py`'s near-identical helper for two reasons — that module imports
    `auth.py`, so importing back from it is a circular import; and its message picks the unit via
    `'RATE' in name`, so it would tell an operator setting a backoff knob to "expect a whole number
    of runs per day". ADR-0051 files the `envconfig.py` extraction that retires this fork.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"invalid {name}={raw!r} — expected a whole number of {unit}.") from None
    if not minimum <= value <= maximum:
        raise SystemExit(f"invalid {name}={value} — must be between {minimum} and {maximum}.")
    return value


def load_backoff_config() -> LoginBackoffConfig:
    """Read the env-only backoff policy, refusing an incoherent one."""
    config = LoginBackoffConfig(
        threshold=_int_env("MOSAERA_LOGIN_BACKOFF_THRESHOLD", _DEFAULT_THRESHOLD, unit="failures"),
        base_seconds=_int_env(
            "MOSAERA_LOGIN_BACKOFF_BASE_SECONDS", _DEFAULT_BASE_SECONDS, unit="seconds", minimum=1
        ),
        max_seconds=_int_env(
            "MOSAERA_LOGIN_BACKOFF_MAX_SECONDS", _DEFAULT_MAX_SECONDS, unit="seconds", minimum=1
        ),
        reset_seconds=_int_env(
            "MOSAERA_LOGIN_BACKOFF_RESET_SECONDS", _DEFAULT_RESET_SECONDS, unit="seconds", minimum=1
        ),
    )
    # A cross-field invariant that per-value range checks cannot catch, and whose failure is
    # SILENT: if the idle-reset window is no longer than the longest lock, then by the time any
    # lock expires the reset window has ALWAYS also elapsed — so the counter resets to 1 on every
    # post-lock attempt and the escalation never escalates. The operator would see a permanent
    # first-tier backoff and no error at all.
    if config.enabled and config.reset_seconds <= config.max_seconds:
        raise SystemExit(
            f"invalid login backoff: MOSAERA_LOGIN_BACKOFF_RESET_SECONDS "
            f"({config.reset_seconds}) must be GREATER than MOSAERA_LOGIN_BACKOFF_MAX_SECONDS "
            f"({config.max_seconds}).\nOtherwise the idle-reset always fires before a lock can "
            "escalate, silently pinning the backoff at its first tier."
        )
    return config


def backoff_seconds(attempts: int, config: LoginBackoffConfig) -> int:
    """How long a subject with ``attempts`` spent attempts must wait. 0 below the threshold.

    A MIRROR of the schedule inside ``AuthMixin.claim_login_attempt``'s SQL, which is the
    authority (it has to be — the predicate must live in the ``WHERE`` for the claim to be atomic).
    This copy exists ONLY to render ``Retry-After``. The two are pinned together by a parametrized
    test; ``LOGIN_BACKOFF_EXP_CAP`` is imported rather than redeclared so the clamp cannot drift.
    """
    if not config.enabled or attempts < config.threshold:
        return 0
    exponent = min(LOGIN_BACKOFF_EXP_CAP, attempts - config.threshold)
    return int(min(config.max_seconds, config.base_seconds * (2**exponent)))


# --- concurrency bound on password verification ---------------------------------------------
#
# `auth_login` is a sync `def`, so FastAPI runs it in anyio's threadpool — ~40 workers, SHARED with
# every other sync endpoint. Each scrypt verification is ~130ms and ~16MiB (N=2^14, r=8), so a
# login flood saturates every core and ~670MB of RSS, stalling the whole API rather than just
# login. Equalizing the unknown-username timing (ADR-0051) means unknown usernames now cost a full
# verification too, which removes the one-request recon step that used to precede such a flood —
# the ceiling is unchanged (a known username always bought 130ms/req) but the precondition is gone.
#
# So: a NON-BLOCKING gate. On contention we refuse (503) rather than queue — queueing would hold a
# worker, which is what "never block the interactive path" forbids and is itself the DoS. A flood
# thus fails fast on one endpoint instead of melting the box.
_VERIFY_SLOTS = _int_env(
    "MOSAERA_LOGIN_VERIFY_SLOTS", _DEFAULT_VERIFY_SLOTS, unit="slots", minimum=1
)
_verify_gate = threading.Semaphore(_VERIFY_SLOTS)


@contextmanager
def verify_slot() -> Iterator[bool]:
    """Hold a verification slot for the block, or yield False when all are busy.

    Never blocks: ``acquire(blocking=False)``. The caller must refuse (503) on False rather than
    proceed — verifying anyway would defeat the bound entirely.
    """
    acquired = _verify_gate.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            _verify_gate.release()


__all__ = [
    "LoginBackoffConfig",
    "backoff_seconds",
    "load_backoff_config",
    "verify_slot",
]
