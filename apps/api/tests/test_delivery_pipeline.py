"""Finish-the-delivery-pipeline regressions (2026-08-18): no state without a way out.

Each test here pins a state the product could reach but not leave, or a branch a live merge
request depended on that nothing protected. They are separated from `test_delivery_posture.py`
so the god-file ratchet on that file stays honest.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from test_api import _client_with, _FakeMemoryWithDiff


def _project_mem(detail: dict[str, Any]) -> Any:
    """A GitLab-backed project memory whose `project_detail` is supplied verbatim."""

    class _Mem(_FakeMemoryWithDiff):
        def __init__(self) -> None:
            super().__init__()
            self.audits: list[tuple[str, str, str]] = []

        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "runs": [{"id": "run-1"}],
                **detail,
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
            self.audits.append((run_id, event, detail))

    return _Mem()


def test_the_project_mrs_recorded_source_is_protected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """0029: the project MR's source branch is READ, not guessed.

    Measured live on 2026-08-18 — project MR !4 sourced from `mosaera/item-102` because
    `open_project_mr` opens from whatever the shared clone is checked out on, while the guard
    protected `projects.branch` and `mosaera/combined-<id>`. Item 102's backlog row was empty,
    so the item guard did not cover it either: the branch a live MR depended on was protected
    by nothing, and this admin delete would have orphaned the merge request.
    """
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")  # asserting mechanics, so: admin
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(
        pd_mod,
        "delete_remote_branch",
        lambda *a, **k: pytest.fail("must not delete the source of a live project MR"),
    )

    mem = _project_mem(
        {
            "backlog": [],  # the item row is empty — the item guard cannot help here
            "branch": "mosaera/project-p1-149ba9",  # the intake branch: NOT the MR's source
            "mr_source": "mosaera/item-102",  # what the MR actually sources from
            "mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/4",
            "status": "in_review",
        }
    )
    r = _client_with(mem).post("/api/projects/p1/branches/mosaera/item-102/delete")
    assert r.status_code == 409


def test_a_merged_project_mr_stops_protecting_its_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The recorded source must not protect FOREVER — once the project MR is merged the branch
    is ordinary again, or recording it would simply be a new way to get stuck."""
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    deleted: list[str] = []
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(pd_mod, "delete_remote_branch", lambda r, br, **k: deleted.append(br))

    mem = _project_mem(
        {
            "backlog": [],
            "branch": "mosaera/project-p1-149ba9",
            "mr_source": "mosaera/item-102",
            "mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/4",
            "status": "merged",
        }
    )
    r = _client_with(mem).post("/api/projects/p1/branches/mosaera/item-102/delete")
    assert r.status_code == 200 and deleted == ["mosaera/item-102"]


def _mr_mem(backlog: list[dict[str, Any]], **extra: Any) -> Any:
    """A project memory with BOTH tokens — the REST lifecycle path needs the api-scoped one."""

    class _Mem(_FakeMemoryWithDiff):
        def __init__(self) -> None:
            super().__init__()
            self.audits: list[tuple[str, str, str]] = []
            self.item_writes: list[tuple[int, dict[str, Any]]] = []
            self.project_writes: list[dict[str, Any]] = []

        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": backlog,
                "runs": [{"id": "run-1"}],
                **extra,
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def get_project_api_token(self, pid: str) -> str | None:
            return "api-tok"

        def update_backlog_item(self, item_id: int, **kw: Any) -> None:
            self.item_writes.append((item_id, kw))

        def update_project(self, pid: str, **kw: Any) -> None:
            self.project_writes.append(kw)

        def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
            self.audits.append((run_id, event, detail))

    return _Mem()


def test_an_item_mr_can_be_closed_and_reopened(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lifecycle's missing half. Until now the product could only OPEN an MR, so an obsolete
    one stayed live here forever and `closed` was a state nothing could produce or clear."""
    import mosaera_api.mr_lifecycle as ml

    sent: list[dict[str, Any]] = []

    def _update(url: str, token: str, project: str, iid: int, **kw: Any) -> tuple[Any, None]:
        sent.append({"token": token, "iid": iid, **kw})
        return {"web_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/2"}, None

    monkeypatch.setattr(ml.glw, "update_merge_request", _update)
    backlog = [
        {
            "id": 1,
            "branch": "mosaera/item-1",
            "mr_state": "opened",
            "mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/2",
        }
    ]

    # The audit event name is spelled out, not derived: `f"{action}d"` yields "mr.reopend".
    # Found in live validation — an audit name is a queryable contract, so a typo is a wrong
    # record rather than a cosmetic slip.
    for action, recorded, event in (
        ("close", "closed", "mr.closed"),
        ("reopen", "opened", "mr.reopened"),
    ):
        mem = _mr_mem(backlog)
        r = _client_with(mem).post("/api/projects/p1/items/1/mr-state", json={"action": action})
        assert r.status_code == 200, r.text
        # The state is recorded from OUR action, not left for the next poll — branch protection
        # reads it, so it must not lag.
        assert mem.item_writes == [(1, {"mr_state": recorded})]
        assert mem.audits and mem.audits[0][1] == event
    # GitLab's own lifecycle verb, on the api-scoped token (a REST edit; ADR-0103 §1).
    assert [s["state_event"] for s in sent] == ["close", "reopen"]
    assert {s["token"] for s in sent} == {"api-tok"}


def test_only_close_and_reopen_reach_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """`state_event` is a GitLab verb; nothing else may be smuggled through the route."""
    import mosaera_api.mr_lifecycle as ml

    monkeypatch.setattr(
        ml.glw,
        "update_merge_request",
        lambda *a, **k: pytest.fail("no other state_event may reach the API"),
    )
    mem = _mr_mem([{"id": 1, "mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/2"}])
    c = _client_with(mem)
    for bad in ("merge", "", "CLOSE ALL", "delete"):
        assert c.post("/api/projects/p1/items/1/mr-state", json={"action": bad}).status_code == 400


def test_an_operators_chosen_target_rescues_an_empty_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_stacked_target` could pick a predecessor that already contains this item's commits —
    the diff is then empty and the opener refuses, permanently. Compose was consulted only
    AFTER that check, so picking a different target could not rescue it."""
    import mosaera_api.delivery as dmod

    seen: list[str] = []

    def _diff(workspace: Any, target: str) -> str:
        seen.append(target)
        return "" if target == "mosaera/item-9" else "diff --git a/x b/x\n"

    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w"))
    monkeypatch.setattr(dmod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(dmod, "project_item_diff", _diff)
    monkeypatch.setattr(dmod, "_stacked_target", lambda *a, **k: "mosaera/item-9")
    # The subject is the ORDER of the diff check vs the operator's target, so stub the opener.
    monkeypatch.setattr(dmod, "_open_via_rest", lambda *a, **k: dmod.MrOutcome(True, url="u"))
    mem = _mr_mem(
        [
            {
                "id": 1,
                "status": "in_review",
                "position": 2,
                "title": "t",
                "description": "d",
                "acceptance": "",
            }
        ]
    )
    from mosaera_api.schemas import MrComposeBody
    from mosaera_core.config import Settings

    # No compose → the recomputed target wins and the item can never get an MR.
    assert dmod.open_item_mr(mem, Settings.from_env(), "p1", 1).skip == "empty_diff"
    # The operator picks a target that DOES have a diff → the check honours it.
    out = dmod.open_item_mr(
        mem, Settings.from_env(), "p1", 1, compose=MrComposeBody(target_branch="main")
    )
    assert out.opened and seen == ["mosaera/item-9", "main"]


def test_a_chosen_target_is_held_to_the_retarget_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """An item MR is deliberately stacked; an arbitrary target makes it propose the whole
    history under a small-item title (red-team 2026-08-18, finding 3)."""
    import mosaera_api.delivery as dmod

    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w"))
    monkeypatch.setattr(dmod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(
        dmod, "project_item_diff", lambda *a, **k: pytest.fail("must refuse before diffing")
    )
    from mosaera_api.schemas import MrComposeBody
    from mosaera_core.config import Settings

    out = dmod.open_item_mr(
        mem := _mr_mem([{"id": 1, "position": 1}]),
        Settings.from_env(),
        "p1",
        1,
        compose=MrComposeBody(target_branch="production"),
    )
    assert mem is not None and not out.opened and "mosaera/*" in str(out.error)


def test_the_poll_recovers_an_item_stranded_without_an_mr_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An item with a branch, a state of "opened", and no MR URL was terminal: nothing polled it
    (no iid), the opener refused `already_open`, retarget had no MR to edit — and its branch
    stayed protected. It got there because the URL fallback was handed the PUSH token, so on the
    common configuration that REST read could only ever fail."""
    import mosaera_api.mr_status as ms_mod

    seen: list[tuple[str, str]] = []

    def _list_mrs(url: str, token: str, project: str, *, source_branch: str, **kw: Any) -> Any:
        seen.append((token, source_branch))
        return [{"web_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/7"}], None

    monkeypatch.setattr(ms_mod.glc, "list_merge_requests", _list_mrs)
    import mosaera_api.delivery as dmod

    monkeypatch.setattr(dmod.glc, "list_merge_requests", _list_mrs)

    mem = _mr_mem(
        [{"id": 1, "branch": "mosaera/item-1", "mr_state": "opened", "mr_url": ""}],
        mr_url="",
        status="active",
    )
    r = _client_with(mem).get("/api/projects/p1/mr-status")
    assert r.status_code == 200
    # Recovered by SOURCE BRANCH, on the api-scoped token — the read the push token cannot do.
    assert seen == [("api-tok", "mosaera/item-1")]
    assert mem.item_writes == [(1, {"mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/7"})]


def test_a_vanished_mr_is_forgotten_but_only_on_two_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merge request deleted in GitLab was permanent here: the poll errored forever, the row
    stayed "opened", its branches stayed protected, and the backlog row could not be deleted,
    split, or merged. Clearing it needs TWO facts, because GitLab answers 404 for *unauthorized*
    as well as *absent* — a bare 404 would let a token that merely lost access strip protection.
    """
    import mosaera_api.mr_status as ms_mod

    monkeypatch.setattr(ms_mod.glc, "get_merge_request", lambda *a, **k: (None, "404: Not Found"))
    row = {
        "id": 1,
        "branch": "mosaera/item-1",
        "mr_state": "opened",
        "mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/9",
    }

    # Fact 2 absent — the project is unreachable too, so the 404 proves nothing. Record stands.
    monkeypatch.setattr(ms_mod.glc, "get_project", lambda *a, **k: (None, "404: Not Found"))
    mem = _mr_mem([dict(row)], mr_url="", status="active")
    assert _client_with(mem).get("/api/projects/p1/mr-status").status_code == 200
    assert mem.item_writes == []

    # Both facts — the project answers, the MR does not. The MR is genuinely gone.
    monkeypatch.setattr(ms_mod.glc, "get_project", lambda *a, **k: ({"id": 1}, None))
    mem = _mr_mem([dict(row)], mr_url="", status="active")
    assert _client_with(mem).get("/api/projects/p1/mr-status").status_code == 200
    # `branch` is cleared too — leaving it swaps one terminal state for another, because it is
    # the opener's idempotency marker (`already_open`) and the UI hides "Open MR" while it is set.
    assert mem.item_writes == [(1, {"branch": "", "mr_url": "", "mr_state": "", "mr_target": ""})]
    # And the clearing is AUDITED against a real run id — `audit_events.run_id` is a FK to
    # `runs.id`, so a synthetic id raises and the best-effort guard hides it.
    assert [(e[0], e[1]) for e in mem.audits] == [("run-1", "mr.vanished")]


def test_a_wrongly_recorded_merged_state_can_be_re_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """`merged` is skipped to bound REST cost — but it is also the state that makes a branch
    PRUNABLE, so a wrong one was both destructive and permanently uncorrectable."""
    import mosaera_api.mr_status as ms_mod

    calls: list[int] = []

    def _get_mr(url: str, token: str, project: str, iid: int) -> Any:
        calls.append(iid)
        return {"state": "opened", "target_branch": "main", "source_branch": "mosaera/item-1"}, None

    monkeypatch.setattr(ms_mod.glc, "get_merge_request", _get_mr)
    row = {
        "id": 1,
        "branch": "mosaera/item-1",
        "mr_state": "merged",
        "mr_url": "https://gitlab.rengifo.me/g/p/-/merge_requests/9",
    }

    mem = _mr_mem([dict(row)], mr_url="", status="active")
    _client_with(mem).get("/api/projects/p1/mr-status")
    assert calls == [] and mem.item_writes == []  # terminal by default

    mem = _mr_mem([dict(row)], mr_url="", status="active")
    _client_with(mem).get("/api/projects/p1/mr-status?force=true")
    assert calls == [9]
    # The wrong state is corrected, and the 0028 target backfills in the same pass.
    assert mem.item_writes == [(1, {"mr_state": "opened", "mr_target": "main"})]
