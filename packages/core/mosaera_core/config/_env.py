"""Environment/.env loading + Docker CLI resolution (host-facing I/O helpers)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from functools import lru_cache
from pathlib import Path


def load_env(start: Path | None = None) -> None:
    """Load a repo-root ``.env`` into ``os.environ`` (existing vars win).

    Walks up from ``start`` (or cwd) to find the nearest ``.env`` beside a
    ``pyproject.toml``. Lines are ``KEY=VALUE``; ``#`` comments and blanks are
    ignored, surrounding quotes stripped. Real environment variables always take
    precedence, so ``.env`` is a convenience, not an override.
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        env_file = directory / ".env"
        if env_file.is_file():
            _apply_env_file(env_file)
            return
        if (directory / "pyproject.toml").is_file():
            if env_file.is_file():
                _apply_env_file(env_file)
            return


def _apply_env_file(env_file: Path) -> None:
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@lru_cache(maxsize=8)
def undeclared_bundled_db() -> str | None:
    """The bundled Postgres' URL when it is REACHABLE but nobody declared it, else None.

    The bundled database's URL is composed in exactly one place — ``scripts/dev-up.sh``, which
    exports it into the process ``make up`` launches. It is not in ``.env`` (shipped commented
    out) and ``Settings.from_env`` reads no fallback, so every other entrypoint reports "no
    database configured" while Postgres is running and healthy on the published port. That is a
    genuinely confusing state: the operator ran ``make db-migrate`` successfully a moment ago.

    This does NOT introduce a default — ``Settings.db_url`` is untouched, so the API's
    refuse-to-start-on-unreachable-DB contract (ADR-0035) is unchanged. It only lets a CLI say
    "it's right there, and here is the line that declares it" instead of "nothing to do".
    """
    if os.environ.get("MOSAERA_DB_URL") or os.environ.get("MOSAERA_TEST_DB_URL"):
        return None
    port = os.environ.get("MOSAERA_DB_PORT", "5432")
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            pass
    except (OSError, ValueError):
        return None
    return f"postgresql://mosaera:mosaera@localhost:{port}/mosaera"


def _cli_works(name: str) -> bool:
    """Whether ``name --version`` runs — distinguishes a real CLI from the
    non-functional Docker Desktop WSL shim (present on PATH but errors unless
    integration is enabled). Client-only, so no daemon needed; cached per process."""
    if not shutil.which(name):
        return False
    try:
        return (
            subprocess.run(  # noqa: S603 — fixed argv, no shell
                [name, "--version"], capture_output=True, timeout=5
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_docker_bin(explicit: str | None = None) -> str:
    """Pick a working Docker CLI. An explicit non-default value is honored as-is;
    otherwise prefer a functioning ``docker`` and fall back to ``docker.exe``
    (the Windows CLI used from WSL when native integration is off).

    DELIBERATELY NOT `Platform.wsl`. This probes — it asks each candidate whether it RUNS — which
    is strictly stronger than asking what kind of machine this is: it catches a Desktop shim that
    is on PATH but errors because integration is off, a state no platform bit can see. The new
    `wsl` flag exists to choose the right ADVICE; this chooses a working binary, and the two
    questions must not be collapsed —
    `test_resolve_docker_bin_probes_rather_than_asking_the_platform` pins that."""
    if explicit and explicit != "docker":
        return explicit
    if _cli_works("docker"):
        return "docker"
    if _cli_works("docker.exe"):
        return "docker.exe"
    return explicit or "docker"
