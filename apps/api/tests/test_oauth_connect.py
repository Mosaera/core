"""GitLab OAuth "Connect" (ADR-0104): the start + callback contract and its security posture.

These are the offline evidence for the trust boundary — state binding, the single-use spend, the
callback's live-session re-check, and the fail-safe redirects — driven through a fake store so no
DB or network is needed. The state-store's DB-level single-use/expiry semantics run in the
Postgres suite; here the fake lets us pin the ENDPOINT logic that decides whether a token is ever
minted.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import create_app
from test_api import _client_with, _fake_factory

_SOURCE = "https://gitlab.rengifo.me/g/p.git"


class _OAuthMem:
    """A duck-typed store for the OAuth endpoints. ``session`` is whatever the tests want
    ``current_user`` to resolve to (an admin dict, a different user, or None)."""

    def __init__(self, session: dict[str, Any] | None) -> None:
        self.session = session
        self.minted: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.audits: list[tuple[str, str, str]] = []
        self._binding: dict[str, Any] | None = None

    # --- auth surface ---
    def session_user(self, token_hash: str, now: Any) -> dict[str, Any] | None:
        return self.session

    # --- project surface ---
    def project_detail(self, pid: str) -> dict[str, Any] | None:
        if pid != "p1":
            return None
        return {"id": "p1", "source_repo": _SOURCE, "runs": [{"id": "run-1"}]}

    def update_project(self, pid: str, **kw: Any) -> None:
        self.updates.append({"id": pid, **kw})

    def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
        self.audits.append((run_id, event, detail))

    # --- oauth state surface ---
    def mint_oauth_state(
        self, state_hash: str, user_id: int, project_id: str, provider: str, expires_at: Any
    ) -> None:
        self.minted.append(
            {"hash": state_hash, "user_id": user_id, "project_id": project_id, "provider": provider}
        )

    def set_binding(self, binding: dict[str, Any] | None) -> None:
        self._binding = binding

    def spend_oauth_state(self, state_hash: str, provider: str, now: Any) -> dict[str, Any] | None:
        return self._binding


_ADMIN = {"id": 7, "username": "admin", "is_admin": True}


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITLAB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MOSAERA_GITLAB_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MOSAERA_BASE_URL", "https://mosaera.example")


def _client(mem: _OAuthMem) -> Any:
    c = _client_with(mem)
    c.cookies.set("mosaera_session", "cookie")  # current_user → mem.session_user(...)
    return c


# ---- start ----------------------------------------------------------------------------------


def test_start_redirects_to_authorize_and_mints_bound_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    mem = _OAuthMem(_ADMIN)
    r = _client(mem).get("/api/oauth/gitlab/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://gitlab.rengifo.me/oauth/authorize?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    assert q["client_id"] == ["cid"] and q["response_type"] == ["code"] and q["scope"] == ["api"]
    assert q["redirect_uri"] == ["https://mosaera.example/oauth/callback"]
    assert q["state"]  # opaque; only its hash is stored
    # The state is bound to the initiating admin + the selected project, and STORED HASHED
    # (the plaintext in the URL never appears in the mint record).
    assert len(mem.minted) == 1
    rec = mem.minted[0]
    assert rec["user_id"] == 7 and rec["project_id"] == "p1" and rec["provider"] == "gitlab"
    assert rec["hash"] != q["state"][0]


def test_start_400_when_oauth_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_GITLAB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("MOSAERA_GITLAB_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("MOSAERA_BASE_URL", raising=False)
    r = _client(_OAuthMem(_ADMIN)).get("/api/oauth/gitlab/start?project_id=p1")
    assert r.status_code == 400 and "not configured" in r.json()["detail"]


def test_start_400_without_a_logged_in_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # A header/token admin passes the admin gate but has NO browser session to ride the redirect;
    # the flow is inherently session-based, so it must refuse honestly (not silently mint an
    # unbindable state). Authorize via the admin token, resolve no session → 400.
    _configure(monkeypatch)
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    c = _client(_OAuthMem(None))
    r = c.get("/api/oauth/gitlab/start?project_id=p1", headers={"X-Mosaera-Admin": "adm1n"})
    assert r.status_code == 400 and "session" in r.json()["detail"]


def test_start_404_for_unknown_project(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    r = _client(_OAuthMem(_ADMIN)).get("/api/oauth/gitlab/start?project_id=nope")
    assert r.status_code == 404


# ---- callback -------------------------------------------------------------------------------


def _patch_gitlab(monkeypatch: pytest.MonkeyPatch, *, exchange: Any, mint: Any) -> dict[str, int]:
    """Patch the two GitLab OAuth calls; return a dict counting how often each was invoked."""
    import mosaera_api.routes.oauth as oauth_mod

    calls = {"exchange": 0, "mint": 0}

    def _ex(*a: Any, **k: Any) -> Any:
        calls["exchange"] += 1
        return exchange

    def _mint(*a: Any, **k: Any) -> Any:
        calls["mint"] += 1
        return mint

    monkeypatch.setattr(oauth_mod.glw, "exchange_oauth_code", _ex)
    monkeypatch.setattr(oauth_mod.glw, "create_project_access_token", _mint)
    return calls


def test_callback_happy_path_mints_stores_both_tokens_and_discards_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    calls = _patch_gitlab(
        monkeypatch, exchange=("user-grant-tok", None), mint=("glpat-minted", None)
    )
    mem = _OAuthMem(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab"})
    r = _client(mem).get("/oauth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302
    # Lands on the Integration PANE, not the settings root — the pane is where the result shows
    # (ADR-0104 Amendment 2). Still a fixed internal literal: nothing here comes from the request.
    assert r.headers["location"] == "/projects/p1/settings?pane=integration&oauth=connected"
    # The MINTED project token populates BOTH credential roles; the OAuth grant is never stored.
    assert len(mem.updates) == 1
    up = mem.updates[0]
    assert up["gitlab_token"] == "glpat-minted" and up["gitlab_api_token"] == "glpat-minted"
    assert "user-grant-tok" not in up.values()
    assert calls == {"exchange": 1, "mint": 1}
    assert mem.audits and mem.audits[0][1] == "project.oauth_connected"


def test_callback_rejects_an_invalid_or_replayed_state_before_any_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    calls = _patch_gitlab(monkeypatch, exchange=("x", None), mint=("y", None))
    mem = _OAuthMem(_ADMIN)
    mem.set_binding(None)  # spend finds nothing (replayed / expired / forged)
    r = _client(mem).get("/oauth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302 and "oauth_error" in r.headers["location"]
    # No code was exchanged and no token minted — the state check gates everything downstream.
    assert calls == {"exchange": 0, "mint": 0}
    assert mem.updates == []


def test_callback_refuses_when_the_session_is_not_the_initiating_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    calls = _patch_gitlab(monkeypatch, exchange=("x", None), mint=("y", None))
    # State was bound to admin 7, but the live session is a DIFFERENT user.
    mem = _OAuthMem({"id": 9, "username": "mallory", "is_admin": True})
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab"})
    r = _client(mem).get("/oauth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302 and "oauth_error" in r.headers["location"]
    assert calls["exchange"] == 0 and mem.updates == []


def test_callback_refuses_a_non_admin_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    calls = _patch_gitlab(monkeypatch, exchange=("x", None), mint=("y", None))
    mem = _OAuthMem({"id": 7, "username": "user", "is_admin": False})
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab"})
    r = _client(mem).get("/oauth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302 and "oauth_error" in r.headers["location"]
    assert calls["exchange"] == 0 and mem.updates == []


def test_callback_redirects_on_provider_error_without_spending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    calls = _patch_gitlab(monkeypatch, exchange=("x", None), mint=("y", None))
    mem = _OAuthMem(_ADMIN)
    r = _client(mem).get("/oauth/callback?error=access_denied", follow_redirects=False)
    assert r.status_code == 302 and "oauth_error" in r.headers["location"]
    assert calls["exchange"] == 0 and mem.updates == []


def test_callback_stores_nothing_when_the_mint_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    # The code exchanges fine but the project-token mint errors (e.g. insufficient role).
    calls = _patch_gitlab(
        monkeypatch, exchange=("user-grant-tok", None), mint=(None, "403: forbidden")
    )
    mem = _OAuthMem(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab"})
    r = _client(mem).get("/oauth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302 and "oauth_error" in r.headers["location"]
    assert calls == {"exchange": 1, "mint": 1} and mem.updates == []  # fail-closed: no token stored


def test_callback_redirect_target_is_always_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Open-redirect guard: every callback outcome lands on our own /projects path — the redirect
    # target is NEVER taken from the request, so a crafted param can't bounce the browser off-site.
    _configure(monkeypatch)
    _patch_gitlab(monkeypatch, exchange=("t", None), mint=("m", None))
    mem = _OAuthMem(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab"})
    for qs in ("code=c&state=s", "error=x", "code=c&state=s&redirect_uri=https://evil.example"):
        mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab"})
        loc = _client(mem).get(f"/oauth/callback?{qs}", follow_redirects=False).headers["location"]
        assert loc.startswith("/projects") or loc.startswith("/projects/")
        assert "evil.example" not in loc


# ---- turnkey setup: OAuth app creds are UI-settable + encrypted (ADR-0104 amendment) ----


def test_oauth_config_encrypts_secret_masks_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # The OAuth app creds are settable from the admin UI like the global token: the SECRET is
    # encrypted at rest + decrypted by from_env, the status reports presence only (never the
    # secret), and an env var still overrides the stored value.
    import mosaera_connectors.gitlab_write as glw_mod
    from cryptography.fernet import Fernet
    from mosaera_core.config import Settings
    from mosaera_core.settings_store import read_settings

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    for k in (
        "MOSAERA_GITLAB_OAUTH_CLIENT_ID",
        "MOSAERA_GITLAB_OAUTH_CLIENT_SECRET",
        "MOSAERA_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    # Don't hit the network to verify — that's covered by its own test below.
    monkeypatch.setattr(glw_mod, "verify_oauth_client", lambda *a, **k: (True, "verified"))

    c = TestClient(create_app(graph_factory=_fake_factory))
    resp = c.post(
        "/api/gitlab/config",
        json={
            "oauth_client_id": "app-id-abcd",
            "oauth_client_secret": "gloas-SECRET9999",
            "base_url": "https://mosaera.example/",  # trailing slash must be stripped
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["oauth_configured"] is True and body["oauth_secret_set"] is True
    assert (
        body["oauth_client_id_masked"] == "…abcd" and body["base_url"] == "https://mosaera.example"
    )
    assert "gloas-SECRET9999" not in resp.text  # the secret is never echoed

    stored = read_settings(tmp_path)
    assert stored["gitlab_oauth_client_secret"].startswith("enc:v1:")  # encrypted at rest
    assert "gloas-SECRET9999" not in stored["gitlab_oauth_client_secret"]
    assert stored["gitlab_oauth_client_id"] == "app-id-abcd"  # id is not secret → plaintext
    assert stored["base_url"] == "https://mosaera.example"

    s = Settings.from_env()  # from_env decrypts the secret back
    assert s.gitlab_oauth_client_secret == "gloas-SECRET9999"
    assert s.gitlab_oauth_client_id == "app-id-abcd" and s.base_url == "https://mosaera.example"
    assert "gloas-SECRET9999" not in c.get("/api/gitlab/status").text

    monkeypatch.setenv("MOSAERA_GITLAB_OAUTH_CLIENT_SECRET", "gloas-FROM-ENV")  # env wins
    assert Settings.from_env().gitlab_oauth_client_secret == "gloas-FROM-ENV"


def test_oauth_config_rejects_an_invalid_client_secret_before_storing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # The reported gap: a wrong secret sailed through to "configured". Now the save VERIFIES the
    # id+secret against GitLab (client_credentials probe) and refuses invalid_client up front —
    # nothing is stored, so the card stays not-configured instead of failing later at Connect.
    import mosaera_connectors.gitlab_write as glw_mod
    from mosaera_core.settings_store import read_settings

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    for k in (
        "MOSAERA_GITLAB_OAUTH_CLIENT_ID",
        "MOSAERA_GITLAB_OAUTH_CLIENT_SECRET",
        "MOSAERA_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        glw_mod,
        "verify_oauth_client",
        lambda *a, **k: (False, "GitLab rejected the Application ID or Secret (invalid_client)."),
    )

    c = TestClient(create_app(graph_factory=_fake_factory))
    resp = c.post(
        "/api/gitlab/config",
        json={
            "oauth_client_id": "app-id",
            "oauth_client_secret": "wrong-secret",
            "base_url": "https://mosaera.example",
        },
    )
    assert resp.status_code == 400 and "invalid_client" in resp.json()["detail"]
    # NOTHING was written — the bad secret is not persisted.
    assert read_settings(tmp_path).get("gitlab_oauth_client_secret") in (None, "")


def test_oauth_config_rejects_a_malformed_base_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    c = TestClient(create_app(graph_factory=_fake_factory))
    resp = c.post("/api/gitlab/config", json={"base_url": "mosaera.example"})  # no scheme
    assert resp.status_code == 400 and "http" in resp.json()["detail"]


def test_oauth_config_can_be_cleared_disconnect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Reconfigure/disconnect: posting empty strings clears all three, so a stale/wrong config can
    # be wiped from the UI and the card returns to not-configured.
    import mosaera_connectors.gitlab_write as glw_mod
    from mosaera_core.config import Settings

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    for k in (
        "MOSAERA_GITLAB_OAUTH_CLIENT_ID",
        "MOSAERA_GITLAB_OAUTH_CLIENT_SECRET",
        "MOSAERA_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(glw_mod, "verify_oauth_client", lambda *a, **k: (True, "verified"))

    c = TestClient(create_app(graph_factory=_fake_factory))
    c.post(
        "/api/gitlab/config",
        json={
            "oauth_client_id": "id",
            "oauth_client_secret": "sec",
            "base_url": "https://m.example",
        },
    )
    assert c.get("/api/gitlab/status").json()["oauth_configured"] is True
    # Disconnect: empty strings clear.
    cleared = c.post(
        "/api/gitlab/config",
        json={"oauth_client_id": "", "oauth_client_secret": "", "base_url": ""},
    ).json()
    assert cleared["oauth_configured"] is False
    s = Settings.from_env()
    assert not s.gitlab_oauth_client_id and not s.gitlab_oauth_client_secret and not s.base_url


def test_oauth_status_reports_env_pinned(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # When an OAuth value comes from an env var (env > stored), the status flags it so the UI can
    # show the form is read-only instead of silently ignoring a save.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    for k in (
        "MOSAERA_GITLAB_OAUTH_CLIENT_ID",
        "MOSAERA_GITLAB_OAUTH_CLIENT_SECRET",
        "MOSAERA_BASE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.get("/api/gitlab/status").json()["oauth_env_pinned"] is False
    monkeypatch.setenv("MOSAERA_GITLAB_OAUTH_CLIENT_SECRET", "gloas-from-env")
    assert c.get("/api/gitlab/status").json()["oauth_env_pinned"] is True
