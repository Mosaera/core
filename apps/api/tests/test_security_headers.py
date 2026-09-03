"""Every response carries the CSP — including the ones that never reach a route.

The PM chat renders model-authored markdown, and that model reads untrusted content by design
(ADR-0105). `PmMarkdown` overrides `img` so a model-named URL is never fetched; this is the layer
underneath, and the reason for two layers is that the first one is a single edit away from being
undone while its failure is silent.

The ordering half is the part worth pinning. `install_security_headers` is registered last so it
is OUTERMOST — a 401 from the auth middleware short-circuits everything inside it, and a response
that renders without a policy is exactly the one an attacker would like to reach.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import RunSubmit, create_app


def _fake_factory(req: RunSubmit, run_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], None]:
    return object(), {"configurable": {"thread_id": run_id}}, {"task": req.task}, None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    return TestClient(create_app(graph_factory=_fake_factory))


def _csp(response: Any) -> dict[str, str]:
    """The policy as {directive: value}, so a test can assert on one without substring games."""
    raw = response.headers["Content-Security-Policy"]
    out = {}
    for part in raw.split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            out[name] = value.strip()
    return out


def test_the_policy_blocks_remote_images(client: TestClient) -> None:
    """The directive this whole slice exists for. `blob:` and `data:` are the app's own
    previews (PmComposer's pending uploads, inline icons); no host may be added here."""
    directives = _csp(client.get("/healthz"))
    assert directives["img-src"] == "'self' data: blob:"
    assert "http" not in directives["img-src"]


def test_no_fetch_directive_permits_a_remote_origin(client: TestClient) -> None:
    """A CSP is only as tight as its loosest directive: a remote `connect-src` exfiltrates just
    as well as a remote `img-src`, and a wildcard anywhere would make this file decorative.

    `form-action` is excluded here and given its own, STRICTER test below. It is not a fetch
    directive — it governs where a user-initiated navigation may go, not where the page may load
    from or send data to from script — and ADR-0121 needs exactly one host there. Excluding it
    from a blanket rule while pinning it precisely is the narrow change; deleting the rule to fit
    a feature would not be."""
    for name, value in _csp(client.get("/healthz")).items():
        assert "*" not in value, f"{name} permits any origin"
        if name == "form-action":
            continue
        assert "//" not in value, f"{name} names a remote origin"


def test_form_action_names_only_the_configured_github_host(client: TestClient) -> None:
    """GitHub's App-manifest registration requires the browser to POST cross-origin to the GitHub
    host (ADR-0121); `form-action 'self'` blocked it silently — no navigation, no error, just a
    console violation, which is how the setup button appeared to do nothing.

    So exactly one remote host is permitted, it must be https, and it must be the one this
    instance is configured to talk to — not an arbitrary origin, and not a wildcard."""
    from mosaera_core.config import Settings

    value = _csp(client.get("/healthz"))["form-action"]
    tokens = value.split()
    assert tokens[0] == "'self'"
    assert len(tokens) <= 2, "form-action may name at most one remote host"
    if len(tokens) == 2:
        assert tokens[1] == Settings.from_env().github_web_url.rstrip("/")
        assert tokens[1].startswith("https://")


def test_unsafe_inline_is_confined_to_styles(client: TestClient) -> None:
    """React writes `style={{...}}` attributes and there is no way to hash those. Scripts have
    no such excuse, and 'unsafe-inline' there would undo the policy."""
    directives = _csp(client.get("/healthz"))
    assert directives["style-src"] == "'self' 'unsafe-inline'"
    assert directives["script-src"] == "'self'"


def test_headers_survive_a_401(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """The ordering assertion. With auth configured, an unauthenticated /api request is answered
    by the auth middleware and never reaches a route — the header must still be there, which is
    only true while this middleware is the outermost layer."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_API_TOKEN", "secret-token")
    client = TestClient(create_app(graph_factory=_fake_factory))
    response = client.get("/api/runs")
    assert response.status_code == 401
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_headers_survive_a_404(client: TestClient) -> None:
    """A path with no handler is answered by Starlette itself, inside everything we register."""
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert "Content-Security-Policy" in response.headers


def test_the_supporting_headers_are_set(client: TestClient) -> None:
    headers = client.get("/healthz").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    # Project and run ids live in the path; no referrer should carry them off-origin.
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"
