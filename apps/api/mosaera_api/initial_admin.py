"""Seeding the first administrator from the environment, for a deploy with no terminal.

WHAT THIS USED TO BE. `setup_gate.py` implemented ADR-0040: on a fresh instance it minted a
one-time SETUP TOKEN, stored its SHA-256, printed the plaintext once to the startup logs, and
`POST /auth/setup` required it before creating the first admin. That closed the unauthenticated
first-admin race (CWE-1188, the Portainer `CVE-2026-55761` class) — a real fix for a real hole.

WHY THE TOKEN IS GONE (ADR-0116). The hole existed because an UNAUTHENTICATED endpoint had to
exist: a browser had to be able to create the first account. Setup now happens in a terminal, and
`mosaera-setup` creates the administrator against the database directly, so there is no such
endpoint any more. Running the command IS the proof the token stood in for — you are already on the
machine — and CWE-1188 is closed by construction rather than guarded. `POST /auth/users` continues
to refuse the FIRST account, so no route mints an admin on an empty instance.

WHAT SURVIVES, AND WHY. `MOSAERA_INITIAL_ADMIN_USER` / `…_PASSWORD` seed an admin directly, with
zero open window (the Django/GitLab pre-provision model). It is the path for an orchestrated deploy
that never sees a terminal, and it is not a gate: it either creates the account or says why it did
not. The accepted cost, recorded in ADR-0116, is that an empty database has no BROWSER way in.
"""

from __future__ import annotations

import os
import sys
from typing import Any


def _validate(user: str, pw: str) -> str:
    from mosaera_api.auth import validate_credentials

    return validate_credentials(user, pw) or ""


def seed_initial_admin(history: Any) -> bool:
    """Create the first admin from `MOSAERA_INITIAL_ADMIN_*`, if both are set and nothing exists.

    Returns whether an account was created. Every refusal names its own cause on stderr: silence
    here means an operator watching an orchestrated deploy come up with no way in, and no idea why.
    Safe to call once per worker at startup, and a no-op on a store with no account tier.
    """
    if history is None:
        return False
    counter = getattr(history, "count_users", None)
    creator = getattr(history, "create_user", None)
    if counter is None or creator is None:
        return False
    user = os.environ.get("MOSAERA_INITIAL_ADMIN_USER", "").strip()
    pw = os.environ.get("MOSAERA_INITIAL_ADMIN_PASSWORD", "")
    if not (user and pw):
        return False

    try:
        if counter() > 0:
            return False  # an administrator already exists; this is not an error
    except Exception:
        # A degraded store is `guard_memory`'s problem, and it fails the boot. Never write an
        # account against a database that cannot answer how many it already has.
        return False

    err = _validate(user, pw)
    if err:
        print(
            f"  WARNING: MOSAERA_INITIAL_ADMIN_* ignored ({err}). No administrator was created — "
            "run `uv run mosaera-setup` on the host, or fix the variables and restart.",
            file=sys.stderr,
        )
        return False

    from mosaera_api.auth import hash_password

    try:
        creator(user, hash_password(pw), is_admin=True)
    except Exception as exc:
        print(
            f"  WARNING: could not seed the initial admin ({exc}). Run `uv run mosaera-setup` on "
            "the host to create one.",
            file=sys.stderr,
        )
        return False
    print(f"  Seeded initial admin '{user}' from MOSAERA_INITIAL_ADMIN_*.", file=sys.stderr)
    return True
