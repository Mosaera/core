"""What this machine needs, what it has, and the exact command that closes the gap.

ONE TABLE, TWO READERS — and one named non-reader. The setup wizard and `mosaera doctor` read it.
Before it existed each guessed separately, and differently: the wizard passed a BINARY name to a
package manager, so on Debian it offered `apt-get install -y node`, which installs an amateur
packet radio program, and `install -y docker`, which is not the engine. On any distribution we did
not recognise, every tool produced `curl get.docker.com | sh`, so "install git" ran the Docker
installer.

`scripts/install.sh` is the non-reader — ADR-0116 was wrong to count it as a third. It needs its
advice BEFORE a clone and before uv exists, so it cannot call this module, and it hand-rolled a
per-distribution table instead. The fix was subtraction (ADR-0117): requiring only `git` and
installing only `uv` leaves it one package name to state by hand, and
`test_git_is_the_same_package_name_everywhere` fails if `git` ever stops being called `git`.

The rules this file keeps:

  - A binary name is NOT a package name. `node` is `nodejs`; `docker` is not `docker.io` is not
    `moby-engine`. Every package name here is declared per family, never derived.
  - An unsupported platform says so and links its documentation. It never emits a command belonging
    to a different tool, and never a command for a different operating system.
  - Presence is not readiness. Docker's CLI on PATH says nothing about whether the daemon answers or
    whether the operator may talk to it, and `docker compose` ships as a SEPARATE package from the
    engine on every distribution that packages them at all.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

_PROBE_TIMEOUT = 5.0

# The install PLANS live next door — split at the god-file ceiling, re-exported whole so every
# existing `from mosaera_core.prereqs import plan_for` (and the docs constants the wizard prints)
# keeps resolving. This module owns what the machine HAS; `_prereq_plans` owns what to do about it.
from mosaera_core._prereq_plans import (  # noqa: E402
    ABSENT,
    COLIMA_DOCS,
    DAEMON_DOWN,
    DOCKER_DESKTOP,
    DOCKER_DESKTOP_WSL,
    DOCKER_DOCS,
    DOCKER_SCRIPT,
    HOMEBREW,
    NO_PERMISSION,
    NODE_DOCS,
    Plan,
    Step,
    package_command,
    plan_for,
)

__all__ = [
    "ABSENT",
    "COLIMA_DOCS",
    "DAEMON_DOWN",
    "DOCKER_DESKTOP",
    "DOCKER_DESKTOP_WSL",
    "DOCKER_DOCS",
    "DOCKER_SCRIPT",
    "HOMEBREW",
    "NODE_DOCS",
    "NO_PERMISSION",
    "PREREQS",
    "Found",
    "Plan",
    "Platform",
    "Prereq",
    "Step",
    "classify_docker_failure",
    "detect_platform",
    "missing",
    "package_command",
    "plan_for",
    "survey",
]

#: Docker's own documented installer. Chosen over per-distro packages because it is the one command
#: that works across distributions AND brings the compose v2 plugin — which the distro packages
#: ship separately, and which `docker compose up` needs. Already the method
#: `infra/dev-server-bootstrap.sh` uses, so the repo does not now have two answers.


@dataclass(frozen=True)
class Platform:
    """The operating system, and — on Linux — which package manager family it belongs to."""

    system: str  #: "linux" | "darwin" | "windows" | ""
    family: str  #: "debian" | "fedora" | "arch" | "suse" | "alpine" | "" when unknown
    pretty: str
    #: A WSL distribution. `platform.system()` says "Linux" there and `/etc/os-release` is
    #: Ubuntu's, so without this bit WSL was told to `systemctl enable --now docker` (no systemd
    #: unless `/etc/wsl.conf` turns it on) and to "log out and back in" (which does not restart the
    #: distro's init — `wsl --shutdown` does).
    wsl: bool = False
    #: Homebrew on PATH. macOS only: every `brew install …` here was unconditional, so a Mac
    #: without it was offered a command that cannot run.
    brew: bool = False
    #: Both are defaulted AND last so every positional `Platform("linux", "fedora", "Fedora")` in
    #: the suite keeps compiling — the new branches are reached only by tests that ask for them.

    @property
    def is_linux(self) -> bool:
        return self.system == "linux"

    @property
    def is_macos(self) -> bool:
        return self.system == "darwin"

    @property
    def known(self) -> bool:
        """Whether we can name a package manager. An unknown platform gets documentation, never a
        guess — a wrong install command is worse than no install command."""
        return bool(self.family) or self.is_macos


#: `ID_LIKE` first: Ubuntu is `ID=ubuntu ID_LIKE=debian`, Rocky is `ID=rocky ID_LIKE="rhel centos
#: fedora"`. Matching the family rather than the distribution is what makes derivatives work without
#: an entry each.
_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("debian", ("debian", "ubuntu")),
    ("fedora", ("fedora", "rhel", "centos", "rocky", "almalinux")),
    ("arch", ("arch", "manjaro")),
    ("suse", ("suse", "opensuse", "sles")),
    ("alpine", ("alpine",)),
)


#: Where Homebrew puts itself: Apple Silicon first, then Intel. A tuple so a test can empty it.
_BREW_CANDIDATES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")


def brew_bin() -> str:
    """Homebrew's binary, PATH or not.

    `shutil.which` alone was wrong on the machine it mattered on. Homebrew installs to
    `/opt/homebrew` on Apple Silicon and `/usr/local` on Intel, and it is `~/.zprofile` running
    `brew shellenv` that puts either on PATH — so a wizard launched from a shell that has not
    sourced that profile (a fresh non-login shell, some terminal configurations, anything spawned
    by another process) asks a machine WITH Homebrew whether it has Homebrew and is told no.

    The consequence was not cosmetic: on macOS the answer decides whether the Docker gap can be
    closed at all (ADR-0118), so a mis-detection turns an installable machine into a dead end.

    Returns the path to use in a command, or "" when there genuinely is none.
    """
    found = shutil.which("brew")
    if found:
        return found
    for candidate in _BREW_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return ""


def _parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def detect_platform(
    *,
    os_release: str | None = None,
    system: str | None = None,
    proc_version: str | None = None,
    env: dict[str, str] | None = None,
    brew: bool | None = None,
) -> Platform:
    """This machine, or a described one.

    Every input is injectable so every branch is testable — the alternative is a function whose
    Debian path can only be exercised on Debian, which is how the wrong command shipped. The WSL
    and Homebrew branches are the same argument: neither can be exercised on this dev box at all.
    """
    sys_name = (system if system is not None else platform.system()).lower()
    if sys_name == "darwin":
        has_brew = bool(brew_bin()) if brew is None else brew
        return Platform("darwin", "", "macOS", brew=has_brew)
    if sys_name != "linux":
        return Platform(sys_name, "", sys_name.title() or "this system")

    if os_release is None:
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                os_release = fh.read()
        except OSError:
            os_release = ""
    fields = _parse_os_release(os_release)
    ident = f"{fields.get('ID', '')} {fields.get('ID_LIKE', '')}".lower()
    pretty = fields.get("PRETTY_NAME") or fields.get("NAME") or "Linux"
    under_wsl = _is_wsl(proc_version, env)
    if under_wsl:
        # Said once, here, so every screen that already prints `plat.pretty` reports it without a
        # branch of its own.
        pretty = f"{pretty} (WSL)"
    for family, keys in _FAMILIES:
        if any(k in ident for k in keys):
            return Platform("linux", family, pretty, wsl=under_wsl)
    return Platform("linux", "", pretty, wsl=under_wsl)


#: Two independent tells. The env vars are absent for a process started by a service or `wsl -e`,
#: so `/proc/version` — "microsoft" in every WSL kernel build — is the backstop. `dev-up.sh:36`
#: greps the same string: this is that fact moved, not a second one invented.
_WSL_ENV_VARS = ("WSL_DISTRO_NAME", "WSL_INTEROP")


def _is_wsl(proc_version: str | None, env: dict[str, str] | None) -> bool:
    environ = os.environ if env is None else env
    if any(environ.get(name) for name in _WSL_ENV_VARS):
        return True
    if proc_version is None:
        try:
            with open("/proc/version", encoding="utf-8") as fh:
                proc_version = fh.read()
        except OSError:
            proc_version = ""
    lowered = proc_version.lower()
    return "microsoft" in lowered or "wsl" in lowered


@dataclass(frozen=True)
class Prereq:
    """A thing this machine needs, and what it is FOR.

    The purpose is not decoration. A newcomer asked to install Docker deserves to know it is what
    every sandboxed command runs inside, not to be told a name and a version.
    """

    key: str
    label: str
    purpose: str
    packages: dict[str, str] = field(default_factory=dict)
    min_version: tuple[int, ...] | None = None
    docs: str = ""


PREREQS: tuple[Prereq, ...] = (
    Prereq(
        key="git",
        label="git",
        purpose="clones the repositories your projects point at",
        packages={
            "debian": "git",
            "fedora": "git",
            "arch": "git",
            "suse": "git",
            "alpine": "git",
            "darwin": "git",
        },
        docs="https://git-scm.com/downloads",
    ),
    Prereq(
        key="docker",
        label="Docker",
        purpose="every command an agent runs executes inside a container",
        docs=DOCKER_DOCS,
    ),
    Prereq(
        key="compose",
        label="Docker Compose",
        purpose="brings up the bundled Postgres",
        docs=DOCKER_DOCS,
    ),
    Prereq(
        key="node",
        label="Node",
        purpose="builds the dashboard you sign in to",
        packages={
            "debian": "nodejs npm",
            "fedora": "nodejs npm",
            "arch": "nodejs npm",
            "suse": "nodejs npm",
            "alpine": "nodejs npm",
            "darwin": "node",
        },
        min_version=(20,),
        docs=NODE_DOCS,
    ),
)


def classify_docker_failure(output: str) -> str:
    """Why `docker info` did not answer — `NO_PERMISSION` or `DAEMON_DOWN`.

    Extracted from `_probe_docker` so `preflight_host` can name a repair without a second matcher
    of its own; two regexes for one question is how the answers drift apart.
    """
    return NO_PERMISSION if "permission denied" in output.lower() else DAEMON_DOWN


def _run(argv: Sequence[str]) -> tuple[int, str]:
    """A bounded probe. Never raises: a missing binary is an answer, not an exception."""
    try:
        proc = subprocess.run(  # noqa: S603 — argv is built here, never from operator input
            list(argv), capture_output=True, text=True, timeout=_PROBE_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _version_of(output: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", output)
    return tuple(int(p) for p in match.groups() if p is not None) if match else ()


@dataclass(frozen=True)
class Found:
    """What we learned about one prerequisite on this machine."""

    prereq: Prereq
    present: bool
    detail: str
    plan: Plan
    #: Why it is not usable — `ABSENT`, `DAEMON_DOWN` or `NO_PERMISSION`. The fix differs per
    #: reason, and offering the install plan for all three is how "Install Docker" came to be
    #: offered for a Docker that was installed.
    reason: str = ""

    @property
    def key(self) -> str:
        return self.prereq.key


def _probe_git() -> tuple[bool, str, str]:
    if shutil.which("git") is None:
        return False, "not installed", ABSENT
    code, out = _run(["git", "--version"])
    if code != 0:
        return False, "not working", ABSENT
    return True, out.replace("git version", "").strip(), ""


def _probe_docker(docker_bin: str) -> tuple[bool, str, str]:
    """Present AND usable. `shutil.which` alone reports a working Docker on a box whose daemon is
    down or whose user is not in the `docker` group — the two failures most likely on a fresh
    install, and the two an operator most needs named."""
    if shutil.which(docker_bin) is None:
        return False, "not installed", ABSENT
    code, out = _run([docker_bin, "info", "--format", "{{.ServerVersion}}"])
    if code == 0:
        return True, out.splitlines()[0] if out else "running", ""
    reason = classify_docker_failure(out)
    if reason == NO_PERMISSION:
        return False, "installed, but this user may not talk to the daemon", NO_PERMISSION
    return False, "installed, but the daemon is not running", DAEMON_DOWN


def _probe_compose(docker_bin: str) -> tuple[bool, str, str]:
    if shutil.which(docker_bin) is None:
        return False, "needs Docker first", ABSENT
    code, out = _run([docker_bin, "compose", "version"])
    if code == 0:
        return True, out.splitlines()[0].replace("Docker Compose version", "").strip(), ""
    return False, "not installed", ABSENT


def _probe_node(minimum: tuple[int, ...] | None) -> tuple[bool, str, str]:
    if shutil.which("node") is None:
        return False, "not installed", ABSENT
    code, out = _run(["node", "--version"])
    if code != 0:
        return False, "not working", ABSENT
    version = _version_of(out)
    if minimum and version and version < minimum:
        wanted = ".".join(str(p) for p in minimum)
        return False, f"{out.strip()} — too old, needs {wanted}+", ABSENT
    # What actually runs is `npm --prefix apps/web install` and `npm run build`; `node` alone is
    # not that. The install plans in this file spell the package as "nodejs npm" precisely because
    # the two are separable, so a row reading "Node 22 ✓" over a machine with no npm promised a
    # dashboard build that then died on `npm: command not found`.
    if shutil.which("npm") is None:
        return (
            False,
            f"{out.strip()} — but npm is missing, and the dashboard build needs it",
            ABSENT,
        )
    return True, out.strip(), ""


def survey(docker_bin: str = "docker", plat: Platform | None = None) -> list[Found]:
    """Every prerequisite, present or not, with its state and how to close the gap.

    Returns ALL of them rather than only the gaps: a list of what is missing tells the operator what
    to do, but the whole list tells them what shape their machine is in, which is the question they
    are actually asking.
    """
    here = plat or detect_platform()
    probes = {
        "git": lambda p: _probe_git(),
        "docker": lambda p: _probe_docker(docker_bin),
        "compose": lambda p: _probe_compose(docker_bin),
        "node": lambda p: _probe_node(p.min_version),
    }
    out: list[Found] = []
    for prereq in PREREQS:
        present, detail, reason = probes[prereq.key](prereq)
        out.append(Found(prereq, present, detail, plan_for(prereq, here, reason), reason))
    return out


def missing(found: Sequence[Found]) -> list[Found]:
    return [f for f in found if not f.present]
