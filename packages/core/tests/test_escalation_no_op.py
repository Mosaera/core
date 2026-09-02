"""A no-op escalation must not overwrite a real result (ADR-0016 amendment, 2026-08-10).

MEASURED: 45 of 61 stored escalations produced ZERO calls from the escalated role — every one
binding `anthropic/claude-sonnet-5` on an unfunded key. Each was returned as the run's outcome,
replacing a tier-0 result that had really happened. `error` stayed None and `escalation_path` still
named the model, so a failed escalation read exactly like "a stronger model tried and could not".
Six MCB runs were interpreted that way and every conclusion drawn from them was wrong.

`cloud_tier_allowed` cannot close it: it checks the model is PRICED (correct — that bounds the USD
cap), and priced is not funded. Reachability is only knowable after a call.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from mosaera_core.bench import _escalation_run as cli
from mosaera_core.cost import role_calls
from mosaera_core.team import AGENT_REGISTRY, team_roles


def _rollup(**calls_by_agent: int) -> dict[str, Any]:
    return {"by_agent": [{"agent": a, "calls": n} for a, n in calls_by_agent.items()]}


# --- the detector -------------------------------------------------------------------------


def test_a_role_with_no_row_made_no_calls() -> None:
    """The signal already existed: a role with zero successful calls contributes no row."""
    assert role_calls(_rollup(Tester=30, PM=6), "coder") == 0


def test_a_role_with_a_row_reports_its_calls() -> None:
    assert role_calls(_rollup(Coder=31, Tester=21), "coder") == 31


def test_an_absent_or_empty_rollup_is_zero_not_a_crash() -> None:
    assert role_calls(None, "coder") == 0
    assert role_calls({}, "coder") == 0


def test_an_unknown_role_is_zero() -> None:
    assert role_calls(_rollup(Coder=5), "not-a-role") == 0


@pytest.mark.parametrize("role", list(team_roles()))
def test_every_role_resolves_to_a_label_the_rollup_actually_uses(role: str) -> None:
    """THE INERTNESS GUARD. A wrong role->label mapping would make the detector read zero for
    every role and silently discard every escalation — failing safe but uselessly, which is the
    defect class this whole fix exists to close. The labels come from `AgentSpec.label`, the same
    field `agent_by_node` attributes spend with, so they cannot drift; this pins it anyway."""
    label = next(s.label for s in AGENT_REGISTRY if s.role == role)
    assert role_calls(_rollup(**{label: 7}), role) == 7


# --- the harness rule ---------------------------------------------------------------------


class _Run:
    def __init__(self, rollup: dict[str, Any], approved: bool, tag: str) -> None:
        self.rollup = rollup
        self.final = {"approved": approved}
        self.tag = tag
        self.workspace = object()
        self.error = None
        self.terminal_reasons: list[str] = []


class _Grader:
    def __init__(self, passed: bool) -> None:
        self.all_passed = passed
        self.ran = True


def _drive(monkeypatch: pytest.MonkeyPatch, attempts: list[_Run], escalated: str) -> Any:
    """Run `_run_with_escalation` over a scripted sequence of attempts."""
    seq = list(attempts)
    monkeypatch.setattr(cli, "run_case", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(cli, "diagnose_bottleneck", lambda *a, **k: "coder")
    monkeypatch.setattr(cli, "cloud_tier_allowed", lambda *a, **k: True)

    class _Esc:
        role = "coder"
        label = escalated
        settings: Any = None

    monkeypatch.setattr(cli, "escalate_role", lambda *a, **k: _Esc())

    class _S:
        model_escalation_enabled = True
        max_model_escalations = 1
        sandbox_image = sandbox_timeout = docker_bin = None

        def role_model(self, _role: str) -> Any:
            return type("M", (), {"provider": "anthropic", "model": "claude-sonnet-5"})()

    _Esc.settings = _S()
    return cli.run_with_escalation(
        cast(Any, object()),
        cast(Any, _S()),
        "docker",
        "rid",
        cast(Any, lambda *a, **k: _Grader(False)),
    )


def test_an_escalation_where_the_ROLE_NEVER_SPOKE_keeps_tier_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REGRESSION. Tier 0 did real work; the escalated attempt produced no coder calls."""
    tier0 = _Run(_rollup(Coder=31, Tester=21), approved=False, tag="tier0")
    noop = _Run(_rollup(Tester=21), approved=False, tag="escalated-no-op")
    run, _grader, path, outcome = _drive(monkeypatch, [tier0, noop], "coder: ollama/x -> anth/y")
    assert cast(Any, run).tag == "tier0", (
        "the no-op must NOT overwrite the result that really happened"
    )
    assert outcome == cli.ESCALATION_NO_CALLS
    assert path, "the attempt is still recorded — discarded, not hidden"


def test_an_escalation_that_DID_run_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """The direction that must not move: a real escalation is still the recorded outcome."""
    tier0 = _Run(_rollup(Coder=31), approved=False, tag="tier0")
    real = _Run(_rollup(Coder=12), approved=False, tag="escalated-real")
    run, _grader, _path, outcome = _drive(monkeypatch, [tier0, real], "coder: ollama/x -> ollama/z")
    assert cast(Any, run).tag == "escalated-real"
    assert outcome == cli.ESCALATION_APPLIED


def test_a_run_with_no_escalation_reports_no_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "run_case", lambda *a, **k: _Run(_rollup(Coder=9), True, "solo"))

    class _S:
        model_escalation_enabled = False
        max_model_escalations = 0
        sandbox_image = sandbox_timeout = docker_bin = None

    run, _g, path, outcome = cli.run_with_escalation(
        cast(Any, object()),
        cast(Any, _S()),
        "docker",
        "rid",
        cast(Any, lambda *a, **k: _Grader(True)),
    )
    assert cast(Any, run).tag == "solo" and path == [] and outcome == ""
