"""Sandbox contract, result type, and shared helpers.

This is the leaf module of the ``sandbox`` package: the abstract
``SandboxWorker`` contract, the ``SandboxResult`` value type, the sandbox
exceptions, and the small deterministic helpers shared by both backends. It
imports nothing from its sibling modules to keep the dependency graph acyclic.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DEFAULT_SANDBOX_IMAGE = "mosaera-sandbox:dev"


@lru_cache(maxsize=1)
def _unshare_works() -> bool:
    """Whether ``unshare -rn`` actually creates namespaces here — not just whether
    the binary exists. Many locked-down environments (CI containers, restrictive
    seccomp) ship ``unshare`` but block user/network namespaces; probing once
    avoids breaking every sandboxed command on those hosts."""
    unshare = shutil.which("unshare") if sys.platform.startswith("linux") else None
    if not unshare:
        return False
    try:
        return (
            subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
                [unshare, "-r", "-n", "true"], capture_output=True, timeout=5
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


# Environment variables allowed through to sandboxed processes. Everything else
# (API keys, tokens, cloud credentials) is stripped.
_SAFE_ENV_VARS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "VIRTUAL_ENV",
    "PYTHONIOENCODING",
)


class SandboxViolation(Exception):
    """A command tried to run outside the sandbox root."""


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    network_isolated: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def combined_output(self, limit: int = 8000) -> str:
        text = self.stdout
        if self.stderr:
            text += ("\n--- stderr ---\n" + self.stderr) if text else self.stderr
        if len(text) > limit:
            text = text[:limit] + f"\n... (truncated at {limit} chars)"
        return text


class SandboxWorker(ABC):
    """Executes tool commands with a restricted cwd, no network, and timeouts."""

    @abstractmethod
    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        """Run a command network-off. ``image`` optionally overrides the sandbox's default
        container image for THIS command (``None`` → the default) — so a validation plan can
        run its steps on a language-specific toolchain image (e.g. a Node image for a TS
        project) without recreating the sandbox. Backends without an image concept ignore it.

        ``readonly_work=True`` mounts the workspace READ-ONLY for this command — a probe that may
        import + run repo code to observe behaviour but must not PERSIST anything (the coder's
        ``sandbox_exec`` tool, ADR-0059). A backend that cannot enforce a read-only workspace MUST
        fail closed (raise ``SandboxViolation``) rather than silently run writable — the caller then
        reports the probe as unavailable, so no path ever bypasses the write-gate/tamper guard.
        """
        ...

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
    ) -> SandboxResult:
        """Run a dependency-install / setup command, which may need network.

        Default: no special phase — delegate to ``run`` (network-off). Backends
        that can open the network for install (``DockerSandbox``) override this;
        the network-off TEST phase always goes through ``run``. ``image`` is the same
        per-command image override as ``run``.
        """
        return self.run(cmd, cwd, timeout, image)


class SandboxUnavailable(Exception):
    """The requested sandbox backend is not usable on this machine."""


def docker_available(docker_bin: str = "docker") -> bool:
    """Whether the docker daemon is reachable via ``docker_bin``."""
    if not (shutil.which(docker_bin) or docker_bin.lower().endswith(".exe")):
        return False
    try:
        proc = subprocess.run(  # noqa: S603
            [docker_bin, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def docker_image_present(tag: str, docker_bin: str = "docker") -> bool:
    """Whether a local docker image ``tag`` exists (``docker image inspect``).

    Distinct from ``docker_available`` (daemon up): a per-language sandbox image
    (``mosaera-sandbox-node:dev`` / ``-sql:dev``) is built by ``dev-up.sh`` and the GitLab
    ``sandbox-e2e`` job, but NOT by the GitHub CI image build. An e2e test gated only on the
    daemon would therefore FAIL where the image is absent (missing image → non-zero
    ``docker run``, not an exception) instead of skipping. This lets such tests skip cleanly
    off the machines/CI that build the image, and run where it exists."""
    if not docker_available(docker_bin):
        return False
    try:
        proc = subprocess.run(  # noqa: S603
            [docker_bin, "image", "inspect", tag],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _is_python_interpreter(arg: str) -> bool:
    """Whether ``arg`` looks like a python interpreter path (e.g. sys.executable).

    Handles both separators so a Windows ``sys.executable`` is recognized even
    when this runs on Linux (where ``Path`` would not split on backslashes).
    """
    name = Path(arg.replace("\\", "/")).name.lower().removesuffix(".exe")
    return name == "python" or (name.startswith("python") and name[6:].replace(".", "").isdigit())


def _is_absolute(arg: str) -> bool:
    """Whether ``arg`` is an absolute host path (POSIX ``/`` or Windows ``C:\\``/``\\``)."""
    return arg.startswith(("/", "\\")) or (len(arg) > 1 and arg[1] == ":")
