"""The hardened Docker sandbox backend.

``DockerSandbox`` runs each tool command in a throwaway container with
``--network none``, a read-only root, resource caps, a non-root user, and a
single writable ``/work`` mount — containment against hostile test code
(TM-0001).
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

from ._base import (
    _DEFAULT_SANDBOX_IMAGE,
    SandboxResult,
    SandboxViolation,
    SandboxWorker,
    _is_absolute,
    _is_python_interpreter,
)

# The ONLY networks the install phase may use (ADR-0035). "bridge" = egress on (the
# repo's own manifest fetches deps); "none" = hard-off. NOT "host": that shares the
# host's network namespace with the target repo's install code (setup.py,
# npm postinstall), which then reaches the loopback-open Mosaera API, Ollama, and the
# dev Postgres — an escalation from "install runs the repo's build code" to "install
# controls the box".
ALLOWED_INSTALL_NETWORKS = ("bridge", "none")


def _safe_install_network(value: str) -> str:
    """Clamp the install network to a supported value.

    Removing "host" from ``Knob.choices`` only guards the SETTINGS-UI write path. The read
    path never consults ``choices``, so a value stored before the change, a
    ``MOSAERA_SANDBOX_INSTALL_NETWORK=host`` env var, or a direct constructor call would all
    still reach ``docker run --network host``. This is the boundary that actually holds.
    """
    if value in ALLOWED_INSTALL_NETWORKS:
        return value
    print(
        f"  WARNING: unsupported sandbox install network {value!r} — falling back to 'bridge'. "
        f"'host' shares the host network namespace with the target repo's install code "
        f"(reaching the local API, Ollama, and the database) and is no longer supported; "
        f"use 'none' to disable install egress entirely."
    )
    return "bridge"


class DockerSandbox(SandboxWorker):
    """Runs commands in a throwaway, network-less, resource-capped container.

    The workspace ``root`` is bind-mounted read-write at ``/work``; the container
    root filesystem is read-only. Callers pass the host interpreter
    (``sys.executable``); it is rewritten to the container's ``python`` since the
    host path does not exist inside the image.
    """

    def __init__(
        self,
        root: Path,
        image: str = _DEFAULT_SANDBOX_IMAGE,
        docker_bin: str = "docker",
        default_timeout: int = 300,
        memory: str = "1g",
        cpus: str = "2",
        pids_limit: int = 256,
        install_network: str = "bridge",
        index_url: str | None = None,
        user: str = "sandbox",
    ):
        self.root = root.resolve()
        self.image = image
        self.docker_bin = docker_bin
        self.default_timeout = default_timeout
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        # The container user. Defaults to the image's non-root ``sandbox`` (uid
        # 1000). Overridable so a CI runner whose job creates the bind-mounted
        # workspace as root can run the container as root too -- otherwise uid
        # 1000 can't write/traverse the root-owned /work. Production keeps the
        # default; the other isolation (network none, read-only rootfs, cap-drop
        # ALL, no-new-privileges) is unchanged regardless of user.
        self.user = user
        # The network the INSTALL phase runs under ("bridge" = egress on;
        # "none" = hard-off, keeps install fully isolated). The TEST phase is
        # always "none". ``index_url`` pins pip to a registry (the seam to a
        # future egress-allowlisted proxy).
        self.install_network = _safe_install_network(install_network)
        self.index_url = index_url

    def _mount_source(self) -> str:
        # The Windows docker.exe (used from WSL without native integration) needs
        # Windows-style mount paths; wslpath translates /mnt/c/... -> C:\...
        # Native Linux docker takes the path unchanged.
        wslpath = shutil.which("wslpath")
        if self.docker_bin.lower().endswith(".exe") and wslpath:
            out = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
                [wslpath, "-w", str(self.root)],
                capture_output=True,
                text=True,
                check=True,
            )
            return out.stdout.strip()
        return str(self.root)

    @staticmethod
    def _translate_cmd(cmd: Sequence[str]) -> list[str]:
        argv = list(cmd)
        # Rewrite ONLY an absolute host interpreter (sys.executable) to the
        # container's "python". A relative interpreter like ".venv/bin/python"
        # (the install phase's venv) must be preserved so tests run inside it.
        if argv and _is_absolute(argv[0]) and _is_python_interpreter(argv[0]):
            argv[0] = "python"
        return argv

    def _docker_argv(
        self,
        name: str,
        container_wd: str,
        cmd: Sequence[str],
        *,
        network: str,
        env: Sequence[str] = (),
        image: str | None = None,
        readonly_work: bool = False,
    ) -> list[str]:
        env_flags: list[str] = []
        for pair in env:
            env_flags += ["-e", pair]
        return [
            self.docker_bin,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            network,
            "--user",
            self.user,
            "--read-only",
            "--tmpfs",
            "/tmp:exec",  # noqa: S108 — container mount target, not a host temp path
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--pids-limit",
            str(self.pids_limit),
            # Defense-in-depth against a container escape from hostile test code:
            # drop every Linux capability and block privilege escalation (setuid/
            # setgid paths). Test execution (pytest, py-compile, pip) needs neither.
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            *env_flags,
            "-v",
            # READ-ONLY probe (ADR-0059): mount /work :ro so a sandbox_exec snippet can import + run
            # repo code but cannot persist — never bypassing the write-gate / protected-paths /
            # tamper guard. The writable /tmp tmpfs above stays, for a probe needing scratch.
            f"{self._mount_source()}:/work:{'ro' if readonly_work else 'rw'}",
            "-w",
            container_wd,
            image or self.image,
            *self._translate_cmd(cmd),
        ]

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        # The TEST phase: always network-off.
        return self._execute(
            cmd, cwd, timeout, network="none", image=image, readonly_work=readonly_work
        )

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
    ) -> SandboxResult:
        # The INSTALL phase: network per ``install_network`` (default egress on),
        # with pip pinned to ``index_url`` when configured. Same read-only root,
        # non-root user, and caps as the test phase.
        env = (f"PIP_INDEX_URL={self.index_url}",) if self.index_url else ()
        return self._execute(cmd, cwd, timeout, network=self.install_network, env=env, image=image)

    def _execute(
        self,
        cmd: Sequence[str],
        cwd: Path | None,
        timeout: int | None,
        *,
        network: str,
        env: Sequence[str] = (),
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        workdir = (cwd or self.root).resolve()
        if not workdir.is_relative_to(self.root):
            raise SandboxViolation(f"cwd {workdir} is outside sandbox root {self.root}")
        rel = workdir.relative_to(self.root)
        container_wd = "/work" if rel == Path(".") else f"/work/{rel.as_posix()}"

        name = f"mosaera-sbx-{uuid.uuid4().hex[:12]}"
        effective_timeout = self.default_timeout if timeout is None else timeout
        argv = self._docker_argv(
            name,
            container_wd,
            cmd,
            network=network,
            env=env,
            image=image,
            readonly_work=readonly_work,
        )
        isolated = network == "none"

        start = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 — argv list, no shell; container is isolated
                argv,
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
            # The container outlives the client on timeout; force-remove it.
            subprocess.run(  # noqa: S603
                [self.docker_bin, "rm", "-f", name],
                capture_output=True,
                text=True,
            )
            return SandboxResult(
                exit_code=-1,
                stdout=exc.stdout.decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr=exc.stderr.decode("utf-8", "replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or ""),
                duration_s=time.monotonic() - start,
                timed_out=True,
                network_isolated=isolated,
            )
        except OSError as exc:
            # The runner binary (e.g. docker / docker.exe) is missing or unusable
            # — fail the step honestly instead of crashing the run with a traceback.
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"sandbox command failed to start: {exc}",
                duration_s=time.monotonic() - start,
                timed_out=False,
                network_isolated=isolated,
            )
