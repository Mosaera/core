"""A live escalation is believed only if the escalated role SPOKE (#119, ADR-0016 Amendment 1).

**The defect.** Across the stored corpus, 45 of 61 recorded escalations produced ZERO calls from
the escalated role — every one binding an unfunded cloud key — with `error` left `None` and
`escalation_path` still naming the model. A failed escalation was therefore indistinguishable from
*"a stronger model tried and could not"*, and read the second way it inverted the conclusions drawn
from six runs. The bench got the detector in ADR-0016 Amendment 1; the live path was recorded as
OWED, and the 2026-08-18 corpus review listed it again. These tests are that debt discharged.

**Why post-hoc and not a pre-check.** `cloud_tier_allowed` requires the model be PRICED — correctly,
since that is what lets the USD cap bound the spend — but priced is not funded. An exhausted key, a
revoked key and a typo'd model name all clear it identically, and reachability is only knowable
after a call has been attempted.

This is the POSITIVE CONTROL the issue asks for: a control must be seen to fire.
"""

from __future__ import annotations

from typing import Any, cast


class _Meter:
    def __init__(self, rollup: dict[str, Any]) -> None:
        self._rollup = rollup

    def rollup(self) -> dict[str, Any]:
        return self._rollup


class _Session:
    def __init__(self, rollup: dict[str, Any]) -> None:
        self.cost_meter = _Meter(rollup)


class _Ctx:
    """The two collaborators `_note_escalation_outcome` touches, and nothing else."""

    def __init__(self) -> None:
        self.audits: list[tuple[str, str, str]] = []
        self.notes: list[str] = []
        self.history = self

    def _safe_audit(self, run_id: str, event: str, detail: str = "") -> None:
        self.audits.append((run_id, event, detail))

    def update_project(self, project_id: str, **kw: Any) -> None:
        if "error" in kw:
            self.notes.append(kw["error"])


def _note(ctx: Any, rollup: dict[str, Any], role: str = "coder") -> None:
    from mosaera_api.app_context._model_escalation import ModelEscalationMixin

    ModelEscalationMixin._note_escalation_outcome(
        ctx, "p1", "run-1", cast(Any, _Session(rollup)), role, 1
    )


def _rollup(**by_agent: int) -> dict[str, Any]:
    """A cost rollup in the shape `role_calls` reads — a role with no successful calls contributes
    no `by_agent` row at all, which is exactly the signal."""
    return {"by_agent": [{"agent": label, "calls": n} for label, n in by_agent.items()]}


def test_an_escalation_whose_role_never_spoke_is_recorded_as_such() -> None:
    ctx = _Ctx()
    _note(ctx, _rollup(Tester=21))  # the Tester spoke; the escalated CODER did not
    events = [e for _, e, _ in ctx.audits]
    assert "escalation.outcome" in events
    detail = ctx.audits[-1][2]
    assert detail.startswith("no_calls_discarded")
    assert "ZERO model calls" in detail


def test_the_no_op_is_visible_where_an_operator_looks() -> None:
    # An audit row alone repeats the original defect one layer up: recorded, and never surfaced.
    ctx = _Ctx()
    _note(ctx, _rollup(Tester=21))
    assert ctx.notes, "a no-op escalation left no note on the project"
    assert "never reached" in ctx.notes[-1]
    assert "not evidence about that model" in ctx.notes[-1]


def test_an_escalation_that_did_speak_is_recorded_as_applied() -> None:
    # The other direction. A detector that only ever reports one outcome is not a detector — this
    # is the `test_guard_liveness` discipline applied to a recording.
    ctx = _Ctx()
    _note(ctx, _rollup(Coder=7))
    assert ctx.audits[-1][2].startswith("applied")
    assert ctx.notes == []  # nothing to warn about


def test_the_role_label_comes_from_the_agent_registry() -> None:
    """`role_calls` maps role -> `AgentSpec.label`, the same field spend is attributed with.

    A wrong mapping would read zero for EVERY role and silently report every escalation as a no-op
    — the failure inverted. Driven per role so a rename cannot pass unnoticed.
    """
    from mosaera_core.team import spec_for

    for role in ("pm", "coder", "reviewer", "tester", "critic"):
        spec = spec_for(role)
        assert spec is not None
        ctx = _Ctx()
        _note(ctx, _rollup(**{spec.label: 3}), role=role)
        assert ctx.audits[-1][2].startswith("applied"), f"{role} spoke but was read as silent"


def test_a_bookkeeping_fault_never_breaks_the_sweep() -> None:
    # The rule every best-effort recorder here follows: a fault in the record must not take down
    # the run that produced it. It still says it could not tell, rather than staying silent.
    class _Boom:
        @property
        def cost_meter(self) -> Any:
            raise RuntimeError("rollup exploded")

    from mosaera_api.app_context._model_escalation import ModelEscalationMixin

    ctx = _Ctx()
    ModelEscalationMixin._note_escalation_outcome(
        cast(Any, ctx), "p1", "run-1", cast(Any, _Boom()), "coder", 1
    )
    assert ctx.audits[-1][1] == "escalation.outcome-unknown"


def test_the_live_vocabulary_matches_the_bench() -> None:
    """A live escalation and a benchmarked one must be describable in the same words, or the two
    bodies of evidence cannot be compared — the reason `run_diagnosis` exists as one definition."""
    from mosaera_api.app_context import _model_escalation as live
    from mosaera_core.bench import _escalation_run as bench

    assert live.ESCALATION_APPLIED == bench.ESCALATION_APPLIED
    assert live.ESCALATION_NO_CALLS == bench.ESCALATION_NO_CALLS


def test_the_escalated_role_is_threaded_into_the_re_run() -> None:
    """Without this the detector cannot fire at all: `_after` has to know WHICH role was bumped.

    This is the half ADR-0016 Amendment 1 named as owed — "the same detector belongs there, but it
    needs the escalated role threaded into the run session".
    """
    import inspect

    from mosaera_api.app_context import _launch, _model_escalation

    assert "escalation_role=esc.role" in inspect.getsource(_model_escalation)
    assert "escalation_role" in inspect.signature(_launch.LaunchMixin.launch_item).parameters
