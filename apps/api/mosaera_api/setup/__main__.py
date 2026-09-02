"""`mosaera-setup` — the first-run wizard (ADR-0116).

Deliberately a separate command rather than something `install.sh` runs for you: piping a script to
`sh` makes the script itself the process's stdin, so a prompt inside it would consume the script.
Handing the operator a command to run in their own shell removes that failure mode entirely, and
`install.sh` accordingly ends by printing this line instead of trying to be interactive.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, NoReturn

from mosaera_core.config import load_env

#: The smallest terminal the wizard can draw a usable screen in. Below this the header alone fills
#: the window; `ui.header_rows` already sheds the art and the strapline on the way down, and this is
#: where there is nothing left to shed.
_MIN_COLS, _MIN_ROWS = 60, 18


def _repo_root() -> Path:
    """The checkout this wizard configures — the directory holding `infra/docker/compose.yaml`.

    Resolved from this file, never from `cwd`: the compose file, the Dockerfiles and `.env` are all
    addressed relative to it, and inheriting a destination from wherever the operator happened to
    stand is precisely the mistake this repo has already paid for once.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "infra" / "docker" / "compose.yaml").exists():
            return parent
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    # BEFORE `load_env`, which merges `.env` into `os.environ` — after it, "the shell set this" and
    # "`.env` says this" are indistinguishable, and the access screen warned about variables the
    # operator had never exported.
    from mosaera_api.setup.env_file import capture_real_env

    capture_real_env()
    load_env()
    if (size := shutil.get_terminal_size((80, 24))) and (
        size.columns < _MIN_COLS or size.lines < _MIN_ROWS
    ):
        # Refused rather than drawn badly. Below this the header alone fills the screen and the
        # choice list has nowhere to go — and a wizard whose controls are off-screen is worse than
        # one that says why it will not start.
        print(
            f"mosaera-setup needs a terminal at least {_MIN_COLS}x{_MIN_ROWS}; "
            f"this one is {size.columns}x{size.lines}. Resize the window and run it again.",
            file=sys.stderr,
        )
        return 2
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Half-running a setup wizard is worse than not starting one. Name the supported
        # alternative rather than failing with a traceback about a missing terminal.
        print(
            "mosaera-setup needs an interactive terminal.\n"
            "For an orchestrated deploy, set MOSAERA_INITIAL_ADMIN_USER and "
            "MOSAERA_INITIAL_ADMIN_PASSWORD and start the API instead.",
            file=sys.stderr,
        )
        return 2
    from mosaera_api.setup.app import SetupApp

    repo_root = _repo_root()
    if not _confirm_data_home(repo_root):
        return 0
    app = SetupApp(repo_root)
    _record_bootstrapped_uv(app.settings.home)
    # CAPTURED BEFORE the TUI touches it. `os.execv` runs no atexit handler and no finalizer, so
    # anything Textual defers to interpreter shutdown never happens on the removal path — including
    # putting the terminal back. See `_hand_off_removal`.
    tty_state = _tty_state()
    code = app.run() or 0
    if app._remove_install is not None:
        _hand_off_removal(app._remove_install, tty_state)  # never returns
    return code


def _tty_state() -> Any | None:
    """The terminal's settings as they were before anything raw-moded them."""
    try:
        import termios

        return termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        return None


def _confirm_data_home(repo_root: Path) -> bool:
    """Where the data will live — stated and agreed to, when it is not the obvious place.

    `Settings.home` is `Path(".mosaera")`, which is CWD-RELATIVE. Run from the install directory —
    what `install.sh` does, and what every doc tells you to do — it resolves under the checkout and
    all is well. Run from anywhere else and the evidence store, `settings.json`, run records and
    workspaces are silently created beside wherever the operator happened to be standing.

    CLAUDE.md names that shape as the most expensive lesson this project has recorded, so the
    wizard does not simply inherit it. It also does not nag: on the expected path there is nothing
    to decide and nothing is asked. The question appears exactly when the answer is not obvious.
    """
    from mosaera_core.config import Settings

    home = Path(Settings.from_env().home).resolve()
    if home.parent == repo_root.resolve():
        return True  # the ordinary case — `install.sh` puts you here

    print(f"\n  Mosaera will keep its data at:\n    {home}\n")
    print("  That is taken from the directory you are standing in, not from the install.")
    try:
        reply = input("  Continue? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if reply in ("", "y", "yes"):
        print()
        return True
    print(
        f"\n  Nothing was changed. To keep the data with the install, run it from there:\n"
        f"    cd {repo_root} && uv run mosaera-setup\n"
    )
    return False


def _hand_off_removal(target: Path, tty_state: Any | None = None) -> NoReturn:
    """Delete the installation by EXEC-ing out of it.

    A process must not be the last user of the thing it is deleting. That is rustup's rule, and on
    Unix `exec` makes it a one-liner instead of the scheduled-copy dance rustup needs on Windows.

    It is not optional here. This process's cwd IS the install directory — `install.sh` ends with
    `( cd "$INSTALL_DIR" && exec uv run … )` — and its interpreter lives in that directory's
    `.venv`. Python imports lazily, so deleting the tree from inside would work right up until the
    first module that had not been loaded yet, and the operator would get a traceback on top of a
    half-removed install. `exec` replaces this process image outright: every descriptor into the old
    virtualenv closes, `/bin/sh` is outside the doomed tree, and the shell's exit status becomes
    ours, so the removal still reports honestly rather than being fired and forgotten.

    Runs only AFTER `app.run()` has returned, which is when Textual has restored the terminal.
    """
    # PUT THE TERMINAL BACK, FIRST. `exec` replaces the process image without running a single
    # atexit handler or finalizer, so Textual's own restore — which happens at interpreter
    # shutdown — never runs on this path. The removal then succeeded, printed, and handed the
    # operator a terminal still in raw mode: no echo, and Enter never forming a line, so the shell
    # appeared to hang and only Ctrl-C got out. Reported from a real macOS run; reproduced here as
    # ECHO=off ICANON=off after an exec from a raw tty.
    if tty_state is not None:
        try:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, tty_state)
        except Exception:  # noqa: S110 - `stty sane` in the script is the second layer
            pass
    os.chdir("/")  # nothing may hold the directory open, including our own cwd
    quoted = shlex.quote(str(target))
    # `rmdir` on the parent, never `rm -rf`: with the default layout the install directory is
    # `~/.mosaera/core`, and leaving an empty `~/.mosaera` behind is untidy — while removing a
    # parent that still holds something would take data this row never offered.
    parent = shlex.quote(str(target.parent))
    print(f"\n  Removing {target}")
    script = (
        # `stty sane` is the second layer, and it is deliberate belt-and-braces: if the capture
        # above failed or never happened, this still hands back a usable terminal.
        "stty sane 2>/dev/null; "
        f"rm -rf -- {quoted} && rmdir {parent} 2>/dev/null; "
        f'if [ -e {quoted} ]; then printf "  could not remove %s\\n" {quoted} >&2; exit 1; '
        f'else printf "  Mosaera has been removed.\\n"; fi'
    )
    # S606: exec without a shell is the POINT — the argv is built here from one path this
    # process chose, never from operator text, and replacing the image is what makes the
    # deletion safe. `/bin/sh` is absolute so PATH cannot redirect it.
    os.execv("/bin/sh", ["sh", "-c", script])  # noqa: S606


def _record_bootstrapped_uv(home: Path) -> None:
    """`install.sh` installed uv before this wizard could exist to ask (ADR-0117 §2).

    The installer states the fact and this writes the record, so there is ONE writer of
    `setup_installed` and it is the module that owns that file's format. Without it the uninstall
    screen would offer everything the wizard put on the machine except the one thing that was put
    there without being asked — which is exactly the item an operator is most entitled to take back.
    """
    if os.environ.get("MOSAERA_BOOTSTRAPPED_UV", "") != "1":
        return
    from mosaera_api.setup.uninstall import record_install

    record_install(home, "uv")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
