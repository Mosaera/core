"""Watching a PM turn over one streamed POST.

The runs stream is an EventSource, which is GET-only — a chat turn is a POST with a body, so it
streams its own response instead. What these pin is the part that matters more than the wire
format: the stream is a VIEW of the work. The turn runs on a thread, writes its rows, and finishes
whether or not anyone is still reading.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import RunSubmit, create_app


def _factory(req: RunSubmit, run_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], None]:
    return object(), {"configurable": {"thread_id": run_id}}, {"task": req.task}, None


def _frames(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse the SSE body into (event, data) pairs."""
    out: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln]
        if len(lines) == 2 and lines[0].startswith("event: "):
            out.append((lines[0][7:], json.loads(lines[1][6:])))
    return out


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    import mosaera_api.pm_context_builder as pcb
    import mosaera_api.pm_turn as pm_turn_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    built = SimpleNamespace(context="", history=[], message_attachment_block="", inclusions=[])
    monkeypatch.setattr(pcb, "build_pm_context", lambda *a, **k: built)
    monkeypatch.setattr(pcb, "make_bundle_loader", lambda *a, **k: lambda *a2, **k2: "")
    monkeypatch.setattr(pm_turn_mod, "get_chat_model", lambda role, settings: None)
    return TestClient(create_app(graph_factory=_factory))


def _run_turn(client: TestClient, monkeypatch: pytest.MonkeyPatch, chat_impl: Any) -> Any:
    import mosaera_api.pm_turn as pm_turn_mod

    monkeypatch.setattr(pm_turn_mod.pm, "chat", chat_impl)
    return client.post("/api/projects/p1/messages/stream", json={"text": "hi"})


def test_a_bad_request_is_a_status_code_not_an_error_frame(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guards run synchronously, before the stream opens.

    This matters because once a StreamingResponse starts, the status is already 200 and the only
    way left to report a problem is a frame inside a success — which every generic HTTP client,
    and every retry policy, will read as "it worked". Rejecting first keeps 4xx meaning 4xx.
    """
    response = _run_turn(client, monkeypatch, lambda *a, **k: ("hello", [], None, None))
    assert response.status_code >= 400
    assert "text/event-stream" not in response.headers.get("content-type", "")


class TestFramesFromTheTurn:
    """The event vocabulary, driven through the bridge directly so no project row is needed."""

    def _stream(
        self, monkeypatch: pytest.MonkeyPatch, payload: Any, events: list[Any]
    ) -> list[Any]:
        import asyncio

        import mosaera_api.pm_stream as stream_mod

        def fake_chat(memory: Any, project_id: str, text: str, **kwargs: Any) -> dict[str, Any]:
            for kind, data in events:
                kwargs["on_event"](kind, data)
            return payload

        monkeypatch.setattr(stream_mod, "pm_chat", fake_chat)

        async def drain() -> list[str]:
            gen = stream_mod.stream_turn(cast(Any, object()), "p1", "hi")
            return [chunk async for chunk in gen]

        return _frames("".join(asyncio.run(drain())))

    def test_steps_and_prose_arrive_before_the_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frames = self._stream(
            monkeypatch,
            {"reply": "Eight runs.", "failure_cause": ""},
            [
                ("step", {"kind": "project_history", "detail": "failures"}),
                ("text", {"text": "Let me check."}),
            ],
        )
        assert [name for name, _ in frames] == ["step", "text", "done"]
        assert frames[-1][1]["reply"] == "Eight runs."

    def test_a_failed_turn_carries_its_cause_in_the_done_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No separate `failed` event: the payload already names the cause, and one place to read
        an outcome cannot disagree with itself."""
        frames = self._stream(monkeypatch, {"reply": "", "failure_cause": "budget_exhausted"}, [])
        assert frames[-1][0] == "done"
        assert frames[-1][1]["failure_cause"] == "budget_exhausted"

    def test_an_unexpected_break_is_reported_not_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`pm_chat` handles its own failures, so reaching here means something outside that
        contract broke. A reader left waiting on a queue nobody will fill is the worse outcome."""
        import asyncio

        import mosaera_api.pm_stream as stream_mod

        def boom(*a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("the floor gave way")

        monkeypatch.setattr(stream_mod, "pm_chat", boom)

        async def drain() -> list[str]:
            gen = stream_mod.stream_turn(cast(Any, object()), "p1", "hi")
            return [chunk async for chunk in gen]

        frames = _frames("".join(asyncio.run(drain())))
        assert frames[-1][0] == "error"
        assert "floor gave way" in frames[-1][1]["detail"]

    def test_the_turn_completes_even_with_nobody_reading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The load-bearing property. The work is on a thread and persists its own rows; the
        stream only watches. Closing the tab costs the animation, never the answer."""
        import asyncio

        import mosaera_api.pm_stream as stream_mod

        finished: list[bool] = []

        def fake_chat(memory: Any, project_id: str, text: str, **kwargs: Any) -> dict[str, Any]:
            kwargs["on_event"]("step", {"kind": "project_history", "detail": "failures"})
            finished.append(True)
            return {"reply": "done", "failure_cause": ""}

        monkeypatch.setattr(stream_mod, "pm_chat", fake_chat)

        async def abandon() -> None:
            agen = stream_mod.stream_turn(cast(Any, object()), "p1", "hi")
            await agen.__anext__()  # read the first frame only
            await agen.aclose()  # then walk away

        asyncio.run(abandon())
        assert finished == [True], "the turn did not run to completion without a reader"
