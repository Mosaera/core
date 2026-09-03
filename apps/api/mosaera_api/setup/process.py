"""Finding and ending a process, on a machine that may not have `/proc`.

Split out of `launch.py` because it is its own problem and was solved wrongly there twice.

**`/proc` is Linux-only.** `_is_our_server` read `/proc/<pid>/cmdline` and failed closed when it
could not — correct reasoning ("unverifiable is not ours") that on **macOS is unconditional**,
because macOS has no procfs at all. So `our_pid` always returned 0 there, `stop` always found
nothing to stop, and the wizard could never end its own server on the one platform it was being
tested on. Every "clean" uninstall left the API running and its port bound.

**A signal is a request, not an outcome.** `stop` sent SIGTERM and returned success, so a process
that ignored it, was still draining, or was already unkillable reported as stopped. The
industry-standard shape — SIGTERM, a grace period, then SIGKILL, then VERIFY — is what
`terminate` does; Docker (10s) and Kubernetes (30s) use the same escalation for the same reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

#: How long a server gets to shut down on its own before SIGKILL. Uvicorn closing listeners and
#: draining is a second or two; this is generous enough not to kill a healthy shutdown and short
#: enough that an uninstall does not appear to hang.
GRACE_SECONDS = 10.0
_POLL = 0.2


def _run(argv: list[str], timeout: float = 5.0) -> str:
    try:
        done = subprocess.run(  # noqa: S603 — argv built here, never from operator text
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def alive(pid: int) -> bool:
    """Whether the pid exists. Signal 0 asks without delivering anything."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it is simply not ours to signal
    except OSError:
        return False
    return True


def cmdline(pid: int) -> str:
    """The process's command line, or "" when it cannot be read.

    `/proc` first because it cannot be forged by whoever wrote a pid file, and is free. `ps` is
    the fallback that makes this work at all on macOS, where there is no procfs.
    """
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        pass
    if shutil.which("ps") is None:
        return ""
    return _run(["ps", "-p", str(pid), "-o", "command="]).strip()


def cwd(pid: int) -> Path | None:
    """The process's working directory, or None when it cannot be read.

    None is NOT "no match" — the caller has to decide what an unanswerable question means, which
    is the distinction this whole module exists because of.
    """
    try:
        return Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        pass
    if shutil.which("lsof") is None:
        return None
    # -Fn is the parseable form: one field per line, `n` prefixing the name.
    for line in _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"]).splitlines():
        if line.startswith("n"):
            return Path(line[1:]).resolve()
    return None


def listeners(port: int) -> list[int]:
    """Every pid LISTENING on `port`. Empty when nothing is, or when we cannot ask.

    This is how a server with no pid file is found at all — the orphan case, where the file that
    identified it was deleted along with the installation that wrote it.
    """
    out: list[int] = []
    if shutil.which("lsof") is not None:
        raw = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
        out = [int(x) for x in raw.split() if x.isdigit()]
    if not out and shutil.which("ss") is not None:
        raw = _run(["ss", "-lptnH", f"sport = :{port}"])
        for chunk in raw.split("pid=")[1:]:
            head = chunk.split(",")[0]
            if head.isdigit():
                out.append(int(head))
    return sorted(set(out))


def terminate(pid: int, grace: float = GRACE_SECONDS) -> str:
    """End `pid`. Returns "" when it is GONE, else why it is not.

    SIGTERM, a grace period, then SIGKILL — and the return value describes the process's state,
    never the signal's delivery. Sending a signal successfully is not the same as the process
    having ended, and reporting the first as the second is what made an uninstall claim a machine
    it had not cleaned.
    """
    if not alive(pid):
        return ""
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return ""
    except OSError as exc:
        return f"could not signal pid {pid}: {exc}"

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not alive(pid):
            return ""
        time.sleep(_POLL)

    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        return ""
    except OSError as exc:
        return f"pid {pid} ignored shutdown and could not be killed: {exc}"

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not alive(pid):
            return ""
        time.sleep(_POLL)
    return f"pid {pid} is still running after SIGKILL"
