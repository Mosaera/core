"""Validation dependency-install: step emission, phase routing, stamp skip.

Offline — a RecordingSandbox stands in for the container so we can assert which
steps hit the network-ON install phase (run_setup) vs the network-off test
phase (run), without a Docker daemon.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mosaera_core.sandbox import SandboxResult, SandboxWorker
from mosaera_core.tools.repo import Workspace
from mosaera_core.validation import detect_validation_plan, run_plan


class RecordingSandbox(SandboxWorker):
    """Records each command and which phase (run vs run_setup) ran it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    @staticmethod
    def _ok() -> SandboxResult:
        return SandboxResult(0, "ok", "", 0.01, False, True)

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        self.calls.append(("run", list(cmd)))
        return self._ok()

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
    ) -> SandboxResult:
        self.calls.append(("run_setup", list(cmd)))
        return self._ok()


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="t", branch="b")


def test_install_step_prepended_for_requirements(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(tmp_path, {"requirements.txt": "requests\n", "test_app.py": "def test(): pass\n"})
    )
    assert [s.name for s in plan.steps] == ["install", "pytest"]
    install, pytest_step = plan.steps
    assert install.network is True and install.skip_if_exists
    assert "requirements.txt" in " ".join(install.cmd)
    # --copies (not the default symlink): the venv lives on the /work mount shared with the host;
    # a symlinked .venv/bin/python is a dangling link on a Windows host → WinError 1920 crash (#56).
    assert "--copies" in " ".join(install.cmd)
    # pytest runs inside the installed venv, not the base interpreter.
    assert pytest_step.network is False
    assert pytest_step.cmd[0] == ".venv/bin/python"


def test_editable_install_for_pyproject(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(
            tmp_path, {"pyproject.toml": "[project]\nname='x'\n", "test_a.py": "def test(): pass\n"}
        )
    )
    assert plan.steps[0].name == "install"
    assert "-e ." in " ".join(plan.steps[0].cmd)


def test_no_install_step_for_zero_dep_suite(tmp_path: Path) -> None:
    # No dependency manifest → base-image pytest, no install phase (unchanged).
    plan = detect_validation_plan(_ws(tmp_path, {"test_app.py": "def test(): pass\n"}))
    assert [s.name for s in plan.steps] == ["pytest"]
    assert plan.steps[0].cmd[0] != ".venv/bin/python"


def test_install_disabled_emits_no_step(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(tmp_path, {"requirements.txt": "requests\n", "test_a.py": "def test(): pass\n"}),
        install=False,
    )
    assert [s.name for s in plan.steps] == ["pytest"]
    assert "disabled" in plan.reason


def test_run_plan_routes_install_to_setup_phase(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"requirements.txt": "requests\n", "test_a.py": "def test(): pass\n"})
    plan = detect_validation_plan(ws)
    sb = RecordingSandbox()
    run_plan(plan, sb, cwd=tmp_path)
    phases = [phase for phase, _ in sb.calls]
    assert phases == ["run_setup", "run"]  # install network-on, pytest network-off


def test_run_plan_skips_install_when_stamp_present(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"requirements.txt": "requests\n", "test_a.py": "def test(): pass\n"})
    plan = detect_validation_plan(ws)
    stamp = plan.steps[0].skip_if_exists
    assert stamp
    (tmp_path / stamp).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / stamp).write_text("", encoding="utf-8")
    sb = RecordingSandbox()
    outcome = run_plan(plan, sb, cwd=tmp_path)
    # The install container never launched — egress stays closed on a warm venv.
    assert [phase for phase, _ in sb.calls] == ["run"]
    assert outcome.passed is True
