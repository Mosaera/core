"""DockerSandbox: pure-helper unit tests (always run) + container integration
tests (skipped when no Docker daemon is reachable)."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from mosaera_core.sandbox import (
    DockerSandbox,
    SandboxUnavailable,
    SandboxViolation,
    _is_python_interpreter,
    create_sandbox,
)

_DOCKER_BIN = os.environ.get("MOSAERA_DOCKER_BIN", "docker")
_IMAGE = os.environ.get("MOSAERA_SANDBOX_IMAGE", "mosaera-sandbox:dev")
# Container user for the integration sandboxes. Defaults to the image's uid-1000
# `sandbox`; a CI runner whose job owns the bind-mounted workspace as root sets
# MOSAERA_SANDBOX_USER=root so the container can write/traverse it.
_SANDBOX_USER = os.environ.get("MOSAERA_SANDBOX_USER", "sandbox")
# Repo root: packages/core/tests/ -> Mosaera/. Workspaces here live on the
# Windows filesystem (/mnt/c), which the Windows docker.exe engine can bind-mount;
# a Linux /tmp path cannot be mounted when WSL integration is off (see docs).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Skip when the daemon is down OR the sandbox image isn't built — otherwise the container
# tests fail with exit 125 (image not found) instead of self-skipping (the documented invariant).
# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_docker = pytest.mark.requires_docker(_IMAGE)


def _mountable_workdir() -> Path:
    """A fresh workspace dir the configured docker engine can bind-mount.

    Native Linux docker mounts anywhere, so tmp is fine. The Windows docker.exe
    used from WSL can only mount Windows-filesystem paths, so use the repo tree.
    """
    if _DOCKER_BIN.lower().endswith(".exe"):
        base = _REPO_ROOT / ".mosaera" / "_pytest_docker"
    else:
        base = Path(os.environ.get("TMPDIR", "/tmp")) / "mosaera_pytest_docker"  # noqa: S108
    d = base / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- pure helpers: no daemon needed ---


def test_python_interpreter_detection() -> None:
    assert _is_python_interpreter("/usr/bin/python3")
    assert _is_python_interpreter("python")
    assert _is_python_interpreter(r"C:\Python312\python.exe")
    assert _is_python_interpreter("/home/u/.venv/bin/python3.12")
    assert not _is_python_interpreter("pytest")
    assert not _is_python_interpreter("/bin/bash")


def test_translate_cmd_rewrites_host_interpreter() -> None:
    argv = DockerSandbox._translate_cmd([sys.executable, "-m", "pytest", "-q"])
    assert argv == ["python", "-m", "pytest", "-q"]
    # Non-interpreter commands pass through untouched.
    assert DockerSandbox._translate_cmd(["ls", "-la"]) == ["ls", "-la"]
    # A RELATIVE venv interpreter (the install phase's .venv) is preserved — it
    # must not be clobbered to the base image's bare python.
    assert DockerSandbox._translate_cmd([".venv/bin/python", "-m", "pytest"]) == [
        ".venv/bin/python",
        "-m",
        "pytest",
    ]


def test_docker_argv_shape(tmp_path: Path) -> None:
    sb = DockerSandbox(tmp_path, image="img:test", docker_bin="docker")
    argv = sb._docker_argv("sbx-1", "/work", ["python", "-m", "pytest"], network="none")
    assert argv[0] == "docker"
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert "--user" in argv and argv[argv.index("--user") + 1] == "sandbox"
    # Kernel-level containment against a container escape from hostile test code.
    assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert (
        "--security-opt" in argv and argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    )
    assert argv[-4:] == ["img:test", "python", "-m", "pytest"]
    # Default is a read-WRITE /work mount (validation writes .pyc, coverage data, etc.).
    assert any(a.endswith(":/work:rw") for a in argv)


def test_docker_argv_readonly_work_mounts_ro(tmp_path: Path) -> None:
    # The sandbox_exec read-only probe (ADR-0059): readonly_work=True mounts /work :ro so a snippet
    # can import + run repo code but cannot persist. Everything else (network none, caps) unchanged.
    sb = DockerSandbox(tmp_path, image="img:test", docker_bin="docker")
    argv = sb._docker_argv("s", "/work", ["python", "-c", "x"], network="none", readonly_work=True)
    assert any(a.endswith(":/work:ro") for a in argv)
    assert not any(a.endswith(":/work:rw") for a in argv)
    assert "--read-only" in argv and "--network" in argv  # the rest of the containment holds


def test_docker_argv_image_override(tmp_path: Path) -> None:
    # A per-command image override (used by a non-Python LanguagePack — e.g. a Node image for
    # a TS project) replaces the sandbox's default image for THAT container only; without it,
    # the default image is used (byte-identical to before, the Python path).
    sb = DockerSandbox(tmp_path, image="img:default", docker_bin="docker")
    assert "img:default" in sb._docker_argv("s", "/work", ["node", "-v"], network="none")
    override = sb._docker_argv("s", "/work", ["node", "-v"], network="none", image="node:22")
    assert override[-3:] == ["node:22", "node", "-v"]
    assert "img:default" not in override


def test_setup_argv_uses_install_network_and_index(tmp_path: Path) -> None:
    # The install phase forks the argv: network per install_network + a pinned
    # PIP_INDEX_URL, while keeping the read-only root and non-root user.
    sb = DockerSandbox(
        tmp_path,
        image="img:test",
        install_network="bridge",
        index_url="https://pypi.example/simple",
    )
    argv = sb._docker_argv(
        "sbx-2", "/work", ["sh", "-c", "true"], network="bridge", env=("PIP_INDEX_URL=x",)
    )
    assert argv[argv.index("--network") + 1] == "bridge"
    assert "-e" in argv and "PIP_INDEX_URL=x" in argv
    assert "--read-only" in argv  # hardening kept during install
    assert "--user" in argv and argv[argv.index("--user") + 1] == "sandbox"


def test_create_sandbox_unknown_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown sandbox backend"):
        create_sandbox("vm", tmp_path)


def test_create_sandbox_docker_unavailable(tmp_path: Path) -> None:
    with pytest.raises(SandboxUnavailable):
        create_sandbox("docker", tmp_path, docker_bin="definitely-not-a-real-docker-bin")


# --- container integration: needs a daemon + the sandbox image ---


@pytest.fixture
def workdir() -> Iterator[Path]:
    d = _mountable_workdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sandbox(workdir: Path) -> DockerSandbox:
    return DockerSandbox(
        workdir, image=_IMAGE, docker_bin=_DOCKER_BIN, default_timeout=60, user=_SANDBOX_USER
    )


@requires_docker
def test_runs_command_and_captures_output(sandbox: DockerSandbox) -> None:
    result = sandbox.run(["python", "-c", "print('marker-xyz')"])
    assert result.ok, result.combined_output()
    assert "marker-xyz" in result.stdout
    assert result.network_isolated


@requires_docker
def test_network_egress_blocked(sandbox: DockerSandbox) -> None:
    # The TEST phase (run) is always --network none.
    result = sandbox.run(
        [
            "python",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)",
        ]
    )
    assert not result.ok  # --network none => name resolution / connect fails
    assert result.network_isolated


@requires_docker
def test_run_setup_allows_egress(workdir: Path) -> None:
    # The INSTALL phase (run_setup) opens egress so pip can reach a registry.
    sb = DockerSandbox(
        workdir, image=_IMAGE, docker_bin=_DOCKER_BIN, default_timeout=60, user=_SANDBOX_USER
    )
    result = sb.run_setup(
        [
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), timeout=5)",
        ]
    )
    assert result.ok, result.combined_output()
    assert not result.network_isolated


@requires_docker
def test_write_confined_to_work_mount(sandbox: DockerSandbox, workdir: Path) -> None:
    # Writing under /work lands on the host mount; writing elsewhere hits the
    # read-only root filesystem.
    ok = sandbox.run(["bash", "-c", "echo hi > /work/out.txt"])
    assert ok.ok, ok.combined_output()
    assert (workdir / "out.txt").read_text().strip() == "hi"

    denied = sandbox.run(["bash", "-c", "echo hi > /etc/passwd"])
    assert not denied.ok


@requires_docker
def test_readonly_work_probe_cannot_write_the_workspace(
    sandbox: DockerSandbox, workdir: Path
) -> None:
    # The sandbox_exec read-only probe (ADR-0059): with readonly_work=True the /work mount is :ro,
    # so a snippet can READ/run repo code but a WRITE to /work fails — it can never persist a change
    # (bypassing the write-gate/tamper guard). /tmp stays writable for scratch; reads still work.
    write = sandbox.run(["bash", "-c", "echo hi > /work/evil.txt"], readonly_work=True)
    assert not write.ok  # the read-only mount rejects the write
    assert not (workdir / "evil.txt").exists()  # nothing persisted to the host workspace
    scratch = sandbox.run(
        ["bash", "-c", "echo ok > /tmp/scratch && cat /tmp/scratch"], readonly_work=True
    )
    assert scratch.ok and "ok" in scratch.stdout  # /tmp is still writable for a probe's scratch
    read = sandbox.run(["bash", "-c", "ls /work"], readonly_work=True)
    assert read.ok  # reads/imports of the repo still work


@requires_docker
def test_cwd_outside_root_rejected(sandbox: DockerSandbox, workdir: Path) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.run(["python", "-c", "pass"], cwd=workdir.parent)


@requires_docker
def test_timeout_kills_container(sandbox: DockerSandbox) -> None:
    result = sandbox.run(["python", "-c", "import time; time.sleep(30)"], timeout=3)
    assert result.timed_out
    assert not result.ok


def test_host_install_network_is_clamped_to_bridge(tmp_path: Path) -> None:
    """`--network host` must never reach docker, from ANY source (ADR-0035).

    Dropping "host" from `Knob.choices` only guards the settings-UI write path: the READ
    path never consults `choices`, so a value stored in settings.json before the change, a
    `MOSAERA_SANDBOX_INSTALL_NETWORK=host` env var, or a direct constructor call would all
    still have reached `docker run --network host` — sharing the host network namespace with
    the target repo's install code, which then reaches the loopback API, Ollama, and the DB.
    The sandbox boundary is what actually holds.
    """
    sb = DockerSandbox(tmp_path, install_network="host")
    assert sb.install_network == "bridge"

    argv = sb._docker_argv("c", "/work", ["echo", "hi"], network=sb.install_network)
    assert "host" not in argv
    assert argv[argv.index("--network") + 1] == "bridge"


def test_supported_install_networks_are_passed_through(tmp_path: Path) -> None:
    assert DockerSandbox(tmp_path, install_network="bridge").install_network == "bridge"
    assert DockerSandbox(tmp_path, install_network="none").install_network == "none"
