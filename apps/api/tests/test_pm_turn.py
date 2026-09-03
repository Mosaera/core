"""`pm_turn.pm_chat` — one PM conversation turn.

Moved here when `pm_chat` was extracted from `projects.py` (which had reached the modularity
ceiling): the tests follow the code they exercise rather than being paid for with thinner
assertions elsewhere.
"""

from __future__ import annotations

from typing import Any

import pytest


def test_pm_chat_records_latency_sample_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """pm_chat times its model call and records a 'pm_chat' latency sample (#22);
    a failed recording must never break the chat (best-effort by contract)."""
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    from types import SimpleNamespace

    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    recorded: list[tuple[str, str, int]] = []

    class _Mem:
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {"brief": "", "backlog": []}

        def ensure_default_pm_session(self, pid: str) -> str:
            return f"sess-{pid}"

        def list_messages(self, pid: str, session_id: str | None = None) -> list[Any]:
            return []

        def add_message(
            self, pid: str, role: str, content: str, session_id: str | None = None
        ) -> int:
            return 1

        def get_repo_overview(self, pid: str) -> str:
            return ""

        def list_project_context_items(self, pid: str) -> list[Any]:
            return []

        def add_message_context_sources(self, mid: int, sources: list[Any]) -> None:
            pass

        def record_latency_sample(
            self, pid: str, path: str, elapsed_ms: int, run_id: Any = None
        ) -> None:
            recorded.append((pid, path, elapsed_ms))

    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    monkeypatch.setattr(
        pm_turn_mod.pm, "chat", lambda *a, **k: ("hello", [{"title": "X"}], None, None)
    )

    out = pm_turn_mod.pm_chat(_Mem(), "p1", "hi")  # type: ignore[arg-type]
    assert out["reply"] == "hello"
    assert len(recorded) == 1
    pid, path, elapsed = recorded[0]
    assert pid == "p1" and path == "pm_chat" and elapsed >= 0

    class _Boom(_Mem):
        def record_latency_sample(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("db down")

    # A recorder that raises is swallowed — the reply still comes back.
    assert pm_turn_mod.pm_chat(_Boom(), "p1", "hi")["reply"] == "hello"  # type: ignore[arg-type]


def test_the_turn_passes_the_REFRESHED_overview_to_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The turn must send what `refresh_repo_overview` returned, not the raw stored column.

    Driven through `pm_chat` rather than by calling the builder directly: a parameter accepted
    and silently dropped is exactly the defect shipped on 2026-08-19 (`on_gitlab`), where the
    unit test passed because it exercised the renderer instead of the assembly. The stub store
    below returns a DIFFERENT string from the refresh, so a turn that read the column straight
    would still look plausible — and fail here.
    """
    from types import SimpleNamespace

    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    seen: dict[str, Any] = {}

    class _Mem:
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {"brief": "", "backlog": []}

        def ensure_default_pm_session(self, pid: str) -> str:
            return "s"

        def list_messages(self, pid: str, session_id: str | None = None) -> list[Any]:
            return []

        def add_message(
            self, pid: str, role: str, content: str, session_id: str | None = None
        ) -> int:
            return 1

        def get_repo_overview(self, pid: str) -> str:
            return "STALE — the column"

        def list_project_context_items(self, pid: str) -> list[Any]:
            return []

        def add_message_context_sources(self, mid: int, sources: list[Any]) -> None:
            pass

        def record_latency_sample(self, *a: Any, **k: Any) -> None:
            pass

    def _capture(*a: Any, **k: Any) -> Any:
        seen.update(k)
        return SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])

    monkeypatch.setattr(pcb, "build_pm_context", _capture)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    monkeypatch.setattr(pm_turn_mod.pm, "chat", lambda *a, **k: ("ok", [], None, None))
    monkeypatch.setattr(
        pm_turn_mod, "refresh_repo_overview", lambda *a, **k: ("FRESH — the clone", True)
    )

    pm_turn_mod.pm_chat(_Mem(), "p1", "hi")  # type: ignore[arg-type]

    assert seen["repo_overview"] == "FRESH — the clone"
    assert seen["overview_current"] is True

    # ...and the honesty flag is threaded, not hardcoded.
    monkeypatch.setattr(pm_turn_mod, "refresh_repo_overview", lambda *a, **k: ("old", False))
    pm_turn_mod.pm_chat(_Mem(), "p1", "hi")  # type: ignore[arg-type]
    assert seen["overview_current"] is False


def test_a_proposal_is_persisted_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card must survive a reload, and a credential inside it must not.

    `pm.chat` strips the proposal out of the reply and substitutes "Here's what I'd suggest.", so a
    response-local changeset left a refreshed transcript showing a sentence with nothing under it.
    Redaction rides along because a changeset op can quote the conversation, and the ADR-0105 red
    team found a pasted credential stored verbatim and replayed every turn.
    """
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    from types import SimpleNamespace

    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    stored: list[tuple[int, list[dict[str, Any]]]] = []

    class _Mem:
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {"brief": "", "backlog": []}

        def ensure_default_pm_session(self, pid: str) -> str:
            return f"sess-{pid}"

        def list_messages(self, pid: str, session_id: str | None = None) -> list[Any]:
            return []

        def add_message(
            self, pid: str, role: str, content: str, session_id: str | None = None
        ) -> int:
            return 42

        def get_repo_overview(self, pid: str) -> str:
            return ""

        def list_project_context_items(self, pid: str) -> list[Any]:
            return []

        def add_message_context_sources(self, mid: int, sources: list[Any]) -> None:
            pass

        def record_latency_sample(self, *a: Any, **k: Any) -> None:
            pass

        def add_message_proposals(self, mid: int, proposals: list[dict[str, Any]]) -> None:
            stored.append((mid, proposals))

    secret = "glpat-AAAAAAAAAAAAAAAAAAAA"
    changeset = [{"op": "enhance", "id": 7, "why": f"use the token {secret} to push"}]
    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    monkeypatch.setattr(
        pm_turn_mod.pm,
        "chat",
        lambda *a, **k: ("Here's what I'd suggest.", changeset, {"goal": "ship"}, None),
    )

    pm_turn_mod.pm_chat(_Mem(), "p1", "tidy the backlog")  # type: ignore[arg-type]

    assert stored, "the proposal was not persisted — the card cannot survive a reload"
    mid, proposals = stored[0]
    assert mid == 42  # anchored to the turn that produced it
    by_kind = {p["kind"]: p["payload"] for p in proposals}
    assert by_kind["charter"] == {"goal": "ship"}
    # The op survives; the credential inside it does not.
    assert by_kind["changeset"][0]["op"] == "enhance"
    assert secret not in str(by_kind["changeset"])


def test_a_failed_proposal_write_never_costs_the_operator_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    from types import SimpleNamespace

    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    class _Mem:
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {"brief": "", "backlog": []}

        def ensure_default_pm_session(self, pid: str) -> str:
            return "s"

        def list_messages(self, pid: str, session_id: str | None = None) -> list[Any]:
            return []

        def add_message(self, *a: Any, **k: Any) -> int:
            return 1

        def get_repo_overview(self, pid: str) -> str:
            return ""

        def list_project_context_items(self, pid: str) -> list[Any]:
            return []

        def add_message_context_sources(self, *a: Any, **k: Any) -> None:
            pass

        def record_latency_sample(self, *a: Any, **k: Any) -> None:
            pass

        def add_message_proposals(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("db down")

    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    monkeypatch.setattr(
        pm_turn_mod.pm, "chat", lambda *a, **k: ("hi", [{"op": "enhance"}], None, None)
    )

    out = pm_turn_mod.pm_chat(_Mem(), "p1", "hi")  # type: ignore[arg-type]
    assert out["reply"] == "hi" and out["changeset"] == [{"op": "enhance"}]


class _FailMem:
    """Records every message written, so a test can assert WHAT was persisted and in what role."""

    def __init__(self) -> None:
        self.written: list[tuple[str, str]] = []
        self.proposals: list[Any] = []
        self.sources: list[Any] = []
        self.latency: list[Any] = []

    def project_detail(self, pid: str) -> dict[str, Any]:
        return {"brief": "", "backlog": []}

    def ensure_default_pm_session(self, pid: str) -> str:
        return f"sess-{pid}"

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
        self.sources.append(sources)

    def add_message_proposals(self, mid: int, proposals: list[Any]) -> None:
        self.proposals.append(proposals)

    def record_latency_sample(self, *a: Any, **k: Any) -> None:
        self.latency.append(a)


def _turn(monkeypatch: pytest.MonkeyPatch, chat_impl: Any) -> tuple[Any, dict[str, Any]]:
    from types import SimpleNamespace

    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    monkeypatch.setattr(pm_turn_mod.pm, "chat", chat_impl)
    mem = _FailMem()
    return mem, pm_turn_mod.pm_chat(mem, "p1", "hi")  # type: ignore[arg-type]


def _raises(*a: Any, **k: Any) -> Any:
    raise RuntimeError("ollama: connection reset")


def test_a_raised_model_error_is_not_an_unhandled_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """`robust_invoke` re-raises a transport failure after its 3 attempts, and nothing above
    caught it: the turn became an unhandled exception, Starlette answered 500, and the operator
    read the literal string "500 Internal Server Error: Internal Server Error".

    The call must return an attributed turn instead — a record, not a crash."""
    _mem, out = _turn(monkeypatch, _raises)
    assert out["failure_cause"] == "model_failed"
    assert out["reply"] == ""


def test_a_failed_turn_leaves_no_dangling_user_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user's message is persisted BEFORE the model call, so a raised exception used to leave
    the thread with a question and nothing after it — no reply, no note, no sign anything had been
    attempted."""
    mem, _out = _turn(monkeypatch, _raises)
    assert [role for role, _ in mem.written] == ["user", "note"]


def test_the_failure_row_records_the_cause_token_not_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunDiagnosisCard's charter applied to the transcript: the record is exact, the sentence is
    a reading rendered by the copy deck. Prose here would freeze today's wording into history."""
    mem, _out = _turn(monkeypatch, _raises)
    assert mem.written[-1] == ("note", "model_failed")


def test_a_failure_is_never_stored_as_a_pm_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """It used to be. An apology stored as a `pm` row arrives with Quincy's avatar and name, so
    the operator had to read the sentence to notice that nothing had been answered — and it fed
    back into his own history as if he had said it."""
    mem, _out = _turn(monkeypatch, _raises)
    assert "pm" not in [role for role, _ in mem.written]


def test_an_empty_turn_is_attributed_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The F48 branch, which had no test at all. `empty` and `model_failed` are different facts:
    one is an infrastructure failure, the other is the honest unknown."""
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    _mem, out = _turn(monkeypatch, lambda *a, **k: ("", [], None, None))
    assert out["failure_cause"] == "empty"


def test_a_failed_turn_records_no_proposals_and_no_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was proposed, so there is nothing to approve. And the elapsed time on a
    `model_failed` turn is three retries plus exponential backoff — folding that into the
    `pm_chat` latency series would poison the number with waiting, not model time."""
    mem, _out = _turn(monkeypatch, _raises)
    assert mem.proposals == [] and mem.latency == []


def test_a_completed_turn_carries_an_empty_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `PlanOutcome` shape: a cause is set only on a failure. Always PRESENT, so no client
    ever has to distinguish absent from empty."""
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    _mem, out = _turn(monkeypatch, lambda *a, **k: ("hello", [], None, None))
    assert out["failure_cause"] == ""
    assert out["reply"] == "hello"


def test_a_fenced_only_reply_is_a_completed_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """F48's other half must not regress: a turn carrying a proposal and no prose is an ANSWER —
    the card holds the content — and must not be attributed as a failure."""
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    _mem, out = _turn(
        monkeypatch, lambda *a, **k: ("Here's what I'd suggest.", [{"op": "add"}], None, None)
    )
    assert out["failure_cause"] == ""
