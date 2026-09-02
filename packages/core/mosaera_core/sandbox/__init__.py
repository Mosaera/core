"""Sandboxed command execution for agent tool phases.

``SandboxWorker`` is the contract with two implementations:

- ``DockerSandbox`` — the hardened default: a throwaway container with
  ``--network none``, a read-only root, resource caps, a non-root user, and a
  single writable mount at ``/work`` (the run workspace). This is containment
  against hostile test code (TM-0001).
- ``SubprocessSandbox`` — the no-Docker fallback: workspace-restricted cwd,
  scrubbed environment, wall-clock timeout, best-effort network isolation via
  ``unshare -rn`` on Linux. Not containment; kept for machines without Docker.
"""

from __future__ import annotations

from pathlib import Path

from ._base import (
    _DEFAULT_SANDBOX_IMAGE,
    SandboxResult,
    SandboxUnavailable,
    SandboxViolation,
    SandboxWorker,
    docker_available,
    docker_image_present,
)
from ._base import (
    _is_python_interpreter as _is_python_interpreter,  # re-exported for test_sandbox_docker
)
from ._docker import DockerSandbox
from ._subprocess import SubprocessSandbox

__all__ = [
    "DockerSandbox",
    "SandboxResult",
    "SandboxUnavailable",
    "SandboxViolation",
    "SandboxWorker",
    "SubprocessSandbox",
    "create_sandbox",
    "docker_available",
    "docker_image_present",
]


def create_sandbox(
    backend: str,
    root: Path,
    *,
    image: str = _DEFAULT_SANDBOX_IMAGE,
    docker_bin: str = "docker",
    default_timeout: int = 300,
    install_network: str = "bridge",
    index_url: str | None = None,
    allow_install: bool = False,
) -> SandboxWorker:
    """Select a sandbox backend.

    ``docker`` is the hardened default; it preflights the daemon and raises
    ``SandboxUnavailable`` (rather than silently degrading to weaker isolation)
    so a missing daemon is an explicit, actionable failure. ``subprocess`` is the
    no-Docker fallback. ``install_network``/``index_url`` govern the install
    phase only (the test phase is always network-off). ``allow_install`` gates the
    subprocess backend's host-network install phase (host RCE — off unless opted in).
    """
    if backend == "subprocess":
        return SubprocessSandbox(root, default_timeout=default_timeout, allow_install=allow_install)
    if backend == "docker":
        if not docker_available(docker_bin):
            raise SandboxUnavailable(
                f"Docker sandbox requested but the daemon is not reachable via "
                f"{docker_bin!r}. Start Docker, or set MOSAERA_SANDBOX=subprocess "
                f"to use the weaker no-Docker fallback."
            )
        return DockerSandbox(
            root,
            image=image,
            docker_bin=docker_bin,
            default_timeout=default_timeout,
            install_network=install_network,
            index_url=index_url,
        )
    raise ValueError(f"unknown sandbox backend: {backend!r} (expected 'docker' or 'subprocess')")
