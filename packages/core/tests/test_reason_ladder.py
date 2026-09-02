"""Reasoning-escalation ladder (ADR-0018): the one-off reasoner diagnosis helper.

`reason_diagnose` binds a tier model, invokes it tool-lessly, and returns a plan — or ""
on empty/failure so the reason node falls back to the own-model pass and never crashes. It
must also thread the graph config into the invoke so the reasoner call is metered.

The tier model is injected via `reason_diagnose(model_factory=...)` rather than
monkeypatching module-global `get_chat_model`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from mosaera_core.config import RoleModel, Settings
from mosaera_core.graph import reason_diagnose

_TIER = RoleModel(provider="ollama", model="deepseek-r1:32b")
_STATE = {"task": "do X", "plan": "P", "design": "D", "coder_summary": "tried Y"}


class FakeReasoner:
    def __init__(self, content: str = "", raises: bool = False) -> None:
        self.content = content
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def invoke(self, messages: Any, config: Any = None) -> AIMessage:
        self.calls.append({"messages": messages, "config": config})
        if self.raises:
            raise RuntimeError("reasoner boom")
        return AIMessage(content=self.content)


def test_reason_diagnose_returns_plan_and_threads_config() -> None:
    fake = FakeReasoner(content="1. root cause: wrong file\n2. edit foo.py")
    cfg: Any = {"callbacks": ["sentinel"]}  # identity sentinel — asserted threaded below
    out = reason_diagnose(
        Settings(),
        _STATE,
        "test",
        "AssertionError: boom",
        _TIER,
        cfg,
        model_factory=lambda role, settings: fake,  # type: ignore[arg-type,return-value]
    )
    assert "root cause" in out and "edit foo.py" in out
    # Metering: the graph RunnableConfig must reach model.invoke or the reasoner is unmetered.
    assert fake.calls and fake.calls[0]["config"] is cfg
    # It sent the DIAGNOSIS_SYSTEM + a packet carrying the stuck failure.
    sent = "".join(str(m.content) for m in fake.calls[0]["messages"])
    assert "senior engineer" in sent.lower() and "AssertionError: boom" in sent


def test_reason_diagnose_empty_reasoner_returns_blank() -> None:
    out = reason_diagnose(
        Settings(),
        _STATE,
        "test",
        "x",
        _TIER,
        None,
        model_factory=lambda role, settings: FakeReasoner(content=""),  # type: ignore[arg-type,return-value]
    )
    assert out == ""


def test_reason_diagnose_swallows_reasoner_failure() -> None:
    # A reasoner crash must NEVER fail the run — the node falls back to own-model.
    out = reason_diagnose(
        Settings(),
        _STATE,
        "test",
        "x",
        _TIER,
        None,
        model_factory=lambda role, settings: FakeReasoner(raises=True),  # type: ignore[arg-type,return-value]
    )
    assert out == ""
