"""Offline tests for PM chat sessions (issue #30): the session lifecycle endpoints and
session-scoped chat. Uses ``create_app(memory=...)`` with a duck-typed in-memory store, so no
database or model is needed — the model call is stubbed. The store-level scoping/backfill is
covered against real Postgres in ``packages/memory/tests/test_store.py``."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import create_app


class _FakeSessionMemory:
    """Duck-typed MemoryStore covering the session + message surface the routes touch."""

    def __init__(self) -> None:
        self.projects = {"p1": {"id": "p1", "brief": "b", "backlog": [], "runs": []}}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.msgs: list[dict[str, Any]] = []
        self._n = 0

    # projects / context (read by pm_chat + the routes)
    def project_detail(self, pid: str) -> dict[str, Any] | None:
        return self.projects.get(pid)

    def get_repo_overview(self, pid: str) -> str:
        return ""

    def list_project_context_items(self, pid: str) -> list[dict[str, Any]]:
        return []

    # sessions
    def create_pm_session(self, pid: str, title: str = "") -> str:
        self._n += 1
        sid = f"sess-{self._n}"
        self.sessions[sid] = {
            "id": sid,
            "project_id": pid,
            "title": title,
            "created_at": None,
            "updated_at": None,
            "archived": False,
            "archived_at": None,
            "message_count": 0,
        }
        return sid

    def get_pm_session(self, sid: str) -> dict[str, Any] | None:
        s = self.sessions.get(sid)
        if s is None:
            return None
        out = dict(s)
        out["message_count"] = sum(1 for m in self.msgs if m["session_id"] == sid)
        return out

    def list_pm_sessions(self, pid: str, include_archived: bool = False) -> list[dict[str, Any]]:
        out = []
        for s in self.sessions.values():
            if s["project_id"] != pid or (s["archived"] and not include_archived):
                continue
            row = dict(s)
            row["message_count"] = sum(1 for m in self.msgs if m["session_id"] == s["id"])
            out.append(row)
        return out

    def ensure_default_pm_session(self, pid: str) -> str:
        active = [s for s in self.sessions.values() if s["project_id"] == pid and not s["archived"]]
        return active[-1]["id"] if active else self.create_pm_session(pid)

    def rename_pm_session(self, sid: str, title: str) -> None:
        self.sessions[sid]["title"] = title

    def set_pm_session_archived(self, sid: str, archived: bool) -> None:
        self.sessions[sid]["archived"] = archived
        self.sessions[sid]["archived_at"] = "t" if archived else None

    # messages
    def list_messages(self, pid: str, session_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "role": m["role"],
                "content": m["content"],
                "created_at": None,
                "attachments": [],
                "context_sources": [],
            }
            for m in self.msgs
            if m["project_id"] == pid and (session_id is None or m["session_id"] == session_id)
        ]

    def add_message(self, pid: str, role: str, content: str, session_id: str | None = None) -> int:
        sid = session_id or self.ensure_default_pm_session(pid)
        self._n += 1
        self.msgs.append(
            {"id": self._n, "project_id": pid, "role": role, "content": content, "session_id": sid}
        )
        s = self.sessions[sid]
        if role == "user" and not s["title"] and content.strip():
            s["title"] = content[:60]
        return self._n

    # pm_chat incidentals
    def get_attachment(self, aid: str) -> None:
        return None

    def link_message_attachments(self, *a: Any) -> None: ...
    def add_message_context_sources(self, *a: Any) -> None: ...
    def record_latency_sample(self, *a: Any) -> None: ...


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    # No real model call — pm.chat is the only model touch on the chat turn.
    import mosaera_agents.pm as pm
    import mosaera_core.models as models

    monkeypatch.setattr(pm, "chat", lambda *a, **k: ("ok reply", [], None, None))
    monkeypatch.setattr(models, "get_chat_model", lambda *a, **k: None)
    return TestClient(
        create_app(graph_factory=lambda *a, **k: None, memory=_FakeSessionMemory())  # type: ignore[arg-type]
    )


def _texts(client: TestClient, url: str) -> list[str]:
    return [m["content"] for m in client.get(url).json()["messages"]]


def test_sessions_start_empty_and_create(client: TestClient) -> None:
    assert client.get("/api/projects/p1/sessions").json() == {"sessions": []}
    created = client.post("/api/projects/p1/sessions", json={"title": "Alpha"})
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "Alpha" and body["project_id"] == "p1"
    assert [s["id"] for s in client.get("/api/projects/p1/sessions").json()["sessions"]] == [
        body["id"]
    ]


def test_history_is_scoped_per_session(client: TestClient) -> None:
    a = client.post("/api/projects/p1/sessions", json={}).json()["id"]
    b = client.post("/api/projects/p1/sessions", json={}).json()["id"]
    client.post("/api/projects/p1/messages", json={"text": "in A", "session_id": a})
    client.post("/api/projects/p1/messages", json={"text": "in B", "session_id": b})
    # Each session sees only its own turns — the boundary that makes #30 real.
    assert _texts(client, f"/api/projects/p1/messages?session_id={a}") == ["in A", "ok reply"]
    assert _texts(client, f"/api/projects/p1/messages?session_id={b}") == ["in B", "ok reply"]
    # No session_id → the whole project (legacy behaviour, e.g. decomposition).
    assert _texts(client, "/api/projects/p1/messages") == ["in A", "ok reply", "in B", "ok reply"]


def test_first_user_turn_autonames_session(client: TestClient) -> None:
    s = client.post("/api/projects/p1/sessions", json={}).json()
    assert s["title"] == ""
    client.post(
        "/api/projects/p1/messages", json={"text": "Add OAuth login", "session_id": s["id"]}
    )
    assert (
        client.get("/api/projects/p1/sessions").json()["sessions"][0]["title"] == "Add OAuth login"
    )


def test_send_without_session_uses_default(client: TestClient) -> None:
    # No session named and none exists → the send creates the project's first session.
    client.post("/api/projects/p1/messages", json={"text": "hello"})
    sessions = client.get("/api/projects/p1/sessions").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["message_count"] == 2


def test_archive_hides_from_active_but_preserves(client: TestClient) -> None:
    a = client.post("/api/projects/p1/sessions", json={}).json()["id"]
    client.post("/api/projects/p1/sessions", json={})
    r = client.patch(f"/api/projects/p1/sessions/{a}", json={"archived": True})
    assert r.status_code == 200 and r.json()["archived"] is True
    active = [s["id"] for s in client.get("/api/projects/p1/sessions").json()["sessions"]]
    assert a not in active
    all_ids = [
        s["id"]
        for s in client.get("/api/projects/p1/sessions?include_archived=true").json()["sessions"]
    ]
    assert a in all_ids  # archive is soft — the thread still exists


def test_rename_session(client: TestClient) -> None:
    a = client.post("/api/projects/p1/sessions", json={}).json()["id"]
    r = client.patch(f"/api/projects/p1/sessions/{a}", json={"title": "Renamed"})
    assert r.status_code == 200 and r.json()["title"] == "Renamed"


def test_unknown_project_and_session_404(client: TestClient) -> None:
    assert client.get("/api/projects/nope/sessions").status_code == 404
    assert client.post("/api/projects/nope/sessions", json={}).status_code == 404
    # A session id that doesn't exist (or belongs elsewhere) can't be posted into or patched.
    assert (
        client.post("/api/projects/p1/messages", json={"text": "x", "session_id": "ghost"})
    ).status_code == 404
    assert client.patch("/api/projects/p1/sessions/ghost", json={"title": "x"}).status_code == 404
