"""The bind guard: what an exposed API must have before it is allowed to start.

Extracted from ``app.py`` when the two clauses #123/#124 added took that module past the 500-line
ceiling. It is a cohesive unit on its own — everything here answers one question, "may this host be
bound", and the helpers exist only to work out which host the server was actually told to use.

Imported back into ``app.py`` so ``mosaera_api.app.guard_bind`` and the private helpers keep
resolving: this is a file split, not an interface change, and ``__main__`` + the tests reach the
guard through the paths they always did.
"""

from __future__ import annotations

import os
import sys

from mosaera_api.auth import COOKIE_SECURE_FALSE, COOKIE_SECURE_TRUE

# NOTE: "" is deliberately NOT loopback — uvicorn.run(host="") binds ALL
# interfaces (INADDR_ANY). Treating an empty host as loopback-safe would let a
# blank MOSAERA_API_HOST expose the API unauthenticated; callers normalize a
# blank value to 127.0.0.1 before this guard, and the guard rejects "" on its own.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _usable_secret_key(raw: str) -> bool:
    """Whether this value can actually encrypt, not merely whether it is present.

    Red-team round 1: presence alone let `MOSAERA_SECRET_KEY=xxxx…` satisfy the #123 clause, so the
    guard reported a precondition it had not established — `encrypt_secret` then raised
    `SecretKeyError` at the first credential write, days later and far from the cause. A guard at
    the door checks the thing it is guarding.
    """
    key = raw.strip()
    if not key:
        return False
    try:
        from cryptography.fernet import Fernet

        Fernet(key.encode())
    except Exception:
        return False
    return True


def guard_bind(host: str, token: str, sandbox: str = "docker") -> None:
    """Refuse to expose the API unsafely on a public interface.

    The API executes code in a sandbox and holds repository tokens. On a
    non-loopback bind we require (a) ``MOSAERA_API_TOKEN`` so it isn't
    unauthenticated, (b) the Docker sandbox — the ``subprocess`` backend runs
    test code on the HOST (not contained), which must never be reachable off-box,
    (c) ``MOSAERA_SECRET_KEY``, without which every stored credential is plaintext
    at rest (#123), and (d) a DECLARED ``MOSAERA_COOKIE_SECURE``, so an exposed
    deployment states its TLS posture rather than inheriting a LAN-shaped default
    (#124). Loopback binds (the default) need none of them.

    (c) and (d) are the "fails closed when exposed" arc: every default here was
    correct for the author's laptop, and the operator population changed the day
    the public installer shipped. They read the environment directly rather than
    taking parameters — see the note at each clause.

    Called both from ``main()`` (the ``mosaera-api`` CLI) AND from ``create_app``
    so a ``--factory``/gunicorn entrypoint that skips ``main`` can't skip the
    guard. The ``create_app`` call passes ``_cli_bind_host() or MOSAERA_API_HOST``,
    and ``_cli_bind_host`` reads the server's own ``--host``/``--bind``/``-b``/
    ``UVICORN_HOST`` — so a host declared ONLY on the command line is visible here
    and setting ``MOSAERA_API_HOST`` to match is no longer required (ADR-0042).
    This docstring said the opposite until 2026-08-20 (see
    ``docs/audits/adr-corpus-review-2026-08-18.md``);
    it understated the guard and sent operators after a step the caller already does.
    RESIDUAL, still true: a gunicorn config-FILE ``bind`` (a ``-c`` Python file) is
    invisible to ``_cli_bind_host`` — on that path DO set ``MOSAERA_API_HOST``.
    """
    if host in _LOOPBACK_HOSTS:
        return
    if not token.strip():
        raise SystemExit(
            f"refusing to bind the API to a public interface ({host}) without "
            "authentication.\nThe API runs code and holds repository tokens — "
            "exposing it unauthenticated is unsafe.\nEither bind to 127.0.0.1 "
            "(the default) or set MOSAERA_API_TOKEN to require a bearer token."
        )
    if sandbox.strip().lower() == "subprocess":
        raise SystemExit(
            f"refusing a public bind ({host}) with the 'subprocess' sandbox — it "
            "runs untrusted test code on the HOST with no containment.\nUse the "
            "Docker sandbox (MOSAERA_SANDBOX=docker) for any exposed deployment."
        )
    # #123. The GitLab PAT, the OAuth client secret, the GitHub App private key and every BYOM
    # provider key are PLAINTEXT at rest without this (`0600` is a permission, not encryption —
    # ADR-0039 made encryption opt-in, and an exposed box is exactly the population that cannot
    # afford the opt-out). Read from the environment HERE rather than taken as a parameter: a
    # clause a caller must remember to pass is a clause a caller can forget, and this guard has
    # two entrypoints precisely because one of them was once skippable.
    if not _usable_secret_key(os.environ.get("MOSAERA_SECRET_KEY", "")):
        raise SystemExit(
            f"refusing a public bind ({host}) with secrets unencrypted at rest.\n"
            "Repository tokens and provider keys are stored in plaintext without a USABLE "
            "MOSAERA_SECRET_KEY — a 0600 file mode is a permission, not encryption, and a\n"
            "value that is not a valid Fernet key encrypts nothing.\n"
            "Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            "and set MOSAERA_SECRET_KEY, or bind to 127.0.0.1 (the default).\n"
            "NEW REQUIREMENT (ADR-0126): an exposed instance that started before 2026-08-31 "
            "will not have this set, and stops here on upgrade until it does."
        )
    # #124. NOT "force Secure on a public bind": a browser will not send a `Secure` cookie over
    # http://, so forcing it silently breaks every plain-http LAN deploy and the operator's fix
    # under pressure is to turn the protection off. Refuse while the posture is UNDECLARED
    # instead — the control refuses to act and says why, which is the Unsuppressible-Ask shape.
    # DECLARED, not enabled: an explicit MOSAERA_COOKIE_SECURE=0 is a valid, informed answer.
    declared = os.environ.get("MOSAERA_COOKIE_SECURE")
    if declared is None or declared.strip().lower() not in (
        *COOKIE_SECURE_TRUE,
        *COOKIE_SECURE_FALSE,
    ):
        raise SystemExit(
            f"refusing a public bind ({host}) without a readable TLS posture"
            + (f" (got {declared!r})" if declared else "")
            + ".\n"
            "The session cookie's Secure flag defaults to off, which is correct for "
            "plain-http LAN and wrong behind TLS — so an exposed bind must say which.\n"
            "Set MOSAERA_COOKIE_SECURE=1 when serving over HTTPS (a reverse proxy "
            "counts), or MOSAERA_COOKIE_SECURE=0 to accept a plain-http deployment.\n"
            "NEW REQUIREMENT (ADR-0126): an exposed instance that started before 2026-08-31 "
            "will not have this set, and stops here on upgrade until it does."
        )


def _host_from_bind(bind: str) -> str:
    """The host part of a gunicorn ``--bind`` value (``0.0.0.0:8000`` → ``0.0.0.0``,
    ``[::]:8000`` → ``::``). A unix-socket/fd bind is not a network bind → loopback."""
    b = bind.strip()
    if b.startswith(("unix:", "fd://")):
        return "127.0.0.1"
    if b.startswith("[") and "]" in b:  # IPv6 [host]:port
        return b[1 : b.index("]")]
    return b.rsplit(":", 1)[0] if ":" in b else b


def _declared_bind_hosts() -> list[str]:
    """Every bind host the SERVER process was told to use — ALL ``--host``/``--bind``/``-b`` flags
    in argv, PLUS the ``UVICORN_HOST`` env var (uvicorn's CLI has ``auto_envvar_prefix="UVICORN"``,
    so ``UVICORN_HOST`` sets ``--host`` with no trace in argv — the standard container pattern)."""
    hosts: list[str] = []
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--host" and i + 1 < len(argv):
            hosts.append(argv[i + 1])
        elif arg.startswith("--host="):
            hosts.append(arg.split("=", 1)[1])
        elif arg in ("--bind", "-b") and i + 1 < len(argv):
            hosts.append(_host_from_bind(argv[i + 1]))
        elif arg.startswith("--bind="):
            hosts.append(_host_from_bind(arg.split("=", 1)[1]))
    env_host = os.environ.get("UVICORN_HOST", "").strip()
    if env_host:
        hosts.append(env_host)
    return hosts


def _cli_bind_host() -> str | None:
    """The MOST-EXPOSED bind host the server was told to use, or None when it declares none.

    ``create_app`` reads the host from ``MOSAERA_API_HOST`` for ``guard_bind``, but a
    ``--factory``/gunicorn/env entrypoint binds via its OWN ``--host``/``--bind``/``UVICORN_HOST``,
    invisible to that env var. So ``uvicorn app:create_app --factory --host 0.0.0.0`` (or
    ``UVICORN_HOST=0.0.0.0``) with no ``MOSAERA_API_HOST`` used to sail past the guard while
    binding all interfaces. We return the most-exposed declared host — a non-loopback one if ANY
    flag/env exposes the API — so a loopback ``--host`` can't mask a second ``-b 0.0.0.0``. The
    official ``mosaera-api`` entrypoint binds programmatically (no such flag) → None → the guard
    falls back to ``MOSAERA_API_HOST``. RESIDUAL: a gunicorn config-FILE ``bind`` (in a ``-c``
    Python file) is still invisible here — an operator on that path must set ``MOSAERA_API_HOST``
    or ``MOSAERA_API_TOKEN``."""
    hosts = _declared_bind_hosts()
    for host in hosts:
        if host and host not in _LOOPBACK_HOSTS:
            return host  # any exposed bind → guard on it
    return hosts[0] if hosts else None
