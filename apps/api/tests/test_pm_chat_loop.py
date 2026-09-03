"""The ledger-tool knob: off by default, and off means unchanged.

The knob only earns its keep if turning it on is the ONLY difference between the arms. That is
what these pin — that the disabled path does not build tools, does not read the store, and takes
the same single-call branch it always did; and that the enabled path scopes its tools through the
policy allowlist rather than handing them over directly.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


class _Mem:
    """Records whether the history reads happened, which is how the OFF arm proves it paid
    nothing for a feature it did not use."""

    def __init__(self) -> None:
        self.history_reads = 0
        self.written: list[tuple[str, str]] = []

    def project_detail(self, pid: str) -> dict[str, Any]:
        return {"brief": "", "backlog": []}

    def ensure_default_pm_session(self, pid: str) -> str:
        return "sess-1"

    def list_messages(self, pid: str, session_id: str | None = None) -> list[Any]:
        return []

    def add_message(self, pid: str, role: str, content: str, session_id: str | None = None) -> int:
        self.written.append((role, content))
        return len(self.written)

    def get_repo_overview(self, pid: str) -> str:
        return ""

    def list_project_context_items(self, pid: str) -> list[Any]:
        return []

    def add_message_context_sources(self, mid: int, sources: list[Any]) -> None:
        pass

    def add_message_proposals(self, mid: int, proposals: list[Any]) -> None:
        pass

    def record_latency_sample(self, *a: Any, **k: Any) -> None:
        pass

    def history_runs(self, pid: str) -> list[Any]:
        self.history_reads += 1
        return []

    def history_items(self, pid: str) -> list[Any]:
        return []

    def history_run_item_ids(self, pid: str) -> list[int]:
        return []


def _turn(
    monkeypatch: pytest.MonkeyPatch, *, tools_on: bool | None
) -> tuple[_Mem, dict[str, Any], list[Any]]:
    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    # None = leave the shipped default in force (the root conftest strips MOSAERA_* per test,
    # so "unset" really is the default); True/False pin the knob explicitly.
    if tools_on is not None:
        monkeypatch.setenv("MOSAERA_PM_CHAT_TOOLS", "1" if tools_on else "0")

    given: list[Any] = []

    def fake_build_agent(model: Any, tools: Any, **kwargs: Any) -> Any:
        given.append(list(tools))
        return object()

    monkeypatch.setattr(pm_turn_mod.pm, "build_pm_agent", fake_build_agent)
    monkeypatch.setattr(
        pm_turn_mod.pm,
        "chat_with_agent",
        lambda *a, **k: pm_turn_mod.pm.ChatOutcome("looped", [], None, None, ""),
    )
    monkeypatch.setattr(pm_turn_mod.pm, "chat", lambda *a, **k: ("single call", [], None, None))
    mem = _Mem()
    return mem, pm_turn_mod.pm_chat(mem, "p1", "hi"), given  # type: ignore[arg-type]


def test_the_default_is_the_tools_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """ON by default: ADR-0111 is accepted and the Alpha flip shipped, so a fresh install's PM
    chat can read its own ledgers without configuration. The single-call arm survives as the
    explicit opt-out below, not as the default."""
    _mem, out, given = _turn(monkeypatch, tools_on=None)
    assert out["reply"] == "looped"
    assert len(given) == 1  # the agent was built, with its ledger tools


def test_the_opt_out_is_the_single_call_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinning the knob off still yields the pre-ADR-0111 single call — no loop with one step."""
    _mem, out, given = _turn(monkeypatch, tools_on=False)
    assert out["reply"] == "single call"
    assert given == []  # no agent was ever built


def test_the_knob_adds_no_reads_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both arms read history exactly once — for the STANDING block, which rides every turn
    whether or not the tool exists (ADR-0111: the tool lets Quincy reach past that block's
    truncation, it does not replace the block).

    So the tool costs a read only when it is actually called. Tools are built inside the enabled
    branch and their store reads are lazy; hoisting either would make the off arm pay for a
    feature it is not using, and the two arms would then differ in database traffic and latency
    even where the prompt matched — the confound the knob exists to avoid.
    """
    off, _o1, _g1 = _turn(monkeypatch, tools_on=False)
    on, _o2, _g2 = _turn(monkeypatch, tools_on=True)
    assert off.history_reads == on.history_reads == 1


def test_the_enabled_path_takes_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    _mem, out, given = _turn(monkeypatch, tools_on=True)
    assert out["reply"] == "looped"
    assert len(given) == 1


def test_the_enabled_path_hands_over_only_the_ledger_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scoped through the allowlist, not passed straight in.

    Asserting the tool list is `["project_history"]` proves nothing on its own — the factory only
    ever builds that one, so the assertion holds whether or not `scoped_tools` is called. So the
    factory is made to hand back a repo tool as well, and the filter has to drop it. That is what
    turns ADR-0111's split from prose into something the code enforces.
    """
    import mosaera_api.pm_turn as pm_turn_mod
    from langchain_core.tools import tool

    @tool
    def read_file(path: str) -> str:
        """A repository read, which the chat must never receive."""
        return "secrets"

    real = pm_turn_mod.build_ledger_tools
    monkeypatch.setattr(pm_turn_mod, "build_ledger_tools", lambda m, p: [*real(m, p), read_file])
    _mem, _out, given = _turn(monkeypatch, tools_on=True)
    assert [t.name for t in given[0]] == ["project_history"]


def test_an_exhausted_budget_becomes_an_honest_failed_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cause that only became reachable with the loop. It must flow into the same failure
    path everything else uses — a note row carrying the token, no reply, and nothing stored as
    though Quincy had said it."""
    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    monkeypatch.setenv("MOSAERA_PM_CHAT_TOOLS", "1")
    monkeypatch.setattr(pm_turn_mod.pm, "build_pm_agent", lambda *a, **k: object())
    monkeypatch.setattr(
        pm_turn_mod.pm,
        "chat_with_agent",
        lambda *a, **k: pm_turn_mod.pm.ChatOutcome("", [], None, None, "budget_exhausted"),
    )
    mem = _Mem()
    out = pm_turn_mod.pm_chat(mem, "p1", "hi")  # type: ignore[arg-type]
    assert out["failure_cause"] == "budget_exhausted"
    assert out["reply"] == ""
    assert mem.written[-1] == ("note", "budget_exhausted")
    assert "pm" not in [role for role, _ in mem.written]
