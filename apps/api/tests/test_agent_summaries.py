"""The per-agent summary is a model-authored DISPLAY artifact: parsed strictly,
persisted as a decision, and silent on every fault (narration never breaks a run)."""

from __future__ import annotations

from mosaera_api.runner._summaries import summarize_agents

_EVENTS = [
    {"type": "update", "data": {"node": "plan", "update": {"plan": "1. do the thing"}}},
    {"type": "update", "data": {"node": "review", "update": {"review": "VERDICT: APPROVE"}}},
    {"type": "activity", "data": {"node": "implement", "kind": "file_read"}},
]


def test_summaries_parse_and_filter_to_known_seats() -> None:
    reply = '{"quincy": "Planned the work.", "rook": "Approved it.", "bogus": "x", "forge": ""}'
    out = summarize_agents(_EVENTS, lambda _p: f"noise {reply} noise")
    assert out == {"quincy": "Planned the work.", "rook": "Approved it."}


def test_model_garbage_yields_none_not_a_crash() -> None:
    assert summarize_agents(_EVENTS, lambda _p: "no json here") is None


def test_model_exception_yields_none() -> None:
    def boom(_p: str) -> str:
        raise RuntimeError("provider down")

    assert summarize_agents(_EVENTS, boom) is None


def test_no_material_means_no_call() -> None:
    called = []

    def spy(p: str) -> str:
        called.append(p)
        return "{}"

    assert summarize_agents([], spy) is None
    assert called == []
