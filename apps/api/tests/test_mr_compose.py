"""ADR-0103 Phase 2: the pre-filled editable MR compose path.

Unit-level tests on delivery.open_project_mr / open_item_mr: with an api token + operator
compose fields the FAITHFUL REST path runs (full multi-line body, push_only); without an api
token it degrades to the push-options path; with no compose the sweep behaviour is unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import mosaera_api.delivery as dmod
import pytest
from mosaera_api.schemas import MrComposeBody
from mosaera_core.config import Settings


class _Mem:
    """Minimal store for the openers — a project with one delivered item, tokens toggled."""

    def __init__(self, *, api_token: str | None) -> None:
        self._api = api_token
        self.item_updates: list[dict[str, Any]] = []
        self.project_updates: list[dict[str, Any]] = []

    def project_detail(self, pid: str) -> dict[str, Any] | None:
        return {
            "id": pid,
            "name": "Demo",
            "brief": "the brief",
            "source_repo": "https://gitlab.rengifo.me/g/p.git",
            "backlog": [
                {
                    "id": 5,
                    "title": "Item five",
                    "description": "do five",
                    "acceptance": "it fives",
                    "status": "in_review",
                    "position": 0,
                    "branch": "",
                }
            ],
        }

    def get_project_token(self, pid: str) -> str | None:
        return "push-tok"

    def get_project_api_token(self, pid: str) -> str | None:
        return self._api

    def update_project(self, pid: str, **kw: Any) -> None:
        self.project_updates.append(kw)

    def update_backlog_item(self, item_id: int, **kw: Any) -> None:
        self.item_updates.append({"id": item_id, **kw})


@pytest.fixture()
def wire(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the workspace + diff + connectors; capture what each opener actually calls."""
    seen: dict[str, Any] = {"push_only": None, "create": None, "push_options_used": False}
    ws = SimpleNamespace(root="/w/s", branch="mosaera/project-p1")  # stub root, never touched
    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a, **k: ws)
    monkeypatch.setattr(dmod, "project_diff", lambda ws, **k: ("main", "diff --git a b"))
    monkeypatch.setattr(dmod, "project_item_diff", lambda ws, target, **k: "diff --git a b")
    monkeypatch.setattr(dmod, "project_base", lambda ws: "main")

    def fake_open_mr(root: Any, plan: Any, **k: Any) -> Any:
        if k.get("push_only"):
            seen["push_only"] = {"branch": plan.branch, "base": plan.base}
            return SimpleNamespace(opened=False, pushed=True, error="")
        seen["push_options_used"] = True  # the lossy fallback path
        return SimpleNamespace(opened=True, pushed=False, url="https://gl/mr/push", error="")

    monkeypatch.setattr(dmod, "open_merge_request", fake_open_mr)
    monkeypatch.setattr(
        dmod.glc, "list_merge_requests", lambda *a, **k: ([], None)
    )  # no existing MR

    def fake_create(url: str, tok: str, proj: str, **k: Any) -> Any:
        seen["create"] = {"token": tok, **k}
        return ({"web_url": "https://gl/mr/rest", "iid": 9}, None)

    monkeypatch.setattr(dmod.glw, "create_merge_request", fake_create)
    return seen


def test_compose_with_api_token_uses_faithful_rest(wire: dict[str, Any]) -> None:
    mem = _Mem(api_token="api-tok")
    body = "para one\n\npara two\n- bullet"  # newlines the push-option path destroys
    compose = MrComposeBody(body=body, target_branch="develop", squash=True, title="Custom title")
    out = dmod.open_project_mr(mem, Settings.from_env(), "p1", compose)  # type: ignore[arg-type]
    assert out.opened and out.url == "https://gl/mr/rest"
    # The branch was pushed WITHOUT push-options; the MR was created via REST.
    assert wire["push_only"] is not None and wire["push_options_used"] is False
    c = wire["create"]
    assert c["token"] == "api-tok"  # the api token, never the push token
    assert c["description"] == body  # FULL multi-line body survives
    assert c["title"] == "Custom title" and c["target_branch"] == "develop" and c["squash"] is True


def test_compose_without_api_token_degrades_to_push_options(wire: dict[str, Any]) -> None:
    mem = _Mem(api_token=None)  # no api token → the faithful path is unavailable
    out = dmod.open_project_mr(mem, Settings.from_env(), "p1", MrComposeBody(body="x\n\ny"))  # type: ignore[arg-type]
    assert out.opened
    assert wire["push_options_used"] is True  # the lossy fallback
    assert wire["create"] is None and wire["push_only"] is None  # REST never touched


def test_no_compose_is_the_unchanged_push_options_path(wire: dict[str, Any]) -> None:
    mem = _Mem(api_token="api-tok")  # even WITH an api token, no compose ⇒ sweep path
    out = dmod.open_project_mr(mem, Settings.from_env(), "p1", None)  # type: ignore[arg-type]
    assert out.opened and wire["push_options_used"] is True and wire["create"] is None


def test_item_compose_stacks_via_rest_and_records_state(wire: dict[str, Any]) -> None:
    mem = _Mem(api_token="api-tok")
    out = dmod.open_item_mr(mem, Settings.from_env(), "p1", 5, MrComposeBody(body="hi\n\nthere"))  # type: ignore[arg-type]
    assert out.opened and out.url == "https://gl/mr/rest"
    # Stacked default: the source branch is NOT removed on merge (a later item may target it).
    assert wire["create"]["remove_source_branch"] is False
    # The TARGET the MR was actually opened against is recorded (0028) — branch protection reads
    # this, never a recomputation. Recomputing it is what deleted a live MR's target branch.
    rec = next(u for u in mem.item_updates if u.get("id") == 5)
    assert rec["branch"] == "mosaera/item-5"
    assert rec["mr_url"] == "https://gl/mr/rest"
    assert rec["mr_state"] == "opened"
    assert rec["mr_target"] == wire["create"]["target_branch"]


def test_stacked_target_skips_a_merged_predecessor() -> None:
    # ADR-0103 Phase 4: a merged predecessor's branch is gone on the remote — targeting it
    # would recreate a dead branch (the ADR-0102 red-team finding). Target base instead.
    backlog = [
        {"id": 1, "position": 0, "branch": "mosaera/item-1", "mr_state": "merged"},
        {"id": 2, "position": 1, "branch": "mosaera/item-2", "mr_state": "opened"},
        {"id": 3, "position": 2, "branch": "", "mr_state": ""},
    ]
    item3 = backlog[2]
    # #1 is merged (skipped), #2 is open → #3 targets #2's branch, not the merged #1.
    assert dmod._stacked_target(backlog, item3, "main") == "mosaera/item-2"
    # If the only predecessor is merged, fall back to the base — never the dead branch.
    assert dmod._stacked_target([backlog[0], item3], item3, "main") == "main"


def test_retarget_repoints_a_stuck_item_mr_and_records_it(
    wire: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery path. Before this, a stuck MR had NO in-product fix: the opener refuses
    `already_open` before reaching REST, there is no close/reopen, and the MR columns are not
    patchable — the only escape was GitLab's own UI."""
    updated: dict[str, Any] = {}

    def _update(url: str, tok: str, proj: str, iid: int, **kw: Any) -> tuple[Any, None]:
        updated.update({"iid": iid, **kw})
        return {"web_url": "https://gl/mr/9"}, None

    monkeypatch.setattr(dmod.glw, "update_merge_request", _update)

    class _M(_Mem):
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "brief": "",
                "name": "P",
                "backlog": [
                    {
                        "id": 100,
                        "title": "t",
                        "description": "",
                        "position": 1,
                        "branch": "mosaera/item-100",
                        "mr_url": "https://gl/x/-/merge_requests/9",
                        "mr_state": "opened",
                        "mr_target": "mosaera/item-99",
                    }
                ],
            }

    mem = _M(api_token="api-tok")
    out = dmod.retarget_item_mr(mem, Settings.from_env(), "p1", 100, "main")  # type: ignore[arg-type]
    assert out.opened
    assert updated["iid"] == 9 and updated["target_branch"] == "main"
    # The record follows the MR, so protection keeps tracking the truth.
    assert any(u.get("mr_target") == "main" for u in mem.item_updates)


def test_retarget_needs_the_api_token_and_says_so(wire: dict[str, Any]) -> None:
    # Editing an existing MR is REST-only; the push token cannot do it (ADR-0103 §1).
    class _M(_Mem):
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "brief": "",
                "name": "P",
                "backlog": [
                    {
                        "id": 100,
                        "title": "t",
                        "description": "",
                        "position": 1,
                        "branch": "mosaera/item-100",
                        "mr_url": "https://gl/x/-/merge_requests/9",
                        "mr_state": "opened",
                        "mr_target": "mosaera/item-99",
                    }
                ],
            }

    out = dmod.retarget_item_mr(_M(api_token=None), Settings.from_env(), "p1", 100, "main")  # type: ignore[arg-type]
    assert not out.opened and "api-scoped token" in (out.error or "")


def test_retarget_refuses_an_arbitrary_branch(
    wire: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red-team 2026-08-18 finding 3. An item MR is deliberately stacked so its diff is just this
    item. Repointing it at any branch would make it propose the whole stacked history under a
    small-item title, carrying any approval already on the MR."""
    monkeypatch.setattr(dmod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w"))
    called: list[str] = []

    def _upd(*a: Any, **k: Any) -> tuple[dict[str, Any], None]:
        called.append(str(k.get("target_branch")))
        return {}, None

    monkeypatch.setattr(dmod.glw, "update_merge_request", _upd)

    class _M(_Mem):
        def project_detail(self, pid: str) -> dict[str, Any]:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "brief": "",
                "name": "P",
                "backlog": [
                    {
                        "id": 100,
                        "title": "t",
                        "description": "",
                        "position": 1,
                        "branch": "mosaera/item-100",
                        "mr_url": "https://gl/x/-/merge_requests/9",
                        "mr_state": "opened",
                        "mr_target": "mosaera/item-99",
                    }
                ],
            }

    mem = _M(api_token="api-tok")
    bad = dmod.retarget_item_mr(mem, Settings.from_env(), "p1", 100, "production")  # type: ignore[arg-type]
    assert not bad.opened and "mosaera/*" in (bad.error or "")
    assert called == []  # nothing was sent to GitLab

    ok = dmod.retarget_item_mr(mem, Settings.from_env(), "p1", 100, "main")  # type: ignore[arg-type]
    assert ok.opened and called == ["main"]
