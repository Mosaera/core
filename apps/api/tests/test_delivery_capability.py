"""Can this project finish? (#120, ADR-0112) — the honest refusal, stated up front.

The regression these pin is F64's, one level up: a GitHub-sourced project could never
open a merge request, and the only place that fact appeared was a 400 at the finish line
whose wording ("not on the configured GitLab") blamed the operator's URL.

Two properties matter here and are asserted separately:
  * the capability record says which provider and why, BEFORE anything is attempted;
  * the refusal itself is unchanged — nothing newly succeeds, and no gate moved.
"""

from __future__ import annotations

from typing import Any

import pytest
from mosaera_api.delivery import open_project_mr, unsupported_source_skip
from mosaera_api.routes._delivery_capability import delivery_capability
from test_api import _client_with, _FakeMemoryWithDiff

GITLAB = "https://gitlab.rengifo.me"


def _settings(gitlab_url: str = GITLAB, *, github_app: bool = False) -> Any:
    from mosaera_core.config import Settings

    if github_app:
        # ADR-0114: an instance WITH a GitHub App configured. The two GitHub refusals have
        # different remedies (an admin configures the instance once, vs an operator installs
        # the App on one repo), so they are distinct reasons and tested separately.
        return Settings(
            gitlab_url=gitlab_url, github_app_id="1", github_app_private_key="-----PEM-----"
        )
    return Settings(gitlab_url=gitlab_url)


def _mem(detail: dict[str, Any] | None) -> Any:
    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return detail

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok" if (detail or {}).get("has_gitlab_token") else None

    return _Mem()


def _project(source: str, **over: Any) -> dict[str, Any]:
    return {
        "id": "p1",
        "source_repo": source,
        "has_gitlab_token": True,
        "has_gitlab_api_token": False,
        "backlog": [],
        "runs": [],
        **over,
    }


# --- the pure record -------------------------------------------------------------


def test_a_github_project_with_no_app_configured_names_the_instance_gap() -> None:
    cap = delivery_capability(_project("https://github.com/owner/repo.git"), _settings())
    assert cap["provider"] == "github"
    assert cap["can_finish"] is False
    assert cap["reason"] == "github_app_unconfigured"
    assert "GitHub" in cap["detail"]


def test_a_github_project_whose_repo_lacks_the_app_names_THAT_gap_instead() -> None:
    """Two different remedies, so two different reasons — collapsing them would send an
    operator to configure an instance that is already configured."""
    cap = delivery_capability(
        _project("https://github.com/owner/repo.git"), _settings(github_app=True)
    )
    assert cap["reason"] == "github_not_connected"
    assert "not installed on this repository" in cap["detail"]


def test_a_connected_github_project_can_finish_and_reads_its_merge_state() -> None:
    cap = delivery_capability(
        _project("https://github.com/owner/repo.git", has_github_connection=True),
        _settings(github_app=True),
    )
    assert cap["can_finish"] is True and cap["reason"] is None
    # F64's bit, true for GitHub because the same installation token that pushes also polls.
    assert cap["merge_state_readable"] is True
    # ...but per-item requests remain GitLab-only, and the page must know not to offer them.
    assert cap["item_requests_supported"] is False
    # The public-repo limit holds even when fully connected, so it is stated separately.
    assert "public repositories" in cap["note"]


def test_a_gitlab_project_with_a_token_can_finish() -> None:
    cap = delivery_capability(_project(f"{GITLAB}/g/p.git"), _settings())
    assert cap["provider"] == "gitlab"
    assert cap["can_finish"] is True
    assert cap["reason"] is None


def test_a_gitlab_project_without_a_token_says_which_credential_is_missing() -> None:
    cap = delivery_capability(_project(f"{GITLAB}/g/p.git", has_gitlab_token=False), _settings())
    assert cap["provider"] == "gitlab" and cap["can_finish"] is False
    assert cap["reason"] == "no_token"


def test_the_f64_bit_is_reported_separately_from_can_finish() -> None:
    """A project can open a merge request and still never READ as delivered — the poll
    that writes `merged` needs `api` scope. Folding that into `can_finish` would hide it
    again, which is the defect F64 named."""
    cap = delivery_capability(_project(f"{GITLAB}/g/p.git"), _settings())
    assert cap["can_finish"] is True
    assert cap["merge_state_readable"] is False

    readable = delivery_capability(
        _project(f"{GITLAB}/g/p.git", has_gitlab_api_token=True), _settings()
    )
    assert readable["merge_state_readable"] is True


def test_an_unrecognized_host_stays_refused_and_does_not_claim_github() -> None:
    cap = delivery_capability(_project("https://github.com.evil.io/o/r.git"), _settings())
    assert cap["provider"] == "unknown"
    assert cap["can_finish"] is False and cap["reason"] == "not_gitlab"


def test_a_local_path_project_is_unknown_not_github() -> None:
    cap = delivery_capability(_project("/home/me/thing"), _settings())
    assert cap["provider"] == "unknown" and cap["can_finish"] is False


# --- action hint (task 4F, F8/F9/F10) ---------------------------------------------


def test_the_not_gitlab_refusal_carries_a_publish_action() -> None:
    """Before this, "delivery has nowhere to open a request" was a dead end — true, but
    naming no next step. `action` is the one thing that fixes THIS reason."""
    cap = delivery_capability(_project("/home/me/thing"), _settings())
    assert cap["reason"] == "not_gitlab"
    assert cap["action"] == {"label": "Publish this project to a remote", "pane": "integration"}


def test_a_credential_refusal_carries_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing GitLab token or an uninstalled GitHub App already have their own remedy text
    (`detail`) — `action` must not duplicate or contradict it with an unrelated 'publish'."""
    no_token = delivery_capability(
        _project(f"{GITLAB}/g/p.git", has_gitlab_token=False), _settings()
    )
    assert no_token["reason"] == "no_token" and no_token["action"] is None

    no_app = delivery_capability(_project("https://github.com/owner/repo.git"), _settings())
    assert no_app["reason"] == "github_app_unconfigured" and no_app["action"] is None


def test_a_project_that_can_finish_carries_no_action() -> None:
    cap = delivery_capability(_project(f"{GITLAB}/g/p.git"), _settings())
    assert cap["can_finish"] is True and cap["action"] is None


# --- the endpoint ----------------------------------------------------------------


def test_capability_endpoint_returns_the_record() -> None:
    c = _client_with(_mem(_project("https://github.com/owner/repo.git")))
    r = c.get("/api/projects/p1/delivery/capability")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "github" and body["can_finish"] is False


def test_capability_endpoint_404s_on_an_unknown_project() -> None:
    c = _client_with(_mem(None))
    assert c.get("/api/projects/nope/delivery/capability").status_code == 404


# --- the refusal is unchanged; only its honesty is -------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # No App configured on this instance (the default _settings) → the instance-level gap.
        ("https://github.com/owner/repo.git", "github_app_unconfigured"),
        ("git@github.com:owner/repo.git", "github_app_unconfigured"),
        ("https://github.com.evil.io/o/r.git", "not_gitlab"),
        ("https://elsewhere.example/o/r.git", "not_gitlab"),
    ],
)
def test_the_skip_names_the_provider(source: str, expected: str) -> None:
    assert unsupported_source_skip(source, _settings()) == expected


def test_a_github_project_still_cannot_open_a_merge_request() -> None:
    """The whole point is that nothing newly succeeds. If this ever opens, slice 1 has
    quietly become slice 2 without the credential work that makes it safe."""
    mem = _mem(_project("https://github.com/owner/repo.git"))
    outcome = open_project_mr(mem, _settings(), "p1")
    assert outcome.opened is False
    assert outcome.skip == "github_app_unconfigured"

    # And with the App configured but this repo not connected, it still refuses.
    unconnected = open_project_mr(mem, _settings(github_app=True), "p1")
    assert unconnected.opened is False
    assert unconnected.skip == "github_not_connected"


def test_the_github_refusal_maps_to_400_and_names_github() -> None:
    c = _client_with(_mem(_project("https://github.com/owner/repo.git")))
    r = c.post("/api/projects/p1/merge")
    assert r.status_code == 400
    assert "GitHub" in r.json()["detail"]


def test_opening_a_pr_is_still_not_a_gated_action() -> None:
    """ADR-0102 §1: `push`/`open_pr` are deliberately out of GATED_ACTIONS, and growing
    that set requires wiring the interrupt. Slice 1 must not have grown it."""
    from mosaera_policies.approval import GATED_ACTIONS

    assert "open_pr" not in GATED_ACTIONS
    assert "push" not in GATED_ACTIONS
