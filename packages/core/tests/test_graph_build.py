"""The graph must assemble and compile fully offline (models are lazy at build time)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from git import Repo
from mosaera_core.config import Settings
from mosaera_core.graph import build_graph, fix_instruction, recursion_limit_for
from mosaera_core.progress import parse_yield
from mosaera_core.sandbox import SubprocessSandbox
from mosaera_core.tools.repo import clone_repo


@pytest.fixture
def workspace(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["a.py"])
    repo.index.commit("init")
    return clone_repo(str(src), tmp_path / "ws", "graph-test")


def test_graph_compiles_with_expected_nodes(workspace, tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / ".mosaera")
    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="graph-test",
        source="local",
    )
    nodes = set(graph.get_graph().nodes)
    expected = {
        "plan",
        "implement",
        "capture",
        "supervise",
        "test",
        "fix",
        "review",
        "gate",
        "deliver",
    }
    assert expected <= nodes
    assert "author_tests" not in nodes  # test-first tester is opt-in (default off)


def test_tester_node_inserted_when_enabled(workspace, tmp_path: Path) -> None:
    # With the tester enabled, author_tests slots between design and implement (ADR-0013).
    settings = Settings(home=tmp_path / ".mosaera", tester_enabled=True)
    graph = build_graph(
        settings, workspace, SubprocessSandbox(workspace.root), run_id="t-tester", source="local"
    )
    assert "author_tests" in set(graph.get_graph().nodes)


def test_oracle_posture_wires_the_full_topology(workspace, tmp_path: Path) -> None:
    # #52 (ADR-0057): the autonomous oracle posture activates the oracle stack, so a posture-built
    # graph WIRES author_tests (the Proctor) + reason nodes — proving the posture's knobs reach the
    # graph topology, not just settings. (The gap_fill node was removed entirely — #56, ADR-0060.)
    from mosaera_core.config import apply_oracle_posture

    settings = apply_oracle_posture(Settings(home=tmp_path / ".mosaera"))
    graph = build_graph(
        settings, workspace, SubprocessSandbox(workspace.root), run_id="t-posture", source="local"
    )
    nodes = set(graph.get_graph().nodes)
    assert {"author_tests", "reason"} <= nodes
    assert "gap_fill" not in nodes  # the subsystem is deleted (#56, ADR-0060)


def test_reason_node_is_opt_in(workspace, tmp_path: Path) -> None:
    # Reason-before-park (ADR-0017): the reason node exists only when the knob is on.
    off = build_graph(
        Settings(home=tmp_path / ".mosaera"),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="t-noreason",
        source="local",
    )
    assert "reason" not in set(off.get_graph().nodes)
    on = build_graph(
        Settings(home=tmp_path / ".mosaera", reason_on_stall_enabled=True),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="t-reason",
        source="local",
    )
    assert "reason" in set(on.get_graph().nodes)


def test_reason_ladder_config_alone_does_not_add_the_node(workspace, tmp_path: Path) -> None:
    # ADR-0018: a reason_escalation ladder is inert without reason_on_stall_enabled — the node
    # is gated on the toggle, not the ladder (config alone must not change the graph shape).
    from mosaera_core.config import RoleModel

    g = build_graph(
        Settings(
            home=tmp_path / ".mosaera",
            reason_escalation=[RoleModel(provider="ollama", model="deepseek-r1:32b")],
        ),
        workspace,
        SubprocessSandbox(workspace.root),
        run_id="t-ladder-only",
        source="local",
    )
    assert "reason" not in set(g.get_graph().nodes)


def test_recursion_limit_scales_with_the_ceiling_and_escalations(tmp_path: Path) -> None:
    # M6: the LangGraph recursion_limit must track BOTH the iteration ceiling AND the supervisor
    # escalation budget — else raising either knob turns an honest park at the cap into a
    # GraphRecursionError crash. The earlier fix covered the ceiling but not max_escalations.
    default = Settings(home=tmp_path / ".mosaera")  # ceiling 12, max_escalations 1
    assert recursion_limit_for(default) == (12 + 1) * 10 + 30  # 160
    # A raised ceiling raises the limit with it (long-but-bounded run parks instead of crashing).
    raised_ceiling = Settings(home=tmp_path / ".mosaera", max_iterations_ceiling=40)
    assert recursion_limit_for(raised_ceiling) > recursion_limit_for(default)
    # A raised escalation budget ALSO raises the limit — the supervise re-scope loop can push the
    # step count past a ceiling-only limit, which is the crash the re-audit still reproduced.
    raised_esc = Settings(home=tmp_path / ".mosaera", max_escalations=20)
    assert recursion_limit_for(raised_esc) == (12 + 20) * 10 + 30
    assert recursion_limit_for(raised_esc) > recursion_limit_for(default)


def test_fix_instruction_tells_the_coder_when_output_is_byte_identical() -> None:
    """#81: the ONLY convergence feedback available when the validator reports no count.

    Before this the no-count path gave the coder raw text and nothing else — no indication its
    last edit changed anything — which is half of why those runs spun until the breaker tripped.
    """
    text = fix_instruction("psql: ERROR:  boom", diagnose=True, failing_now=None, repeat=2)
    assert "IDENTICAL to your last attempt (3 in a row)" in text
    assert "DIFFERENT root cause" in text


def test_fix_instruction_repeat_line_is_unreachable_when_a_count_exists() -> None:
    # No-op for pytest BY CONSTRUCTION: the repeat branch only fires when failing_now is None,
    # so a counted run keeps the exact trend line it always had.
    text = fix_instruction(
        "=== 3 failed ===", diagnose=True, failing_now=3, failing_prev=5, repeat=9
    )
    assert "IDENTICAL to your last attempt" not in text
    assert "Failing tests: 3 (was 5" in text


def test_fix_instruction_offers_over_specification_escalation_valve() -> None:
    # A protected acceptance test that over-specifies beyond the contract can't be satisfied
    # by any correct change (the coder can't edit tests) → without a valve the run thrashes
    # then parks. The fix prompt offers the SUMMARY: escalate hand-raise, and capture_node's
    # parse_yield routes that to the supervisor (MCB cloud-tester finding, 2026-07-12).
    text = fix_instruction("E   assert 1 == 2  # exit code")
    assert "E   assert 1 == 2" in text  # the failure delta is fed back
    assert "over-specifies beyond the contract" in text
    # The exact hand-raise the prompt tells the coder to emit must parse as an escalation
    # (so route_after_capture sends it to supervise, not the iteration-cap park).
    _blocked, escalate = parse_yield(
        "SUMMARY: escalate — test_x over-specifies beyond the contract: wants exit 2"
    )
    assert escalate


def test_fix_instruction_diagnose_mode_asks_for_a_hypothesis_and_shows_convergence() -> None:
    # #55 (ADR-0059): diagnose mode pushes the coder to state a root-cause HYPOTHESIS before
    # editing and shows the failing-count trend so it can tell converging from spinning.
    plain = fix_instruction("out")
    assert "HYPOTHESIS" not in plain  # off by default → today's behaviour
    diag = fix_instruction("out", diagnose=True, failing_now=3, failing_prev=8)
    assert "HYPOTHESIS" in diag
    assert "3" in diag and "8" in diag and "CLOSER" in diag  # getting closer
    # No change → tell the coder its last edit didn't help.
    stuck = fix_instruction("out", diagnose=True, failing_now=5, failing_prev=5)
    assert "NO change" in stuck
    # First failure (no prior count) → just the current count, no "was".
    first = fix_instruction("out", diagnose=True, failing_now=4, failing_prev=None)
    assert "Failing tests: 4" in first and "was" not in first
    # A non-pytest validator (count None) → no trend line, but still the hypothesis ask.
    nocount = fix_instruction("out", diagnose=True, failing_now=None, failing_prev=None)
    assert "HYPOTHESIS" in nocount and "Failing tests:" not in nocount


# --- F49: the ESCALATE arm stops the futile loop ----------------------------------------------
#
# Measured on the guided corpus: the producer diagnosed the broken bar in 6 of 6 runs and was
# re-scoped back at the same unfixable wall every time, riding to the iteration cap and scoring
# thrash_park for having nowhere to send a correct objection.


def _supervise_state(**over: Any) -> dict[str, Any]:
    return {
        "task": "t",
        "iteration": 1,
        "escalations": 0,
        "coder_escalated": True,
        "escalate_reason": "the task conflicts with a test: it pins a date never supplied",
        "integrity_baseline": {"tests/test_add.py": "h1"},
        "authored_tests": [],
        "test_output": "FAILED tests/test_add.py::test_row - AssertionError\n1 failed, 2 passed\n",
        "gate_decision": {"reasons": ["validation_failed"]},
        **over,
    }


def _supervise_ctx(escalate_arm: bool, *, amendment_gate: bool = False) -> Any:
    from pathlib import Path

    return SimpleNamespace(
        max_iter=6,
        max_escalations=1,
        settings=SimpleNamespace(
            escalate_arm=escalate_arm, stall_limit=3, amendment_gate=amendment_gate
        ),
        agents=SimpleNamespace(tester_enabled=True),
        # Real since #127: the authorization delta captures the authorized paths' PRISTINE source,
        # because the amend pass re-executes in guided mode and can no longer re-read it from disk.
        # No file exists here, so the capture is empty — which is what this test's assertions cover.
        workspace=SimpleNamespace(root=Path("/nonexistent")),
    )


def _run_supervise(
    ctx: Any, state: dict[str, Any], resume: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Drive supervise_node through a real interrupt/resume, resolving it as a re-scope —
    the autonomous resolution that produced the measured loop."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState

    g: Any = StateGraph(RunState)
    g.add_node("supervise", lambda s: nodes_plan.supervise_node(ctx, s))
    g.add_edge(START, "supervise")
    g.add_edge("supervise", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "sup-1"}}
    app.invoke(state, cfg)
    return dict(app.invoke(Command(resume=resume or {"resolution": "rescope"}), cfg))


def test_an_unfixable_hand_raise_concludes_instead_of_re_scoping() -> None:
    final = _run_supervise(_supervise_ctx(True), _supervise_state())
    assert final.get("give_up_reason"), "the arm must conclude, not re-scope"
    assert not final.get("feedback"), "a re-scope would send it back at the same wall"
    # `stalled` False is what makes an accurate stop read honest_park rather than thrash.
    assert final.get("stalled") is False
    # The operator's next move is to amend the ITEM, so the reason must name what blocked it.
    assert "tests/test_add.py" in final["give_up_reason"]


def test_with_the_knob_off_the_behaviour_is_unchanged() -> None:
    """The assertion that protects the baseline: OFF must re-scope exactly as it does today."""
    final = _run_supervise(_supervise_ctx(False), _supervise_state())
    assert final.get("feedback"), "knob OFF must still re-scope"
    assert not final.get("give_up_reason")


def test_a_coder_owned_failure_still_re_scopes_even_with_the_arm_on() -> None:
    # The producer CAN fix this one, so a re-scope is the right answer and the arm must keep out.
    state = _supervise_state(
        test_output="FAILED tests/test_mine.py::test_x - AssertionError\n1 failed\n"
    )
    final = _run_supervise(_supervise_ctx(True), state)
    assert final.get("feedback")
    assert not final.get("give_up_reason")


# --- the escalation-gate amendment: the arm stops ASKING into the void (ADR-0087, #65) ---------
#
# The arm above concludes the run — correctly, since re-planning cannot change an acceptance bar.
# But `oracle_conflict` was OR'd into `give_up`, so it concluded WHATEVER the operator answered:
# the arm asked, and then ignored the answer. F63, measured at ~4M tokens across three runs.


def _authorize(paths: list[str]) -> dict[str, Any]:
    return {"resolution": "human", "feedback": "requirement changed", "authorize_tests": paths}


def test_an_authorized_amendment_continues_the_run_instead_of_concluding() -> None:
    final = _run_supervise(
        _supervise_ctx(True, amendment_gate=True),
        _supervise_state(),
        _authorize(["tests/test_add.py"]),
    )
    assert not final.get("give_up_reason"), "the operator answered — the arm must not conclude"
    assert final.get("pending_amendment") == ["tests/test_add.py"]
    assert final.get("amendment_reason") == "requirement changed"


def test_the_offer_reaches_the_operator_in_the_interrupt_payload() -> None:
    """The operator cannot authorize what they were never shown. The payload must name the
    blocking test, not just say 'escalation unresolved'."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState

    ctx = _supervise_ctx(True, amendment_gate=True)
    g: Any = StateGraph(RunState)
    g.add_node("supervise", lambda s: nodes_plan.supervise_node(ctx, s))
    g.add_edge(START, "supervise")
    g.add_edge("supervise", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "sup-offer"}}
    result = app.invoke(_supervise_state(), cfg)
    payload = result["__interrupt__"][0].value
    assert payload["amendable"]["paths"] == ["tests/test_add.py"]
    assert payload["amendable"]["tests"] == ["tests/test_add.py::test_row"]


# --- the hand-raise branch has no engine validation, so capture pins the coder's (F70, #75) -----


def _capture_ctx(output: str, taken_at: str, current: str) -> Any:
    return SimpleNamespace(
        coder_validation={"output": output, "tree_hash": taken_at},
        # `evidence_hash`: `pinned_coder_validation` moved onto the git-sourced evidence listing
        # with the other three pins (ADR-0108 successor) — the walk-based `tree_hash` could not see
        # a write under any `_SKIP_DIRS` name at any depth, all of which the delivery path commits.
        workspace=SimpleNamespace(evidence_hash=lambda: current, tree_hash=lambda: current),
    )


def _capture(ctx: Any) -> dict[str, Any]:
    from mosaera_core.graph import nodes_plan

    return nodes_plan.capture_node(ctx, {"messages": []})  # type: ignore[arg-type]


_FAIL = "FAILED tests/test_add.py::test_row - AssertionError\n"


def test_capture_keeps_the_coders_run_when_the_tree_has_not_moved() -> None:
    assert _capture(_capture_ctx(_FAIL, "abc", "abc"))["coder_test_output"] == _FAIL


def test_capture_REFUSES_a_run_the_coder_has_since_written_over() -> None:
    """THE pin that makes this evidence rather than an anecdote. The coder runs the suite, sees a
    protected test fail, then writes code and raises its hand — the recorded output now describes
    a tree that no longer exists, and it is about to help authorize amending an acceptance test.
    A moved tree fails CLOSED."""
    assert _capture(_capture_ctx(_FAIL, "abc", "xyz"))["coder_test_output"] == ""


def test_capture_refuses_a_record_with_no_hash_at_all() -> None:
    """An unpinnable record is not weaker evidence, it is none — the hash is the whole warrant."""
    assert _capture(_capture_ctx(_FAIL, "", "abc"))["coder_test_output"] == ""
    assert _capture(_capture_ctx("", "abc", "abc"))["coder_test_output"] == ""


def test_capture_clears_a_stale_record_rather_than_leaving_it() -> None:
    """It writes "" rather than omitting the key: an omitted key leaves the PREVIOUS iteration's
    record in checkpointed state to answer this iteration's question."""
    assert _capture(_capture_ctx(_FAIL, "old", "new"))["coder_test_output"] == ""


def test_a_first_iteration_hand_raise_reaches_the_amendment_gate() -> None:
    """The reproduction of runs 20260807-194739-644d8f and 20260807-195038-936bdf.

    A hand-raise routes `implement → capture → supervise` and never touches `test`, so
    `test_output` is absent and the offer was withheld — on exactly the branch where the coder is
    saying a protected test blocks it. With the coder's own pinned run in state, the operator is
    asked the question the control exists to ask."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState

    ctx = _supervise_ctx(True, amendment_gate=True)
    state = _supervise_state()
    del state["test_output"]  # `test` never ran — the whole point
    state["coder_test_output"] = "FAILED tests/test_add.py::test_row - AssertionError\n"

    g: Any = StateGraph(RunState)
    g.add_node("supervise", lambda s: nodes_plan.supervise_node(ctx, s))
    g.add_edge(START, "supervise")
    g.add_edge("supervise", END)
    app = g.compile(checkpointer=InMemorySaver())
    payload = app.invoke(state, {"configurable": {"thread_id": "sup-handraise"}})[  # type: ignore[arg-type]
        "__interrupt__"
    ][0].value
    assert payload["amendable"]["tests"] == ["tests/test_add.py::test_row"]


def test_a_hand_raise_with_no_validation_at_all_still_PARKS_without_an_offer() -> None:
    """Deny-by-default must not become deny-to-ask. The escalation still reaches the operator; it
    simply carries no amendment."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState

    ctx = _supervise_ctx(True, amendment_gate=True)
    state = _supervise_state()
    del state["test_output"]

    g: Any = StateGraph(RunState)
    g.add_node("supervise", lambda s: nodes_plan.supervise_node(ctx, s))
    g.add_edge(START, "supervise")
    g.add_edge("supervise", END)
    app = g.compile(checkpointer=InMemorySaver())
    payload = app.invoke(state, {"configurable": {"thread_id": "sup-noev"}})[  # type: ignore[arg-type]
        "__interrupt__"
    ][0].value
    assert payload["action"] == "escalation"
    assert "amendable" not in payload


def test_a_tampering_run_is_told_WHY_the_amendment_is_not_offered() -> None:
    """F65: the offer disappearing and the offer never applying looked identical to the operator.
    A suppression nobody can see is indistinguishable from a control that is not there."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState

    ctx = _supervise_ctx(True, amendment_gate=True)
    g: Any = StateGraph(RunState)
    g.add_node("supervise", lambda s: nodes_plan.supervise_node(ctx, s))
    g.add_edge(START, "supervise")
    g.add_edge("supervise", END)
    app = g.compile(checkpointer=InMemorySaver())
    payload = app.invoke(
        _supervise_state(tests_modified=True), {"configurable": {"thread_id": "sup-tamper"}}
    )["__interrupt__"][0].value
    assert "amendable" not in payload
    assert "integrity guard" in payload["amendable_withheld"]


def test_the_amendment_knob_off_concludes_exactly_as_before() -> None:
    """OFF is byte-identical: the authorization is not even read, so the arm concludes."""
    final = _run_supervise(
        _supervise_ctx(True, amendment_gate=False),
        _supervise_state(),
        _authorize(["tests/test_add.py"]),
    )
    assert final.get("give_up_reason")
    assert not final.get("pending_amendment")


def test_an_autonomous_resolution_cannot_authorize_an_amendment() -> None:
    """The unattended path must never reach this. `resolution` is `rescope`, not `human`, and the
    API layer does not even construct the field on that branch — two independent refusals."""
    final = _run_supervise(
        _supervise_ctx(True, amendment_gate=True),
        _supervise_state(),
        {"resolution": "rescope", "authorize_tests": ["tests/test_add.py"]},
    )
    assert final.get("give_up_reason"), "an autonomous run must still conclude"
    assert not final.get("pending_amendment")


def test_authorizing_a_test_that_is_not_blocking_does_not_continue_the_run() -> None:
    final = _run_supervise(
        _supervise_ctx(True, amendment_gate=True),
        _supervise_state(),
        _authorize(["tests/test_something_else.py"]),
    )
    assert final.get("give_up_reason")
    assert not final.get("pending_amendment")


# --- #68: the escalation offers named choices, and the ask is not re-derived -------------------


def _supervise_payload(ctx: Any, state: dict[str, Any]) -> dict[str, Any]:
    """The interrupt payload the operator is actually shown, without resolving it."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState

    g: Any = StateGraph(RunState)
    g.add_node("supervise", lambda s: nodes_plan.supervise_node(ctx, s))
    g.add_edge(START, "supervise")
    g.add_edge("supervise", END)
    app = g.compile(checkpointer=InMemorySaver())
    res = app.invoke(state, {"configurable": {"thread_id": "sup-payload"}})
    return dict(res["__interrupt__"][0].value)


def test_the_escalation_hands_over_named_options_not_a_boolean() -> None:
    """F62: the operator got an honest stop and nothing to answer."""
    payload = _supervise_payload(_supervise_ctx(True), _supervise_state())
    ids = [o["id"] for o in payload["outcomes"]]
    assert "stop_honestly" in ids
    assert ids == sorted(set(ids), key=ids.index), "ids must be unique — the API validates one"


def test_the_option_shown_agrees_with_what_the_engine_then_does() -> None:
    """The anti-drift pin, and the reason this is computed from ONE predicate.

    F61 was a "send back to revise" button that terminated the run and discarded the notes. Here
    the arm has already decided to conclude, so a revision channel would be exactly that lie: the
    option must declare `end_run`, and the engine must in fact end.
    """
    ctx, state = _supervise_ctx(True), _supervise_state()
    send_back = next(
        o for o in _supervise_payload(ctx, state)["outcomes"] if o["id"] == "send_back"
    )
    assert send_back["effect"] == "end_run"
    assert not send_back["recommended"]
    # ...and the engine really does end, from the same predicate.
    assert _run_supervise(ctx, state).get("give_up_reason")


def test_a_continuable_escalation_still_offers_a_real_revision_channel() -> None:
    # Knob off → no oracle conflict → nothing forces a stop, so send-back must mean send-back.
    payload = _supervise_payload(_supervise_ctx(False), _supervise_state())
    send_back = next(o for o in payload["outcomes"] if o["id"] == "send_back")
    assert send_back["effect"] == "send_back" and send_back["recommended"]


def test_supervise_records_the_blocking_tests_for_the_ask_to_read() -> None:
    """#68/ADR-0090 MR3: the ask consumes this instead of re-deriving the predicate.

    It used to run `is_oracle_conflict_escalation` a second time against a `gate_decision` that had
    moved on, so a stop could fire and the ask still be refused. Recording the decision at the
    moment it is made removes the second evaluation entirely.
    """
    final = _run_supervise(_supervise_ctx(True), _supervise_state())
    # FILE grain, exactly as the ask named them before this change — the fix moves WHEN the ask
    # fires, deliberately not what it says. (`amendable.tests` keeps its file::function grain,
    # because that is what an operator ticks to authorise.)
    assert final.get("ask_blocking_tests") == ["tests/test_add.py"]


def test_nothing_is_recorded_for_the_ask_when_the_run_re_scopes() -> None:
    # No conclusion, no ask: a re-scoped run has not decided anything for the operator to answer.
    final = _run_supervise(_supervise_ctx(False), _supervise_state())
    assert not final.get("ask_blocking_tests")
