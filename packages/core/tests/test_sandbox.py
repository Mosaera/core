import sys
from pathlib import Path

import pytest
from mosaera_core.sandbox import SandboxViolation, SubprocessSandbox


@pytest.fixture
def sandbox(tmp_path: Path) -> SubprocessSandbox:
    return SubprocessSandbox(root=tmp_path, default_timeout=30)


def test_runs_command_in_root(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run([sys.executable, "-c", "import os; print(os.getcwd()); print('marker')"])
    assert result.ok
    assert "marker" in result.stdout
    assert str(sandbox.root) in result.stdout


def test_readonly_work_fails_closed_on_subprocess(sandbox: SubprocessSandbox) -> None:
    # The subprocess backend runs on the HOST against the real workspace — it cannot enforce a
    # read-only mount, so a read-only probe (sandbox_exec) MUST raise rather than run writable
    # (ADR-0059). The tool then reports itself unavailable on this backend.
    with pytest.raises(SandboxViolation):
        sandbox.run([sys.executable, "-c", "print(1)"], readonly_work=True)


def test_run_setup_stays_contained_unless_install_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # run_setup must NOT drop network isolation (host-network install = RCE) unless
    # explicitly allowed. Capture the isolate flag passed to _execute.
    from mosaera_core.sandbox import SandboxResult

    captured: dict[str, bool] = {}

    def fake_execute(
        self: SubprocessSandbox, cmd: object, cwd: object, timeout: object, *, isolate: bool
    ) -> SandboxResult:
        captured["isolate"] = isolate
        return SandboxResult(0, "", "", 0.0, False, network_isolated=isolate)

    monkeypatch.setattr(SubprocessSandbox, "_execute", fake_execute)

    SubprocessSandbox(root=tmp_path, allow_install=False).run_setup(["echo", "x"])
    assert captured["isolate"] is True  # contained (delegates to run)

    SubprocessSandbox(root=tmp_path, allow_install=True).run_setup(["echo", "x"])
    assert captured["isolate"] is False  # opted in → drops isolation for install


def test_timeout_is_enforced(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert result.timed_out
    assert not result.ok


def test_cwd_outside_root_rejected(sandbox: SubprocessSandbox, tmp_path: Path) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.run([sys.executable, "-c", "pass"], cwd=tmp_path.parent)


def test_environment_is_scrubbed(
    sandbox: SubprocessSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOSAERA_FAKE_API_KEY", "super-secret")
    result = sandbox.run(
        [sys.executable, "-c", "import os; print(os.environ.get('MOSAERA_FAKE_API_KEY', 'ABSENT'))"]
    )
    assert result.ok
    assert "ABSENT" in result.stdout
    assert "super-secret" not in result.stdout


def test_nonzero_exit_reported(sandbox: SubprocessSandbox) -> None:
    result = sandbox.run([sys.executable, "-c", "raise SystemExit(3)"])
    assert result.exit_code == 3
    assert not result.ok
