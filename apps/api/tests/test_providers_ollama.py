"""POST /providers/test's local (Ollama) branch — M1 fix (#119).

Split out as its own file rather than grown onto the grandfathered ``test_api.py`` (the
5.7k-line file the size ratchet is working down; ``test_settings_general.py`` set this
precedent already). Uses ``create_app()`` with no graph factory, same as that file — this
route never touches the run graph.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import create_app


def test_providers_test_endpoint_ollama(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """The local branch of POST /providers/test probes the Ollama server itself and returns
    the SAME {ok, count, models} shape a hosted provider does — a 422 here used to make an
    Ollama role change unsaveable from the primary Settings screen (RoleRow's Test→Save gate
    never reaches "ready" on a non-2xx response)."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app())
    hdr = {"X-Mosaera-Admin": "adm1n"}

    # Server unreachable → ok:false, a human sentence naming Ollama, never a raw exception dump.
    def _boom(*_a: object, **_k: object) -> object:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.get", _boom)
    down = c.post("/api/providers/test", headers=hdr, json={"provider": "ollama"})
    assert down.status_code == 200
    body = down.json()
    assert body["ok"] is False and body["count"] == 0 and body["models"] == []
    assert "ollama" in body["error"].lower() or "reach" in body["error"].lower()

    # Server reachable, tags served → ok:true with the served model list, distinguishing
    # "unreachable" from "reachable but this model isn't pulled" (the caller checks membership).
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"models": [{"name": "qwen3-coder:30b"}, {"name": "gpt-oss:20b"}]}

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp())
    up = c.post("/api/providers/test", headers=hdr, json={"provider": "ollama"})
    assert up.status_code == 200
    ubody = up.json()
    assert ubody["ok"] is True and ubody["count"] == 2
    assert "qwen3-coder:30b" in ubody["models"] and "gpt-oss:20b" in ubody["models"]
    # A model that is NOT in the served list is simply absent — the client's own membership
    # check (`res.models.includes(model)`) is what turns that into "not pulled".
    assert "llama3:8b" not in ubody["models"]


def test_providers_test_endpoint_ollama_unknown_provider_still_422(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A genuinely unknown provider id is still a real validation error (422) — only "ollama
    is not testable" was the M1 bug; "not a provider at all" stays a client mistake."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app())
    r = c.post(
        "/api/providers/test",
        headers={"X-Mosaera-Admin": "adm1n"},
        json={"provider": "not-a-real-provider"},
    )
    assert r.status_code == 422
