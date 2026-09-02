"""The held-out critic node + its held-out predicate (#60, ADR-0065).

The node is a veto-only judge wired between review and the gate. It must: run ONLY on a
green + held-out run (deny-by-default), memoize by tree hash (one model call per delivered
tree), and degrade to no-verdict on any fault (never crash, never park by itself).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from mosaera_core.config import Settings
from mosaera_core.graph.nodes_critic import critic_node
from mosaera_core.graph.state import RunState

_CFG: RunnableConfig = {}


def _state(**kw: Any) -> RunState:
    return cast(RunState, dict(kw))


class _FakeWorkspace:
    def __init__(self, tree_hash: str = "h1") -> None:
        self._h = tree_hash

    def tree_hash(self, limit: int = 300) -> str:
        return self._h

    def diff_all(self) -> str:
        return "diff --git a/x b/x"


class _FakeAgents:
    def __init__(self, verdict: Any, *, raises: bool = False, raise_first: int = 0) -> None:
        self._verdict = verdict
        self._raises = raises
        self._raise_first = raise_first  # raise on the first N calls, then return verdict
        self.calls = 0

    def critic(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self._raises or self.calls <= self._raise_first:
            raise RuntimeError("model down")
        return self._verdict


def _ctx(agents: Any, *, held_out: bool = True, ws: Any = None) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(held_out_ok=lambda: held_out),
        workspace=ws or _FakeWorkspace(),
        evidence_memo={},
        agents=agents,
    )


def test_veto_on_a_green_held_out_run_sets_the_verdict() -> None:
    agents = _FakeAgents({"vetoed": True, "reason": "N=0 branch is wrong"})
    ctx = _ctx(agents)
    out = critic_node(ctx, _state(tests_passed=True, task="t", plan="p"), _CFG)
    assert out == {"outcome_verdict": {"vetoed": True, "reason": "N=0 branch is wrong"}}
    assert agents.calls == 1


def test_ship_sets_a_non_veto_verdict() -> None:
    agents = _FakeAgents({"vetoed": False, "reason": "meets spec"})
    out = critic_node(_ctx(agents), _state(tests_passed=True, task="t"), _CFG)
    assert out["outcome_verdict"]["vetoed"] is False


def test_skipped_when_not_green() -> None:
    # Deny-by-default: a failing / unavailable run already parks and has no delivered code to
    # judge — the critic never runs (no wasted model call).
    for tp in (False, None):
        agents = _FakeAgents({"vetoed": True, "reason": "x"})
        out = critic_node(_ctx(agents), _state(tests_passed=tp, task="t"), _CFG)
        assert out == {}
        assert agents.calls == 0


def test_skipped_when_not_held_out() -> None:
    # A critic bound to the coder's model is not an independent check — skip it (efficacy loss,
    # never a safety hole: veto-only means a skipped critic just doesn't act).
    agents = _FakeAgents({"vetoed": True, "reason": "x"})
    out = critic_node(_ctx(agents, held_out=False), _state(tests_passed=True, task="t"), _CFG)
    assert out == {}
    assert agents.calls == 0


def test_memoized_one_call_per_tree() -> None:
    # Off the iteration loop: two passes over the SAME tree cost one model call.
    agents = _FakeAgents({"vetoed": True, "reason": "x"})
    ctx = _ctx(agents)
    state = _state(tests_passed=True, task="t")
    first = critic_node(ctx, state, _CFG)
    second = critic_node(ctx, state, _CFG)
    assert first == second
    assert agents.calls == 1  # the second read hit the memo


def test_fault_degrades_to_no_verdict() -> None:
    # A judge fault is inconclusive → None (no veto), never a crash that discards the diff.
    agents = _FakeAgents(None, raises=True)
    out = critic_node(_ctx(agents), _state(tests_passed=True, task="t"), _CFG)
    assert out == {"outcome_verdict": None}


def test_a_transient_fault_is_not_memoized_and_retries_on_re_delivery() -> None:
    # Red-team #60: a single transient fault must NOT permanently suppress the critic. The fault
    # is not cached, so a re-delivery of the SAME tree (a looping coder → identical tree_hash)
    # re-invokes and the recovered critic raises the veto it would have.
    agents = _FakeAgents({"vetoed": True, "reason": "wrong"}, raise_first=1)
    ctx = _ctx(agents)
    state = _state(tests_passed=True, task="t")
    first = critic_node(ctx, state, _CFG)  # faults → None, NOT memoized
    assert first == {"outcome_verdict": None}
    second = critic_node(ctx, state, _CFG)  # same tree → retries → recovered veto
    assert second == {"outcome_verdict": {"vetoed": True, "reason": "wrong"}}
    assert agents.calls == 2


def test_held_out_ok_predicate() -> None:
    # Default: critic gpt-oss:20b != coder qwen3-coder:30b → held out.
    assert Settings().held_out_ok() is True
    # Same model as the coder → NOT held out.
    assert Settings(critic_model="qwen3-coder:30b").held_out_ok() is False
