"""GitHub delivery end to end (#120 slice 2, ADR-0114).

The properties worth pinning are the ones that would be invisible if wrong:

* the installation is RE-RESOLVED, never taken on trust from a stored id;
* the token is minted per delivery, scoped to one repo, and is what authenticates the push
  and the PR — the App JWT never touches repository work;
* a merged PR reads as merged, despite GitHub reporting ``state: closed`` for one;
* connect is admin-gated and refuses a non-GitHub project.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mosaera_api import github_delivery as ghd
from test_api import _client_with, _FakeMemoryWithDiff

GH = "https://github.com/acme/widget.git"


def _settings(**over: Any) -> Any:
    from mosaera_core.config import Settings

    base = {
        "gitlab_url": "https://gitlab.rengifo.me",
        "github_app_id": "1",
        "github_app_private_key": "-----PEM-----",
        "github_app_slug": "mosaera",
    }
    return Settings(**{**base, **over})


def _project(**over: Any) -> dict[str, Any]:
    return {
        "id": "p1",
        "name": "Widget",
        "source_repo": GH,
        "brief": "make it good",
        "backlog": [],
        "runs": [{"id": "run-1"}],
        "has_gitlab_token": False,
        "has_gitlab_api_token": False,
        "has_github_connection": True,
        "github_installation_id": "42",
        **over,
    }


def _mem(detail: dict[str, Any] | None) -> Any:
    class _Mem(_FakeMemoryWithDiff):
        def __init__(self) -> None:
            super().__init__()
            self.updates: list[dict[str, Any]] = []
            self.audits: list[tuple[str, str, str]] = []
            self._detail = dict(detail) if detail else None

        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return self._detail

        def update_project(self, pid: str, **kw: Any) -> None:
            self.updates.append({"id": pid, **kw})
            if self._detail is not None and "github_installation_id" in kw:
                self._detail["github_installation_id"] = kw["github_installation_id"]

        def get_project_token(self, pid: str) -> str | None:
            return None

        def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
            self.audits.append((run_id, event, detail))

    return _Mem()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the GitHub surface and the workspace; record exactly what was called with what."""
    seen: dict[str, Any] = {"minted": [], "pushed": [], "created": [], "listed": [], "updated": []}

    monkeypatch.setattr(ghd.gapp, "app_jwt", lambda *a, **k: "JWT")
    monkeypatch.setattr(
        ghd.gapp, "installation_for_repo", lambda api, jwt, repo: (seen.get("resolve", 42), None)
    )

    def _mint(api: str, jwt: str, ident: int, *, repo: str) -> tuple[str | None, str | None]:
        seen["minted"].append({"jwt": jwt, "installation": ident, "repo": repo})
        return seen.get("mint_result", ("ghs_tok", None))

    monkeypatch.setattr(ghd.gapp, "mint_installation_token", _mint)

    def _push(root: Any, **kw: Any) -> Any:
        seen["pushed"].append(kw)
        return SimpleNamespace(pushed=True, error="")

    monkeypatch.setattr(ghd, "push_branch", _push)

    # NB: the first positional is the API base URL, but `create_pull_request` also takes a
    # `base=` KEYWORD (the target branch). Naming this parameter `base` collides.
    def _list(api: str, tok: str, repo: str, **kw: Any) -> tuple[Any, str | None]:
        seen["listed"].append({"token": tok, "repo": repo, **kw})
        return seen.get("existing", []), None

    def _create(api: str, tok: str, repo: str, **kw: Any) -> tuple[Any, str | None]:
        seen["created"].append({"token": tok, "repo": repo, **kw})
        return {"html_url": "https://github.com/acme/widget/pull/7", "number": 7}, None

    def _update(api: str, tok: str, repo: str, number: int, **kw: Any) -> tuple[Any, str | None]:
        seen["updated"].append({"token": tok, "repo": repo, "number": number, **kw})
        return {"number": number}, None

    monkeypatch.setattr(ghd.gwrite, "list_pull_requests", _list)
    monkeypatch.setattr(ghd.gwrite, "create_pull_request", _create)
    monkeypatch.setattr(ghd.gwrite, "update_pull_request", _update)

    monkeypatch.setattr(
        ghd,
        "open_project_workspace",
        lambda *a, **k: SimpleNamespace(root="ws-root", branch="mosaera/project-p1"),
    )
    monkeypatch.setattr(ghd, "project_diff", lambda ws: ("main", "diff --git a/x b/x\n+y\n"))
    return seen


# --- owner/repo parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://github.com/acme/widget.git", "acme/widget"),
        ("https://github.com/acme/widget", "acme/widget"),
        ("git@github.com:acme/widget.git", "acme/widget"),
        ("https://github.com/acme", None),
        ("", None),
    ],
)
def test_owner_repo_parsing(source: str, expected: str | None) -> None:
    assert ghd.owner_repo_from_source(source) == expected


# --- the credential ---------------------------------------------------------------


def test_the_minted_token_is_scoped_to_this_projects_repo(wired: dict[str, Any]) -> None:
    mem = _mem(_project())
    access, err = ghd.access_for(mem, _settings(), "p1", _project())
    assert err is None and access is not None
    assert access.owner_repo == "acme/widget" and access.token == "ghs_tok"
    assert wired["minted"] == [{"jwt": "JWT", "installation": 42, "repo": "widget"}]


def test_a_stored_id_is_never_spent__the_installation_is_re_resolved_every_time(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red-team round 1. A cached id is bound to a PROJECT, but what it must match is the
    project's CURRENT source_repo — and those diverge the moment someone edits the source.
    Trusting the cache there mints a credential for a repository nobody asked about.

    Here the stored id (999) is stale and GitHub says the real one is 42; the mint must use
    42, not 999."""
    resolved: list[str] = []

    def _resolve(api: str, jwt: str, repo: str) -> tuple[int | None, str | None]:
        resolved.append(repo)
        return 42, None

    monkeypatch.setattr(ghd.gapp, "installation_for_repo", _resolve)
    mem = _mem(_project(github_installation_id="999"))
    access, err = ghd.access_for(mem, _settings(), "p1", _project(github_installation_id="999"))
    assert err is None and access is not None
    assert resolved == ["acme/widget"], "GitHub must be asked, about the CURRENT source repo"
    assert wired["minted"][0]["installation"] == 42, "the stale 999 must never be spent"


def test_a_source_repo_change_cannot_mint_against_the_old_owners_installation(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The concrete attack the above prevents: same bare repo name, different owner."""
    seen: list[str] = []

    def _resolve(api: str, jwt: str, repo: str) -> tuple[int | None, str | None]:
        seen.append(repo)
        return 77, None

    monkeypatch.setattr(ghd.gapp, "installation_for_repo", _resolve)
    moved = _project(source_repo="https://github.com/other/widget.git", github_installation_id="42")
    access, err = ghd.access_for(_mem(moved), _settings(), "p1", moved)
    assert err is None and access is not None
    assert seen == ["other/widget"], "resolution follows the new source, not the stored id"
    assert access.installation_id == 77 and access.owner_repo == "other/widget"


def test_a_mint_failure_gives_up_rather_than_looping(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        ghd.gapp, "mint_installation_token", lambda *a, **k: (None, "401: bad credentials")
    )
    mem = _mem(_project(github_installation_id="999"))
    access, err = ghd.access_for(mem, _settings(), "p1", _project(github_installation_id="999"))
    assert access is None and err is not None and "401" in err


def test_a_broken_private_key_surfaces_as_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    def _boom(*a: Any, **k: Any) -> str:
        raise ValueError("the GitHub App private key is not a readable PEM private key")

    monkeypatch.setattr(ghd.gapp, "app_jwt", _boom)
    mem = _mem(_project(github_installation_id=""))
    access, err = ghd.access_for(mem, _settings(), "p1", _project(github_installation_id=""))
    assert access is None and err is not None and "PEM" in err


# --- opening the pull request -----------------------------------------------------


def test_the_installation_token_authenticates_push_and_pr_never_the_jwt(
    wired: dict[str, Any],
) -> None:
    mem = _mem(_project())
    opened, url, err, skip = ghd.project_pr_outcome(mem, _settings(), "p1", _project())
    assert (opened, skip, err) == (True, "", "")
    assert url == "https://github.com/acme/widget/pull/7"
    assert wired["pushed"][0]["token"] == "ghs_tok"
    assert wired["created"][0]["token"] == "ghs_tok"
    assert "JWT" not in str(wired["pushed"]) and "JWT" not in str(wired["created"])


def test_the_pr_body_is_the_shared_assembly_so_a_pr_matches_an_mr(
    wired: dict[str, Any],
) -> None:
    mem = _mem(_project())
    ghd.project_pr_outcome(mem, _settings(), "p1", _project())
    created = wired["created"][0]
    assert created["title"].startswith("mosaera: ")
    assert "make it good" in created["body"]
    assert created["head"] == "mosaera/project-p1"


def test_compose_title_and_body_reach_the_pull_request_call(wired: dict[str, Any]) -> None:
    """The S3 regression: `delivery.py`'s GitHub branch used to call `project_pr_outcome`
    without `compose` at all, so an operator's edited title/body were silently discarded and a
    default PR opened instead. `compose` must overlay the assembled defaults, same as the
    GitLab REST path's `_composed()`."""
    from mosaera_api.schemas import MrComposeBody

    mem = _mem(_project())
    compose = MrComposeBody(title="Operator's title", body="Operator's full body")
    opened, _url, _err, _skip = ghd.project_pr_outcome(
        mem, _settings(), "p1", _project(), compose=compose
    )
    assert opened is True
    created = wired["created"][0]
    assert created["title"] == "Operator's title"
    assert created["body"] == "Operator's full body"


def test_compose_target_branch_overrides_the_pr_base(wired: dict[str, Any]) -> None:
    """The target-branch picker in the compose sheet must not be decorative for GitHub — an
    operator's chosen target reaches the PR's actual base, same split the GitLab REST path
    makes between the diff's detected base and the compose-chosen target."""
    from mosaera_api.schemas import MrComposeBody

    mem = _mem(_project())
    compose = MrComposeBody(target_branch="release")
    ghd.project_pr_outcome(mem, _settings(), "p1", _project(), compose=compose)
    assert wired["created"][0]["base"] == "release"


def test_an_empty_compose_falls_back_to_the_assembled_defaults(wired: dict[str, Any]) -> None:
    from mosaera_api.schemas import MrComposeBody

    mem = _mem(_project())
    compose = MrComposeBody()  # every field unset — "open with the defaults"
    ghd.project_pr_outcome(mem, _settings(), "p1", _project(), compose=compose)
    created = wired["created"][0]
    assert created["title"].startswith("mosaera: ")
    assert created["base"] == "main"


def test_opening_twice_finds_the_existing_pr_instead_of_duplicating(
    wired: dict[str, Any],
) -> None:
    wired["existing"] = [{"html_url": "https://github.com/acme/widget/pull/3", "number": 3}]
    mem = _mem(_project())
    opened, url, _err, _skip = ghd.project_pr_outcome(mem, _settings(), "p1", _project())
    assert opened is True and url.endswith("/pull/3")
    assert wired["created"] == [], "a second open must not create a duplicate pull request"


def test_compose_reaches_an_already_open_pull_request(wired: dict[str, Any]) -> None:
    """The gap `advisor` caught: the existing-PR branch above returned before this fix without
    ever looking at `compose` — an operator who edits title/body on a readiness-stale project
    (a PR already exists, the page hasn't refreshed) got a silent no-op success. GitLab's REST
    path already patches an existing MR unconditionally (`_open_via_rest` in delivery.py); this
    pins the GitHub side doing the same via `update_pull_request`."""
    from mosaera_api.schemas import MrComposeBody

    wired["existing"] = [{"html_url": "https://github.com/acme/widget/pull/3", "number": 3}]
    mem = _mem(_project())
    compose = MrComposeBody(title="Edited after the PR already existed", body="New body")
    opened, url, _err, _skip = ghd.project_pr_outcome(
        mem, _settings(), "p1", _project(), compose=compose
    )
    assert opened is True and url.endswith("/pull/3")
    assert wired["created"] == []
    patched = wired["updated"][0]
    assert patched["number"] == 3
    assert patched["title"] == "Edited after the PR already existed"
    assert patched["body"] == "New body"


def test_a_retargeted_compose_reaches_an_already_open_pull_requests_base(
    wired: dict[str, Any],
) -> None:
    """The other half of S3 on the existing-PR branch: a compose-chosen target branch must
    reach the PR's actual base the same way title/body do, not just on first-open (already
    covered by `test_compose_target_branch_overrides_the_pr_base`)."""
    from mosaera_api.schemas import MrComposeBody

    wired["existing"] = [{"html_url": "https://github.com/acme/widget/pull/3", "number": 3}]
    mem = _mem(_project())
    compose = MrComposeBody(target_branch="release")
    ghd.project_pr_outcome(mem, _settings(), "p1", _project(), compose=compose)
    assert wired["updated"][0]["base"] == "release"


def test_a_failed_patch_on_an_existing_pr_is_not_swallowed(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`opened` stays True — the PR genuinely exists and its URL is valid — but a PATCH
    failure must still surface, or the operator's edit vanishes exactly as silently as the
    original S3 discard, one layer down."""
    from mosaera_api.schemas import MrComposeBody

    def _fail_update(api: str, tok: str, repo: str, number: int, **kw: Any) -> tuple[Any, str]:
        return None, "403 rate limited"

    monkeypatch.setattr(ghd.gwrite, "update_pull_request", _fail_update)
    wired["existing"] = [{"html_url": "https://github.com/acme/widget/pull/3", "number": 3}]
    mem = _mem(_project())
    compose = MrComposeBody(title="New title")
    opened, url, err, _skip = ghd.project_pr_outcome(
        mem, _settings(), "p1", _project(), compose=compose
    )
    assert opened is True and url.endswith("/pull/3")
    assert err == "403 rate limited"


def test_a_successful_open_records_the_url_and_source_branch(wired: dict[str, Any]) -> None:
    mem = _mem(_project())
    ghd.project_pr_outcome(mem, _settings(), "p1", _project())
    update = next(u for u in mem.updates if u.get("mr_url"))
    assert update["mr_url"] == "https://github.com/acme/widget/pull/7"
    assert update["mr_source"] == "mosaera/project-p1"
    assert update["status"] == "in_review"


def test_a_failed_push_does_not_record_a_pull_request(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ghd, "push_branch", lambda *a, **k: SimpleNamespace(pushed=False, error="rejected")
    )
    mem = _mem(_project())
    opened, url, err, _skip = ghd.project_pr_outcome(mem, _settings(), "p1", _project())
    assert opened is False and url == "" and err == "rejected"
    assert not [u for u in mem.updates if u.get("mr_url")]


def test_an_empty_diff_skips_before_spending_any_credential(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ghd, "project_diff", lambda ws: ("main", "   "))
    mem = _mem(_project())
    opened, _url, _err, skip = ghd.project_pr_outcome(mem, _settings(), "p1", _project())
    assert opened is False and skip == "empty_diff"
    assert wired["minted"] == [], "nothing should be minted for a delivery with no diff"


# --- reading it back --------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"state": "open", "merged": False}, "opened"),
        ({"state": "closed", "merged": False}, "closed"),
        ({"state": "closed", "merged": True}, "merged"),
    ],
)
def test_pr_state_round_trips_into_the_stores_vocabulary(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch, payload: dict, expected: str
) -> None:
    monkeypatch.setattr(ghd.gwrite, "get_pull_request", lambda *a, **k: (payload, None))
    mem = _mem(_project())
    state, err = ghd.read_pr_state(
        mem, _settings(), "p1", _project(), "https://github.com/acme/widget/pull/7"
    )
    assert (state, err) == (expected, None)


def test_a_url_without_a_pr_number_claims_nothing(wired: dict[str, Any]) -> None:
    state, err = ghd.read_pr_state(mem := _mem(_project()), _settings(), "p1", _project(), "")
    assert state is None and err is None
    assert mem.updates == [], "an unreadable url must not overwrite a real record"


def test_the_poll_flips_the_project_to_merged(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.mr_status import poll_mr_status

    monkeypatch.setattr(
        ghd.gwrite, "get_pull_request", lambda *a, **k: ({"state": "closed", "merged": True}, None)
    )
    detail = _project(mr_url="https://github.com/acme/widget/pull/7", status="in_review")
    mem = _mem(detail)
    out = poll_mr_status(mem, _settings(), "p1")
    assert out["state"] == "merged"
    assert {"id": "p1", "status": "merged"} in mem.updates


def test_an_unreadable_poll_degrades_and_never_overwrites(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mosaera_api.mr_status import poll_mr_status

    monkeypatch.setattr(ghd.gwrite, "get_pull_request", lambda *a, **k: (None, "503: down"))
    detail = _project(mr_url="https://github.com/acme/widget/pull/7", status="in_review")
    mem = _mem(detail)
    out = poll_mr_status(mem, _settings(), "p1")
    assert out["state"] is None
    assert not [u for u in mem.updates if u.get("status") == "merged"]


# --- connect ----------------------------------------------------------------------


def test_connect_resolves_from_the_repo_and_audits(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    mem = _mem(_project(github_installation_id=""))
    r = _client_with(mem).post("/api/projects/p1/github/connect")
    assert r.status_code == 200 and r.json()["owner_repo"] == "acme/widget"
    assert {"id": "p1", "github_installation_id": "42"} in mem.updates
    assert any(e[1] == "project.github_connected" for e in mem.audits)


def test_connect_refuses_a_non_github_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    mem = _mem(_project(source_repo="https://gitlab.rengifo.me/g/p.git"))
    r = _client_with(mem).post("/api/projects/p1/github/connect")
    assert r.status_code == 400 and "not a GitHub repository" in r.json()["detail"]


def test_connect_without_an_app_configured_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    mem = _mem(_project())
    r = _client_with(mem).post("/api/projects/p1/github/connect")
    assert r.status_code == 400 and "not configured" in r.json()["detail"]


def test_connect_on_an_uninstalled_repo_names_the_install_link(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_SLUG", "mosaera")
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setattr(ghd.gapp, "installation_for_repo", lambda *a, **k: (None, "404: Not Found"))
    mem = _mem(_project(github_installation_id=""))
    r = _client_with(mem).post("/api/projects/p1/github/connect")
    assert r.status_code == 400
    assert "github.com/apps/mosaera/installations/new" in r.json()["detail"]


# --- endpoint-only, enforced rather than documented (red-team round 3) ------------


def test_the_autonomous_sweep_cannot_open_a_github_pull_request(wired: dict[str, Any]) -> None:
    """ADR-0114 §5. `open_project_mr` has two callers: the authenticated endpoint, and the
    sweep's `_maybe_open_project_mr`. Only the endpoint passes `allow_github`.

    This was a REAL defect at first: the claim was written in the ADR while the sweep could
    still reach the path, because both callers share one function. The default is now closed,
    so a future caller that forgets the flag gets a skip rather than an unattended push."""
    from mosaera_api.delivery import open_project_mr

    mem = _mem(_project())
    swept = open_project_mr(mem, _settings(), "p1")  # the sweep's call shape
    assert swept.opened is False and swept.skip == "github_endpoint_only"
    assert wired["minted"] == [], "no credential may be minted on the unattended path"
    assert wired["pushed"] == [], "and certainly nothing pushed"


def test_the_authenticated_endpoint_may_open_one(wired: dict[str, Any]) -> None:
    from mosaera_api.delivery import open_project_mr

    mem = _mem(_project())
    out = open_project_mr(mem, _settings(), "p1", allow_github=True)
    assert out.opened is True and (out.url or "").endswith("/pull/7")


def test_the_endpoints_compose_reaches_the_pull_request_call(wired: dict[str, Any]) -> None:
    """The exact S3 site: `delivery.open_project_mr`'s GitHub branch used to call
    `ghd.project_pr_outcome` without forwarding `compose` at all, so the operator's edited
    title/body were silently thrown away and a default PR opened regardless. This pins the
    fix at the caller `delivery.py` actually uses, not just at `project_pr_outcome` directly."""
    from mosaera_api.delivery import open_project_mr
    from mosaera_api.schemas import MrComposeBody

    mem = _mem(_project())
    compose = MrComposeBody(title="From the compose sheet", body="Full edited body")
    out = open_project_mr(mem, _settings(), "p1", compose=compose, allow_github=True)
    assert out.opened is True
    created = wired["created"][0]
    assert created["title"] == "From the compose sheet"
    assert created["body"] == "Full edited body"


def test_the_sweeps_real_call_site_does_not_pass_allow_github() -> None:
    """Pins the caller, not just the parameter — the defect was in the wiring, so asserting
    the default alone would not have caught it."""
    import inspect

    from mosaera_api.app_context import _delivery

    src = inspect.getsource(_delivery.DeliveryMixin._maybe_open_project_mr)
    assert "open_project_mr(" in src
    assert "allow_github" not in src, "the unattended sweep must never opt into GitHub"


def test_connect_refuses_a_non_admin_session(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    """Connect writes a credential-bearing record, so it sits at the same tier as any project
    secret write. A logged-in NON-admin must be refused."""
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")

    class _NonAdmin(type(_mem(_project()))):  # type: ignore[misc]
        def session_user(self, token_hash: str, now: Any) -> dict[str, Any]:
            return {"id": 7, "username": "user", "is_admin": False}

    mem = _NonAdmin()
    client = _client_with(mem)
    client.cookies.set("mosaera_session", "cookie")
    r = client.post("/api/projects/p1/github/connect")
    assert r.status_code == 403
    assert mem.updates == [], "nothing may be recorded on a refused connect"


def test_installations_listing_refuses_a_non_admin_session(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    """It names the accounts the App can reach — organisation information, not a capability
    bit — so it sits at the admin tier alongside connect, unlike `/github/status`."""
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")

    class _NonAdmin(type(_mem(_project()))):  # type: ignore[misc]
        def session_user(self, token_hash: str, now: Any) -> dict[str, Any]:
            return {"id": 7, "username": "user", "is_admin": False}

    client = _client_with(_NonAdmin())
    client.cookies.set("mosaera_session", "cookie")
    assert client.get("/api/github/installations").status_code == 403


def test_installations_listing_is_empty_and_unconfigured_without_an_app(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    """No App registered is not an error — the panel renders it as the step to take."""
    monkeypatch.delenv("MOSAERA_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")

    client = _client_with(_mem(_project()))
    r = client.get("/api/github/installations")
    assert r.status_code == 200
    assert r.json() == {
        "configured": False,
        "installations": [],
        "install_url": "",
        "error": None,
    }


def test_installations_listing_never_resolves_an_installation_for_delivery(
    monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    """ADR-0114's core property, pinned against this new surface: listing is a *display*
    question. It must not touch `installation_for_repo`, and nothing it returns may be minted
    against — delivery still asks about the project's own `source_repo`."""
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")

    def _boom(*a: Any, **k: Any) -> Any:  # pragma: no cover - must never run
        raise AssertionError("the listing must not resolve a per-repo installation")

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setattr(ghd.gapp, "installation_for_repo", _boom)
    monkeypatch.setattr(
        ghd.gapp,
        "list_installations",
        lambda api, jwt: ([{"id": 9, "account": "acme"}], None),
    )

    client = _client_with(_mem(_project()))
    r = client.get("/api/github/installations")
    assert r.status_code == 200
    assert r.json()["installations"] == [{"id": 9, "account": "acme"}]
    assert wired["minted"] == [], "a listing must never mint a token"


# --- status liveness probe (task 4B-i, F1/F2) --------------------------------------------


def _configure_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", "-----PEM-----")
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")


def _clear_verify_cache() -> None:
    from mosaera_api.routes import github_connect as gc

    gc._verify_cache.clear()


def test_status_is_unverified_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent credentials never probe — there is nothing to verify, and configured stays a
    pure presence bit for an unconfigured instance."""
    monkeypatch.delenv("MOSAERA_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", raising=False)
    _clear_verify_cache()
    r = _client_with(_mem(_project())).get("/api/github/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["verified"] is None
    assert body["verify_error"] is None


def test_status_reports_a_verified_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_app(monkeypatch)
    _clear_verify_cache()
    from mosaera_api.routes import github_connect as gc

    monkeypatch.setattr(gc.gapp, "verify_app_credentials", lambda *a, **k: (True, None))
    r = _client_with(_mem(_project())).get("/api/github/status")
    body = r.json()
    assert body["configured"] is True
    assert body["verified"] is True
    assert body["verify_error"] is None


def test_status_reports_a_rejected_credential_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The F1/F2 fix, pinned end to end: `configured` used to be the only bit, and it lied for
    a bad key exactly as readily as for a good one."""
    _configure_app(monkeypatch)
    _clear_verify_cache()
    from mosaera_api.routes import github_connect as gc

    monkeypatch.setattr(
        gc.gapp, "verify_app_credentials", lambda *a, **k: (False, "401: Bad credentials")
    )
    r = _client_with(_mem(_project())).get("/api/github/status")
    body = r.json()
    assert body["configured"] is True
    assert body["verified"] is False
    assert body["verify_error"] == "401: Bad credentials"


def test_status_verify_result_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """~60s in-process cache — a status card polled repeatedly must not mint a fresh JWT and
    hit GitHub on every request."""
    _configure_app(monkeypatch)
    _clear_verify_cache()
    from mosaera_api.routes import github_connect as gc

    calls: list[int] = []

    def _verify(*a: Any, **k: Any) -> tuple[bool, str | None]:
        calls.append(1)
        return True, None

    monkeypatch.setattr(gc.gapp, "verify_app_credentials", _verify)
    client = _client_with(_mem(_project()))
    client.get("/api/github/status")
    client.get("/api/github/status")
    client.get("/api/github/status")
    assert len(calls) == 1, "repeated polling within the TTL must not re-verify"


# --- disconnect (task 4B-ii, F3) -----------------------------------------------------------


def test_project_disconnect_clears_the_installation_id_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_app(monkeypatch)
    mem = _mem(_project(github_installation_id="42"))
    r = _client_with(mem).post("/api/projects/p1/github/disconnect")
    assert r.status_code == 200
    assert r.json() == {"disconnected": True}
    assert {"id": "p1", "github_installation_id": ""} in mem.updates
    assert any(e == "project.github_connected" for _run, e, _d in mem.audits)


def test_project_disconnect_refuses_a_non_admin_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_app(monkeypatch)

    class _NonAdmin(type(_mem(_project()))):  # type: ignore[misc]
        def session_user(self, token_hash: str, now: Any) -> dict[str, Any]:
            return {"id": 7, "username": "user", "is_admin": False}

    client = _client_with(_NonAdmin())
    client.cookies.set("mosaera_session", "cookie")
    r = client.post("/api/projects/p1/github/disconnect")
    assert r.status_code == 403


def test_project_disconnect_refuses_an_unknown_project(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_app(monkeypatch)
    r = _client_with(_mem(None)).post("/api/projects/p1/github/disconnect")
    assert r.status_code == 404


def test_app_disconnect_clears_stored_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from mosaera_core.settings_store import read_settings, write_settings

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    write_settings(
        tmp_path,
        {"github_app_id": "1", "github_app_private_key": "pem", "github_app_slug": "mosaera"},
    )
    assert read_settings(tmp_path).get("github_app_id") == "1"
    r = _client_with(_mem(_project())).post("/api/github/app/disconnect")
    assert r.status_code == 200 and r.json() == {"ok": True}
    stored = read_settings(tmp_path)
    assert "github_app_id" not in stored
    assert "github_app_private_key" not in stored
    assert "github_app_slug" not in stored


def test_app_disconnect_refuses_a_non_admin_session(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NonAdmin(type(_mem(_project()))):  # type: ignore[misc]
        def session_user(self, token_hash: str, now: Any) -> dict[str, Any]:
            return {"id": 7, "username": "user", "is_admin": False}

    client = _client_with(_NonAdmin())
    client.cookies.set("mosaera_session", "cookie")
    r = client.post("/api/github/app/disconnect")
    assert r.status_code == 403


# --- installation repositories listing (task 4C) --------------------------------------------


def test_installation_repositories_lists_the_bounded_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_app(monkeypatch)
    monkeypatch.setattr(ghd.gapp, "app_jwt", lambda *a, **k: "APP_JWT")
    minted: list[dict[str, Any]] = []

    def _mint_call(
        method: str, api: str, jwt: str, path: str, payload: Any = None, **k: Any
    ) -> Any:
        if path.endswith("/access_tokens"):
            minted.append({"jwt": jwt, "path": path})
            return {"token": "ghs_scoped"}, None
        assert path == "installation/repositories?per_page=100"
        assert jwt == "ghs_scoped"
        return {
            "repositories": [
                {
                    "full_name": "acme/widget",
                    "html_url": "https://github.com/acme/widget",
                    "private": False,
                },
                {
                    "full_name": "acme/secret",
                    "html_url": "https://github.com/acme/secret",
                    "private": True,
                },
            ]
        }, None

    monkeypatch.setattr(ghd.gapp, "_api", _mint_call)
    r = _client_with(_mem(_project())).get("/api/github/installations/42/repositories")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["error"] is None
    assert body["repositories"] == [
        {
            "full_name": "acme/widget",
            "html_url": "https://github.com/acme/widget",
            "private": False,
        },
        {"full_name": "acme/secret", "html_url": "https://github.com/acme/secret", "private": True},
    ]
    assert minted, "must mint an installation token rather than list with the App JWT"


def test_installation_repositories_refuses_a_non_admin_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_app(monkeypatch)

    class _NonAdmin(type(_mem(_project()))):  # type: ignore[misc]
        def session_user(self, token_hash: str, now: Any) -> dict[str, Any]:
            return {"id": 7, "username": "user", "is_admin": False}

    client = _client_with(_NonAdmin())
    client.cookies.set("mosaera_session", "cookie")
    r = client.get("/api/github/installations/42/repositories")
    assert r.status_code == 403


def test_installation_repositories_unconfigured_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MOSAERA_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    r = _client_with(_mem(_project())).get("/api/github/installations/42/repositories")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "repositories": [], "error": None}
