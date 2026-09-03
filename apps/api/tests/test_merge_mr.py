"""Merging from the console — the only path that changes a real repository's target branch.

Opening a merge request proposes; merging delivers, and cannot be undone from this UI. Driving
LedgerCLI to completion on 2026-08-23/24 needed nine merges and every one happened in GitLab,
because the console could open and close an MR and not merge one.

Two pins here are structural rather than behavioural, and they are the ones that make ADR-0102's
*"a human still merges"* a property instead of a word:

- **nothing in the engine imports this path** — if the graph or the sweep could call it, automation
  could merge whatever the route said;
- **an unreadable verdict is never "ready"** — the readiness read exists to answer a confirmation,
  and a failed read that reported ready would put a green button over an unchecked claim on the one
  action that cannot be taken back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_api import merge_mr
from mosaera_core.config import Settings


class _Mem:
    """The three reads the merge path makes."""

    def __init__(
        self,
        *,
        source: str = "https://gl.example.com/grp/proj.git",
        mr_url: str = "https://gl.example.com/grp/proj/-/merge_requests/7",
        api_token: str = "apitok",  # noqa: S107 — a fixture value, not a credential
        item_id: int = 5,
    ) -> None:
        self._source = source
        self._mr_url = mr_url
        self._api_token = api_token
        self._item_id = item_id

    def project_detail(self, project_id: str) -> dict[str, Any] | None:
        return {
            "id": project_id,
            "source_repo": self._source,
            "backlog": [{"id": self._item_id, "mr_url": self._mr_url}],
        }

    def get_project_api_token(self, project_id: str) -> str:
        return self._api_token


def _settings() -> Settings:
    return Settings(home=Path(".mosaera"), gitlab_url="https://gl.example.com")


def _readiness(monkeypatch: Any, mr: Any, err: str | None = None, **kw: Any) -> Any:
    monkeypatch.setattr(merge_mr, "get_merge_request", lambda *a, **k: (mr, err))
    return merge_mr.item_mr_readiness(_Mem(**kw), _settings(), "p1", 5)  # type: ignore[arg-type]


# ------------------------------------------------------------------ readiness never guesses


def test_an_open_mr_returns_gitlabs_own_token_verbatim(monkeypatch: Any) -> None:
    r = _readiness(
        monkeypatch,
        {
            "state": "opened",
            "detailed_merge_status": "ci_still_running",
            "sha": "deadbeef",
            "source_branch": "mosaera/item-5",
            "target_branch": "main",
            "web_url": "https://gl.example.com/grp/proj/-/merge_requests/7",
        },
    )
    assert r.status == "ci_still_running"
    assert r.sha == "deadbeef"
    assert (r.source_branch, r.target_branch) == ("mosaera/item-5", "main")
    assert r.skip is None and r.error is None


def test_a_failed_read_reports_an_error_and_an_EMPTY_status(monkeypatch: Any) -> None:
    """LOAD-BEARING. The SPA maps an empty status to "GitLab has not said whether this can merge"
    and offers nothing. A failed read that returned a status would be inventing a verdict on the
    one action that cannot be undone."""
    r = _readiness(monkeypatch, None, err="503: upstream down")
    assert r.status == ""
    assert r.error == "503: upstream down"


def test_a_closed_or_merged_mr_is_reported_as_not_open(monkeypatch: Any) -> None:
    r = _readiness(monkeypatch, {"state": "merged", "detailed_merge_status": "not_open"})
    assert r.skip == "not_open"


def test_no_api_token_is_named_rather_than_attempted(monkeypatch: Any) -> None:
    """ADR-0103 §1 keeps the unattended path off `api` scope on purpose; merging is a REST write.
    Saying so beats presenting a control that cannot work."""
    r = _readiness(monkeypatch, {"state": "opened"}, api_token="")
    assert r.skip == "no_api_token"


def test_an_item_with_no_mr_cannot_be_merged(monkeypatch: Any) -> None:
    assert _readiness(monkeypatch, {"state": "opened"}, mr_url="").skip == "no_mr"


# ------------------------------------------------------------------ merging


def _merge(monkeypatch: Any, data: Any, err: str | None = None, **kw: Any) -> Any:
    seen: dict[str, Any] = {}

    def fake(url: str, token: str, project: str, iid: int, **kwargs: Any) -> tuple[Any, str | None]:
        seen.update({"project": project, "iid": iid, **kwargs})
        return data, err

    monkeypatch.setattr(merge_mr, "merge_merge_request", fake)
    out = merge_mr.merge_item_mr(_Mem(), _settings(), "p1", 5, **kw)  # type: ignore[arg-type]
    return out, seen


def test_a_merged_mr_reports_merged(monkeypatch: Any) -> None:
    out, seen = _merge(monkeypatch, {"state": "merged"})
    assert out.merged is True and out.queued is False and out.error is None
    assert seen["iid"] == 7 and seen["project"] == "grp/proj"


def test_the_operators_sha_rides_the_merge(monkeypatch: Any) -> None:
    """The head shown in the confirmation. If the branch moved between the read and the click,
    GitLab refuses — so approving one diff and merging another is unreachable from here."""
    _out, seen = _merge(monkeypatch, {"state": "merged"}, sha="cafe1234")
    assert seen["sha"] == "cafe1234"


def test_auto_merge_reports_QUEUED_and_never_merged(monkeypatch: Any) -> None:
    """The operator asked whether it landed. "Accepted, will merge when CI passes" is a different
    answer from "merged", and the second would be a false claim about a real repository."""
    out, seen = _merge(monkeypatch, {"state": "opened"}, when_pipeline_succeeds=True)
    assert out.queued is True and out.merged is False
    assert seen["when_pipeline_succeeds"] is True


def test_a_refused_merge_carries_the_reason(monkeypatch: Any) -> None:
    out, _seen = _merge(monkeypatch, None, err="405: Branch cannot be merged")
    assert out.merged is False and out.queued is False
    assert out.error is not None and "405" in out.error


def test_an_accepted_but_unmerged_response_is_NOT_reported_as_merged(monkeypatch: Any) -> None:
    """A 200 whose state is not `merged`, without auto-merge asked for, is an unknown outcome.
    Reporting it as merged is the shape that puts a false success in front of the operator."""
    out, _seen = _merge(monkeypatch, {"state": "opened"})
    assert out.merged is False
    assert out.error is not None


# ------------------------------------------------------ the property, not the intention


def test_no_engine_package_can_reach_the_merge_path() -> None:
    """ADR-0102's *"a human still merges"* survives only if the engine cannot merge. An import is
    the cheapest thing to check and the first thing that would change if someone wired a sweep to
    it — which is exactly the review this test exists to force."""
    roots = [Path("packages/core"), Path("packages/agents"), Path("packages/policies")]
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "merge_mr" in text or "merge_merge_request" in text:
                offenders.append(str(path))
    assert offenders == [], f"the engine must never reach the merge path: {offenders}"
