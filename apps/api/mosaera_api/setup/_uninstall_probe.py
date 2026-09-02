"""What a machine actually HAS of ours — the questions `uninstall.plan` asks before it offers a row.

Split from `uninstall.py` at the god-file ceiling, on the seam the module already had: deciding
whether a thing EXISTS is a different question from deciding whether to remove it, and a different
one again from carrying that out. Every function here is a probe — it asks the daemon or reads a
file and answers yes or no. `uninstall` re-exports them, so existing imports and the tests that
stub these predicates keep working unchanged.

Why probes at all: the three rows below `plan`'s recorded-install check used to be appended
unconditionally, under a screen that says "Only what this wizard installed is listed". A run that
stopped at the prerequisites screen was offered to stop a database it never started and delete
project data that had never existed.
"""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_core.config import Settings

#: What the wizard itself writes into `settings.json`. `setup_steps_acked` is deliberately absent —
#: the DASHBOARD writes that one, and the whole point of this list is the difference.
OUR_SETTINGS_KEYS = ("setup_installed", "setup_progress")

#: And into `.env`. Everything else in that file belongs to whoever put it there.
OUR_ENV_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "MOSAERA_DB_URL",
    # Written by the port-conflict repair, so it belongs here for the same reason the URL does:
    # a value this wizard chose is a value this wizard has to be able to take back. Left out, an
    # operator who moved the port once would carry that number through every later install of
    # theirs, including onto a machine where the original port was free all along.
    "MOSAERA_DB_PORT",
    "MOSAERA_DB_BIND_HOST",
    "MOSAERA_API_HOST",
    "MOSAERA_API_PORT",
    "MOSAERA_API_TOKEN",
)


def _compose_argv(settings: Settings, repo_root: Path, project: str, *, volumes: bool) -> list[str]:
    """Teardown, scoped to THIS install.

    `--project-directory` is the whole safety property: without it Compose derives the project from
    the compose file's own parent directory, so `down --volumes` from any checkout erased whichever
    database happened to answer to the shared name. With it, this command can only ever remove the
    container, network and volume carrying this directory's project prefix.
    """
    from mosaera_api.setup.steps import compose_argv

    rest = ("down", "--volumes") if volumes else ("down",)
    return compose_argv(settings.docker_bin, repo_root, *rest, project=project or None)


def data_volume(docker_bin: str = "docker", repo_root: Path | None = None) -> str:
    """The volume `--volumes` will erase, spelled the way `docker volume ls` spells it.

    NAMED on the row, because the row is the last thing between an operator and their history. The
    compose project used to be derived from the file's own directory, so a scratch checkout and a
    live install resolved to the SAME volume — and nothing on screen said which one was about to go.

    `config --volumes` lists the compose KEY (`mosaera-pgdata`), not the resolved name
    (`mosaera-5ac386_mosaera-pgdata`) — so the row named something the operator could not find on
    their own machine. The JSON form carries the resolved name; the key is the fallback, because a
    row that names the volume imprecisely still beats a row that names nothing.
    """

    root = repo_root or Path.cwd()
    code, out = _compose_config(docker_bin, root, "--format", "json")
    if code == 0 and out.strip():
        with suppress(ValueError, AttributeError):
            volumes = json.loads(out).get("volumes") or {}
            for key, spec in volumes.items():
                return str((spec or {}).get("name") or key)
    code, out = _compose_config(docker_bin, root, "--volumes")
    return out.strip().splitlines()[0] if code == 0 and out.strip() else ""


def _compose_config(docker_bin: str, root: Path, *flags: str) -> tuple[int, str]:
    from mosaera_api.setup.steps import compose_argv

    try:
        done = subprocess.run(  # noqa: S603 — argv is built here, never from operator text
            compose_argv(docker_bin, root, "config", *flags),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    return done.returncode, done.stdout


def _data_exists(settings: Settings, repo_root: Path | None = None) -> bool:
    """Is there a volume to destroy? A thin predicate on purpose.

    Separate from `data_volume` so that "does the row belong on the list" can be answered — and
    stubbed — without touching the function that works out what the volume is CALLED, which has its
    own behaviour and its own tests.
    """
    return bool(data_volume(settings.docker_bin, repo_root))


def _compose_project_exists(settings: Settings, repo_root: Path | None = None) -> bool:
    """Is there a container of ours to stop? Asked of the daemon, never assumed.

    `docker compose ps -q` prints an id per running service and nothing at all when the project was
    never brought up, which is exactly the distinction the row needs.
    """
    from mosaera_api.setup.steps import compose_argv

    root = repo_root or Path.cwd()
    try:
        done = subprocess.run(  # noqa: S603 — argv is built here, never from operator text
            compose_argv(settings.docker_bin, root, "ps", "-q"),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and bool(done.stdout.strip())


def _our_config_exists(home: Path, repo_root: Path | None = None) -> bool:
    """Did this wizard actually write anything to take back?

    The keys, not the files. Both files may exist and belong entirely to someone else — the
    dashboard writes `settings.json`, and `.env` holds whatever the operator put there — so their
    presence says nothing about whether we have anything to remove.
    """
    root = repo_root or Path.cwd()
    settings_file = home / "settings.json"
    if settings_file.is_file():
        with suppress(OSError, ValueError):
            raw = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and any(k in raw for k in OUR_SETTINGS_KEYS):
                return True
    env = root / ".env"
    if env.is_file():
        with suppress(OSError):
            text = env.read_text(encoding="utf-8")
            if any(f"{k}=" in text for k in OUR_ENV_KEYS):
                return True
    return False


#: uv's caches and managed interpreters. NOT the two binaries `install.sh` put on PATH — these are
#: SHARED with every other uv project on the machine, which is why they are their own row and are
#: never ticked by default. Measured on a developer box: ~1 GB of cache and ~116 MB of downloaded
#: CPython, none of which the previous uninstall touched.
def uv_shared_paths() -> list[Path]:
    """uv's shared trees that actually exist, in the order a human would name them."""
    home = Path.home()
    candidates = [
        Path(os.environ.get("UV_CACHE_DIR") or home / ".cache" / "uv"),
        home / ".local" / "share" / "uv",
        home / ".config" / "uv",
    ]
    return [p for p in candidates if p.exists()]


def bytes_under(paths: list[Path]) -> int:
    """Total size, best effort. A row that says "several GB" when it means 40 MB is a row nobody
    can act on, and the number is the whole reason this is offered separately."""
    total = 0
    for path in paths:
        with suppress(OSError):
            for entry in path.rglob("*"):
                with suppress(OSError):
                    if entry.is_file() and not entry.is_symlink():
                        total += entry.stat().st_size
    return total


def human_size(count: int) -> str:
    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit != "GB" else f"{value:.1f} GB"
        value /= 1024
    return f"{value:.1f} GB"


def colima_profile_exists(profile: str = "default") -> bool:
    """Did this machine end up with a Colima VM? Asked of colima, not of the filesystem.

    `colima list` prints a row per profile and exits non-zero when colima is not installed at all,
    so one call answers both "is it here" and "is there anything to tear down".
    """
    try:
        done = subprocess.run(
            ["colima", "list", "--json"],  # noqa: S607 — resolved via PATH, as every other probe
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and profile in done.stdout
