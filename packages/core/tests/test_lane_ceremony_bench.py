"""Targeted ceremony benchmark for #118 — how much orchestration does a trivial item actually pay?

**Why this and not an MCB sweep.** The MCB corpus has no comment/docstring/typo case, so a bench
run would never arm the lane and would measure nothing about it. The question here is architectural
— does a certified non-behavioural item still pay for design and a Proctor authoring pass — and
that is answered by driving the REAL graph (`build_graph`, real nodes, real routing, real tools)
with fake models and counting which stages executed. Deterministic, seconds, no GPU.

It is a benchmark AND a regression test: the assertions are the claim each approach makes, so an
approach that silently stops saving anything fails here rather than in a sweep three weeks later.
"""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import pytest
from git import Repo
from langgraph.checkpoint.memory import InMemorySaver
from mosaera_core.config import Settings
from mosaera_core.graph import build_graph
from mosaera_core.sandbox import SubprocessSandbox
from mosaera_core.tools.repo import clone_repo
from test_graph_integration import _patch_models, recording_team_factory

# A brief the classifier certifies: non-behavioural, one existing file, no behaviour verb.
_TRIVIAL = "Fix the stale comment above the constant in a.py"


def _with(base: Settings, **over: Any) -> Settings:
    """replace(), but silently dropping knobs this BRANCH does not have.

    The two approaches carry different knobs, and this one file has to measure either — a bench
    that only runs on the branch it was written for cannot compare them."""
    known = {f.name for f in fields(base)}
    return replace(base, **{k: v for k, v in over.items() if k in known})


@pytest.fixture
def workspace(tmp_path: Path) -> Any:
    """A clone with ONE committed module, so `a.py` is a real repo file the classifier can certify
    (an invented path certifies nothing — `test_task_scale` pins that)."""
    src = tmp_path / "src"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "a.py").write_text("# a stale comment\nx = 1\n", encoding="utf-8")
    repo.index.add(["a.py"])
    repo.index.commit("init")
    return clone_repo(str(src), tmp_path / "ws", "lane-bench")


def _run(workspace: Any, settings: Settings, thread: str) -> dict[str, Any]:
    """Drive one full run and report which ceremony stages executed."""
    seen: dict[str, Any] = {}
    calls: dict[str, int] = {"plan": 0, "design": 0, "author_tests": 0}

    def _count(name: str, result: Any) -> Any:
        def fn(*a: Any, **k: Any) -> Any:
            calls[name] += 1
            return result

        return fn

    graph = build_graph(
        settings,
        workspace,
        SubprocessSandbox(workspace.root),
        f"bench-{thread}",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=_patch_models(review="VERDICT: APPROVE"),
        team_factory=recording_team_factory(
            seen,
            plan=_count("plan", "1. edit the comment in a.py"),
            design=_count("design", "design: none needed"),
            author_tests=_count("author_tests", None),
        ),
    )
    graph.invoke(
        {"task": _TRIVIAL},
        {"configurable": {"thread_id": thread}, "recursion_limit": 80},
    )
    return calls


def test_the_lane_removes_ceremony_a_trivial_item_cannot_use(workspace: Any) -> None:
    """THE MEASUREMENT. Baseline pays for design and (when the Proctor is on) an authoring pass
    before the coder ever runs. The lane's whole claim is that a certified non-behavioural item
    does not need either — design elaborates behaviour that is not changing, and the Proctor cannot
    red-verify a change with no behavioural surface (the MCB-14 wall).

    Asserted as a STRICT reduction rather than an exact count: the point is that ceremony falls and
    the plan still happens, not that a particular number is sacred.
    """
    # The Proctor MUST be on, or author_tests is 0 in both arms and the benchmark silently
    # measures half the question — which is exactly what the first run of it did.
    base = _with(Settings.from_env(), tester_enabled=True)
    off = _run(workspace, _with(base, reduced_lane=False, inert_oracle_scaffold=False), "off")

    assert off["plan"] >= 1, "the baseline must still plan — otherwise this measures nothing"
    lane_on = _with(base, reduced_lane=True, inert_oracle_scaffold=True)
    on = _run(workspace, lane_on, "on")

    print(f"\nceremony: baseline={off}  lane={on}")
    # Whichever approach this branch carries, the trivial item must cost strictly less ceremony
    # than baseline, and must still be planned.
    assert on["plan"] >= 1, "the lane must not skip planning — scope still has to be decided"
    assert (on["design"] + on["author_tests"]) < (off["design"] + off["author_tests"]), (
        f"the lane saved no ceremony at all: baseline={off} lane={on}"
    )


def test_a_behavioural_item_is_untouched_by_the_lane(workspace: Any) -> None:
    """The other half, and the one that matters for safety: turning the knob on must change
    NOTHING for an item the classifier does not certify. A lane that quietly cheapens real work is
    the failure mode both approaches exist to avoid."""
    base = Settings.from_env()
    task_settings = _with(base, reduced_lane=True, inert_oracle_scaffold=True, tester_enabled=True)

    seen: dict[str, Any] = {}
    calls = {"design": 0}

    def _design(*a: Any, **k: Any) -> str:
        calls["design"] += 1
        return "design: real work"

    graph = build_graph(
        task_settings,
        workspace,
        SubprocessSandbox(workspace.root),
        "bench-behavioural",
        source="local",
        checkpointer=InMemorySaver(),
        model_factory=_patch_models(review="VERDICT: APPROVE"),
        team_factory=recording_team_factory(seen, design=_design),
    )
    graph.invoke(
        {"task": "Add a --quiet flag to the list command"},
        {"configurable": {"thread_id": "behavioural"}, "recursion_limit": 80},
    )
    assert calls["design"] >= 1, "a behavioural item must still be designed with the knob ON"
