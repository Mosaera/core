"""The intake park (ADR-0080 §2, Wave 3) — offline sentinels.

UNDER_SPECIFIED claims park at plan-entry with ZERO model calls; CHECKABLE claims (or no
claims — the headless/CLI/bench default) are byte-identical to today. The FROZEN classifier
buckets the park honest_park by construction; classify_park_cause gains a diagnostic label.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

from mosaera_core.bench.reliability import classify_outcome, classify_park_cause
from mosaera_core.graph.nodes_plan import plan_node


class _NeverCallAgents:
    def plan(self, *a: Any, **k: Any) -> str:
        raise AssertionError("the intake park must fire BEFORE any model call")


def _claim(kind: str, material: bool = True) -> dict[str, Any]:
    return {
        "id": "1-c1",
        "item_id": 1,
        "text": "everything is wired up nicely somehow",
        "provenance": "ENTAILED",
        "oracle_kind": kind,
        "material": material,
    }


def _ctx(agents: Any) -> Any:
    return SimpleNamespace(agents=agents, workspace=None, settings=SimpleNamespace())


def test_under_specified_claims_park_before_any_model_call() -> None:
    state = {"task": "wire it up", "claims": [_claim("none")], "iteration": 0}
    out = plan_node(_ctx(_NeverCallAgents()), state, None)  # type: ignore[arg-type]
    assert out["plan_unworkable_reason"].startswith("under_specified")
    # The frozen classifier buckets it honest_park with ZERO edits (below cap, no stall).
    final = {"approved": False, "iteration": 1, **out}
    assert classify_outcome(final, errored=False, acceptance_failed=False) == "honest_park"
    assert classify_park_cause(final, max_iterations=8) == "under_specified"


def _drive_past_intake(state: dict[str, Any], monkeypatch: Any) -> list[str]:
    """Drive plan_node far enough to prove the intake park did NOT fire: the model gets
    consulted. Downstream (baseline snapshot etc.) is stubbed — not under test here."""
    import mosaera_core.graph.nodes_plan as np_mod

    called: list[str] = []

    class Agents:
        def plan(self, *a: Any, **k: Any) -> str:
            called.append("plan")
            return "1. do it"

    monkeypatch.setattr(np_mod, "planning_overview", lambda ctx: "")
    # The run-start baseline (tamper hashes + the suite-green verdict) moved behind
    # `graph/_baseline.run_start_baseline`; stub the seam where it lives now.
    monkeypatch.setattr(np_mod, "run_start_baseline", lambda ctx: {"integrity_baseline": {}})
    ctx = SimpleNamespace(
        agents=Agents(),
        workspace=None,
        settings=SimpleNamespace(plan_stall_limit=3, stall_detection_enabled=False),
    )
    with contextlib.suppress(Exception):
        # anything after the plan call is out of scope for these sentinels
        plan_node(ctx, state, None)  # type: ignore[arg-type]
    return called


def test_soft_claims_alone_do_not_park(monkeypatch: Any) -> None:
    # Quality-soft (non-material) claims are preferences, not gates — no material claims,
    # no park (the empty-claims path).
    state = {"task": "t", "claims": [_claim("none", material=False)], "iteration": 0}
    assert _drive_past_intake(state, monkeypatch) == ["plan"]


def test_bound_claims_do_not_park(monkeypatch: Any) -> None:
    state = {"task": "t", "claims": [_claim("acceptance_test")], "iteration": 0}
    assert _drive_past_intake(state, monkeypatch) == ["plan"]


def test_replan_after_human_feedback_never_intake_parks(monkeypatch: Any) -> None:
    # A gate-deny re-plan (iteration > 0 / feedback present) means a human chose to continue.
    state = {
        "task": "t",
        "claims": [_claim("none")],
        "iteration": 1,
        "feedback": ["do it anyway"],
    }
    assert _drive_past_intake(state, monkeypatch) == ["plan"]
