"""The access step's pure logic: what "who can reach this" means in `.env` terms.

Split out of `steps.py` when the #123/#124 clauses (ADR-0126) took that module past the 500-line
ceiling. These two functions are a cohesive pair — one decides whether a network bind may be
OFFERED, the other computes what choosing it WRITES — and both are pure, which is why the wizard's
idempotence is testable without a terminal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from mosaera_core.config import Settings

#: The bind that means "anything on the network", as it appears in `.env`.
_ALL_INTERFACES = "0.0.0.0"  # noqa: S104


def access_env(
    *,
    public: bool,
    port: int,
    current: Mapping[str, str],
    make_token: Callable[[], str],
    secure: bool = False,
    make_secret_key: Callable[[], str] | None = None,
) -> dict[str, str]:
    """What the access answer means in `.env` terms — computed against what is ALREADY there.

    Idempotence lives here. The first version minted a fresh `MOSAERA_API_TOKEN` on every run and
    rewrote the live one, silently invalidating every credential already issued to a client, while
    the screen reported success. So: an existing token is KEPT, a new one is minted only when there
    is none, and a value that already matches is not rewritten at all.

    Going the other way matters too. Choosing "this machine only" used to leave the old token active
    in `.env` while the screen said the instance was private; an empty value now clears it.
    """
    host = "127.0.0.1" if not public else _ALL_INTERFACES
    out: dict[str, str] = {}
    if current.get("MOSAERA_API_HOST") != host:
        out["MOSAERA_API_HOST"] = host
    if current.get("MOSAERA_API_PORT") != str(port):
        out["MOSAERA_API_PORT"] = str(port)
    if public:
        # All three are `guard_bind` preconditions (#123/#124, ADR-0126): writing a bind the
        # server then refuses to boot on is the failure this function exists to avoid.
        if not current.get("MOSAERA_API_TOKEN"):
            out["MOSAERA_API_TOKEN"] = make_token()
        # Minted only when ABSENT — replacing a key strands every secret encrypted under the old.
        if not current.get("MOSAERA_SECRET_KEY", "").strip() and make_secret_key is not None:
            out["MOSAERA_SECRET_KEY"] = make_secret_key()
        # Written when it DIFFERS, covering both cases that matter: absent (what the guard
        # refuses) and stale. Unchanged, left alone — this function's idempotence rule.
        want = "1" if secure else "0"
        if current.get("MOSAERA_COOKIE_SECURE") != want:
            out["MOSAERA_COOKIE_SECURE"] = want
    elif current.get("MOSAERA_API_TOKEN"):
        out["MOSAERA_API_TOKEN"] = ""
    return out


def public_bind_blocked_by(settings: Settings, current: Mapping[str, str] | None = None) -> str:
    """Why this instance may NOT be exposed, or "".

    `guard_bind` refuses a public bind on the subprocess sandbox as well as on a missing token —
    it runs the target repository's test code on the HOST. Offering the choice without checking
    both halves means writing a configuration the server then refuses to boot on.
    """
    if settings.sandbox_backend.strip().lower() == "subprocess":
        return "the subprocess sandbox runs repository code on this host, so it may not be exposed"
    # Red-team round 3, and the same defect class as the guard's own: PRESENCE is not USABILITY.
    # `access_env` mints a key only when one is ABSENT — correctly, since replacing it would strand
    # whatever it encrypted — so an install carrying a present-but-unusable value would be offered
    # a network bind, be told it succeeded, and then meet a server that refuses to start on it.
    # That is exactly the outcome this function exists to prevent, one clause later.
    from mosaera_api.bind_guard import _usable_secret_key

    key = (current or {}).get("MOSAERA_SECRET_KEY", "")
    if key.strip() and not _usable_secret_key(key):
        return (
            "MOSAERA_SECRET_KEY in .env is not a valid Fernet key, so stored credentials "
            "cannot be encrypted — fix or remove it and run setup again"
        )
    return ""
