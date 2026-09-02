"""Removing Mosaera again, and only what is ours to remove.

THE RULE THIS FILE EXISTS FOR: **never remove something we did not install.** Most machines already
had Docker, or git, or Node, long before Mosaera arrived; taking those away because we happen to
need them would break unrelated work. "Present" and "we put it there" are indistinguishable after
the fact, so the wizard records each install as it happens (`setup_installed` in `settings.json`)
and only what is recorded is ever offered.

The second rule: **say what is irreversible, before it happens.** The database volume holds every
project, every run and every piece of history the instance ever produced. There is no undo, and a
list of tick-boxes is not consent — the caller confirms separately, on a screen whose cursor starts
on Cancel.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mosaera_core.config import Settings
from mosaera_core.prereqs import PREREQS
from mosaera_core.sandbox._base import docker_available
from mosaera_core.settings_store import read_settings, write_settings

# The probes live next door — split at the god-file ceiling, re-exported so `plan` still resolves
# them from THIS module's globals, which is what the tests stub.
from mosaera_api.setup._uninstall_probe import (
    OUR_ENV_KEYS,
    OUR_SETTINGS_KEYS,
    _compose_argv,
    _compose_project_exists,
    _data_exists,
    _our_config_exists,
    bytes_under,
    colima_profile_exists,
    data_volume,
    human_size,
    uv_shared_paths,
)
from mosaera_api.setup.explain import explain
from mosaera_api.setup.ui import DIM, DONE, FAILED, RUNNING

#: What a negative runner status means, in words. Mirrors `steps.FAILURE_REASON`, imported lazily
#: there to keep this module free of the terminal layer.
_FAILURE = {-1: "could not start — is Docker installed?", -2: "timed out", -3: "cancelled"}


class _Tail:
    """The last line a command printed, kept because the status alone names no cause."""

    line = ""


def _tee(on_line: object, tail: _Tail) -> object:
    def _write(line: str) -> None:
        if line.strip():
            tail.line = line
        on_line(line)  # type: ignore[operator]

    return _write


def _cause(line: str, code: int) -> str:
    """The command's last line in words, or the bare status if it said nothing."""
    return explain(line).summary if line.strip() else f"exit {code}"


def record_install(home: Path, key: str) -> None:
    """Remember that WE installed `key`. Idempotent."""
    current = [k for k in read_settings(home).get("setup_installed", []) if isinstance(k, str)]
    if key not in current:
        write_settings(home, {"setup_installed": sorted([*current, key])})


def installed_by_setup(home: Path) -> list[str]:
    raw = read_settings(home).get("setup_installed")
    return [k for k in raw if isinstance(k, str)] if isinstance(raw, list) else []


@dataclass(frozen=True)
class Removable:
    """One thing that can be taken away, and what taking it away costs."""

    key: str
    label: str
    detail: str
    #: True when there is no way back. These are confirmed separately, never by a tick alone.
    destructive: bool = False


def _data_row(settings: Settings, repo_root: Path | None = None) -> Removable:
    """The destructive row — and it must not promise what it cannot do.

    `docker compose down --volumes` erases the BUNDLED volume. Pointed at an external Postgres —
    the case the "different database URL" option exists for — it removes nothing at all, while the
    row said "every project, run, backlog item and piece of history. There is no undo". A row that
    claims to destroy your history and then does nothing is worse than one that admits it cannot.
    """
    url = settings.db_url or ""
    external = bool(url) and "localhost" not in url and "127.0.0.1" not in url
    volume = data_volume(settings.docker_bin, repo_root)
    named = f" (volume {volume})" if volume else ""
    if external:
        return Removable(
            key="data",
            label="Delete all project data",
            detail=(
                "unavailable — your database is external, so remove it there. "
                "Selecting this deletes only the bundled volume, which is empty"
            ),
            destructive=True,
        )
    return Removable(
        key="data",
        label="Delete all project data",
        detail=f"every project, run, backlog item and piece of history{named} — no undo",
        destructive=True,
    )


def plan(settings: Settings, home: Path, repo_root: Path | None = None) -> list[Removable]:
    """Everything this machine could give back, most reversible first.

    Ordered deliberately: the harmless items are at the top, so an operator scanning the list meets
    "stop the database" before they meet "delete every run you have ever done".
    """
    out = []
    # Only when a server WE started is still alive. Without this row, "leave a clean machine" would
    # be false the moment the wizard launches one — and the pid is checked rather than assumed, so a
    # server the operator started themselves is never offered.
    from mosaera_api.setup.launch import our_pid

    if our_pid(home, repo_root):
        out.append(
            Removable(
                key="server",
                label="Stop the Mosaera server",
                detail="the API this wizard started; your data and configuration are untouched",
            )
        )
    # ONLY WHAT EXISTS. These three used to be appended unconditionally, directly beneath a screen
    # that says "Only what this wizard installed is listed; anything already here is left alone" —
    # so a run that got as far as the prerequisites screen and stopped was offered to stop a
    # database it never started, remove configuration it never wrote, and delete project data that
    # has never existed. The rows below this one were already careful; these were not, and the
    # header made a claim the list underneath it contradicted.
    have_docker = docker_available(settings.docker_bin)
    if have_docker and _compose_project_exists(settings, repo_root):
        out.append(
            Removable(
                key="containers",
                label="Stop the database container",
                detail="data is preserved; the wizard can start it again",
            )
        )
    if _our_config_exists(home, repo_root):
        out.append(
            Removable(
                key="config",
                label="Remove configuration",
                detail=(
                    "the keys this wizard wrote to settings.json and .env, including any service "
                    "token — anything else in those files is left alone"
                ),
            )
        )
    if have_docker and _data_exists(settings, repo_root):
        out.append(_data_row(settings, repo_root))
    #: Only what we installed. A prerequisite that was already here is not ours to remove, and is
    #: not offered at all rather than being offered and disabled — an option you may not choose is
    #: still a thing the operator has to read and reason about.
    ours = set(installed_by_setup(home))
    # Image TAGS are global to the daemon, not scoped to a project or a directory — so this row was
    # offering to delete the images another checkout's running instance depends on, and Ctrl-X
    # pre-ticked it. Same rule as the prerequisites: only what we recorded building.
    if "images" in ours:
        out.append(
            Removable(
                key="images",
                label="Remove the sandbox images",
                detail="built by this wizard; several GB, rebuildable",
            )
        )
    if "uv" in ours:
        # The one thing installed WITHOUT being asked — `install.sh` cannot prompt (ADR-0117 §2) —
        # so it is also the one an operator is most entitled to take back. Unlike a system package
        # this is ours to remove: two files, in the operator's own home, that we put there.
        out.append(
            Removable(
                key="uv",
                label="Remove uv",
                detail="installed by the Mosaera installer; other projects may also use it",
            )
        )
    for prereq in PREREQS:
        if prereq.key in ours and prereq.key != "compose":
            # NAME WHAT IS ACTUALLY THERE. On macOS the Docker gap is closed by installing Colima
            # (ADR-0118), so a row reading "Uninstall Docker" would offer to remove a product this
            # machine does not have — and, worse, would be handed back to the operator as something
            # to do themselves when it is in fact ours to tear down.
            if prereq.key == "docker" and colima_profile_exists():
                out.append(
                    Removable(
                        key="colima",
                        label="Remove Colima",
                        detail="the VM, its images and volumes, and the Compose plugin link",
                        destructive=True,
                    )
                )
                continue
            out.append(
                Removable(
                    key=f"prereq:{prereq.key}",
                    label=f"Uninstall {prereq.label}",
                    detail=f"installed by this wizard — {prereq.purpose}",
                )
            )

    # SHARED, so its own row and never a default. `install.sh` bootstrapped uv without asking
    # (ADR-0117 §2), and uv then filled ~1 GB of cache and downloaded its own CPython — none of
    # which the two-binary removal above touched. Every other uv project on this machine uses the
    # same trees, which is why the size is stated and the choice is left to the operator.
    if "uv" in ours and (shared := uv_shared_paths()):
        out.append(
            Removable(
                key="uv_cache",
                label=f"Remove uv's shared caches ({human_size(bytes_under(shared))})",
                detail=(
                    "downloads and interpreters uv reuses — other uv projects will re-fetch them"
                ),
            )
        )

    # LAST, and it is the one thing that was always missing. Without it "stop and remove" left the
    # clone and its virtualenv — the largest single item on disk — sitting exactly where they were.
    out.append(
        Removable(
            key="install",
            label="Remove Mosaera itself",
            detail=(
                "the installation directory, its virtualenv, and the project data inside it. "
                "The database volume lives in Docker, NOT in this directory, and survives"
            ),
            destructive=True,
        )
    )
    return out


def commands_for(
    key: str, settings: Settings, home: Path, repo_root: Path, project: str = ""
) -> list[list[str]]:
    """The argv list that removes `key`. Empty when nothing external need run.

    `home` and `repo_root` are unused today and kept deliberately: `paths_for` takes the same pair,
    and a caller that had to remember which of the two functions wants roots would get it wrong.
    """
    if key == "server":
        return []  # a signal, not a command — see `perform`
    if key == "containers":
        return [_compose_argv(settings, repo_root, project, volumes=False)]
    if key == "data":
        # `--volumes` is the whole difference between stopping and erasing.
        return [_compose_argv(settings, repo_root, project, volumes=True)]
    if key == "images":
        from mosaera_core.preflight_host import _image_tags

        return [[settings.docker_bin, "image", "rm", "-f", tag] for tag in _image_tags(settings)]
    if key == "uv":
        # Exactly the two files the vendor installer writes, at the destination `install.sh` PASSED
        # it. Never a glob, never a directory: this deletes from the operator's home.
        target = Path(os.environ.get("UV_INSTALL_DIR") or Path.home() / ".local" / "bin")
        return [["rm", "-f", str(target / "uv"), str(target / "uvx")]]
    if key == "uv_cache":
        # The trees named by the probe, and nothing inferred. No globs, no parent directories: this
        # removes from the operator's home and every path here was checked to exist first.
        from mosaera_api.setup._uninstall_probe import uv_shared_paths

        return [["rm", "-rf", *[str(p) for p in uv_shared_paths()]]]
    if key == "colima":
        # `--data` because the default keeps images and volumes, which is not what "remove" means
        # here; `--force` because there is no terminal to answer its confirmation and the operator
        # has already given theirs on the confirm screen.
        #
        # NOT `rm -rf ~/.docker`, which several uninstall guides suggest. That directory holds
        # Docker Desktop's configuration, the operator's contexts and other tools' CLI plugins —
        # only the one symlink ADR-0118 created is ours to take back.
        return [
            ["colima", "delete", "--force", "--data"],
            ["rm", "-rf", str(Path.home() / ".colima"), str(Path.home() / ".lima")],
            ["rm", "-f", str(Path.home() / ".docker" / "cli-plugins" / "docker-compose")],
        ]
    if key == "install":
        # A SIGNAL, like `server`. This one cannot be a command: the process is running FROM the
        # directory it removes, so it is handed to `__main__` to exec after the terminal is
        # restored. See `_hand_off_removal`.
        return []
    if key.startswith("prereq:"):
        return []  # handled by the platform's own remover, which needs a terminal
    return []


def paths_for(key: str, home: Path, repo_root: Path) -> list[Path]:
    """Files this key touches, for the removal to report on. Deliberately explicit: no globs, and no
    recursion into anything we did not create."""
    if key == "config":
        return [home / "settings.json", repo_root / ".env"]
    return []


def remove_our_config(home: Path, repo_root: Path) -> None:
    """Take back what this wizard wrote, and only that.

    IT USED TO `unlink` BOTH FILES WHOLE, under a row that says "settings.json and the .env **this
    wizard wrote**". Neither file is ours. `settings.json` is mostly the dashboard's — provider API
    keys, a GitLab token, role and model bindings, cost modes, every operational knob the Settings
    page manages — and `.env` holds whatever the operator put beside our five lines. An uninstall
    that removes what it installed must not carry those off with it.

    Each file is deleted only when nothing but our own keys was ever in it, so an instance the
    wizard configured and nobody else touched still disappears completely.
    """

    from mosaera_core.settings_store import write_settings

    from mosaera_api.setup.env_file import remove_env_keys

    settings_path = home / "settings.json"
    if settings_path.exists():
        try:
            # The RAW file decides whether anything of theirs is left, not `read_settings` — that
            # filters to the keys this version knows, so a key written by a newer one would look
            # like an empty file and take the whole thing with it.
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            theirs = isinstance(raw, dict) and any(k not in OUR_SETTINGS_KEYS for k in raw)
        except (OSError, ValueError):
            # Unreadable. Removing our keys means rewriting it, and rewriting a file we cannot read
            # is how a transient bad read becomes permanent loss — so leave it exactly as it is.
            theirs = True
        if theirs:
            write_settings(home, dict.fromkeys(OUR_SETTINGS_KEYS))
        else:
            settings_path.unlink(missing_ok=True)
    remove_env_keys(repo_root / ".env", OUR_ENV_KEYS)


def _still_there(key: str, docker_bin: str, project: str) -> str:
    """What the removal claimed to take away and did not. "" when it is genuinely gone."""
    if key == "containers":
        code, out = _docker(
            docker_bin, "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"
        )
        return (
            f"the container is still there (project {project})" if code == 0 and out.strip() else ""
        )
    if key == "data":
        code, out = _docker(
            docker_bin,
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        )
        return f"the volume is still there (project {project})" if code == 0 and out.strip() else ""
    return ""


def _docker(docker_bin: str, *args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 — argv is built here, never from operator text
            [docker_bin, *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    return done.returncode, done.stdout


def summary(selected: list[Removable]) -> str:
    """What is about to happen: the action on its own line, its cost indented beneath.

    One long line per item wrapped mid-sentence and dropped the continuation to column zero, so the
    list stopped looking like a list exactly where it mattered most.
    """
    return "\n".join(
        f"  {'· ' if not r.destructive else '! '}{r.label}\n      [{DIM}]{r.detail}[/]"
        for r in selected
    )


def survives(selected: list[Removable], offered: list[Removable]) -> str:
    """What this selection LEAVES, said before it runs rather than found on the next install.

    "Remove Mosaera itself" used to close with "the machine is left as it was before the install
    command was run". The database volume is a Docker volume — on macOS it is inside the Colima VM,
    nowhere near the install directory — so removing the installation without ticking "Delete all
    project data" left it, and the next install adopted it: a "clean" first run that opened on
    `Accounts: 1` (reported from a live macOS run, 2026-08-30). The bundled password is the static
    compose default, so a surviving volume authenticates against a fresh clone perfectly.

    Nothing is armed here. ADR-0119 §5 — silence is not cleanliness — so the leave-behind is NAMED
    and the operator decides, which is the same rule the result screen already follows.
    """
    keys = {r.key for r in selected}
    if "install" not in keys or "data" in keys:
        return ""
    if not any(r.key == "data" for r in offered):
        return ""
    return (
        "This removes the installation but KEEPS the database volume: your projects, runs and "
        "accounts survive, and a later install will find them and resume rather than start clean. "
        "Tick 'Delete all project data' as well for a machine with nothing of Mosaera left on it."
    )


def perform(
    selected: list[Removable],
    settings: Settings,
    home: Path,
    repo_root: Path,
    on_line: object,
    runner: object,
    on_item: object = None,
) -> list[str]:
    """Carry out the selection. Returns one line per item describing what happened.

    Nothing here is clever. Each item is handled explicitly, failures are reported rather than
    raised, and a prerequisite is never touched — removing a system package needs the operator's own
    terminal, so it is handed back to them instead.

    `on_item(index, state, note)` is called before and after each item, so a caller can show a task
    list instead of a wall of command output. Reporting from HERE rather than from the caller is
    what makes it honest: it advances when the work advances, not when the loop that scheduled it
    does.
    """

    def _report(index: int, state: str, note: str) -> None:
        if on_item is not None:
            on_item(index, state, note)  # type: ignore[operator]

    from mosaera_api.setup.launch import stop as stop_server
    from mosaera_api.setup.steps import compose_project

    # Resolved ONCE, up front. The project name lives in `.env`, and "Remove configuration" deletes
    # `.env` — so every step after it silently retargeted a project that does not exist, and
    # `down --volumes` then "succeeded" against nothing while the real container and volume stayed.
    project = compose_project(repo_root)
    results: list[str] = []
    for n, item in enumerate(selected):
        _report(n, RUNNING, "removing")
        if item.key == "server":
            problem = stop_server(home, repo_root)
            _report(n, FAILED if problem else DONE, "failed" if problem else "stopped")
            results.append(f"{item.label}: {explain(problem).summary if problem else 'done'}")
            continue
        if item.key.startswith("prereq:"):
            _report(n, DONE, "run it yourself")
            results.append(f"{item.label}: remove it with your package manager — see the summary")
            continue
        if item.key == "install":
            # Deliberately last and deliberately not done here. `__main__` execs a shell outside
            # this tree once the TUI has torn down; saying "removed" now would be a claim made
            # before the fact.
            _report(n, DONE, "on exit")
            results.append(f"{item.label}: removed as this wizard exits")
            continue
        failed = False
        why = ""
        for argv in commands_for(item.key, settings, home, repo_root, project):
            last = _Tail()
            code = runner(argv, _tee(on_line, last))  # type: ignore[operator]
            if code != 0:
                failed = True
                # NAMED. "could not start — is it installed?" and "timed out after 30 minutes" both
                # collapsed into "did not fully succeed"; an ordinary non-zero exit collapsed into
                # "exit 1", which names no cause at all. The command's own last line does.
                why = why or _FAILURE.get(code) or _cause(last.line, code)
        if item.key == "config":
            try:
                remove_our_config(home, repo_root)
            except OSError as exc:
                failed = True
                why = why or explain(str(exc)).summary
        if not failed and (left := _still_there(item.key, settings.docker_bin, project)):
            # CHECKED, not trusted. A zero exit only says the command ran; it said "done" for a
            # teardown that removed nothing at all, because it had been pointed at the wrong
            # project. What matters is whether the thing is gone.
            failed, why = True, left
        _report(n, FAILED if failed else DONE, "failed" if failed else "removed")
        results.append(f"{item.label}: {why or 'did not fully succeed' if failed else 'done'}")
    return results
