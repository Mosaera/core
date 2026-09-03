"""The planner says WHY it produced nothing (F39 / issue #71) — offline sentinels.

A fallback plan has three causes that demand OPPOSITE responses from a human: raise a budget,
restart a server, or clarify the item. Until now all three arrived as one sentence that guessed
("budget exhausted or empty") and, two attempts later, as one that blamed the item ("needs
clarification or a smaller scope").

Measured 2026-08-07 on the live box: the planner spent all 12 of its model calls reading a
five-slice repo and had none left to write with. The run told the operator their backlog item
needed clarification — the item was fine — and the gate then said validation was unavailable, which
sent them to check Docker. Three hops, three wrong answers, one hour.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mosaera_core.graph import nodes_plan
from mosaera_core.graph.nodes_plan import plan_node


class _FallbackAgents:
    """A planner that always falls back, for a stated reason."""

    def __init__(self, why: str) -> None:
        self._why = why

    def plan(self, *a: Any, **k: Any) -> str:
        return (
            "1. Inspect the relevant files.\n"
            "2. Make the smallest change that satisfies the task.\n"
            "3. Run the tests and iterate until they pass."
        )

    def plan_is_fallback(self, plan: str) -> bool:
        return True

    def plan_fallback_reason(self) -> str:
        return self._why

    def plan_fallback_evidence(self) -> str:
        return ""


def _ctx(why: str, *, stall: bool = True) -> Any:
    return SimpleNamespace(
        agents=_FallbackAgents(why),
        workspace=None,
        memory=None,
        item_id=None,
        settings=SimpleNamespace(
            stall_detection_enabled=stall, plan_stall_limit=2, pm_step_limit=20
        ),
    )


@pytest.fixture(autouse=True)
def _no_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repo overview needs a real workspace; this suite is about ATTRIBUTION, not grounding."""
    monkeypatch.setattr(nodes_plan, "planning_overview", lambda ctx: "(files)")


def _drive(why: str, streak: int = 0) -> dict[str, Any]:
    state: dict[str, Any] = {
        "task": "t",
        "integrity_baseline": {"x": "y"},  # non-empty so plan_node doesn't touch the workspace
        "stall_by_kind": {"plan": ["<<FALLBACK>>", streak]},
    }
    return plan_node(_ctx(why), state, None)  # type: ignore[arg-type]


# --- the hand-raise names the cause ------------------------------------------------------------


def test_budget_exhaustion_names_the_budget_and_its_knob() -> None:
    out = _drive("budget_exhausted")
    reason = out["escalate_reason"]
    assert "20-call budget" in reason  # the actual limit, so the operator can act
    assert "pm_step_limit" in reason  # and the knob to change


def test_a_transport_failure_points_at_the_endpoint() -> None:
    reason = _drive("model_failed")["escalate_reason"]
    assert "never reached the model" in reason
    assert "endpoint" in reason


def test_an_empty_response_claims_nothing_it_cannot_know() -> None:
    assert _drive("empty")["escalate_reason"] == "planner returned no grounded plan"


# --- the give-up reason must not blame the item for an engine limit ----------------------------


def test_needs_clarification_is_reserved_for_the_empty_case() -> None:
    """THE regression pin. "needs clarification or a smaller scope" sends a human to rewrite a
    backlog item. That is right when the model had nothing to say, and wrong — actively
    misleading — when the engine ran out of model calls or could not reach the server."""
    assert "needs clarification" in _drive("empty", streak=1)["plan_unworkable_reason"]
    for why in ("budget_exhausted", "model_failed"):
        assert "needs clarification" not in _drive(why, streak=1)["plan_unworkable_reason"]


def test_the_budget_give_up_says_the_item_is_not_the_problem() -> None:
    reason = _drive("budget_exhausted", streak=1)["plan_unworkable_reason"]
    assert "pm_step_limit" in reason
    assert "the item is not the problem" in reason


def test_a_transport_give_up_calls_itself_infrastructure() -> None:
    reason = _drive("model_failed", streak=1)["plan_unworkable_reason"]
    assert "infrastructure" in reason
    assert "not a limit of the task" in reason


def test_every_cause_produces_a_DIFFERENT_operator_string() -> None:
    """If any two collapse, the operator is back to guessing between 'raise a budget' and
    'restart a server' — which is the whole defect."""
    causes = ("budget_exhausted", "model_failed", "empty")
    assert len({_drive(w)["escalate_reason"] for w in causes}) == 3
    assert len({_drive(w, streak=1)["plan_unworkable_reason"] for w in causes}) == 3


def test_the_give_up_reason_fits_the_durable_column() -> None:
    """`runs.termination_reason` is 80 chars. A reason that is truncated to uselessness is the
    same defect wearing a different hat."""
    for why in ("budget_exhausted", "model_failed", "empty"):
        assert len(_drive(why, streak=1)["plan_unworkable_reason"]) <= 200


def test_a_real_plan_raises_nothing() -> None:
    """The quiet path stays quiet: no fallback ⇒ no escalate_reason, no give-up."""

    class _GoodAgents(_FallbackAgents):
        def plan(self, *a: Any, **k: Any) -> str:
            return "1. Do the actual thing.\n2. Verify it."

        def plan_is_fallback(self, plan: str) -> bool:
            return False

    ctx = _ctx("empty")
    ctx.agents = _GoodAgents("empty")
    out = plan_node(ctx, {"task": "t", "integrity_baseline": {"x": "y"}}, None)  # type: ignore[arg-type]
    assert "escalate_reason" not in out
    assert "plan_unworkable_reason" not in out


# --- the evidence reaches the run record (#71, F39) --------------------------------------------


class _EvidenceAgents(_FallbackAgents):
    def plan_fallback_evidence(self) -> str:
        return "messages=9 ai=4\n--- ai[-1] done_reason='length' content_len=0 reasoning_len=812"


def test_the_raw_evidence_lands_in_run_state() -> None:
    ctx = _ctx("empty")
    ctx.agents = _EvidenceAgents("empty")
    out = plan_node(ctx, {"task": "t", "integrity_baseline": {"x": "y"}}, None)  # type: ignore[arg-type]
    assert "done_reason='length'" in out["plan_fallback_evidence"]


def test_a_healthy_plan_records_no_evidence() -> None:
    """Only a FALLBACK explains itself. A clean run must not carry a diagnostic payload."""

    class _Good(_EvidenceAgents):
        def plan(self, *a: Any, **k: Any) -> str:
            return "1. Do the thing."

        def plan_is_fallback(self, plan: str) -> bool:
            return False

    ctx = _ctx("empty")
    ctx.agents = _Good("empty")
    out = plan_node(ctx, {"task": "t", "integrity_baseline": {"x": "y"}}, None)  # type: ignore[arg-type]
    assert "plan_fallback_evidence" not in out


def test_persist_writes_the_evidence_as_a_decision() -> None:
    """It must reach the DURABLE record, not just RunState — the whole point is that a human can
    read it after the run is over, which is when they actually go looking."""
    from mosaera_core.persist import persist_run

    written: list[tuple[str, str]] = []

    class _Mem:
        def __getattr__(self, name: str) -> Any:  # every other persist call is a no-op
            return lambda *a, **k: None

        def add_decision(self, run_id: str, kind: str, content: str) -> None:
            written.append((kind, content))

    persist_run(
        _Mem(),  # type: ignore[arg-type]
        SimpleNamespace(reports_dir=None),  # type: ignore[arg-type]
        "r1",
        source="local",
        branch="b",
        state={"plan_fallback_evidence": "done_reason='length'"},
        commit_sha="",
    )
    assert ("plan_fallback_evidence", "done_reason='length'") in written


# --- a NEW subsystem must never corrupt the record that predates it ----------------------------


def _record_contract_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Drive `persist_run` and capture what reached the contract registry."""
    from mosaera_core.persist import persist_run

    rows: list[dict[str, Any]] = []

    class _Mem:
        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

        def record_test_contract(self, project_id: str, path: str, **kw: Any) -> None:
            rows.append({"path": path, **kw})

    persist_run(
        _Mem(),  # type: ignore[arg-type]
        SimpleNamespace(reports_dir=None),  # type: ignore[arg-type]
        "r1",
        source="local",
        branch="b",
        state={"approved": True, "gate_decision": {"action": "deliver", "reasons": []}, **state},
        commit_sha="abc123",
        project_id="proj-1",
        item_id=7,
        workspace_root=None,
    )
    return rows


def test_a_test_authored_AND_amended_in_one_run_is_a_DELIVERY_not_an_amendment() -> None:
    """#76 red team, round 2 — FIX-NOW, caught before it reached the registry's first real rows.

    An amendment renegotiates a bar that already existed, so it must have been baselined. A path
    the Proctor both authored and amended within THIS run is new to the project whatever happened
    to it mid-run: version 1. Recording it as `amended` would claim a prior version that was never
    delivered — and `proctor_edits` only ever holds BASELINED paths, so the row would also have
    carried an EMPTY content hash. Item 88 produces exactly this shape."""
    rows = _record_contract_rows(
        {
            "integrity_baseline": {},
            "authored_tests": ["tests/test_new.py"],
            "tests_baseline": {"tests/test_new.py": "rawhash"},
            "amended_tests": ["tests/test_new.py"],
            "amendment_reason": "the bar could not be met",
        }
    )
    assert [r["path"] for r in rows] == ["tests/test_new.py"]
    assert rows[0]["provenance"] == "delivered"
    assert rows[0]["content_hash"] == "rawhash"  # pinned, never blank
    assert rows[0]["authorized_by"] is None
    assert rows[0]["amend_reason"] == ""


def test_amending_a_BASELINED_bar_is_still_recorded_as_an_amendment() -> None:
    """The other side of the same rule — the inherited origin must be unchanged."""
    rows = _record_contract_rows(
        {
            "integrity_baseline": {"tests/test_old.py": "h"},
            "authored_tests": [],
            "amended_tests": ["tests/test_old.py"],
            "proctor_edits": {"tests/test_old.py": "integrityhash"},
            "amendment_reason": "the requirement changed",
        }
    )
    assert rows[0]["provenance"] == "amended"
    assert rows[0]["content_hash"] == "integrityhash"
    assert rows[0]["authorized_by"] == "human"
    assert rows[0]["amend_reason"] == "the requirement changed"


def test_a_broken_contract_registry_does_not_lose_the_run_record() -> None:
    """`persist_run` wraps its whole body in ONE try/except and the registry write sits mid-way,
    so an exception there would skip the gate decision, receipt, test results, claims AND the
    final `record_run` status flip — leaving a delivered run stuck in its interim state.

    The concrete way this happens is a deploy that restarts the API without running
    `make db-migrate`: the API does NOT apply migrations on boot, so `test_contracts` simply is
    not there. That must degrade to a warning, never to a mangled record.
    """
    from mosaera_core.persist import persist_run

    written: list[str] = []

    class _Mem:
        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

        def add_decision(self, run_id: str, kind: str, content: str) -> None:
            written.append(kind)

        def record_run(self, *a: Any, **k: Any) -> None:
            written.append("record_run")

        def record_test_contract(self, *a: Any, **k: Any) -> None:
            raise RuntimeError('relation "test_contracts" does not exist')

    persist_run(
        _Mem(),  # type: ignore[arg-type]
        SimpleNamespace(reports_dir=None),  # type: ignore[arg-type]
        "r1",
        source="local",
        branch="b",
        state={
            "approved": True,
            "plan": "a plan",
            "authored_tests": ["tests/test_new.py"],
            "gate_decision": {"action": "deliver", "reasons": []},
        },
        commit_sha="abc123",
        project_id="proj-1",
        item_id=7,
        workspace_root=None,
    )
    # The evidence AFTER the registry write must still be there — that is the whole point.
    assert "gate_decision" in written
    assert "record_run" in written
