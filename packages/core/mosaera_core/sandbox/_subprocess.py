"""The no-Docker subprocess fallback backend.

``SubprocessSandbox`` runs commands with a workspace-restricted cwd, a scrubbed
environment, a wall-clock timeout, and best-effort network isolation via
``unshare -rn`` on Linux. This is NOT containment; it is kept for machines
without Docker.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from ._base import (
    _SAFE_ENV_VARS,
    SandboxResult,
    SandboxViolation,
    SandboxWorker,
    _unshare_works,
)


class SubprocessSandbox(SandboxWorker):
    def __init__(
        self,
        root: Path,
        default_timeout: int = 300,
        network_isolation: bool = True,
        allow_install: bool = False,
    ):
        self.root = root.resolve()
        self.default_timeout = default_timeout
        self.network_isolation = network_isolation
        # When False (default), the install phase does NOT drop isolation to reach
        # the network: running a target repo's build code on the host with egress
        # is host RCE. Only an explicit opt-in enables it (for trusted repos).
        self.allow_install = allow_install

    def _scrubbed_env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _SAFE_ENV_VARS if k in os.environ}
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _isolation_prefix(self) -> tuple[list[str], bool]:
        # Best-effort network isolation: a user+network namespace on Linux, only
        # when it actually works here (see _unshare_works).
        if self.network_isolation and _unshare_works():
            return ["unshare", "-r", "-n"], True
        return [], False

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,  # no-op: the subprocess backend has no container image
        readonly_work: bool = False,
    ) -> SandboxResult:
        if readonly_work:
            # The subprocess backend runs on the HOST against the real workspace — it cannot enforce
            # a read-only mount. Fail CLOSED (ADR-0059): a read-only probe must never silently run
            # with write access, so the caller (sandbox_exec) reports it unavailable on this backend
            raise SandboxViolation(
                "the subprocess sandbox cannot run a read-only probe — use the Docker backend"
            )
        return self._execute(cmd, cwd, timeout, isolate=True)

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,  # no-op: the subprocess backend has no container image
    ) -> SandboxResult:
        # Install phase. Only when explicitly allowed do we drop the network
        # namespace so pip/uv can reach the registry — that runs the repo's build
        # code on the host with egress (RCE). Otherwise stay contained (network-off,
        # isolated) like any other command; a real dependency repo should use Docker.
        if not self.allow_install:
            return self.run(cmd, cwd, timeout)
        return self._execute(cmd, cwd, timeout, isolate=False)

    def _execute(
        self,
        cmd: Sequence[str],
        cwd: Path | None,
        timeout: int | None,
        *,
        isolate: bool,
    ) -> SandboxResult:
        workdir = (cwd or self.root).resolve()
        if not workdir.is_relative_to(self.root):
            raise SandboxViolation(f"cwd {workdir} is outside sandbox root {self.root}")

        prefix, isolated = self._isolation_prefix() if isolate else ([], False)
        full_cmd = [*prefix, *cmd]
        effective_timeout = self.default_timeout if timeout is None else timeout

        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 — argv list, no shell; cwd/env/timeout constrained above
                full_cmd,
                cwd=workdir,
                env=self._scrubbed_env(),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=effective_timeout,
            )
            return SandboxResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_s=time.monotonic() - start,
                timed_out=False,
                network_isolated=isolated,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                exit_code=-1,
                stdout=(exc.stdout or b"").decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr=(exc.stderr or b"").decode("utf-8", "replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or ""),
                duration_s=time.monotonic() - start,
                timed_out=True,
                network_isolated=isolated,
            )
        except OSError as exc:
            # A missing binary (e.g. `sh`/`npm` absent, or a bad --test-cmd) must
            # fail the step honestly, not crash the run with a traceback.
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"command failed to start: {exc}",
                duration_s=time.monotonic() - start,
                timed_out=False,
                network_isolated=isolated,
            )
