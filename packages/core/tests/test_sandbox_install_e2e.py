"""End-to-end: the two-phase install actually makes a real dependency importable.

Docker-gated (skipped without a daemon + the sandbox image). Runs the FULL
validation path — resolve_plan(install=True) → run_plan — against a real
``DockerSandbox`` on a repo that declares a third-party dependency, proving the
install phase installs it with egress and the network-off test phase imports it.
This is the regression net for P1-1 that the current CI can't run (see the
``sandbox-e2e`` job in .gitlab-ci.yml).
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from mosaera_core.sandbox import DockerSandbox
from mosaera_core.tools.repo import Workspace
from mosaera_core.validation import resolve_plan, run_plan

_DOCKER_BIN = os.environ.get("MOSAERA_DOCKER_BIN", "docker")
_IMAGE = os.environ.get("MOSAERA_SANDBOX_IMAGE", "mosaera-sandbox:dev")
_SANDBOX_USER = os.environ.get("MOSAERA_SANDBOX_USER", "sandbox")
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Skip when the daemon is down OR the sandbox image isn't built (self-skip, not an exit-125 fail).
# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_docker = pytest.mark.requires_docker(_IMAGE)


def _mountable_workdir() -> Path:
    # docker.exe (WSL) can only bind-mount Windows-filesystem paths; native
    # Linux docker mounts anywhere.
    if _DOCKER_BIN.lower().endswith(".exe"):
        base = _REPO_ROOT / ".mosaera" / "_pytest_install_e2e"
    else:
        base = Path(os.environ.get("TMPDIR", "/tmp")) / "mosaera_install_e2e"  # noqa: S108
    d = base / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def workdir() -> Iterator[Path]:
    d = _mountable_workdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@requires_docker
def test_install_phase_makes_dependency_importable(workdir: Path) -> None:
    # A repo whose test imports a third-party dep it declares in requirements.txt.
    (workdir / "requirements.txt").write_text("six\n", encoding="utf-8")
    (workdir / "test_dep.py").write_text(
        "import six\n\n\ndef test_dep_is_importable():\n    assert six.PY3\n",
        encoding="utf-8",
    )
    ws = Workspace(root=workdir, run_id="e2e", branch="b")
    sandbox = DockerSandbox(
        workdir,
        image=_IMAGE,
        docker_bin=_DOCKER_BIN,
        default_timeout=120,
        install_network="bridge",
        user=_SANDBOX_USER,
    )

    plan = resolve_plan(ws, None, install=True, install_timeout=300)
    assert [s.name for s in plan.steps] == ["install", "pytest"]
    assert plan.steps[0].network is True  # install opens egress
    assert plan.steps[1].network is False  # pytest stays network-off

    outcome = run_plan(plan, sandbox, cwd=workdir)
    # The dependency installed (with egress) and imported under --network none.
    assert outcome.passed is True, outcome.output
    assert "1 passed" in outcome.output

    # Warm re-run: the stamp skips the install container — egress opens once.
    again = run_plan(plan, sandbox, cwd=workdir)
    assert again.passed is True
    install_result = next(r for r in again.step_results if r["name"] == "install")
    assert install_result.get("skipped") is True
