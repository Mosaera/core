"""GitHub repository creation by authorization (ADR-0120): the start + callback contract.

The offline evidence for a NEW trust boundary — the first user-token grant in the GitHub path.
ADR-0114 avoided a redirect entirely; this one needs a real handshake, so these tests pin the
properties that make it safe: the state binding and its single-use spend, the callback's
live-session re-check, the fact that nothing from the redirect names the repository, and that the
user grant is never persisted. Driven through a fake store — no DB, no network.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from mosaera_api.routes import github_repo as ghr
from mosaera_core.config import Settings
from test_api import _client_with

_ADMIN = {"id": 7, "username": "admin", "is_admin": True}


class _Mem:
    def __init__(self, session: dict[str, Any] | None = None) -> None:
        self.session = session
        self.minted: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.audits: list[tuple[str, str, str]] = []
        self._binding: dict[str, Any] | None = None

    def session_user(self, token_hash: str, now: Any) -> dict[str, Any] | None:
        return self.session

    def project_detail(self, pid: str) -> dict[str, Any] | None:
        if pid != "p1":
            return None
        return {"id": "p1", "name": "My Widget", "source_repo": "", "runs": [{"id": "run-1"}]}

    def update_project(self, pid: str, **kw: Any) -> None:
        self.updates.append({"id": pid, **kw})

    def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
        self.audits.append((run_id, event, detail))

    def mint_oauth_state(
        self, state_hash: str, user_id: int, project_id: str, provider: str, expires_at: Any
    ) -> None:
        self.minted.append(
            {"hash": state_hash, "user_id": user_id, "project_id": project_id, "provider": provider}
        )

    def set_binding(self, binding: dict[str, Any] | None) -> None:
        self._binding = binding

    def spend_oauth_state(self, state_hash: str, provider: str, now: Any) -> dict[str, Any] | None:
        return self._binding if provider == "github" else None


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MOSAERA_GITHUB_OAUTH_CLIENT_SECRET", "shh")
    monkeypatch.setenv("MOSAERA_BASE_URL", "https://mosaera.example")


def _client(mem: _Mem) -> Any:
    c = _client_with(mem)
    c.cookies.set("mosaera_session", "cookie")
    return c


# ---- the derived name -----------------------------------------------------------------


def test_the_repo_name_is_derived_and_cannot_carry_a_path_or_owner() -> None:
    """The name never crosses the redirect — it is computed from the project. These are the
    shapes that would matter if it ever did: a slash would change the OWNER, and `..` a path."""
    assert ghr.repo_name_for("My Widget", "p1") == "My-Widget"
    assert "/" not in ghr.repo_name_for("evil/owner", "p1")
    assert ghr.repo_name_for("../../etc/passwd", "p1") == "etc-passwd"
    # A name that reduces to nothing still has to be creatable.
    assert ghr.repo_name_for("///", "p1abcdefghijkl").startswith("mosaera-")
    assert ghr.repo_name_for("...", "p1abcdefghijkl").startswith("mosaera-")


# ---- start ----------------------------------------------------------------------------


def test_start_redirects_to_github_and_mints_bound_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    mem = _Mem(_ADMIN)
    r = _client(mem).get("/api/oauth/github/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://github.com/login/oauth/authorize?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    assert q["client_id"] == ["cid"]
    # public_repo, not `repo`: this flow has no use for private access, so it does not ask.
    assert q["scope"] == ["public_repo"]
    assert q["redirect_uri"] == ["https://mosaera.example/oauth/github/callback"]
    assert "shh" not in loc, "the client secret must never ride the browser redirect"
    rec = mem.minted[0]
    assert rec["user_id"] == 7 and rec["project_id"] == "p1" and rec["provider"] == "github"
    assert rec["hash"] not in loc, "only the state's hash is stored; the plaintext is not it"


def test_start_refuses_a_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    mem = _Mem({"id": 9, "username": "member", "is_admin": False})
    r = _client(mem).get("/api/oauth/github/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 403
    assert mem.minted == [], "a refused start must not mint a state"


def test_start_without_oauth_configured_names_where_the_values_come_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("MOSAERA_GITHUB_OAUTH_CLIENT_ID", "MOSAERA_GITHUB_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MOSAERA_BASE_URL", "https://mosaera.example")
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    mem = _Mem(_ADMIN)
    r = _client(mem).get("/api/oauth/github/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 400
    assert "same GitHub App" in r.json()["detail"]


# ---- callback -------------------------------------------------------------------------


def _wire(monkeypatch: pytest.MonkeyPatch, *, created: Any = None, err: str | None = None) -> dict:
    seen: dict[str, Any] = {"exchanged": [], "created": []}

    def _exchange(web_base: str, **kw: Any) -> tuple[str | None, str | None]:
        seen["exchanged"].append(kw)
        return "ghu_USERTOKEN", None

    def _create(api_base: str, token: str, name: str, **kw: Any) -> tuple[Any, str | None]:
        seen["created"].append({"token": token, "name": name, **kw})
        return created, err

    monkeypatch.setattr(ghr.gapp, "exchange_user_code", _exchange)
    monkeypatch.setattr(ghr.gwrite, "create_public_repo", _create)
    return seen


def test_callback_creates_the_repo_and_points_the_project_at_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created={"clone_url": "https://github.com/me/My-Widget.git"})
    mem = _Mem(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/projects/p1/settings?pane=integration&repo=created"

    # The name was DERIVED from the project, not read from the request.
    assert seen["created"][0]["name"] == "My-Widget"
    assert seen["created"][0]["token"] == "ghu_USERTOKEN"
    assert mem.updates == [{"id": "p1", "source_repo": "https://github.com/me/My-Widget.git"}]
    assert any(e[1] == "project.github_repo_created" for e in mem.audits)


def test_callback_refuses_a_state_it_cannot_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    """A replay, an expired state, or a forged one finds no binding — and must die BEFORE any
    code is exchanged, so a stolen code is worth nothing on its own."""
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created={"clone_url": "x"})
    mem = _Mem(_ADMIN)
    mem.set_binding(None)

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 302 and "repo_error=" in r.headers["location"]
    assert seen["exchanged"] == [], "no code may be exchanged without a live state"
    assert mem.updates == [] and mem.audits == []


def test_callback_refuses_a_session_that_is_not_the_initiating_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state binding alone does not authorize: the live session must be the same admin."""
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created={"clone_url": "x"})
    mem = _Mem({"id": 99, "username": "other", "is_admin": True})
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    assert "session+does+not+match" in r.headers["location"].replace("%20", "+")
    assert seen["exchanged"] == [] and mem.updates == []


def test_a_creation_failure_passes_githubs_own_message_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If GitHub rejects this token TYPE, that text is the evidence that settles an open
    question (ADR-0120 §unverified). A generic 'could not create' would hide it."""
    _configure(monkeypatch)
    _wire(monkeypatch, created=None, err="403: Resource not accessible by integration")
    mem = _Mem(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    loc = urllib.parse.unquote(r.headers["location"])
    assert "Resource not accessible by integration" in loc
    assert mem.updates == [], "nothing is recorded when creation fails"


# ---- red-team round 1: the precondition is a CONTROL, not a UI preference --------------


class _MemWithSource(_Mem):
    """A project that already has a repository."""

    def project_detail(self, pid: str) -> dict[str, Any] | None:
        d = super().project_detail(pid)
        if d is not None:
            d["source_repo"] = "https://github.com/me/already-here.git"
        return d


def test_start_refuses_a_project_that_already_has_a_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI withholds the control for a project with a source. If only the UI enforced it,
    any admin — or an admin following a crafted link — could repoint a WORKING project at a new
    empty repo and clear its installation id."""
    _configure(monkeypatch)
    mem = _MemWithSource(_ADMIN)
    r = _client(mem).get("/api/oauth/github/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 400
    assert "already has a repository" in r.json()["detail"]
    assert mem.minted == [], "a refused start must not mint a state"


def test_callback_rechecks_the_precondition_it_cannot_assume_still_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A state minted while the project had no source could be spent after one was set. The
    start-time check alone leaves that window open."""
    _configure(monkeypatch)
    seen = _wire(monkeypatch, created={"clone_url": "x"})
    mem = _MemWithSource(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    assert "already+has+a+repository" in r.headers["location"].replace("%20", "+")
    assert seen["exchanged"] == [], "no code exchanged once the precondition fails"
    assert mem.updates == [], "a working project's source_repo must not be repointed"


# ---- create AND push, in that order (ADR-0120 Amendment 1) -----------------------------


def _working_repo() -> Path:
    """Put the project's working repository where the code will look for it.

    Derived from `Settings.projects_dir` rather than assembled by hand: the suite isolates
    `Settings.home` per test, so a hand-built `tmp_path/.mosaera/...` is simply a different
    directory and the push would be skipped for a reason that has nothing to do with the code.

    The push comes from the project's OWN clone, not `source_repo` — that is where the agent's
    committed work lives, and for a local-first project `source_repo` is empty.
    """
    working = Settings.from_env().projects_dir / "p1" / "repo"
    working.mkdir(parents=True, exist_ok=True)
    return working


class _MemLocal(_Mem):
    """A project whose source is a local path — code on disk, no repository. The case
    repository creation exists for, and the one the first precondition locked out."""

    def __init__(self, session: dict[str, Any] | None, path: str) -> None:
        super().__init__(session)
        self.path = path

    def project_detail(self, pid: str) -> dict[str, Any] | None:
        d = super().project_detail(pid)
        if d is not None:
            d["source_repo"] = self.path
        return d


def test_a_local_path_project_may_have_a_repository_created(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A local path is a source but not a repository. Refusing on 'has any source' locked
    creation out of every project with code on disk — exactly the ones that need it."""
    _configure(monkeypatch)
    mem = _MemLocal(_ADMIN, str(tmp_path))
    r = _client(mem).get("/api/oauth/github/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 302
    assert len(mem.minted) == 1


def test_the_push_runs_before_the_project_is_repointed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    _configure(monkeypatch)
    seen = _wire(
        monkeypatch,
        created={"clone_url": "https://github.com/me/w.git", "full_name": "me/w"},
    )
    working = _working_repo()
    order: list[str] = []

    def _push(path: Any, **kw: Any) -> tuple[str | None, str | None]:
        order.append("push")
        assert path == working, "the push must come from the project's own working repository"
        return "work", None

    monkeypatch.setattr(ghr.ghub, "push_existing_repository", _push)
    mem = _MemLocal(_ADMIN, str(tmp_path))
    original_update = mem.update_project

    def _update(pid: str, **kw: Any) -> None:
        order.append("repoint")
        original_update(pid, **kw)

    mem.update_project = _update  # type: ignore[method-assign]
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.headers["location"] == "/projects/p1/settings?pane=integration&repo=created"
    assert order == ["push", "repoint"], "an empty repo must never be pointed at first"
    assert mem.updates == [{"id": "p1", "source_repo": "https://github.com/me/w.git"}]
    assert seen["created"], "the repository is still created"


def test_a_failed_push_leaves_the_project_where_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Fails CLOSED. A project pointed at an empty repository cannot run at all — strictly
    worse than the dead end this replaced — so a push failure must not repoint anything, and
    must say the repository exists so the operator is not hunting a phantom."""
    _configure(monkeypatch)
    _wire(monkeypatch, created={"clone_url": "https://github.com/me/w.git", "full_name": "me/w"})
    _working_repo()
    monkeypatch.setattr(
        ghr.ghub,
        "push_existing_repository",
        lambda path, **kw: (None, "remote rejected"),
    )
    mem = _MemLocal(_ADMIN, str(tmp_path))
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    loc = urllib.parse.unquote(r.headers["location"])
    assert "could not push" in loc and "me/w" in loc
    assert mem.updates == [], "the project keeps its working source"


def test_a_project_already_on_gitlab_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The red-team control is unchanged by the widening: a project on a forge may not be
    repointed at a new empty repository."""
    _configure(monkeypatch)
    monkeypatch.setenv("MOSAERA_GITLAB_URL", "https://gitlab.example.com")
    mem = _MemLocal(_ADMIN, "https://gitlab.example.com/g/p.git")
    r = _client(mem).get("/api/oauth/github/start?project_id=p1", follow_redirects=False)
    assert r.status_code == 400
    assert mem.minted == []


# ---- finishing connected rather than handing back a checklist --------------------------


def test_a_successful_publish_ends_connected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """An installation covering the account already covers a repository just created inside it.
    Asking the operator to go and connect asks them to confirm something already true — and it is
    the step most likely to be skipped, leaving a project that looks published and cannot deliver.
    """
    _configure(monkeypatch)
    _wire(monkeypatch, created={"clone_url": "https://github.com/me/w.git", "full_name": "me/w"})
    _working_repo()
    monkeypatch.setattr(ghr.ghub, "push_existing_repository", lambda p, **k: ("work", None))
    asked: list[str] = []

    def _resolve(
        mem: Any, settings: Any, pid: str, owner_repo: str
    ) -> tuple[int | None, str | None]:
        asked.append(owner_repo)
        return 42, None

    monkeypatch.setattr(ghr.ghd, "resolve_installation", _resolve)
    mem = _MemLocal(_ADMIN, "")
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.headers["location"].endswith("&connected=1")
    # Asked about the project's OWN repository, exactly as the connect endpoint does (ADR-0114).
    assert asked == ["me/w"]


def test_an_unconnectable_publish_still_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The repository exists and the code is in it. If the app is not installed on that account,
    that is the next step — not a reason to report the publish as failed or to undo it."""
    _configure(monkeypatch)
    _wire(monkeypatch, created={"clone_url": "https://github.com/me/w.git", "full_name": "me/w"})
    _working_repo()
    monkeypatch.setattr(ghr.ghub, "push_existing_repository", lambda p, **k: ("work", None))
    monkeypatch.setattr(ghr.ghd, "resolve_installation", lambda *a: (None, "404: not installed"))
    mem = _MemLocal(_ADMIN, "")
    mem.set_binding({"user_id": 7, "project_id": "p1", "provider": "github"})

    r = _client(mem).get("/oauth/github/callback?code=abc&state=xyz", follow_redirects=False)
    loc = r.headers["location"]
    assert "repo=created" in loc and "connected=1" not in loc
    assert mem.updates, "the project is still pointed at its new repository"
