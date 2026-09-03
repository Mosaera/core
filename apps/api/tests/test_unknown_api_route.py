"""An unknown `/api` path is a 404 for EVERY verb, not just GET.

The SPA catch-all is `@app.get`, so it only answered GET. A POST/PUT/DELETE to a path no real route
claimed fell through to Starlette's method check against that GET-only route and came back **405
Method Not Allowed** — telling a client "this path exists, wrong verb" about a path that does not
exist. `app.py`'s own comment already commits to the opposite; the fix it describes covered GET
alone.

**These tests build a `dist` on purpose.** Neither handler is registered without one, and
`make ci` runs `build` AFTER `test` — so in CI there is no bundle, the catch-all does not exist,
and a test that assumes production shape passes by never exercising it. That is the same
green-by-vacancy the GET half's comment records, and it is why the fixture below writes an
`index.html` rather than relying on whatever happens to be on disk.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _fake_factory(req: Any, run_id: str) -> Any:
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        task: str

    b: StateGraph = StateGraph(S)
    b.add_node("n", lambda s: {"task": s.get("task", "")})
    b.add_edge(START, "n")
    b.add_edge("n", END)
    return b.compile(), {"configurable": {"thread_id": run_id}}, {"task": req.task}, None


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """An app serving a REAL bundle — the production shape, which CI never builds."""
    from mosaera_api.app import create_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body><div id=root></div></body></html>")
    yield TestClient(create_app(graph_factory=_fake_factory, memory=None, web_dist=dist))


def test_the_fixture_really_serves_the_SPA__or_nothing_below_is_tested(
    client: TestClient,
) -> None:
    """THE CONTROL. Without a registered catch-all every assertion below passes trivially, because
    the handler under test does not exist. Prove the SPA path is live first."""
    r = client.get("/some/client/route")
    assert r.status_code == 200 and "<div id=root>" in r.text, (
        "the SPA catch-all is not registered, so the 404 tests below prove nothing"
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_an_unknown_api_path_is_404_for_every_verb(client: TestClient, method: str) -> None:
    """THE defect: these returned 405 — "wrong verb" for a path that does not exist."""
    r = client.request(method, "/api/definitely-not-a-route", json={})
    assert r.status_code == 404, f"{method} on an unknown /api path returned {r.status_code}"


def test_GET_on_an_unknown_api_path_is_still_404(client: TestClient) -> None:
    """The half that already worked must keep working — the SPA must never answer for /api."""
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    assert "<div id=root>" not in r.text, "an /api path was answered with the SPA"


def test_a_REAL_api_route_still_wins(client: TestClient) -> None:
    """First-match-wins: the new handler is registered after every real router, so it must not
    shadow one. If this fails the fix has broken the API rather than its 404s."""
    assert client.get("/api/auth/status").status_code == 200


def test_a_non_api_client_route_still_gets_the_SPA(client: TestClient) -> None:
    """The new handler is scoped to /api and must not swallow client-side routing."""
    for path in ("/projects/abc", "/settings", "/"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} should serve the SPA, got {r.status_code}"
