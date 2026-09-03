"""End-to-end wiring test for the REAL orchestration graph.

`test_graph_build` only proves the graph compiles, and `apps/api`'s tests drive a
hand-written FAKE graph — so the actual node bodies + edge routing in
`mosaera_core.graph` had zero behavioral coverage (a wrong edge, a broken route
predicate, or a swapped node argument would pass the whole suite). This drives
`build_graph()` itself with fake models injected into the real nodes and a real
(offline subprocess) sandbox, through one approve→deliver cycle and one
deny→loop→finalize cycle.

Models are injected via `build_graph(model_factory=...)` — a fake role→model
factory — rather than monkeypatching module-global `get_chat_model`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from git import Repo
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from mosaera_core.agents_bridge import build_default_team
from mosaera_core.bench.escalation import diagnose_bottleneck
from mosaera_core.config import RoleModel, Settings
from mosaera_core.graph import build_graph
from mosaera_core.hygiene import HygieneReport
from mosaera_core.sandbox import SubprocessSandbox
from mosaera_core.tools.repo import clone_repo
from mosaera_policies import autonomous_resolution

#: The scripted PM plan — four factories use it, and truthiness alone cannot tell it from an error.
_PLAN = "1. inspect the file\n2. verify"


class FakeToolCallingModel(BaseChatModel):
    """Tool-capable fake for EVERY agent role — `create_agent` needs `bind_tools`; no tool calls,
    so the agent ends immediately. Never `FakeMessagesListChatModel` here: lacking `bind_tools`,
    the retry middleware turned `create_agent`'s NotImplementedError into a "Model call failed"
    message that `_last_ai_text` handed back AS OUTPUT — the PM planner never ran and `_PLAN` was
    dead text, until 2026-08-24 when 30 tests here failed at once."""

    responses: list[AIMessage]

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolCallingModel:
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        msg = self.responses[0] if len(self.responses) == 1 else self.responses.pop(0)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"


@pytest.fixture
def workspace(tmp_path: Path) -> Any:
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["a.py"])
    repo.index.commit("init")
    return clone_repo(str(src), tmp_path / "ws", "graph-int")


def _patch_models(review: str) -> Any:
    """Return a fake model_factory for build_graph(model_factory=...)."""

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content=_PLAN)])
        if role == "coder":
            return FakeToolCallingModel(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content=review)])

    return factory


def _drive(
    graph: Any,
    task: str,
    resume: dict[str, Any],
    max_cycles: int = 10,
    seed: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Run to the first pause, then resume with the same decision until the graph
    ends. Returns (final state values, number of gate interrupts resumed). ``seed`` merges
    extra declared RunState keys into the initial input (e.g. to isolate a gate branch)."""
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": task, **(seed or {})}, config)
    cycles = 0
    while graph.get_state(config).next and cycles < max_cycles:
        cycles += 1
        graph.invoke(Command(resume=resume), config)
    return graph.get_state(config).values, cycles


class _RecordingTeam:
    """Wraps the real AgentTeam, overriding only plan/design/author_tests. An override is
    either a callable (invoked with the real method's args — it may record into `records`
    and returns the stub) or a plain value (returned directly); left None, the method
    delegates to the real team. Every other member (coder, tester_enabled, review, clarify,
    diagnose, the instruction builders) delegates to the real team via __getattr__."""

    def __init__(self, real: Any, records: dict, plan: Any, design: Any, author_tests: Any):
        self._real = real
        self._records = records
        self._plan = plan
        self._design = design
        self._author_tests = author_tests

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def plan(self, task: str, overview: str, feedback: Any, config: Any) -> str:
        if self._plan is None:
            return self._real.plan(task, overview, feedback, config)
        return self._plan(task, overview, feedback, config) if callable(self._plan) else self._plan

    def design(self, task: str, plan: str, overview: str, feedback: Any, config: Any) -> str:
        if self._design is None:
            return self._real.design(task, plan, overview, feedback, config)
        if callable(self._design):
            return self._design(task, plan, overview, feedback, config)
        return self._design

    def author_tests(self, instruction: str, config: Any, corrections: Any = ()) -> Any:
        if self._author_tests is None:
            return self._real.author_tests(instruction, config)
        return (
            self._author_tests(instruction, config)
            if callable(self._author_tests)
            else self._author_tests
        )


def recording_team_factory(
    records: dict, *, plan: Any = None, design: Any = None, author_tests: Any = None
) -> Any:
    """A `team_factory` for build_graph(team_factory=...) that wraps the REAL team
    (build_default_team, so protected_tests/tools wiring is exercised for real) and overrides
    only plan/design/author_tests. Replaces the old monkeypatches of graph_mod.pm /
    graph_mod.build_tester_agent now that graph.py imports nothing from mosaera_agents."""

    def factory(settings: Settings, all_tools: Any, tester_tools: Any, model_factory: Any) -> Any:
        real = build_default_team(settings, all_tools, tester_tools, model_factory)
        return _RecordingTeam(real, records, plan, design, author_tests)

    return factory


def test_project_context_reaches_planning(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #26: the shared run-time context must actually reach the planner's overview,
    # not just be assembled and dropped. Spy on the team's plan to capture its input.
    factory = _patch_models(review="VERDICT: APPROVE")
    captured: dict[str, str] = {}

    def spy_plan(task: str, overview: str, feedback: Any, config: Any) -> str:
        captured["overview"] = overview
        return "1. inspect the file"

    graph = build_graph(
        Settings.from_env(),
        workspace,
        SubprocessSandbox(workspace.root),
        "ctx-run",
        source="local",
        checkpointer=InMemorySaver(),
        project_context="SHARED_CTX_MARKER: an earlier item added foo.py",
        model_factory=factory,
        team_factory=recording_team_factory(captured, plan=spy_plan),
    )
    graph.invoke(
        {"task": "do the thing"}, {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    )

    assert "SHARED_CTX_MARKER" in captured["overview"]  # context reached the plan
    assert "foo.py" in captured["overview"]
    assert "## Repository files" in captured["overview"]  # and the file listing still follows
    assert "## Doctrine" in captured["overview"]  # trusted global doctrine is prepended


def test_doctrine_kill_switch_drops_the_block(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # doctrine_enabled=False must drop the doctrine block (budget kill-switch).
    factory = _patch_models(review="VERDICT: APPROVE")
    captured: dict[str, str] = {}

    def spy_plan(task: str, overview: str, feedback: Any, config: Any) -> str:
        captured["overview"] = overview
        return "1. do it"

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False, doctrine_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        "no-doctrine",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
        team_factory=recording_team_factory(captured, plan=spy_plan),
    )
    graph.invoke({"task": "x"}, {"configurable": {"thread_id": "t"}, "recursion_limit": 80})
    assert "## Doctrine" not in captured["overview"]


def test_design_stage_produces_design_and_feeds_it_to_the_coder(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #3: plan → design → implement. The design builds on the plan, is stored in
    # state, and the coder's instruction includes both the plan and the design.
    coder_seen: dict[str, str] = {}

    class RecordingCoder(FakeToolCallingModel):
        def _generate(self, messages: list[BaseMessage], *a: Any, **k: Any) -> ChatResult:
            coder_seen["text"] = "\n".join(
                m.content for m in messages if isinstance(m.content, str)
            )
            return super()._generate(messages, *a, **k)

    def fake_get_chat_model(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            return RecordingCoder(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    seen: dict[str, str] = {}

    def fake_design(task: str, plan: str, overview: str, feedback: Any, config: Any) -> str:
        seen["plan"] = plan
        return "DESIGN_X: use the Foo interface"

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="design-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=fake_get_chat_model,
        team_factory=recording_team_factory(seen, plan="PLAN_X", design=fake_design),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "do the thing"}, config)
    final = graph.get_state(config).values

    assert seen["plan"] == "PLAN_X"  # design builds on the plan (plan → design order)
    assert final.get("design") == "DESIGN_X: use the Foo interface"  # stored in state
    assert "DESIGN_X" in coder_seen["text"] and "PLAN_X" in coder_seen["text"]  # coder saw both


def test_foresight_mitigations_reach_the_coder(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The design's actuated pre-mortem (RISK→MITIGATION→CHECK) is extracted into the
    # foresight state field AND appended to the coder's instruction as build requirements.
    coder_seen: dict[str, str] = {}

    class RecordingCoder(FakeToolCallingModel):
        def _generate(self, messages: list[BaseMessage], *a: Any, **k: Any) -> ChatResult:
            coder_seen["text"] = "\n".join(
                m.content for m in messages if isinstance(m.content, str)
            )
            return super()._generate(messages, *a, **k)

    def fake_get_chat_model(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            return RecordingCoder(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    design = (
        "## Approach\nx\n\n## Risks & mitigations\n"
        "- RISK: bad input → MITIGATION: validate → CHECK: raises ValueError\n"
    )

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="fs-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=fake_get_chat_model,
        team_factory=recording_team_factory({}, plan="PLAN", design=design),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "do the thing"}, config)
    final = graph.get_state(config).values

    assert final.get("foresight") and "raises ValueError" in final["foresight"]
    assert "Mitigations you MUST implement" in coder_seen["text"]
    assert "CHECK: raises ValueError" in coder_seen["text"]


def test_design_stage_grounds_in_named_file_contents(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P2: the design stage receives the CONTENTS of the files the plan names, not
    # just a filename list — so it grounds signatures in real code, not hallucination.
    factory = _patch_models(review="VERDICT: APPROVE")
    seen: dict[str, str] = {}

    def fake_design(task: str, plan: str, overview: str, feedback: Any, config: Any) -> str:
        seen["overview"] = overview
        return "DESIGN"

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="ground-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
        # The clone fixture ships a.py = "x = 1\n"; the plan names it.
        team_factory=recording_team_factory(
            seen, plan="1. Edit a.py to change x", design=fake_design
        ),
    )
    graph.invoke(
        {"task": "do the thing"}, {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    )

    assert "## Relevant file contents" in seen["overview"]
    assert (
        "a.py" in seen["overview"] and "x = 1" in seen["overview"]
    )  # actual contents reached design


def test_design_reused_from_the_item_when_stored_and_no_feedback(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fresh run of an already-designed item reuses the stored design — no model call
    # (deterministic-first: design once per item, reuse across runs) — but ONLY while the cache
    # KEY still matches the design's inputs (ADR-0084 §3, migration 0023).
    from mosaera_core.graph import nodes_plan

    monkeypatch.setattr(nodes_plan, "design_cache_key", lambda *a, **k: "KEY_X")
    factory = _patch_models(review="VERDICT: APPROVE")
    calls = {"design": 0}

    def fake_design(*a: Any, **k: Any) -> str:
        calls["design"] += 1
        return "FRESH_DESIGN"

    class FakeMem:
        def get_backlog_item(self, item_id: int) -> dict[str, str]:
            return {"design": "STORED_DESIGN", "design_key": "KEY_X"}

        def update_backlog_item(self, item_id: int, **kw: Any) -> None:
            pass

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="reuse-t",
        source="local",
        checkpointer=InMemorySaver(),
        memory=FakeMem(),  # type: ignore[arg-type]
        item_id=7,
        model_factory=factory,
        team_factory=recording_team_factory(calls, plan="PLAN_X", design=fake_design),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "do the thing"}, config)
    final = graph.get_state(config).values

    assert final.get("design") == "STORED_DESIGN"  # reused
    assert calls["design"] == 0  # no model call — the stored design was reused


def test_design_is_regenerated_when_the_cache_key_does_not_match(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0084 §3, and the defect it was written for. Measured 2026-08-06: a design authored the
    # previous day told the coder to import `src.budget_tracker.cli`; the operator corrected
    # exactly that at a write gate, and the run was STILL served the old design and wrote the
    # forbidden import. A stored design whose key does not match its inputs — including a NULL
    # key, i.e. every pre-0023 row — is stale, deny-by-default.
    from mosaera_core.graph import nodes_plan

    factory = _patch_models(review="VERDICT: APPROVE")
    calls = {"design": 0}

    def fake_design(*a: Any, **k: Any) -> str:
        calls["design"] += 1
        return "FRESH_DESIGN"

    monkeypatch.setattr(nodes_plan, "design_cache_key", lambda *a, **k: "KEY_NOW")
    saved: dict[str, Any] = {}

    class FakeMem:
        def get_backlog_item(self, item_id: int) -> dict[str, Any]:
            return {"design": "STALE_DESIGN", "design_key": None}  # a pre-0023 row

        def update_backlog_item(self, item_id: int, **kw: Any) -> None:
            saved.update(kw)

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        "graph-int",
        source="local",
        checkpointer=InMemorySaver(),
        memory=FakeMem(),  # type: ignore[arg-type]
        item_id=7,
        model_factory=factory,
        team_factory=recording_team_factory(calls, plan="PLAN_X", design=fake_design),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "do the thing"}, config)

    assert graph.get_state(config).values.get("design") == "FRESH_DESIGN"  # stale NOT served
    assert calls["design"] == 1
    # Design and key persist together — a design without its key reads stale forever, a key
    # without its design serves the wrong text.
    assert saved.get("design") == "FRESH_DESIGN"
    assert saved.get("design_key") == "KEY_NOW"


def test_real_graph_happy_path_runs_every_node_and_delivers(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _patch_models(review="VERDICT: APPROVE")
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-ok",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "keep x equal to 1", {"approve": True})

    assert cycles == 1  # exactly one deliver gate
    # Every node ran in order: plan → implement → capture → test → scan → review → gate → deliver.
    assert "inspect the file" in final.get("plan", "")  # plan_node — OURS, not just truthy
    assert "coder_summary" in final  # capture_node
    assert "test_output" in final and "validation_plan" in final  # test_node (real sandbox)
    assert "findings_text" in final  # scan_node
    # scan_enabled=False → honest "disabled" status (ADR-0076), never a false "clean"; the
    # gate adds no security_unverified reason, so the run still delivers.
    assert final.get("security_status") == "disabled"
    assert "security_unverified" not in (final.get("gate_decision") or {}).get("reasons", [])
    assert final.get("review") == "VERDICT: APPROVE"  # review_node
    assert final.get("approved") is True and final.get("gate_decision")  # gate_node
    assert final.get("report_path")  # deliver_node


def test_scan_expected_but_unavailable_parks_on_security_unverified(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0076: the mirror of the happy path. scan_enabled=True but the graph has NO scan
    # sandbox (the false-green path that used to ship as "clean") now emits security_status
    # "unavailable" and PARKS on `security_unverified` — even though tests pass and the
    # reviewer APPROVES. Deny-by-default: "we did not look" is never "clean".
    factory = _patch_models(review="VERDICT: APPROVE")
    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=True),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="sec-unverified",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    # Inspect the gate decision at the interrupt, before any human answer, so the AUTONOMOUS
    # verdict is what we read (same technique as the critic-veto test below).
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "keep x equal to 1"}, config)
    state = graph.get_state(config)
    assert state.values.get("security_status") == "unavailable"
    gd = state.tasks[0].interrupts[0].value["gate_decision"]
    assert "security_unverified" in gd["reasons"]
    assert autonomous_resolution(gd) == "park"


def test_held_out_critic_veto_parks_a_would_be_ship(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The end-to-end #60 (ADR-0065) property: a run whose tests PASS and whose reviewer APPROVES —
    # the exact shape that DELIVERS in test_real_graph_ok above — instead PARKS when the held-out
    # critic vetoes. Proves the critic node runs on the green path, records the veto, and that the
    # veto reaches the gate as `critic_vetoed` and forces an autonomous park (universal downgrade).
    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content=_PLAN)])
        if role == "coder":
            return FakeToolCallingModel(responses=[AIMessage(content="Done — no change needed.")])
        if role == "critic":
            return FakeToolCallingModel(
                responses=[AIMessage(content="VERDICT: VETO\nSpec requires x==2 but x stays 1.")]
            )
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False, critic_enabled=True),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="critic-veto",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    # Inspect the gate decision at the interrupt (before answering), so a human approve doesn't
    # mask the AUTONOMOUS verdict — same technique as the already-satisfied test.
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "keep x equal to 1"}, config)
    state = graph.get_state(config)
    values = state.values

    # The critic ran on the green run and recorded a veto...
    assert (values.get("outcome_verdict") or {}).get("vetoed") is True
    # ...though the reviewer would have shipped it (APPROVE)...
    assert values.get("review") == "VERDICT: APPROVE"
    # ...and the veto reaches the gate as `critic_vetoed`, parking the run autonomously.
    gd = state.tasks[0].interrupts[0].value["gate_decision"]
    assert "critic_vetoed" in gd["reasons"]
    assert autonomous_resolution(gd) == "park"


def test_real_graph_denial_loops_to_the_cap_then_finalizes_without_shipping(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _patch_models(review="VERDICT: BLOCK")
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-deny",
        source="local",
        max_iterations=2,
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "do the thing", {"approve": False, "feedback": "not yet"})

    # Denied at the gate → route_after_gate loops back to plan until the iteration
    # cap, then finalizes (deliver) WITHOUT approval — never ships.
    assert cycles >= 2  # gated more than once → it looped
    assert final.get("approved") is not True
    assert final.get("iteration", 0) >= 2  # reached the cap
    assert final.get("report_path")  # finalized a report
    assert not final.get("commit_sha")  # nothing committed (not approved)


def test_gate_stuck_on_the_same_reason_concludes_honest_park_below_the_cap(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #67 (ADR-0069): the gate-deny → re-plan loop has no breaker — a gate that keeps denying THE
    # SAME reason re-plans to the cap on correct code → thrash. The gate-loop honest-stop concludes
    # `honest_park` (give_up_reason, stalled False, strictly below the cap) after gate_stall_limit
    # same-reason denials. Cap of 6 leaves room below it for the breaker to fire (contrast the cap=2
    # test above, where the 2nd deny lands AT the cap so the guard correctly holds it back).
    from mosaera_core.bench.reliability import classify_outcome

    factory = _patch_models(review="VERDICT: BLOCK")  # reviewer blocks identically every cycle
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False, gate_stall_limit=2)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-gate-stuck",
        source="local",
        max_iterations=6,
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the thing", {"approve": False, "feedback": "not yet"})

    assert final.get("give_up_reason", "").startswith("gate kept denying")  # the named blocker
    assert not final.get("stalled")  # HONEST, never the thrash flag
    assert final.get("iteration", 0) < 6  # concluded strictly BELOW the cap
    assert (
        classify_outcome(final, errored=False, acceptance_failed=False, max_iterations=6)
        == "honest_park"
    )
    assert final.get("report_path") and not final.get("commit_sha")  # finalized, nothing shipped


def _fake_validation(monkeypatch: pytest.MonkeyPatch, outputs: Any) -> None:
    """Force validation to fail with the given output(s): a str repeats identically;
    a list yields a distinct output per call (progress)."""
    import types

    seen = {"n": 0}

    def fake_run_plan(*_a: Any, **_k: Any) -> Any:
        out = outputs if isinstance(outputs, str) else outputs[min(seen["n"], len(outputs) - 1)]
        seen["n"] += 1
        return types.SimpleNamespace(output=out, passed=False, step_results=[])

    monkeypatch.setattr(
        "mosaera_core.graph.nodes_impl.resolve_plan",
        lambda *a, **k: types.SimpleNamespace(
            as_dict=lambda: {"project_type": "python-pytest"}, pack_name="python"
        ),
    )
    monkeypatch.setattr("mosaera_core.graph.nodes_impl.run_plan", fake_run_plan)


def test_no_progress_breaker_trips_and_stops_before_the_cap(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unfixable task: validation fails IDENTICALLY every iteration. The breaker
    # must trip at stall_limit and finalize honestly — NOT loop to a high iteration
    # cap burning tokens (the 3.3M-token spiral this fixes).
    #
    # #81: pinned to honest_stop_no_signal=False, which is the PRE-#81 behaviour verbatim. This is
    # the OFF arm of the knob's A/B and the rollback proof — the ON arm (the default) is
    # test_uncountable_validation_concludes_as_an_honest_give_up below.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "AssertionError: boom at line 5")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        honest_stop_no_signal=False,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-stall",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert final.get("stalled") is True
    assert "same way" in final.get("stall_reason", "")
    assert final.get("iteration", 0) < 10  # stopped EARLY — did not loop to max_iter
    assert final.get("report_path") and not final.get("commit_sha")  # finalized, unshipped


def test_uncountable_validation_concludes_as_an_honest_give_up(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#81, the ON arm: a validator with NO countable result concludes honestly, not as thrash.

    Before this, a run whose validator reports no `N failed` line (SQL before stage 2, a
    well-formedness check, an operator --test-cmd) fingerprint-stalled → `stalled=True` → routed
    past every self-heal loop → bucketed thrash_park, while an identical PYTEST run took the
    supervise ladder to an honest_park. Same failure, different label, purely because one runner
    prints a number.
    """
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "psql:schema.sql:3: ERROR:  relation does not exist")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        honest_stop_no_signal=True,  # opt in: measured, default OFF (ADR-0077)
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-nosignal",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert not final.get("stalled")  # NOT the thrash signal
    give_up = final.get("give_up_reason", "")
    assert "no countable result" in give_up, give_up
    # The reason must name the actual failure, not an anonymous "same way N times" — that is what
    # makes the relabel honest rather than flattering.
    assert "relation does not exist" in give_up, give_up
    assert final.get("iteration", 0) < 10  # concluded strictly below the cap
    assert final.get("report_path") and not final.get("commit_sha")


def test_uncountable_validation_at_the_cap_is_still_thrash(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rung 3: rode-to-cap IS thrash and must never be dressed up. stall_limit=2 trips on the
    # SECOND identical failure (bump_stall needs limit > 1 to trip at all), which lands exactly at
    # max_iterations=2 — so the honest window is closed and the old stall park stands.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "psql: ERROR:  boom")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=2,
        stall_limit=2,
        honest_stop_no_signal=True,  # opt in: measured, default OFF (ADR-0077)
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-nosignal-cap",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})
    assert final.get("stalled") is True
    assert "no countable result" in final.get("stall_reason", "")


def test_uncountable_validation_still_reasons_first_when_enabled(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rung 1 is unchanged on the no-count path: reason-before-park (ADR-0017) still gets its
    # one-shot attempt before the run climbs to supervise. #81 changes the CONCLUSION, not the
    # ladder's shape — so a reason pass must still fire, and the run must still end honestly.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "psql: ERROR:  relation does not exist")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=12,
        stall_limit=2,
        reason_on_stall_enabled=True,
        max_reason_attempts=1,
        honest_stop_no_signal=True,  # opt in: measured, default OFF (ADR-0077)
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-nosignal-reason",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert final.get("reason_attempts") == 1  # the reason rung fired
    assert not final.get("stalled")  # ...and the run still concluded honestly, not as thrash
    assert "no countable result" in final.get("give_up_reason", "")


def test_uncountable_rescope_resets_the_fingerprint_streak(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A granted re-scope must actually get a fresh run at the problem.

    On the no-count path the ONLY progress signal is the fingerprint streak, and at the trip it
    already sits at the limit. Without an explicit reset the very next identical failure re-trips
    instantly and the re-scope the supervisor just granted is a no-op — so the run would conclude
    on the first post-re-scope evaluation instead of getting its `stall_limit` attempts.
    """
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "psql: ERROR:  boom")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=12,
        stall_limit=3,
        max_escalations=1,  # allow exactly one re-scope before the give-up
        honest_stop_no_signal=True,  # opt in: measured, default OFF (ADR-0077)
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-nosignal-rescope",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    # Two full episodes ran (the original + the re-scoped one), so the second genuinely re-tried
    # rather than re-tripping on its first evaluation.
    assert final.get("escalations", 0) == 2, final.get("escalations")
    assert not final.get("stalled")
    assert "no countable result" in final.get("give_up_reason", "")


def test_tampering_with_an_uncountable_validator_still_stalls(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE stage-4 security regression (ADR-0060 tamper invariant).

    `stalled` is overloaded: the no-progress breaker sets it, and so does the TAMPER branch — and
    route_after_test checks `stalled` BEFORE `progress_trip` precisely so a tampering run can never
    earn a supervise re-scope. #81 moves one producer (the no-count breaker) off `stalled`; this
    pins that the OTHER producer is untouched, so a run that edits its own protected tests still
    stalls straight to the gate and is classified thrash — never routed to supervise, never
    relabelled honest.
    """
    from mosaera_core.bench.reliability import classify_outcome

    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "psql: ERROR:  boom")  # uncountable, so #81's path would apply
    # Tamper fires: a baselined test whose content moved. Patched in `_tamper` — the one origin
    monkeypatch.setattr(
        "mosaera_core.graph._tamper.tampered_files",
        lambda *_a, **_k: ["tests/test_protected.py"],
    )
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        honest_stop_no_signal=True,  # opt in: measured, default OFF (ADR-0077)
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-tamper-nosignal",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "cheat the tests", {"approve": False, "feedback": "no"})

    assert final.get("stalled") is True, "tamper must still set the thrash signal"
    assert "modified" in final.get("stall_reason", "")
    assert not final.get("progress_trip")  # never took the supervise ladder
    assert not final.get("give_up_reason")  # never relabelled as an honest conclusion
    assert classify_outcome(final, errored=False, acceptance_failed=False) == "thrash_park"


def _fail_then_pass(monkeypatch: pytest.MonkeyPatch, fail_output: str, fail_times: int) -> None:
    """Validation fails IDENTICALLY `fail_times` times (same fingerprint → trips), then
    passes — for reason-before-park: the reason pass re-enters and the next attempt clears."""
    import types

    seen = {"n": 0}

    def fake_run_plan(*_a: Any, **_k: Any) -> Any:
        seen["n"] += 1
        if seen["n"] <= fail_times:
            return types.SimpleNamespace(output=fail_output, passed=False, step_results=[])
        return types.SimpleNamespace(output="1 passed", passed=True, step_results=[])

    monkeypatch.setattr(
        "mosaera_core.graph.nodes_impl.resolve_plan",
        lambda *a, **k: types.SimpleNamespace(
            as_dict=lambda: {"project_type": "python-pytest"}, pack_name="python"
        ),
    )
    monkeypatch.setattr("mosaera_core.graph.nodes_impl.run_plan", fake_run_plan)


def test_reason_on_stall_reasons_then_a_new_attempt_delivers(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0017: validation fails the SAME way stall_limit times → instead of parking, the
    # reason pass fires (streak reset, reason_attempts=1) and the next attempt passes → delivers.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fail_then_pass(monkeypatch, "AssertionError: boom at line 5", fail_times=3)
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=6,
        stall_limit=3,
        reason_on_stall_enabled=True,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-ok",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "get past the wall", {"approve": True})

    assert final.get("reason_attempts") == 1  # exactly one reason pass fired
    assert final.get("tests_passed") is True  # the new attempt cleared validation
    assert not final.get("stalled")  # it did NOT park
    assert final.get("approved") is True and final.get("report_path")  # delivered


def test_reason_budget_spent_parks_with_a_reasoned_note(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0017: validation always fails identically. The reason pass fires ONCE; when the
    # same failure re-trips with the budget spent, the run parks honestly (reasoned note).
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "AssertionError: boom at line 5")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        reason_on_stall_enabled=True,
        max_reason_attempts=1,
        # #81: these assert the REASON LADDER (attempts, tiers, fallback) and its
        # apply_trip-specific park text, so they are pinned to the pre-#81 conclusion.
        # The no-count path's own conclusion is covered by the dedicated #81 tests.
        honest_stop_no_signal=False,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-park",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert final.get("reason_attempts") == 1  # tried once, then gave up
    assert final.get("stalled") is True
    assert "reason-and-change-approach pass was already attempted" in final.get("stall_reason", "")
    assert final.get("iteration", 0) < 10  # bounded — did not loop to max_iter
    assert final.get("report_path") and not final.get("commit_sha")  # finalized, unshipped


def test_reason_pass_can_escalate_to_the_supervisor(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0017: the reason prompt preserves the escalate valve — a coder that yields
    # 'SUMMARY: escalate' on the reason re-entry routes to the supervisor (not a thrash).
    def fake_get_chat_model(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            # calls 1-3 = normal fix attempts; call 4 = the reason re-entry, which escalates.
            return FakeToolCallingModel(
                responses=[
                    AIMessage(content="Done."),
                    AIMessage(content="Done."),
                    AIMessage(content="Done."),
                    AIMessage(content="SUMMARY: escalate — the contract is unsatisfiable; decide"),
                ]
            )
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    _fake_validation(monkeypatch, "AssertionError: boom at line 5")

    graph = build_graph(
        Settings(
            home=tmp_path / ".mosaera",
            scan_enabled=False,
            max_iterations=10,
            stall_limit=3,
            reason_on_stall_enabled=True,
        ),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-esc",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=fake_get_chat_model,
        team_factory=recording_team_factory({}, plan="1. do it", design="## Approach\nx"),
    )
    final, _ = _drive(graph, "satisfy the impossible", {"resolution": "stop"})

    assert final.get("reason_attempts") == 1  # the reason pass ran...
    assert final.get("escalations", 0) >= 1  # ...and its SUMMARY: escalate reached the supervisor
    # #56 (ADR-0060): a stop-resolved hand-raise is an HONEST conclusion — give_up_reason set,
    # `stalled` left False so classify_outcome buckets it honest_park, not thrash.
    assert final.get("give_up_reason")
    assert not final.get("stalled")
    assert final.get("report_path") and not final.get("commit_sha")


def test_reason_disabled_by_default_parks_without_reasoning(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default OFF: an identical-fail run parks at stall_limit as before — no reason pass.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, "AssertionError: boom at line 5")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        # #81: asserts the REASON LADDER, not how the final park is labelled — pinned to the
        # pre-#81 conclusion. The no-count path's own conclusion has dedicated #81 tests.
        honest_stop_no_signal=False,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-off",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert not final.get("reason_attempts")  # the reason pass never fired
    assert final.get("stalled") is True
    assert "reason-and-change-approach" not in final.get("stall_reason", "")


# --- Reasoning-escalation ladder (ADR-0018) --------------------------------


def _patch_models_with_reasoner(
    coder_seen: dict[str, str],
    reasoner_calls: dict[str, int],
    *,
    reasoner_plan: str = "1. root cause: wrong op\n2. edit calc.py to use +",
    reasoner_raises: bool = False,
) -> Any:
    """Like `_patch_models`, but a `pm`-role call whose settings bind `deepseek-r1:32b` (the
    reasoning tier) returns a spy reasoner; the normal `pm` call stays the planner fake. The
    coder records the instruction it received so a test can assert the injected plan. Returns
    the fake model_factory for build_graph(model_factory=...)."""

    class RecordingCoder(FakeToolCallingModel):
        def _generate(self, messages: list[BaseMessage], *a: Any, **k: Any) -> ChatResult:
            coder_seen["text"] = "\n".join(
                m.content for m in messages if isinstance(m.content, str)
            )
            return super()._generate(messages, *a, **k)

    class RaisingModel(BaseChatModel):
        def _generate(self, messages: Any, *a: Any, **k: Any) -> ChatResult:
            raise RuntimeError("reasoner boom")

        @property
        def _llm_type(self) -> str:
            return "raising"

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm" and settings.pm_model == "deepseek-r1:32b":  # the reasoning tier
            reasoner_calls["n"] = reasoner_calls.get("n", 0) + 1
            if reasoner_raises:
                return RaisingModel()
            return FakeToolCallingModel(responses=[AIMessage(content=reasoner_plan)])
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content="1. inspect\n2. verify")])
        if role == "coder":
            return RecordingCoder(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    return factory


def test_reason_ladder_escalates_to_reasoner_tier_then_delivers(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0018: own-model pass 0 doesn't clear it, so pass 1 escalates to the reasoner tier,
    # whose plan is injected for the coder, and the next attempt passes → delivers.
    coder_seen: dict[str, str] = {}
    reasoner_calls: dict[str, int] = {}
    factory = _patch_models_with_reasoner(coder_seen, reasoner_calls)
    _fail_then_pass(monkeypatch, "AssertionError: boom at line 5", fail_times=4)
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=8,
        stall_limit=2,
        reason_on_stall_enabled=True,
        reason_escalation=[RoleModel(provider="ollama", model="deepseek-r1:32b")],
        # #81: these assert the REASON LADDER (attempts, tiers, fallback) and its
        # apply_trip-specific park text, so they are pinned to the pre-#81 conclusion.
        # The no-count path's own conclusion is covered by the dedicated #81 tests.
        honest_stop_no_signal=False,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-ladder",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "get past the wall", {"approve": True})

    assert final.get("reason_attempts") == 2  # pass0 own-model + pass1 reasoner tier
    assert reasoner_calls.get("n") == 1  # the reasoner tier fired exactly once
    assert "SENIOR ENGINEER'S PLAN" in coder_seen.get("text", "")  # the plan reached the coder
    assert "edit calc.py" in coder_seen.get("text", "")
    assert not final.get("stalled")
    assert final.get("approved") is True and final.get("report_path")


def test_reason_ladder_exhausted_still_parks(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reasoner tier fires but the coder still can't clear it → the ladder exhausts and the
    # run parks honestly, bounded (double bound: reason budget + iteration cap).
    coder_seen: dict[str, str] = {}
    reasoner_calls: dict[str, int] = {}
    factory = _patch_models_with_reasoner(coder_seen, reasoner_calls)
    _fake_validation(monkeypatch, "AssertionError: boom at line 5")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=12,
        stall_limit=2,
        reason_on_stall_enabled=True,
        reason_escalation=[RoleModel(provider="ollama", model="deepseek-r1:32b")],
        # #81: asserts the REASON LADDER, not how the final park is labelled — pinned to the
        # pre-#81 conclusion. The no-count path's own conclusion has dedicated #81 tests.
        honest_stop_no_signal=False,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-exhaust",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert final.get("reason_attempts") == 2  # own + reasoner, then the budget is spent
    assert reasoner_calls.get("n") == 1
    assert final.get("stalled") is True
    assert final.get("iteration", 0) < 12  # bounded — did not loop to the cap
    assert final.get("report_path") and not final.get("commit_sha")


def test_reason_ladder_reasoner_failure_falls_back_to_own_model(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A crashing reasoner must NEVER fail the run: the pass falls back to the own-model prompt
    # and the run stays bounded and finalizes cleanly.
    coder_seen: dict[str, str] = {}
    reasoner_calls: dict[str, int] = {}
    factory = _patch_models_with_reasoner(coder_seen, reasoner_calls, reasoner_raises=True)
    _fake_validation(monkeypatch, "AssertionError: boom at line 5")
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=12,
        stall_limit=2,
        reason_on_stall_enabled=True,
        reason_escalation=[RoleModel(provider="ollama", model="deepseek-r1:32b")],
        # #81: asserts the REASON LADDER, not how the final park is labelled — pinned to the
        # pre-#81 conclusion. The no-count path's own conclusion has dedicated #81 tests.
        honest_stop_no_signal=False,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-reason-fallback",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the impossible", {"approve": False, "feedback": "no"})

    assert reasoner_calls.get("n") == 1  # the reasoner tier was attempted...
    # ...and on its failure the coder got the own-model prompt, not the injected plan.
    assert "SENIOR ENGINEER'S PLAN" not in coder_seen.get("text", "")
    assert final.get("stalled") is True  # bounded, finalized cleanly (no crash)
    assert final.get("report_path")


def test_progressing_run_does_not_trip_the_breaker(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A run whose failure changes each iteration is (maybe) progressing — the breaker
    # must NOT trip (no false positive); it loops normally to the cap.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, ["alpha broke", "beta broke", "gamma broke", "delta broke"])
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False, max_iterations=3, stall_limit=3
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-prog",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "keep trying", {"approve": False, "feedback": "no"})

    assert not final.get("stalled")  # distinct failures → no stall
    assert final.get("iteration", 0) >= 3  # ran to the iteration cap instead


def test_coder_blocked_yield_finalizes_incomplete(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P1 baseline: a coder that raises its hand with 'SUMMARY: blocked — …' (it hit a
    # wall it cannot pass) must be believed — capture_node parses it and trips the
    # honest no-progress path so the run finalizes `incomplete` instead of looping.
    def fake_get_chat_model(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            return FakeToolCallingModel(
                responses=[
                    AIMessage(
                        content="SUMMARY: blocked — cannot rename files; the user must run "
                        "`git mv old.py new.py` themselves."
                    )
                ]
            )
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False, max_iterations=10),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="blocked-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=fake_get_chat_model,
        team_factory=recording_team_factory(
            {}, plan="1. rename the file", design="## Approach\nrename it"
        ),
    )
    final, _ = _drive(graph, "rename old.py to new.py", {"resolution": "stop", "feedback": "no"})

    # The blocked coder is routed to the supervisor; a give-up resolution finalizes honestly.
    # #56 (ADR-0060): "believed immediately — did not loop to the cap" IS the honest_park spec —
    # the give-up now records give_up_reason and leaves `stalled` False accordingly.
    assert final.get("escalations", 0) >= 1
    assert "blocked" in final.get("give_up_reason", "")
    assert not final.get("stalled")
    assert final.get("iteration", 0) < 10  # believed immediately — did not loop to the cap
    assert final.get("report_path") and not final.get("commit_sha")  # finalized, unshipped


def test_escalation_rescopes_to_plan_then_gives_up_at_max(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The supervise node routing (graph-level; mode-gating is runner-side): an escalation
    # re-scopes back to PLAN with the supervisor's feedback, then gives up at
    # max_escalations and finalizes incomplete. Here the resume is a fixed "rescope".
    plan_feedback: list[list[str]] = []

    def spy_plan(task: str, overview: str, feedback: Any, config: Any) -> str:
        plan_feedback.append(list(feedback))
        return "1. do it"

    def fake_get_chat_model(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            return FakeToolCallingModel(
                responses=[
                    AIMessage(content="SUMMARY: escalate — the task conflicts with test_x; decide")
                ]
            )
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    graph = build_graph(
        Settings(
            home=tmp_path / ".mosaera", scan_enabled=False, max_iterations=10, max_escalations=1
        ),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="esc-graph",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=fake_get_chat_model,
        team_factory=recording_team_factory({}, plan=spy_plan, design="## Approach\nx"),
    )
    final, _ = _drive(
        graph,
        "do the thing",
        {"resolution": "rescope", "feedback": "update test_x to the new contract"},
    )

    # The supervisor's re-scope reached plan_node's feedback (a later plan attempt saw it).
    assert any("supervisor re-scope" in f for fb in plan_feedback for f in fb)
    assert final.get("escalations", 0) >= 1
    # #56 (ADR-0060): an exhausted re-scope budget after a believed hand-raise is an honest
    # BOUNDED conclusion — give_up_reason, not a thrash-labeled stall.
    assert final.get("give_up_reason")
    assert not final.get("stalled")
    assert final.get("report_path") and not final.get("commit_sha")


def test_tester_authors_protected_tests_reaching_the_coder(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Test-first, strict (ADR-0013): with the tester enabled, author_tests runs between
    # design and implement, writes an acceptance test, marks it protected, and hands it to
    # the coder as a must-pass contract.
    def fake_author_tests(instruction: str, config: Any) -> dict[str, Any]:
        # Stands in for the tool-using tester: writes an acceptance test to tests/.
        (workspace.root / "tests").mkdir(exist_ok=True)
        (workspace.root / "tests" / "test_accept.py").write_text(
            "def test_contract():\n    assert True\n", encoding="utf-8"
        )
        return {"messages": [AIMessage(content="SUMMARY: wrote tests/test_accept.py")]}

    coder_seen: dict[str, str] = {}

    class RecordingCoder(FakeToolCallingModel):
        def _generate(self, messages: list[BaseMessage], *a: Any, **k: Any) -> ChatResult:
            coder_seen["text"] = "\n".join(
                m.content for m in messages if isinstance(m.content, str)
            )
            return super()._generate(messages, *a, **k)

    def fake_get_chat_model(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            return RecordingCoder(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False, tester_enabled=True),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="tester-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=fake_get_chat_model,
        team_factory=recording_team_factory(
            {}, plan="1. implement it", design="## Approach\nx", author_tests=fake_author_tests
        ),
    )
    final, _ = _drive(graph, "do the thing", {"approve": True})

    # The tester authored the acceptance test...
    assert "tests/test_accept.py" in final.get("authored_tests", [])
    # ...and the coder was handed it as an explicit must-pass contract.
    assert "Acceptance tests you must pass" in coder_seen.get("text", "")
    assert "tests/test_accept.py" in coder_seen.get("text", "")
    # ...and it passed the gate (the acceptance test passes on the no-op change).
    assert final.get("commit_sha")  # delivered


def test_already_satisfied_task_concludes_early_and_honestly_not_thrashing(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #44 (ADR-0052, post red-team): the Proctor's real-asserting acceptance suite passes on the
    # untouched tree, so no red→green proof can exist. The run must CONCLUDE EARLY + HONESTLY —
    # reach the gate in one pass (not a 138-call thrash to a mislabeled give-up) — but it must NOT
    # auto-deliver: a green-pre-impl suite can't confirm the requirement is met, so it PARKS on
    # oracle_unverified for a human, and the honest signals say "appears already satisfied".
    def fake_author_tests(instruction: str, config: Any) -> dict[str, Any]:
        # A real assertion (a Call, not a literal → clears the assertion floor), not skipped, and
        # already green with no implementation. stdlib-only, so it imports cleanly in the sandbox.
        (workspace.root / "tests").mkdir(exist_ok=True)
        (workspace.root / "tests" / "test_acc.py").write_text(
            "import math\n\n\ndef test_already_met():\n    assert math.factorial(5) == 120\n",
            encoding="utf-8",
        )
        return {"messages": [AIMessage(content="SUMMARY: wrote tests/test_acc.py")]}

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            # The acceptance already holds → the coder correctly makes no source change.
            return FakeToolCallingModel(responses=[AIMessage(content="Done — no change needed.")])
        # A SILENT reviewer (no VERDICT) — the realistic local-model case.
        return FakeToolCallingModel(responses=[AIMessage(content="Looks already done to me.")])

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False, tester_enabled=True),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="already-sat",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
        team_factory=recording_team_factory(
            {},
            plan="1. it may already be done",
            design="## Approach\nx",
            author_tests=fake_author_tests,
        ),
    )
    # Run to the first interrupt and inspect the gate decision there (before answering), so a human
    # approve/deny doesn't mask the AUTONOMOUS verdict.
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "ensure factorial(5) is 120"}, config)
    state = graph.get_state(config)
    values = state.values

    # 1. author_tests_node measured the already-satisfied signal (green-pre-impl, real-asserting).
    assert values.get("already_satisfied") is True
    assert values.get("tests_red_verified") is False and values.get("tests_assert_real") is True
    # 2. It reached the DELIVERY gate in one pass — not a supervise give-up, no thrash to the caps.
    intr = state.tasks[0].interrupts[0].value
    assert intr.get("action") == "deliver"
    # 3. NO auto-deliver: a green-pre-impl suite is not an independent oracle, so oracle_unverified
    #    fires and the autonomous policy PARKS. already_satisfied rides in state (honest reason).
    gd = intr["gate_decision"]
    assert "oracle_unverified" in gd["reasons"]
    assert autonomous_resolution(gd) == "park"


def test_already_satisfied_does_not_swallow_a_genuine_coder_escalate(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #44 red-team (ADR-0052): the already-satisfied route override must NOT discard a real coder
    # hand-raise. Here the suite is green pre-impl (already_satisfied True) but the coder escalates
    # that the requirement isn't actually covered — that must reach the supervisor, not auto-route
    # to the gate. (Guided mode → the escalation parks for a human.)
    def fake_author_tests(instruction: str, config: Any) -> dict[str, Any]:
        (workspace.root / "tests").mkdir(exist_ok=True)
        (workspace.root / "tests" / "test_acc.py").write_text(
            "import math\n\n\ndef test_partial():\n    assert math.factorial(5) == 120\n",
            encoding="utf-8",
        )
        return {"messages": [AIMessage(content="SUMMARY: wrote tests/test_acc.py")]}

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "coder":
            # A genuine escalate: the green suite doesn't cover the whole requirement.
            return FakeToolCallingModel(
                responses=[
                    AIMessage(
                        content="SUMMARY: escalate — acceptance suite is green but does not cover "
                        "the logging half; shipping now would be incomplete."
                    )
                ]
            )
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    graph = build_graph(
        Settings(
            home=tmp_path / ".mosaera", scan_enabled=False, tester_enabled=True
        ),  # guided (not autonomous)
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="already-sat-esc",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
        team_factory=recording_team_factory(
            {}, plan="1. do it", design="## Approach\nx", author_tests=fake_author_tests
        ),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "reject overdrafts AND log them"}, config)
    interrupt_val = graph.get_state(config).tasks[0].interrupts[0].value
    # The run raised the ESCALATION interrupt (supervisor), not the delivery gate — the coder's
    # hand-raise was respected despite already_satisfied being set.
    assert interrupt_val.get("action") == "escalation"
    assert interrupt_val.get("kind") == "escalate"


def test_degenerate_plan_concludes_an_honest_early_park_not_thrash(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #51 (ADR-0056): a fallback plan (the planner produced nothing usable) self-stops as an HONEST
    # EARLY park — routed straight to the gate BEFORE design/implement — instead of burning the
    # coder cycle then the supervise give-up (honest since #56, but later). At `cautious` the
    # plan_stall_limit is 1, so it trips on the very FIRST fallback.
    from mosaera_agents import pm
    from mosaera_core.bench.reliability import HONEST_PARK, classify_outcome

    design_calls: list[int] = []

    def spy_design(task: str, plan: str, overview: str, feedback: Any, config: Any) -> str:
        design_calls.append(1)
        return "## Approach\nx"

    graph = build_graph(
        Settings(
            home=tmp_path / ".mosaera", scan_enabled=False, reliability_sensitivity="cautious"
        ),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="degen-plan",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=_patch_models(review="VERDICT: APPROVE"),
        team_factory=recording_team_factory({}, plan=pm._FALLBACK_PLAN, design=spy_design),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "do something underspecified"}, config)
    state = graph.get_state(config)
    values = state.values

    # It self-stopped at the plan with an honest reason, NOT stalled, and design NEVER ran.
    assert values.get("plan_unworkable_reason")
    assert not values.get("stalled")
    assert design_calls == []
    # It paused at the DELIVERY gate (the early honest park), not a supervise give-up.
    assert state.tasks[0].interrupts[0].value.get("action") == "deliver"
    # The scoreboard buckets it CLEAN (honest_park), converting the old late thrash_park.
    assert classify_outcome(values, errored=False, acceptance_failed=False, max_iterations=2) == (
        HONEST_PARK
    )


def test_second_degenerate_plan_trips_the_breaker_before_the_supervise_give_up(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #51 (ADR-0056): at `balanced` (plan_stall_limit=2) the FIRST fallback still takes the
    # degraded-plan → supervise re-scope (one more try), but a SECOND consecutive fallback trips the
    # plan-breaker and self-stops as an HONEST EARLY park — intercepting the supervise give-up that
    # used to grind a full extra cycle. Proves the "plan" stall-streak accrues across a re-scope.
    from mosaera_agents import pm

    graph = build_graph(
        Settings(
            home=tmp_path / ".mosaera", scan_enabled=False, max_escalations=1
        ),  # balanced default
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="degen-twice",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=_patch_models(review="VERDICT: APPROVE"),
        team_factory=recording_team_factory({}, plan=pm._FALLBACK_PLAN, design="## Approach\nx"),
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 80}
    graph.invoke({"task": "underspecified"}, config)
    # 1st interrupt: the degraded-plan escalation (supervise) — the breaker hasn't tripped yet.
    assert graph.get_state(config).tasks[0].interrupts[0].value.get("action") == "escalation"
    # Re-scope → plan re-runs → the 2nd fallback trips the breaker → routes to the gate, not another
    # supervise round (which at max_escalations=1 would give up — honest since #56, but later).
    graph.invoke(Command(resume={"resolution": "rescope", "feedback": "try again"}), config)
    state = graph.get_state(config)
    assert state.values.get("plan_unworkable_reason")
    assert not state.values.get("stalled")
    assert state.tasks[0].interrupts[0].value.get("action") == "deliver"


def test_coder_tampering_with_a_pre_existing_test_is_caught_end_to_end(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0036 + the ADR-0026 completion, proven through the REAL compiled graph (not a
    # hand-built state dict). A pre-existing test encodes a requirement the coder hasn't met;
    # the coder "passes" it by WEAKENING it. The suite then goes green — and before this fix,
    # a silent reviewer + that green "suite" would have shipped it autonomously.
    (workspace.root / "tests").mkdir(exist_ok=True)
    contract = workspace.root / "tests" / "test_contract.py"
    contract.write_text(
        "def test_contract():\n    assert False  # a real requirement, not yet met\n",
        encoding="utf-8",
    )

    tampered_once = {"done": False}

    class TamperingCoder(FakeToolCallingModel):
        def _generate(self, messages: list[BaseMessage], *a: Any, **k: Any) -> ChatResult:
            # Simulate the coder editing the pre-existing test to make it pass — the exact
            # manufacture-a-green-suite move the integrity baseline exists to catch.
            if not tampered_once["done"]:
                contract.write_text(
                    "def test_contract():\n    assert True  # weakened\n", encoding="utf-8"
                )
                tampered_once["done"] = True
            return super()._generate(messages, *a, **k)

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content="1. do it")])
        if role == "coder":
            return TamperingCoder(responses=[AIMessage(content="Done.")])
        # A SILENT reviewer (no VERDICT) — the case ADR-0034's backstop would otherwise ship.
        return FakeToolCallingModel(responses=[AIMessage(content="Looks fine to me.")])

    graph = build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="tamper-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "meet the contract in test_contract.py", {"approve": True})

    # 1. The dead signal is DEAD no more: declared in RunState, it survives the reducer.
    assert final.get("tests_modified") is True
    assert "tests/test_contract.py" in (final.get("tampered_paths") or [])
    # 2. The gate raised the dedicated reason, and it can never ride the silence backstop.
    gd = final["gate_decision"]
    assert "tests_tampered" in gd["reasons"]
    assert autonomous_resolution(gd) == "park"
    # 3. The ADR-0026 escalation rule finally fires from a LIVE run (it reads tests_modified,
    #    which used to be dropped) — the tamper is attributed to the coder, not a weak tester.
    assert (
        diagnose_bottleneck(final, Settings(home=tmp_path / ".mosaera", scan_enabled=False))
        == "coder"
    )


def _standing_suite_repo(workspace: Any) -> None:
    """Give the clone a pre-existing, real-asserting suite so the standing-suite oracle credits it:
    it lands in the integrity baseline and asserts a NON-trivial property (`2 + 2 == 4` — left is a
    BinOp, so it clears the assertion floor), and it passes → the validation is green + strength
    "suite". This isolates the Phase-1b wiring: the ONLY thing that can move oracle_verified is the
    mutation verdict, which each test controls by patching `suite_catches_a_mutation`."""
    (workspace.root / "tests").mkdir(exist_ok=True)
    (workspace.root / "tests" / "test_c.py").write_text(
        "def test_c():\n    assert 2 + 2 == 4\n", encoding="utf-8"
    )


def _mutation_graph(workspace: Any, tmp_path: Path, reviewer: str) -> Any:
    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content="1. do it")])
        if role == "coder":
            return FakeToolCallingModel(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content=reviewer)])

    return build_graph(
        Settings(home=tmp_path / ".mosaera", scan_enabled=False, oracle_mutation_check=True),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="mut-t",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )


def test_surviving_mutation_downgrades_the_oracle_and_parks(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 1b, the safety property: a green suite that a reviewer even APPROVED must still not
    # auto-ship if it demonstrably CANNOT fail bad code. The mutation survives → oracle_verified is
    # downgraded → the gate raises `oracle_unverified` → autonomous parks, no matter the approve.
    _standing_suite_repo(workspace)
    monkeypatch.setattr("mosaera_core.oraclecheck.suite_catches_a_mutation", lambda *a, **k: False)
    graph = _mutation_graph(workspace, tmp_path, reviewer="VERDICT: APPROVE")
    final, _ = _drive(graph, "do the thing", {"approve": True})

    assert final.get("tests_mutation_caught") is False
    gd = final["gate_decision"]
    assert "oracle_unverified" in gd["reasons"]
    assert autonomous_resolution(gd) == "park"


def test_caught_mutation_keeps_the_oracle_and_ships(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other side: the mutation is CAUGHT (suite went red under it) → the suite is a real oracle
    # → oracle_verified stays True → the run ships autonomously with no `oracle_unverified` park.
    _standing_suite_repo(workspace)
    monkeypatch.setattr("mosaera_core.oraclecheck.suite_catches_a_mutation", lambda *a, **k: True)
    graph = _mutation_graph(workspace, tmp_path, reviewer="VERDICT: APPROVE")
    final, _ = _drive(graph, "do the thing", {"approve": True})

    assert final.get("tests_mutation_caught") is True
    gd = final["gate_decision"]
    assert "oracle_unverified" not in gd["reasons"]
    assert autonomous_resolution(gd) == "approve"
    assert final.get("commit_sha")  # delivered


def test_mutation_check_off_never_consults_the_suite(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Opt-in (default OFF): with the knob off, the extra sandbox run is never spent — the mutation
    # helper is not even consulted (it would raise if it were), and the run ships on the standing
    # suite exactly as before. Proves Phase 1b adds zero cost/behaviour change when disabled.
    _standing_suite_repo(workspace)

    def _boom(*_a: Any, **_k: Any) -> bool:
        raise AssertionError("suite_catches_a_mutation must not run when the knob is off")

    monkeypatch.setattr("mosaera_core.oraclecheck.suite_catches_a_mutation", _boom)

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content="1. do it")])
        if role == "coder":
            return FakeToolCallingModel(responses=[AIMessage(content="Done — no change needed.")])
        return FakeToolCallingModel(responses=[AIMessage(content="VERDICT: APPROVE")])

    graph = build_graph(
        Settings(
            home=tmp_path / ".mosaera", scan_enabled=False
        ),  # oracle_mutation_check defaults False
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="mut-off",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the thing", {"approve": True})

    assert final.get("tests_mutation_caught") is None  # never computed
    assert autonomous_resolution(final["gate_decision"]) == "approve"
    assert final.get("commit_sha")  # delivered on the standing suite, unchanged


def test_unmeasured_mutation_ships_a_normal_run(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Baseline for the #54 tightening: with the mutation check ON but the verdict UNMEASURED (None),
    # a NORMAL run (no proctor_edits) still ships — deny-by-default only parks on a proven False.
    _standing_suite_repo(workspace)
    monkeypatch.setattr("mosaera_core.oraclecheck.suite_catches_a_mutation", lambda *a, **k: None)
    graph = _mutation_graph(workspace, tmp_path, reviewer="VERDICT: APPROVE")
    final, _ = _drive(graph, "do the thing", {"approve": True})

    assert final.get("tests_mutation_caught") is None
    assert "oracle_unverified" not in final["gate_decision"]["reasons"]
    assert final.get("commit_sha")  # None mutation does not block a normal run


def test_proctor_edited_run_requires_a_proven_mutation_catch(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #54 (ADR-0058), the tighter gate: once the Proctor has repaired a pre-existing test up front
    # (proctor_edits present), gaming is structurally closed by coder-blind timing, but an HONEST
    # over-relax could still ship — so the run vouches ONLY on a PROVEN catch. Same setup as
    # above (mutation UNMEASURED → None), but with proctor_edits seeded → it must now PARK where the
    # normal run shipped. proctor_edits names a path NOT in the standing baseline, so it is inert to
    # the tamper check and only trips the gate's stricter mutation requirement.
    _standing_suite_repo(workspace)
    monkeypatch.setattr("mosaera_core.oraclecheck.suite_catches_a_mutation", lambda *a, **k: None)
    graph = _mutation_graph(workspace, tmp_path, reviewer="VERDICT: APPROVE")
    final, _ = _drive(
        graph, "do the thing", {"approve": True}, seed={"proctor_edits": {"tests/other.py": "abc"}}
    )

    assert final.get("tests_mutation_caught") is None
    gd = final["gate_decision"]
    assert "oracle_unverified" in gd["reasons"]  # None can't vouch a proctor-edited run
    assert autonomous_resolution(gd) == "park"


def _no_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force validation to be unavailable (passed=None) — a project type with no
    automated validator (JS / unknown)."""
    import types

    monkeypatch.setattr(
        "mosaera_core.graph.nodes_impl.resolve_plan",
        lambda *a, **k: types.SimpleNamespace(
            as_dict=lambda: {"project_type": "javascript", "strength": "none"},
            pack_name="node",
        ),
    )
    monkeypatch.setattr(
        "mosaera_core.graph.nodes_impl.run_plan",
        lambda *a, **k: types.SimpleNamespace(
            output="[no validation available]", passed=None, step_results=[]
        ),
    )


def test_deliver_unverified_on_delivers_with_caveat(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P3: no automated validator + toggle ON → deliver-with-caveat (tests_passed=True
    # + the unverified flag), not park forever.
    factory = _patch_models(review="VERDICT: APPROVE")
    _no_validator(monkeypatch)
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False, deliver_unverified=True)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="unv-on",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "build a JS thing", {"approve": True})
    assert final.get("validation_unverified") is True
    assert final.get("tests_passed") is True  # caveated pass, recorded "unverified"
    assert final.get("approved") is True and final.get("report_path")


def test_deliver_unverified_with_a_silent_reviewer_never_ships_autonomously(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # THE composition that was never tested (ADR-0034). `deliver_unverified` coerces
    # tests_passed None→True upstream of the gate, and reviewer silence used to ride the
    # ADR-0031 backstop — so two individually-defensible opt-ins composed into an autonomous
    # ship with ZERO evidence of any kind: no validator ran, and no reviewer signed off.
    # Drive the REAL graph, then ask the REAL policy what it would have done unattended.
    factory = _patch_models(review="The change looks reasonable to me.")  # no VERDICT → silence
    _no_validator(monkeypatch)
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False, deliver_unverified=True)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="unv-silent",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "build a JS thing", {"approve": True})
    gd = final["gate_decision"]
    assert gd["reviewer_verdict"] == "UNKNOWN"
    assert gd["tests_passed"] is True  # the coerced pass...
    assert gd["validation_strength"] == "none"  # ...standing for nothing executed
    assert gd["reasons"] == ["reviewer_unknown"]
    assert autonomous_resolution(gd) == "park"  # would NOT have shipped unattended
    # A human resume with no actor is never branded a human override — we under-claim
    # rather than blame a person for a decision we can't attribute.
    assert gd["human_override"] is False


def test_a_conflicting_verdict_parks_instead_of_shipping(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Verdict-conflict poisoning (ADR-0034): the reviewer genuinely objects, but its notes also
    # quote a "VERDICT: APPROVE" it read in the repo. Two distinct verdicts used to parse to
    # UNKNOWN — i.e. SILENCE — which with green tests rode the backstop straight to an
    # autonomous ship, laundering a real veto into a delivery.
    review = (
        "The README claims: VERDICT: APPROVE\n"
        "But the diff drops the error handling the plan asked for.\n"
        "VERDICT: REQUEST_CHANGES"
    )
    factory = _patch_models(review=review)
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="conflict",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "add a feature", {"approve": True})
    gd = final["gate_decision"]
    assert gd["reviewer_verdict"] == "CONFLICT"
    assert gd["reasons"] == ["reviewer_conflict"]  # NOT reviewer_unknown → not silence
    assert autonomous_resolution(gd) == "park"  # a human decides what the reviewer meant


def test_a_human_approving_over_blocking_reasons_is_recorded_as_an_override(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the honesty fix: a REAL person approving despite blocking reasons IS
    # a human override, and must still be recorded as one.
    factory = _patch_models(review="VERDICT: BLOCK\nthis is wrong")
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="override",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "add a feature", {"approve": True, "actor": "human"})
    gd = final["gate_decision"]
    assert gd["reasons"] == ["reviewer_blocked"]
    assert gd["human_override"] is True


def test_deliver_unverified_off_stays_unavailable(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default OFF: no validator → tests_passed stays None (park behavior preserved).
    factory = _patch_models(review="VERDICT: APPROVE")
    _no_validator(monkeypatch)
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False
    )  # deliver_unverified defaults False
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="unv-off",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "build a JS thing", {"approve": True})
    assert not final.get("validation_unverified")
    assert final.get("tests_passed") is None  # unavailable, not a caveated pass


def test_below_bar_change_triggers_one_targeted_quality_revise_then_delivers(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 2: with the quality-revise loop enabled, a below-bar first pass loops
    # review→quality_revise→implement once, then (now at bar) proceeds to the gate
    # and delivers. Quality measurement is monkeypatched so the wiring — not ruff —
    # is under test: below bar first, at bar after the revise.
    from mosaera_core.quality import QualityDimension, QualityScore

    factory = _patch_models(review="VERDICT: APPROVE")

    below = QualityScore(
        66, [QualityDimension("Complexity", 60, ""), QualityDimension("Style", 72, "")]
    )
    at_bar = QualityScore(
        95, [QualityDimension("Complexity", 90, ""), QualityDimension("Style", 100, "")]
    )
    seen = {"n": 0}

    def fake_run_quality(ws: Any, diff: str) -> QualityScore:
        seen["n"] += 1
        return below if seen["n"] == 1 else at_bar

    monkeypatch.setattr("mosaera_core.graph.nodes_review.run_quality", fake_run_quality)
    monkeypatch.setattr(
        "mosaera_core.graph.nodes_review.quality_findings",
        lambda ws, paths: {"Complexity": ["pkg/x.py:1 C901 too complex"]},
    )

    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False, quality_revise_enabled=True)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-quality",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "do the thing", {"approve": True})

    assert cycles == 1  # exactly one deliver gate — the revise happened before it
    assert final.get("quality_revises") == 1  # one targeted revise fired
    assert final.get("quality_revise_log")  # trail recorded for the evidence log
    assert "Complexity" in final["quality_revise_log"][0]  # targeted the weak dimension
    assert seen["n"] >= 2  # quality was re-measured after the revise
    assert final.get("approved") is True and final.get("report_path")  # delivered


def test_quality_revise_disabled_by_default_goes_straight_to_gate(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default (opt-in off): even a below-bar change never revises — Phase-1 behavior.
    from mosaera_core.quality import QualityDimension, QualityScore

    factory = _patch_models(review="VERDICT: APPROVE")
    below = QualityScore(40, [QualityDimension("Complexity", 40, "")])
    monkeypatch.setattr("mosaera_core.graph.nodes_review.run_quality", lambda ws, diff: below)

    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False
    )  # quality_revise_enabled defaults False
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-noq",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "do the thing", {"approve": True})

    assert cycles == 1
    assert not final.get("quality_revises")  # never revised
    assert final.get("approved") is True


def _patch_models_reviews(reviews: list[str]) -> Any:
    """Like _patch_models, but the reviewer returns a SEQUENCE of verdicts across
    successive review_node calls (a single-element list repeats). The reviewer model
    instance is shared so its responses pop across calls. Returns the fake model_factory
    for build_graph(model_factory=...)."""
    reviewer_model = FakeToolCallingModel(responses=[AIMessage(content=r) for r in reviews])

    def factory(role: str, settings: Settings) -> BaseChatModel:
        if role == "pm":
            return FakeToolCallingModel(responses=[AIMessage(content=_PLAN)])
        if role == "coder":
            return FakeToolCallingModel(responses=[AIMessage(content="Done — addressed it.")])
        return reviewer_model

    return factory


def test_reviewer_request_changes_auto_fixes_then_delivers(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default ON: a first-pass REQUEST_CHANGES routes to a TARGETED review_fix loop
    # (review → review_fix → implement → … → review) and, once the reviewer approves,
    # proceeds to the gate — the change-request itself never parks a human.
    factory = _patch_models_reviews(
        ["VERDICT: REQUEST_CHANGES\nRename x to y for clarity.", "VERDICT: APPROVE"],
    )
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False
    )  # review_fix_enabled defaults True
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-revfix",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "rename x", {"approve": True})

    assert cycles == 1  # exactly one deliver gate — the REQUEST_CHANGES fixed itself first
    assert final.get("review_revises") == 1  # one targeted reviewer-fix fired
    assert final.get("review_revise_log")  # trail recorded for the evidence log
    assert final.get("iteration", 0) >= 1  # the loop shares (and advances) the budget
    assert final.get("approved") is True and final.get("report_path")  # delivered


def test_reviewer_loop_breaker_trips_before_the_cap(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reviewer keeps requesting the SAME change: the no-progress breaker (now in
    # review_node) must trip at stall_limit and park honestly — NOT loop the review_fix
    # cycle to a high iteration cap.
    factory = _patch_models_reviews(["VERDICT: REQUEST_CHANGES\nthe same unmet ask"])
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False, max_iterations=10, stall_limit=3
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-revstall",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(
        graph, "satisfy the impossible reviewer", {"approve": False, "feedback": "no"}
    )

    assert final.get("stalled") is True
    assert "same change" in final.get("stall_reason", "")
    assert final.get("iteration", 0) < 10  # stopped EARLY — did not loop to max_iter
    assert "review" in (final.get("stall_by_kind") or {})  # per-kind streak was tracked
    assert final.get("report_path") and not final.get("commit_sha")  # finalized, unshipped


def test_reviewer_fix_disabled_goes_straight_to_gate(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MOSAERA_REVIEW_FIX off: a REQUEST_CHANGES no longer auto-loops the coder — it
    # reaches the delivery gate directly (the legacy park/re-plan behavior).
    factory = _patch_models_reviews(["VERDICT: REQUEST_CHANGES\nplease change it"])
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False, review_fix_enabled=False, max_iterations=2
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-revoff",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "change it", {"approve": False, "feedback": "no"})

    assert not final.get("review_revises")  # the auto-fix loop never ran
    assert cycles >= 1  # reached the gate (parked for a human)
    assert final.get("approved") is not True


def _patch_hygiene(monkeypatch: pytest.MonkeyPatch, findings_seq: list[list[str]]) -> None:
    """Drive the hygiene node deterministically: a fixed changed-file, a no-op autofix,
    and a SEQUENCE of residual findings (the last entry repeats)."""
    seen = {"n": 0}

    def fake_findings(ws: Any, files: list[str]) -> HygieneReport:
        i = min(seen["n"], len(findings_seq) - 1)
        seen["n"] += 1
        return HygieneReport(findings=findings_seq[i], unavailable=[])

    monkeypatch.setattr(
        "mosaera_core.graph.nodes_impl.hygiene_targets", lambda ws, diff: ["mod.py"]
    )
    monkeypatch.setattr("mosaera_core.graph.nodes_impl.autofix", lambda ws, files: False)
    monkeypatch.setattr("mosaera_core.graph.nodes_impl.hygiene_findings", fake_findings)


def test_clean_change_passes_the_hygiene_gate_without_looping(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gate ON, but the change has no residual lint/type issues (the coder fake makes no
    # edits → no changed files) → hygiene finds nothing and proceeds to scan/deliver.
    factory = _patch_models(review="VERDICT: APPROVE")
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False
    )  # hygiene_gate_enabled defaults True
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-hyg-clean",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "keep x equal to 1", {"approve": True})

    assert cycles == 1
    assert not final.get("hygiene_fixes")  # no residual → no coder loop
    assert final.get("approved") is True and final.get("report_path")


def test_residual_lint_triggers_one_hygiene_fix_then_delivers(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A residual type/lint issue on the first pass loops the coder once (hygiene_fix →
    # implement → … → hygiene); the re-check is clean, so it proceeds to the gate.
    factory = _patch_models(review="VERDICT: APPROVE")
    _patch_hygiene(monkeypatch, [["mod.py:1 F821 undefined name 'foo'"], []])
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-hyg-fix",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, cycles = _drive(graph, "define foo", {"approve": True})

    assert cycles == 1  # only the delivery gate — hygiene fixed itself first
    assert final.get("hygiene_fixes") == 1
    assert final.get("hygiene_fix_log")  # trail recorded for the evidence log
    assert final.get("iteration", 0) >= 1  # the loop shares (and advances) the budget
    assert final.get("approved") is True and final.get("report_path")


def test_hygiene_breaker_trips_before_the_cap(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same lint/type issue survives every coder pass → the no-progress breaker (in
    # hygiene_node) trips and parks honestly, rather than looping to a high cap.
    factory = _patch_models(review="VERDICT: APPROVE")
    _patch_hygiene(monkeypatch, [["mod.py:1 F821 undefined name 'foo'"]])  # always the same
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        hygiene_max_fixes=10,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-hyg-stall",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "chase an unfixable lint", {"approve": False, "feedback": "no"})

    assert final.get("stalled") is True
    assert "lint/type issue" in final.get("stall_reason", "")
    assert final.get("iteration", 0) < 10  # stopped EARLY — did not loop to max_iter


def test_hygiene_gate_disabled_goes_straight_to_scan(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MOSAERA_HYGIENE_GATE off: test goes straight to scan; the hygiene node never runs
    # even when there would be residual findings.
    factory = _patch_models(review="VERDICT: APPROVE")
    _patch_hygiene(monkeypatch, [["mod.py:1 F821 undefined name 'foo'"]])
    settings = Settings(home=tmp_path / ".mosaera", scan_enabled=False, hygiene_gate_enabled=False)
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-hyg-off",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "do the thing", {"approve": True})

    assert not final.get("hygiene_fixes")  # the gate never ran
    assert final.get("hygiene_findings") is None  # hygiene_node was skipped entirely
    assert final.get("approved") is True and final.get("report_path")


def test_max_iterations_clamped_prevents_runaway(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An over-large max_iterations (the UI once sent 999 for "Unlimited") must be
    # CLAMPED to the ceiling so a long non-converging run bounds and parks instead of
    # crashing with GraphRecursionError. Distinct failures + a high stall_limit keep the
    # no-progress breaker from stopping it early, so only the clamp bounds it.
    factory = _patch_models(review="VERDICT: APPROVE")
    _fake_validation(monkeypatch, ["e1", "e2", "e3", "e4", "e5", "e6", "e7"])
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=999,
        stall_limit=99,
        max_iterations_ceiling=5,
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-clamp",
        source="local",
        max_iterations=999,  # caller also passes the unbounded value
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "loop forever", {"approve": False, "feedback": "no"})

    assert final.get("iteration", 0) <= 5  # clamped to the ceiling, never ran toward 999
    assert final.get("report_path")  # finalized cleanly (no GraphRecursionError)


def test_review_fix_bounded_by_review_max_fixes(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reviewer keeps requesting DISTINCT changes (so the breaker won't trip); the
    # review-fix loop must still stop at review_max_fixes rather than running the shared
    # iteration budget dry (the previously-dead review_revises limiter is now enforced).
    factory = _patch_models_reviews(
        [
            "VERDICT: REQUEST_CHANGES\nrename a",
            "VERDICT: REQUEST_CHANGES\nrename b",
            "VERDICT: REQUEST_CHANGES\nrename c",
            "VERDICT: REQUEST_CHANGES\nrename d",
        ],
    )
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False, max_iterations=8, review_max_fixes=2
    )
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="int-revcap",
        source="local",
        max_iterations=8,
        checkpointer=InMemorySaver(),
        model_factory=factory,
    )
    final, _ = _drive(graph, "endless nitpicks", {"approve": True})

    assert final.get("review_revises") == 2  # stopped at the sub-cap, not the iteration cap


# --- The honest-stop: progress breaker → supervise → give_up_reason (#56, ADR-0060) -----

# Pytest-style failing output WITH a summary count + FAILED lines: the PARSEABLE path that
# feeds the progress breaker (the fingerprint path is exercised by the AssertionError tests).
_FLAT_FAIL = "FAILED tests/test_x.py::test_a - assert 1 == 2\n=== 5 failed, 3 passed ==="


def _honest_stop_graph(
    workspace: Any,
    tmp_path: Path,
    settings: Settings,
    run_id: str,
    max_iterations: int | None = None,
) -> Any:
    return build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id=run_id,
        source="local",
        max_iterations=max_iterations,
        checkpointer=InMemorySaver(),
        model_factory=_patch_models(review="VERDICT: APPROVE"),
        team_factory=recording_team_factory({}, plan="1. do it", design="## Approach\nx"),
    )


def test_progress_breaker_trips_rescopes_once_then_gives_up_honest_park(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The arc's core spec (#56): flat failing counts trip the breaker → supervise re-scopes
    # once (autonomous) → a second no-convergence episode gives up EARLY with an accurate
    # reason — and the FROZEN classifier buckets it honest_park (stalled False, below cap).
    from mosaera_core.bench.reliability import classify_outcome

    _fake_validation(monkeypatch, _FLAT_FAIL)
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        max_escalations=1,
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-core")
    final, _ = _drive(
        graph, "make the suite pass", {"resolution": "rescope", "feedback": "try again"}
    )

    assert final.get("escalations") == 2  # one re-scope granted, then the honest give-up
    assert final.get("give_up_reason", "").startswith("no convergence")
    assert not final.get("stalled")  # the honest field, never the thrash flag
    assert final.get("iteration", 0) < 10  # concluded strictly below the cap
    # The re-scope RESET the tracker: the second episode needed its own three evals.
    assert len((final.get("progress_track") or {}).get("history", [])) == 3
    assert final.get("report_path") and not final.get("commit_sha")
    # The frozen classifier (metric integrity: driven as a CONSUMER, never edited):
    assert (
        classify_outcome(final, errored=False, acceptance_failed=False, max_iterations=10)
        == "honest_park"
    )
    # Escalation continuity: the give-up park still attributes the bottleneck to the coder,
    # so a model-escalation re-run (ADR-0016) fires on exactly these honest parks.
    assert diagnose_bottleneck(final, settings) == "coder"


def test_progress_breaker_cautious_gives_up_immediately(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # cautious (#51 dial): stall_limit≤2 + max_escalations=0 → the FIRST trip concludes —
    # the "flag it right away" behavior, still an honest park under the frozen classifier.
    # Mirrors the BENCH shape: the case cap (build_graph max_iterations=6) overrides the
    # cautious iteration clamp, exactly as harness.run_case passes case.max_iterations.
    from mosaera_core.bench.reliability import classify_outcome

    _fake_validation(monkeypatch, _FLAT_FAIL)
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False, reliability_sensitivity="cautious"
    )
    graph = _honest_stop_graph(
        workspace, tmp_path, settings, "honest-stop-cautious", max_iterations=6
    )
    final, _ = _drive(graph, "make the suite pass", {"resolution": "rescope"})

    assert final.get("escalations") == 1  # supervise visited once — and concluded
    assert final.get("give_up_reason", "").startswith("no convergence")
    assert not final.get("stalled")
    assert final.get("iteration", 0) < 6  # tripped at streak 1 (cautious stall_limit=2)
    assert (
        classify_outcome(final, errored=False, acceptance_failed=False, max_iterations=6)
        == "honest_park"
    )


def test_progress_breaker_budget_short_skips_the_rescope(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The budget-aware ladder (#56 sanity-check fix): with a small cap, a granted re-scope
    # would run dry mid-cycle and ride to the cap (thrash under the frozen classifier) — so
    # supervise gives up NOW, strictly below the cap, even though escalations remain.
    from mosaera_core.bench.reliability import classify_outcome

    _fake_validation(monkeypatch, _FLAT_FAIL)
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=4,
        stall_limit=3,
        max_escalations=1,
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-budget")
    final, _ = _drive(graph, "make the suite pass", {"resolution": "rescope"})

    assert final.get("escalations") == 1  # first supervise visit → immediate honest give-up
    assert final.get("give_up_reason", "").startswith("no convergence")
    assert not final.get("stalled")
    assert final.get("iteration", 0) < 4
    assert (
        classify_outcome(final, errored=False, acceptance_failed=False, max_iterations=4)
        == "honest_park"
    )


def test_improving_counts_never_trip_the_progress_breaker(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 5 → 3 → 1: every attempt beats the best → no trip, no supervise; the run spends its
    # budget in the fix loop (an exhausted-but-converging run is the iteration cap's job).
    _fake_validation(
        monkeypatch,
        [
            "FAILED t.py::a\n=== 5 failed ===",
            "FAILED t.py::a\n=== 3 failed ===",
            "FAILED t.py::a\n=== 1 failed ===",
        ],
    )
    settings = Settings(
        home=tmp_path / ".mosaera", scan_enabled=False, max_iterations=3, stall_limit=3
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-improving")
    final, _ = _drive(graph, "make the suite pass", {"approve": False, "feedback": "no"})

    assert final.get("escalations", 0) == 0  # supervise never entered
    assert not final.get("give_up_reason")
    assert not final.get("progress_trip")


def test_oscillating_counts_trip_the_progress_breaker(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 5 → 6 → 5 never beats best=5 → a non-converging streak the old prev-vs-now window and
    # the digit-stripped fingerprint both miss. Trips → supervise → honest give-up.
    _fake_validation(
        monkeypatch,
        [
            "FAILED t.py::a\n=== 5 failed ===",
            "FAILED t.py::b\n=== 6 failed ===",
            "FAILED t.py::a\n=== 5 failed ===",
        ],
    )
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=10,
        stall_limit=3,
        max_escalations=0,
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-osc")
    final, _ = _drive(graph, "make the suite pass", {"resolution": "rescope"})

    assert final.get("give_up_reason", "").startswith("no convergence")
    assert not final.get("stalled")


def test_reason_pass_diverts_before_the_supervise_ladder(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rung order (#56): with reason-on-stall ON and budget to spare, the FIRST trip diverts
    # to the reason pass (streak reset, best kept); the breaker then re-trips and climbs to
    # supervise → give-up. All three rungs bounded; the conclusion is still honest.
    from mosaera_core.bench.reliability import classify_outcome

    _fake_validation(monkeypatch, _FLAT_FAIL)
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=12,
        max_iterations_ceiling=12,
        stall_limit=3,
        max_escalations=1,
        reason_on_stall_enabled=True,
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-reason")
    final, _ = _drive(graph, "make the suite pass", {"resolution": "rescope"}, max_cycles=12)

    assert final.get("reason_attempts") == 1  # rung 1 ran once (budget max_reason=1)
    assert final.get("escalations") == 2  # rung 2 re-scoped once, then the give-up
    assert final.get("give_up_reason", "").startswith("no convergence")
    assert not final.get("stalled")
    assert final.get("iteration", 0) < 12
    assert (
        classify_outcome(final, errored=False, acceptance_failed=False, max_iterations=12)
        == "honest_park"
    )


def test_projected_non_convergence_forces_give_up_not_a_rescope(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #65: a SLOW crawl (12 → 11 → 10) keeps beating its best, so the streak breaker never
    # trips — but the optimistic-rate projection sees it can't reach 0 in the remaining budget.
    # A projected trip must FORCE the supervisor to give up (honest_park), NOT grant a re-scope
    # that restarts the same crawl and rides to the cap (thrash). The resolver SAYS "rescope";
    # the projection overrides it. Contrast test_progress_breaker_trips_rescopes... (escalations
    # == 2, a streak trip that DOES re-scope once): here supervise is visited exactly once.
    from mosaera_core.bench.reliability import classify_outcome

    _fake_validation(
        monkeypatch,
        [
            "FAILED t.py::a\n=== 12 failed ===",
            "FAILED t.py::a\n=== 11 failed ===",
            "FAILED t.py::a\n=== 10 failed ===",
        ],
    )
    # max_iterations=8: at the 3rd eval (iteration 3) remaining=5, and 10/(avg-rate 1)=10 > 5 →
    # projected. budget_short is False here (8-3=5 > stall_limit-1) so the give-up is attributable
    # to the projection alone, not the budget ladder.
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=8,
        stall_limit=3,
        max_escalations=1,
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-projected")
    final, _ = _drive(
        graph, "make the suite pass", {"resolution": "rescope", "feedback": "keep trying"}
    )

    assert final.get("escalations") == 1  # supervise visited ONCE — the re-scope was refused
    assert final.get("give_up_reason", "").startswith("no convergence")
    # the projection's diagnosis ("improving too slowly"), not a streak ("non-improving")
    assert "too slowly" in final.get("give_up_reason", "")
    assert not final.get("stalled")  # honest, never the thrash flag
    assert final.get("iteration", 0) < 8  # concluded strictly below the cap
    assert (
        classify_outcome(final, errored=False, acceptance_failed=False, max_iterations=8)
        == "honest_park"
    )


def test_projection_off_lets_the_slow_crawl_keep_fixing(
    workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The knob gates it: with honest_stop_projection OFF, the same always-improving crawl never
    # trips the streak breaker either, so the run spends its budget in the fix loop (supervise
    # never entered) — proving the projection, not some other path, is what concludes it above.
    _fake_validation(
        monkeypatch,
        [
            "FAILED t.py::a\n=== 12 failed ===",
            "FAILED t.py::a\n=== 11 failed ===",
            "FAILED t.py::a\n=== 10 failed ===",
        ],
    )
    settings = Settings(
        home=tmp_path / ".mosaera",
        scan_enabled=False,
        max_iterations=3,  # a small cap so the run ends without a 4th validation
        stall_limit=3,
        honest_stop_projection=False,
    )
    graph = _honest_stop_graph(workspace, tmp_path, settings, "honest-stop-proj-off")
    final, _ = _drive(graph, "make the suite pass", {"resolution": "rescope"})

    assert final.get("escalations", 0) == 0  # supervise never entered — no projected trip
    assert not final.get("give_up_reason")
    assert not final.get("progress_trip")


def test_route_after_test_stalled_wins_over_a_progress_trip() -> None:
    # Precedence (pure router): a stalled park (tamper, or the unparseable-output
    # fingerprint breaker) must NEVER earn a supervise re-scope — stalled outranks the trip.
    from types import SimpleNamespace

    from mosaera_core.graph.nodes_impl import route_after_test

    ctx: Any = SimpleNamespace(settings=SimpleNamespace(hygiene_gate_enabled=True), max_iter=6)
    state: Any = {"stalled": True, "progress_trip": {"reason": "x"}, "tests_passed": False}
    assert route_after_test(ctx, state) == "hygiene"  # not "supervise"
    state = {"progress_trip": {"reason": "x"}, "tests_passed": False, "iteration": 2}
    assert route_after_test(ctx, state) == "supervise"  # the trip routes when not stalled
