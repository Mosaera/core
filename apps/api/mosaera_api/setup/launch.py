"""Starting the instance, so the link on the last screen is a live one.

The completion screen promises an address. A promise the operator has to run `make up` to redeem is
not a completion screen, so the wizard brings the instance up itself.

THREE THINGS THIS GETS RIGHT, each of which is a way it could be wrong:

  - **Already serving wins.** The probe runs FIRST and short-circuits everything. This wizard's
    whole contract is that running it again changes nothing, and a second `mosaera-api` on a taken
    port would either die on bind or — worse — succeed on a different one.
  - **The child is detached.** `start_new_session=True`, with output to a log file rather than to a
    pipe. The installer closes itself sixty seconds later; a foreground child would die with it, and
    a piped one would block forever once the pipe buffer filled.
  - **The environment is passed, never inherited.** `mosaera-api` reads `os.environ` and does not
    load `.env` itself — that is what `dev-up.sh` was doing for it. The child gets the file's values
    explicitly, which is also the rule this repo learned the expensive way about anything that
    writes.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from mosaera_api.setup import process

#: Where the detached server's output and process id go. Under `.mosaera/`, which is gitignored and
#: is where every other piece of local instance state already lives.
LOG_NAME = "api.log"
PID_NAME = "api.pid"

#: How long to wait for the port to answer. Uvicorn on a warm machine is a second or two; this is
#: long enough for a cold import and short enough that a wedged start is reported rather than waited
#: on forever.
START_TIMEOUT = 90.0
_POLL_SECONDS = 0.4


def already_serving(host: str, port: int, timeout: float = 0.35) -> bool:
    """Whether something already answers there.

    Loopback is probed on 127.0.0.1 whatever the bind says: `0.0.0.0` is not an address you can
    connect TO, and treating it as one made the probe fail on exactly the public binds it mattered
    for.
    """
    target = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host  # noqa: S104
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return True
    except OSError:
        return False


def responds_ok(host: str, port: int, timeout: float = 3.0) -> bool:
    """Whether the instance ANSWERS, not merely whether the port is open.

    `already_serving` opens a TCP connection, which is the right question for "is this port taken,
    should I refrain from starting a second server". It is the WRONG question for "is the thing I
    just started actually working": uvicorn accepts connections perfectly while every request comes
    back 500, so the completion screen printed `Running at http://127.0.0.1:8000` over an instance
    the browser could only get an Internal Server Error out of. Reported from a live macOS run,
    2026-08-30.

    `/healthz` is unauthenticated and already refuses to answer "ok" over a dead database (ADR-0035)
    — the same lesson, learned at the API layer and never asked for here.
    """
    target = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host  # noqa: S104
    try:
        with urllib.request.urlopen(  # http, loopback, url built here — never operator text
            f"http://{target}:{port}/healthz", timeout=timeout
        ) as answer:
            return 200 <= answer.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def dashboard_built(repo_root: Path) -> bool:
    """Whether the SPA the API serves exists AND was built from the source now on disk.

    Presence alone was the test, and `install.sh` updates the clone IN PLACE — so every update
    produced a new backend served behind the previous dashboard, silently, because `index.html`
    existed and the build was skipped. The API already knows this failure (`_warn_if_stale_dist`
    in `app.py` calls a stale bundle "the classic reason freshly-added UI doesn't appear"), but it
    warns into `api.log`, which nobody reads, and warns too late to rebuild.

    Missing `src/` means a packaged wheel with no source to compare against: presence is then the
    only question there is, and the honest answer.
    """
    web = repo_root / "apps" / "web"
    index = web / "dist" / "index.html"
    if not index.is_file():
        return False
    src = web / "src"
    if not src.is_dir():
        return True
    try:
        built = index.stat().st_mtime
        newest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0.0)
    except OSError:
        return True  # cannot compare: do not force a rebuild on a guess
    return newest <= built


def dashboard_argv() -> list[list[str]]:
    """Install then build, as argv — never a shell string. Same two commands `dev-up.sh` runs."""
    return [
        ["npm", "--prefix", "apps/web", "install", "--silent"],
        ["npm", "--prefix", "apps/web", "run", "build", "--silent"],
    ]


def serve_argv() -> list[str]:
    """`--no-sync` deliberately: syncing here would re-resolve the workspace while the wizard is
    running out of it."""
    return ["uv", "run", "--no-sync", "mosaera-api"]


#: How long the exit failsafe waits before forcing the process down. Ample for Textual's
#: `driver.close()` to restore the terminal on the graceful path first; short enough that a held
#: terminal is released almost at once.
_EXIT_FAILSAFE_SECONDS = 3.0


def arm_exit_failsafe(code: int) -> None:
    """Guarantee the process ends, even if `App.run()` never returns.

    Textual tears down gracefully — `_shutdown` restores the terminal via `driver.close()` — but
    `App.run()` returns through `asyncio.run`, whose loop teardown calls
    `shutdown_default_executor()`, which JOINS the worker thread-pool with NO timeout. A
    `@work(thread=True)` build or probe still running (the first-ever sandbox image build on a
    fresh machine is exactly this) therefore blocks `run()` from returning at all, and the
    operator's shell never comes back (reproduced on CachyOS 2026-09-03).

    The failsafe is a DAEMON thread — it never itself blocks interpreter exit — that force-exits
    a few seconds after teardown begins. On a healthy machine `run()` returns at once and the
    process is already gone (via `__main__._finalize`) long before this fires, so it is inert
    there. `os._exit` is the point: it skips the very executor join that is stuck.
    """

    def _force() -> None:
        time.sleep(_EXIT_FAILSAFE_SECONDS)
        os._exit(code)

    threading.Thread(target=_force, daemon=True).start()


def start_detached(repo_root: Path, home: Path, env: dict[str, str]) -> tuple[int, Path]:
    """Launch the API so it outlives this process. Returns its pid and its log path.

    Raises `OSError` if it cannot be started at all — the caller reports that rather than showing a
    link to nothing.
    """
    home.mkdir(parents=True, exist_ok=True)
    log_path = home / LOG_NAME
    child_env = {**os.environ, **{k: v for k, v in env.items() if v != ""}}
    with log_path.open("ab") as log:
        proc = subprocess.Popen(  # noqa: S603 — argv is built here, never from operator text
            serve_argv(),
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=child_env,
            # Its own session: it survives the installer exiting, and a Ctrl-C in the terminal the
            # wizard was launched from does not reach it.
            start_new_session=True,
        )
    (home / PID_NAME).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid, log_path


def wait_until_serving(
    host: str,
    port: int,
    timeout: float = START_TIMEOUT,
    should_cancel: Callable[[], bool] | None = None,
) -> bool:
    """Poll until the instance ANSWERS, or give up. Returns whether it came up.

    `should_cancel` is polled between attempts. Without it the screen said "Esc cancels" and then
    ignored Esc for ninety seconds, which is the kind of small lie that teaches an operator the
    whole interface is lying.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # `responds_ok`, NOT `already_serving`: an open port is not a working instance.
        if responds_ok(host, port):
            return True
        if should_cancel is not None and should_cancel():
            return False
        time.sleep(_POLL_SECONDS)
    return False


def our_pid(home: Path, repo_root: Path | None = None) -> int:
    """The server WE started, if it is still alive AND still that server. 0 otherwise.

    A pid FILE IS NOT PROOF. It is an integer in a file the wizard also writes, so a stale entry
    after a reboot — or a hand-edited one — named some unrelated process, and `stop` then SIGTERMed
    it and reported success. Demonstrated: a `sleep 900` was killed by pointing `api.pid` at it.

    So the number is checked against the process it names: it must be running `mosaera-api`, and it
    must be running out of THIS install. Signal 0 alone only answers "does this pid exist".
    """
    try:
        pid = int((home / PID_NAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    if pid <= 1:
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        # Gone, or belonging to another user — either way the number is not ours any more.
        return 0
    return pid if _is_our_server(pid, repo_root) else 0


def _is_our_server(pid: int, repo_root: Path | None) -> bool:
    """Whether `pid` really is this install's API process.

    Asked of the SYSTEM, not of whoever wrote the pid file — `/proc` where it exists, `ps`/`lsof`
    where it does not. The first cut read `/proc` only and failed closed, which is right on Linux
    and unconditional on macOS, where there is no procfs: `our_pid` returned 0 for every server
    the wizard had itself started, so `stop` found nothing and every uninstall left the API
    running with its port bound. See `process.py`.

    Still fails CLOSED when genuinely unanswerable — an unverified pid is not signalled.
    """
    if "mosaera-api" not in process.cmdline(pid):
        return False
    if repo_root is None:
        return True
    here = process.cwd(pid)
    return here is not None and here == repo_root.resolve()


def stop(home: Path, repo_root: Path | None = None) -> str:
    """Stop the server we started. Returns "" on success, else why not.

    `our_pid` does the verifying: an unverified pid is not signalled at all, so a stale or crafted
    `api.pid` can no longer make this kill somebody else's process.
    """
    pid = our_pid(home, repo_root)
    if not pid:
        # Nothing OF OURS by the pid file — but the file is deleted with the installation, so an
        # orphan from a previous install has none. Ask the port, and stop only what identifies
        # itself as a Mosaera API: an unidentified process on a port is somebody else's.
        problems = [
            problem
            for holder in _our_holders(home, repo_root)
            if (problem := process.terminate(holder))
        ]
        if not problems:
            (home / PID_NAME).unlink(missing_ok=True)
        return "; ".join(problems)
    problem = process.terminate(pid)
    if problem:
        return problem  # the pid file STAYS: it still names something that is running
    (home / PID_NAME).unlink(missing_ok=True)
    return ""


def _our_holders(home: Path, repo_root: Path | None) -> list[int]:
    """Pids listening on this install's port that identify as a Mosaera API.

    `repo_root` is deliberately NOT required to match here. An orphan's working directory is the
    installation that has already been removed, so demanding equality would refuse to clean up
    exactly the case this exists for — while "is a mosaera-api process, on the port this install
    is configured to use" is still a positive identification and never somebody else's server.
    """
    from mosaera_api.setup.env_file import effective_env, port_from

    root = repo_root or Path.cwd()
    port = port_from(effective_env(root / ".env"), "MOSAERA_API_PORT", 8000)
    return [pid for pid in process.listeners(port) if "mosaera-api" in process.cmdline(pid)]


def address(host: str, port: int, lan: str) -> str:
    """The URL to put on the completion screen: the one that will actually resolve.

    A `0.0.0.0` bind is reachable from the network, so it is shown as the machine's real address —
    printing `http://0.0.0.0:8000` tells the operator nothing they can click.
    """
    shown = lan if host == "0.0.0.0" else (host or "127.0.0.1")  # noqa: S104
    return f"http://{shown}:{port}"
