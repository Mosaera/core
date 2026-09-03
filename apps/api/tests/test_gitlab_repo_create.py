"""Creating a GitLab repository by authorizing (ADR-0125) — the GitHub flow's twin.

The properties are the same and are pinned the same way, because the point of this slice is that
the two forges behave alike: the state binding and its spend-before-exchange ordering, the session
re-check, a name that never crosses the redirect, push-before-repoint, and the refusal to touch a
project that already has a repository.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from mosaera_api.routes import gitlab_repo as glr
from mosaera_core.config import Settings
from test_api import _client_with

_ADMIN = {"id": 7, "username": "admin", "is_admin": True}


class _Mem:
    def __init__(self, session: dict[str, Any] | None = None, source: str = "") -> None:
        self.session = session
        self.source = source
        self.minted: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.audits: list[tuple[str, str, str]] = []
        self._binding: dict[str, Any] | None = None

    def session_user(self, token_hash: str, now: Any) -> dict[str, Any] | None:
        return self.session

    def project_detail(self, pid: str) -> dict[str, Any] | None:
        if pid != "p1":
            return None
        return {"id": "p1", "name": "My Widget", "source_repo": self.source, "runs": [{"id": "r1"}]}

    def update_project(self, pid: str, **kw: Any) -> None:
        self.updates.append({"id": pid, **kw})

    def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
        self.audits.append((run_id, event, detail))

    def mint_oauth_state(
        self, state_hash: str, user_id: int, project_id: str, provider: str, expires_at: Any
    ) -> None:
        self.minted.append({"user_id": user_id, "project_id": project_id, "provider": provider})

    def set_binding(self, b: dict[str, Any] | None) -> None:
        self._binding = b

    def spend_oauth_state(self, state_hash: str, provider: str, now: Any) -> dict[str, Any] | None:
        # The real store matches on provider. A connect state must never be spendable here.
        return self._binding if provider == "gitlab-create" else None


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("MOSAERA_GITLAB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MOSAERA_GITLAB_OAUTH_CLIENT_SECRET", "shh")
    monkeypatch.setenv("MOSAERA_BASE_URL", "https://mosaera.example")


def _client(mem: _Mem) -> Any:
    c = _client_with(mem)
    c.cookies.set("mosaera_session", "cookie")
    return c


def _working_repo() -> Path:
    working = Settings.from_env().projects_dir / "p1" / "repo"
    working.mkdir(parents=True, exist_ok=True)
    return working


def _wire(monkeypatch: pytest.MonkeyPatch, *, created: Any, push: Any = ("work", None)) -> dict:
    seen: dict[str, Any] = {"exchanged": [], "created": [], "pushed": [], "minted": []}
    monkeypatch.setattr(
        glr.glw,
        "exchange_oauth_code",
        lambda url, **kw: (seen["exchanged"].append(kw), ("gl_USERTOKEN", None))[1],
    )

    def _create(url: str, token: str, name: str, **kw: Any) -> tuple[Any, str | None]:
        seen["created"].append({"token": token, "name": name})
        return created, None

    def _push(path: Any, **kw: Any) -> tuple[str | None, str | None]:
        seen["pushed"].append({"path": path, **kw})
        return push

    def _mint(url: str, token: str, project: str, **kw: Any) -> tuple[str | None, str | None]:
        seen["minted"].append(project)
        return "glpat-minted", None

    monkeypatch.setattr(glr.glw, "create_project", _create)
    monkeypatch.setattr(glr.glw, "push_existing_project", _push)
    monkeypatch.setattr(glr.glw, "create_project_access_token", _mint)
    return seen


_CREATED = {
    "http_url_to_repo": "https://gitlab.example.com/me/My-Widget.git",
    "path_with_namespace": "me/My-Widget",
}


# ---- start ----------------------------------------------------------------------------


def test_start_redirects_with_the_api_scope_and_a_bound_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`api` is what both creates the project and mints its access token — one grant, one trip."""
    _configure(monkeypatch)
    mem = _Mem(_ADMIN, source="/home/me/widget")
    r = _client(mem).get("/api/oauth/gitlab/create/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://gitlab.example.com/oauth/authorize?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    assert q["scope"] == ["api"] and q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["https://mosaera.example/oauth/gitlab/create/callback"]
    assert "shh" not in loc, "the client secret must never ride the browser redirect"
    rec = mem.minted[0]
    assert rec["user_id"] == 7 and rec["provider"] == "gitlab-create"


def test_start_refuses_a_project_already_on_a_forge(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same control the GitHub path carries: creation may not repoint a working project."""
    _configure(monkeypatch)
    mem = _Mem(_ADMIN, source="https://gitlab.example.com/g/p.git")
    r = _client(mem).get("/api/oauth/gitlab/create/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 400
    assert mem.minted == []


def test_start_refuses_a_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    mem = _Mem({"id": 9, "username": "m", "is_admin": False}, source="/local")
    r = _client(mem).get("/api/oauth/gitlab/create/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 403
    assert mem.minted == []


# ---- callback -------------------------------------------------------------------------


def test_the_project_ends_created_pushed_repointed_and_credentialed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """What GitLab can finish that GitHub cannot: the same grant mints the project's access
    token, so it ends ready to deliver rather than with a connect step to go and do."""
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created=_CREATED)
    working = _working_repo()
    mem = _Mem(_ADMIN, source="/home/me/widget")
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab-create"})

    r = _client(mem).get("/oauth/gitlab/create/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.headers["location"] == "/projects/p1/settings?pane=integration&repo=created"

    # Name DERIVED from the project, never read from the request.
    assert seen["created"][0]["name"] == "My-Widget"
    assert seen["pushed"][0]["path"] == working
    assert seen["minted"] == ["me/My-Widget"]
    # Repointed, then credentialed — both recorded.
    assert {"id": "p1", "source_repo": "https://gitlab.example.com/me/My-Widget.git"} in mem.updates
    assert any("gitlab_token" in u for u in mem.updates)
    assert any(e[1] == "project.gitlab_repo_created" for e in mem.audits)


def test_a_failed_push_leaves_the_project_where_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Fails closed, exactly as the GitHub path does: a project pointed at an empty repository
    cannot run at all, which is strictly worse than not having published."""
    _configure(monkeypatch)
    _wire(monkeypatch, created=_CREATED, push=(None, "remote rejected"))
    _working_repo()
    mem = _Mem(_ADMIN, source="/home/me/widget")
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab-create"})

    r = _client(mem).get("/oauth/gitlab/create/callback?code=abc&state=xyz", follow_redirects=False)
    loc = urllib.parse.unquote(r.headers["location"])
    assert "could not push" in loc and "me/My-Widget" in loc
    assert mem.updates == [], "the project keeps its working source"


def test_a_state_it_cannot_spend_exchanges_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created=_CREATED)
    mem = _Mem(_ADMIN, source="/home/me/widget")
    mem.set_binding(None)

    r = _client(mem).get("/oauth/gitlab/create/callback?code=abc&state=xyz", follow_redirects=False)
    assert "repo_error=" in r.headers["location"]
    assert seen["exchanged"] == [], "no code may be exchanged without a live state"
    assert mem.updates == []


def test_a_session_that_is_not_the_initiating_admin_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created=_CREATED)
    mem = _Mem({"id": 99, "username": "other", "is_admin": True}, source="/home/me/widget")
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "gitlab-create"})

    r = _client(mem).get("/oauth/gitlab/create/callback?code=abc&state=xyz", follow_redirects=False)
    assert "session" in r.headers["location"]
    assert seen["exchanged"] == [] and mem.updates == []
