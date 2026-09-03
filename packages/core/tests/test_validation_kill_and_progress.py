"""An infrastructure kill is not a test failure, and validation is not a silent phase.

Both pins come from driving LedgerCLI on 2026-08-23:

- **F77.** The test step was SIGKILLed (`exit code 137` — the container's `--memory`/`--pids-limit`
  cap). `run_plan` special-cased only `TIMED OUT`, so `result.ok` was False, `tests_passed` was
  False, and the graph routed to `fix`. The coder then spent 3 iterations and ~794k tokens
  repairing code that was passing — the captured output shows 69 passing dots and no failures
  before the kill. A producer cannot fix an OOM, so that loop is unwinnable by construction.
- **F80.** Validation makes no model calls, so the token counter is flat throughout; with nothing
  emitted until the last step finished, a healthy install+suite cycle was indistinguishable from a
  hung run for minutes.

The load-bearing assertion is that 137 and 1 land in DIFFERENT states. A pin that only checked
"137 does not pass" would be satisfied by the very bug it exists to catch.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mosaera_core.sandbox import SandboxResult, SandboxWorker
from mosaera_core.validation import (
    ValidationOutcome,
    ValidationPlan,
    ValidationStep,
    killing_signal,
    run_plan,
)


class _FixedSandbox(SandboxWorker):
    """Returns one canned result for every command."""

    def __init__(self, exit_code: int, *, timed_out: bool = False, output: str = "") -> None:
        self._result = SandboxResult(exit_code, output, "", 0.01, timed_out, True)

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        return self._result

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        return self._result


def _plan() -> ValidationPlan:
    return ValidationPlan(
        "python", [ValidationStep("pytest", ["pytest", "-q"], 300)], "detected", strength="suite"
    )


def _run(exit_code: int, **kw: Any) -> ValidationOutcome:
    return run_plan(_plan(), _FixedSandbox(exit_code, **kw))


# ----------------------------------------------------------------- F77: kill != failure


def test_a_killed_step_is_unavailable_not_failed() -> None:
    """`None` = no honest validation available, which the gate reads as `validation_unavailable`
    and parks for a human — instead of handing the coder a defect that is not in the code."""
    outcome = _run(137)
    assert outcome.passed is None
    assert "KILLED by signal 9" in outcome.output
    assert "validation unavailable" in outcome.output


def test_a_real_test_failure_still_reads_as_failed() -> None:
    """The pin that stops the fix from swallowing genuine failures: 1 and 137 must not converge."""
    assert _run(1).passed is False
    assert _run(137).passed is not False  # the two land in DIFFERENT states


def test_a_passing_step_is_unaffected() -> None:
    assert _run(0).passed is True


def test_a_timeout_keeps_its_own_reporting() -> None:
    """A timeout already had an honest path; it must not be reclassified as a signal kill."""
    outcome = _run(124, timed_out=True)
    assert "TIMED OUT" in outcome.output
    assert "KILLED" not in outcome.output


def test_killing_signal_bounds() -> None:
    """No runner we drive emits 129-192: pytest exits 0-5, unittest 0-1."""
    assert killing_signal(137, False) == 9  # SIGKILL — the OOM case
    assert killing_signal(143, False) == 15  # SIGTERM
    assert killing_signal(1, False) is None  # an ordinary failing suite
    assert killing_signal(5, False) is None  # pytest: no tests collected
    assert killing_signal(0, False) is None
    assert killing_signal(137, True) is None  # a timeout owns its own reporting


# ----------------------------------------------------------------- F80: progress is emitted


def test_progress_brackets_every_step() -> None:
    seen: list[tuple[str, str]] = []
    run_plan(
        _plan(),
        _FixedSandbox(0),
        on_step=lambda phase, name, detail: seen.append((phase, name)),
    )
    assert seen == [("start", "pytest"), ("done", "pytest")]


def test_progress_reports_the_outcome_of_each_step() -> None:
    details: dict[str, str] = {}
    run_plan(
        _plan(),
        _FixedSandbox(137),
        on_step=lambda phase, name, detail: details.__setitem__(phase, detail),
    )
    assert "up to 300s" in details["start"]  # a long wait reads as bounded, not hung
    assert "KILLED by signal 9" in details["done"]


def test_a_raising_progress_sink_cannot_break_validation() -> None:
    """Telemetry must never fail a validation — the verdict is the thing that matters."""

    def _boom(phase: str, name: str, detail: str) -> None:
        raise RuntimeError("sink exploded")

    assert run_plan(_plan(), _FixedSandbox(0), on_step=_boom).passed is True
