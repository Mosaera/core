"""D4 (#116): the guided-run SSE stream must survive its own interactions — no duplicated
transcript on a reconnect, no connection silently dying during a long approval park.

Split out of ``test_api.py`` (whose god-file ratchet is at its recorded ceiling) rather than
grown there — this file owns the stream-cursor/heartbeat behavior of
``RunSessionBase._emit`` / ``LifecycleMixin._subscribe``/``events``/``aevents``
(``runner/_base.py``, ``runner/_lifecycle.py``) and the ``/api/runs/{id}/events`` route
(``routes/runs.py``).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, TypedDict, cast

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from mosaera_api.app import RunSubmit, create_app


class _State(TypedDict, total=False):
    task: str
    plan: str
    iteration: int
    approved: bool


def _build_fake_graph() -> Any:
    """A minimal plan -> gate -> deliver graph, mirroring production's gate_node closely enough
    to exercise a real park/approve/complete cycle (the real thing the SSE route streams)."""
    from mosaera_agents.reviewer import parse_reviewer_verdict
    from mosaera_policies import evaluate_gate

    def plan_node(state: _State) -> dict[str, Any]:
        return {"plan": f"1. do: {state['task']}", "iteration": state.get("iteration", 0) + 1}

    def gate_node(state: _State) -> dict[str, Any]:
        gd = evaluate_gate(
            tests_passed=True,
            reviewer_verdict=parse_reviewer_verdict("VERDICT: APPROVE\nok"),
            findings_count=0,
            iteration=state.get("iteration", 0),
            max_iterations=1,
            oracle_verified=True,
        )
        raw = interrupt(
            {"action": "deliver", "summary": "approve delivery?", "gate_decision": gd.as_dict()}
        )
        approved = bool(raw.get("approve")) if isinstance(raw, dict) else False
        return {"approved": approved, "gate_decision": gd.as_dict()}

    def deliver_node(state: _State) -> dict[str, Any]:
        return {"report_path": "/tmp/report.md", "commit_sha": "deadbeef"}  # noqa: S108

    builder: StateGraph = StateGraph(_State)
    builder.add_node("plan", plan_node)
    builder.add_node("gate", gate_node)
    builder.add_node("deliver", deliver_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "gate")
    builder.add_edge("gate", "deliver")
    builder.add_edge("deliver", END)
    return builder.compile(checkpointer=InMemorySaver())


def _factory(req: RunSubmit, run_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], None]:
    graph = _build_fake_graph()
    config = {"configurable": {"thread_id": run_id}}
    return graph, config, {"task": req.task}, None


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(graph_factory=_factory))


def _wait_for(client: TestClient, run_id: str, status: str, tries: int = 100) -> dict[str, Any]:
    import time

    for _ in range(tries):
        snap = client.get(f"/api/runs/{run_id}").json()
        if snap["status"] == status:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"run did not reach {status}; last={snap}")


def test_events_stream_carries_id_and_last_event_id_resumes_past_it(client: TestClient) -> None:
    """Every frame carries an `id:` line (its history cursor). A browser's automatic EventSource
    reconnect resends the last one it saw as `Last-Event-ID`; the route must honor it and replay
    only what came AFTER — a fresh (no-cursor) connection still gets the whole replay (existing
    first-connect semantics), but a resume must not re-deliver what a dropped connection already
    showed the client, which is exactly what duplicated the live transcript.

    Every stream read here happens AFTER the run is terminal: `aevents()` (by design, see
    `_lifecycle.py`) only ends on `_end`/terminal-drained, so draining one opened mid-park would
    block forever — this only exercises what a real reconnect resumes past, not an open
    connection's own liveness across a still-live park (unit-tested directly below)."""
    run_id = client.post("/api/runs", json={"repo": "x", "task": "t"}).json()["run_id"]
    _wait_for(client, run_id, "awaiting_approval")
    client.post(f"/api/runs/{run_id}/approve", json={"approve": True})
    _wait_for(client, run_id, "completed")

    with client.stream("GET", f"/api/runs/{run_id}/events") as fresh:
        fresh_body = "".join(chunk for chunk in fresh.iter_text())
    fresh_ids = [int(ln[4:]) for ln in fresh_body.splitlines() if ln.startswith("id: ")]
    assert fresh_ids, "no id: line on a fresh (no-cursor) replay"
    assert "event: update" in fresh_body  # a bare reconnect (no cursor) still replays everything

    # Resume from the FIRST event this run ever emitted — a real Last-Event-ID would come from
    # the last frame a dropped connection actually saw, but any real cursor proves the same
    # thing: what came at-or-before it is skipped, what came after still arrives.
    cursor = fresh_ids[0]
    with client.stream(
        "GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(cursor)}
    ) as resumed:
        resumed_body = "".join(chunk for chunk in resumed.iter_text())
    resumed_ids = [int(ln[4:]) for ln in resumed_body.splitlines() if ln.startswith("id: ")]
    assert resumed_ids, "a Last-Event-ID resume delivered nothing after the cursor"
    assert min(resumed_ids) > cursor  # nothing at-or-before the cursor was re-sent
    assert len(resumed_ids) < len(fresh_ids)  # strictly less than the full replay


def test_events_after_cursor_skips_already_seen_backlog() -> None:
    # `_subscribe`/`events(after=...)` is the resume primitive the SSE route drives from
    # Last-Event-ID — a subscriber that already saw up to sid N must only get what came after.
    from mosaera_api.runner import RunSession

    s = RunSession("cursor", graph=None, config={}, initial={})
    s._emit("update", {"n": 1})  # sid 1
    s._emit("update", {"n": 2})  # sid 2
    s._emit("update", {"n": 3})  # sid 3
    s.status = "completed"
    assert [e["data"]["n"] for e in s.events()] == [1, 2, 3]  # no cursor: full replay, unchanged
    assert [e["data"]["n"] for e in s.events(after=1)] == [2, 3]
    assert [e["data"]["n"] for e in s.events(after=3)] == []


def test_aevents_after_cursor_skips_already_seen_backlog() -> None:
    import asyncio

    from mosaera_api.runner import RunSession

    s = RunSession("acursor", graph=None, config={}, initial={})
    s._emit("update", {"n": 1})
    s._emit("update", {"n": 2})
    s.status = "completed"

    async def drain(after: int) -> list[int]:
        return [e["data"]["n"] async for e in s.aevents(after=after)]

    assert asyncio.run(drain(0)) == [1, 2]
    assert asyncio.run(drain(1)) == [2]


def test_aevents_emits_a_heartbeat_ping_during_a_long_idle_park(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An awaiting_approval park is exactly where the stream goes quiet for however long a human
    # takes to decide — the one shape an idle proxy/NAT timeout is most likely to kill.
    # aevents() must emit a synthetic, sid-less `_ping` after enough silence so the SSE route can
    # keep bytes flowing (rendered as a bare comment — never a dispatched client event, and never
    # a resume cursor, since it carries no sid).
    import asyncio

    import mosaera_api.runner._lifecycle as lifecycle_mod
    from mosaera_api.runner import RunSession

    monkeypatch.setattr(lifecycle_mod, "_HEARTBEAT_IDLE_POLLS", 2)  # ~0.5s instead of ~15s
    s = RunSession("heartbeat", graph=None, config={}, initial={})
    s.status = "awaiting_approval"  # not terminal: the poll loop stays open, idle

    async def drain_one() -> dict[str, Any]:
        gen = cast(AsyncGenerator[dict[str, Any], None], s.aevents())
        try:
            return await gen.__anext__()
        finally:
            await gen.aclose()

    ping = asyncio.run(drain_one())
    assert ping["type"] == "_ping"
    assert "sid" not in ping
