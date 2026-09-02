"""ADR-0102 slice T: MR-opening token posture + the death of the fabricated approval.

`POST /runs/{id}/open-mr` used the GLOBAL GitLab token for project runs and wrote a
retroactive `open_pr` approval row nobody had granted. These tests pin the fixed
contract: project runs use the project-scoped token and fail closed without one, and
the only record of an MR open is the audit event — never an approval row.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from test_api import _client_with, _FakeMemoryWithDiff


class _FakeMemoryProjectRun(_FakeMemoryWithDiff):
    """A run that belongs to a project — the token-posture cases (ADR-0102)."""

    def __init__(self, token: str | None) -> None:
        super().__init__()
        self._token = token
        self.approvals: list[Any] = []
        self.audits: list[Any] = []

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        d = super().run_detail(run_id)
        if d is not None:
            d["project_id"] = "p1"
        return d

    def get_project_token(self, project_id: str) -> str | None:
        assert project_id == "p1"
        return self._token

    def add_approval(self, *a: Any, **k: Any) -> None:
        self.approvals.append(a)

    def add_audit_event(self, *a: Any, **k: Any) -> None:
        self.audits.append(a)


def test_diverged_base_fails_the_launch_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0102 slice D: a diverged base refuses the launch BEFORE any branch cut;
    # unreachable/fast-forwarded proceed (here: on to the workspace-open, which
    # honestly fails on the missing clone — proving the check didn't block).
    import mosaera_api.factory as factory_mod
    from mosaera_api.factory import default_graph_factory
    from mosaera_api.schemas import RunSubmit
    from mosaera_core.tools.repo import DriftStatus

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    req = RunSubmit(repo="unused", task="t", project_id="p1", item_id=7)

    monkeypatch.setattr(
        factory_mod, "check_base_drift", lambda *a, **k: DriftStatus("diverged", "split history")
    )
    with pytest.raises(RuntimeError, match="base drift: split history"):
        default_graph_factory(req, "r-drift")

    monkeypatch.setattr(
        factory_mod, "check_base_drift", lambda *a, **k: DriftStatus("fast_forwarded", "a → b")
    )
    with pytest.raises(FileNotFoundError):  # proceeded past the drift check
        default_graph_factory(req, "r-drift")


def test_item_open_mr_endpoint_maps_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR-0102 slice O: the manual per-item opener — before it, with the default
    # mr_granularity="item" and auto_open_mr off, no human could open an item MR.
    import mosaera_api.routes.project_delivery as pd_mod
    from mosaera_api.delivery import MrOutcome

    mem = _FakeMemoryProjectRun("tok")
    for skip, code in (("no_item", 404), ("already_open", 409), ("no_token", 400)):
        monkeypatch.setattr(
            pd_mod, "open_item_mr", lambda *a, _s=skip, **k: MrOutcome(False, skip=_s)
        )
        r = _client_with(mem).post("/api/projects/p1/items/3/open-mr")
        assert r.status_code == code, skip
    monkeypatch.setattr(
        pd_mod, "open_item_mr", lambda *a, **k: MrOutcome(True, url="https://gl/mr/9")
    )
    r = _client_with(mem).post("/api/projects/p1/items/3/open-mr")
    assert r.status_code == 200 and r.json() == {"opened": True, "url": "https://gl/mr/9"}


def test_manual_item_open_is_audited_with_an_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR-0102 red-team fix: "the authenticated call IS the approval" must be RECORDED,
    # or no reader of the trail can back the claim. A manual open writes an mr.opened
    # audit event carrying who did it.
    import mosaera_api.routes.project_delivery as pd_mod
    from mosaera_api.delivery import MrOutcome

    monkeypatch.setattr(
        pd_mod, "open_item_mr", lambda *a, **k: MrOutcome(True, url="https://gl/mr/9")
    )

    class _Mem(_FakeMemoryProjectRun):
        def __init__(self) -> None:
            super().__init__("tok")
            self.audits: list[tuple[str, str, str]] = []

        def project_detail(self, project_id: str) -> dict[str, Any] | None:
            return {"id": "p1", "runs": [{"id": "run-9"}]}

        def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
            self.audits.append((run_id, event, detail))

    mem = _Mem()
    r = _client_with(mem).post("/api/projects/p1/items/3/open-mr")
    assert r.status_code == 200
    assert len(mem.audits) == 1
    run_id, event, detail = mem.audits[0]
    assert run_id == "run-9" and event == "mr.opened"
    assert "item 3 MR" in detail and "actor=" in detail  # the actor is on the record


def test_prune_deletes_only_merged_item_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Branch destruction is admin-only by default (ADR-0004 amendment); this test asserts
    # MECHANICS, so it runs with admin authority. Authorization has its own tests.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    # ADR-0103 Phase 4: prune deletes MERGED item branches (write_repository) and NEVER a branch
    # still targeted by an open item MR (a stacked chain must not be orphaned).
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    deleted: list[str] = []
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w/s")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")

    def _del(root: Any, br: str, **k: Any) -> None:
        deleted.append(br)  # success = None, like the real connector

    monkeypatch.setattr(pd_mod, "delete_remote_branch", _del)

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": [
                    {"id": 1, "branch": "mosaera/item-1", "mr_state": "merged"},
                    {
                        "id": 2,
                        "branch": "mosaera/item-2",
                        "mr_state": "opened",
                    },  # still open → keep
                    {"id": 3, "branch": "", "mr_state": ""},  # no branch → nothing to prune
                ],
                "runs": [{"id": "run-1"}],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, *a: Any, **k: Any) -> None: ...

    r = _client_with(_Mem()).post("/api/projects/p1/branches/prune")
    assert r.status_code == 200
    assert r.json() == {"pruned": ["mosaera/item-1"]}  # ONLY the merged one
    assert deleted == ["mosaera/item-1"]


def test_prune_never_deletes_a_RECORDED_open_MR_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The 2026-08-18 regression, exactly.

    item-99 is MERGED and item-100's MR is still OPEN against `mosaera/item-99`.
    `_stacked_target` skips merged predecessors, so the RECOMPUTED target for item-100 is `main`
    — and on the old code that dropped `mosaera/item-99` out of the protected set, letting prune
    delete the branch a live MR pointed at ("The target branch mosaera/item-99 does not exist").
    Protection must read the RECORDED `mr_target` instead.
    """
    # Branch destruction is admin-only by default (ADR-0004 amendment); this test asserts
    # MECHANICS, so it runs with admin authority. Authorization has its own tests.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    deleted: list[str] = []
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w/s")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(pd_mod, "delete_remote_branch", lambda root, br, **k: deleted.append(br))

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": [
                    {"id": 99, "branch": "mosaera/item-99", "mr_state": "merged", "mr_target": ""},
                    {
                        "id": 100,
                        "branch": "mosaera/item-100",
                        "mr_state": "opened",
                        "mr_target": "mosaera/item-99",  # what the MR ACTUALLY points at
                    },
                ],
                "runs": [{"id": "run-1"}],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, *a: Any, **k: Any) -> None: ...

    r = _client_with(_Mem()).post("/api/projects/p1/branches/prune")
    assert r.status_code == 200
    assert r.json() == {"pruned": []}
    assert deleted == []  # the live MR's target survives

    # ...and the single-branch delete refuses it too.
    d = _client_with(_Mem()).post("/api/projects/p1/branches/mosaera%2Fitem-99/delete")
    assert d.status_code == 409


def test_branch_delete_rule_is_enforced_by_the_SERVER(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Branch destruction is admin-only by default (ADR-0004 amendment); this test asserts
    # MECHANICS, so it runs with admin authority. Authorization has its own tests.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    # The mosaera/* restriction and "never the base" lived only in the web client, so the API was
    # a way around the product's own safety rule.
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w/s")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(pd_mod, "delete_remote_branch", lambda *a, **k: None)

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": [],
                "runs": [],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, *a: Any, **k: Any) -> None: ...

    c = _client_with(_Mem())
    assert c.post("/api/projects/p1/branches/feature%2Fsomeones-work/delete").status_code == 400
    assert c.post("/api/projects/p1/branches/main/delete").status_code == 400  # not mosaera/*


def test_branches_list_reads_local_clone_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A1: the target-branch picker reads the LOCAL clone — no api token gate. Empty only when
    # there is no clone; populated straight from local_branches otherwise.
    import mosaera_api.routes.project_delivery as pd_mod

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {"id": "p1", "source_repo": "https://gitlab.rengifo.me/g/p.git", "backlog": []}

    # No clone → honest empty, still a 200 (never a 500 from the picker).
    assert _client_with(_Mem()).get("/api/projects/p1/branches").json() == {
        "source": "clone",
        "branches": [],
    }

    branches = [{"name": "main", "merged": False, "protected": True}]
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w")
    )
    monkeypatch.setattr(pd_mod, "local_branches", lambda *a, **k: branches)
    # With a clone present the branches populate WITHOUT any api token being set on the memory —
    # but the response SAYS it is the degraded source, so the UI cannot present a partial list as
    # authoritative (the clone never holds this project's mosaera/* branches at all).
    assert _client_with(_Mem()).get("/api/projects/p1/branches").json() == {
        "source": "clone",
        "branches": branches,
    }


def test_branches_list_prefers_gitlab_when_an_api_token_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0103 §4: branch READ rides the api token.

    The local-clone enumeration could never serve the delete/prune surface — item branches are cut
    in per-run workspaces and pushed by URL, so the project clone holds neither the heads nor the
    origin refs, and local_branches excludes mosaera/* and hardcodes merged=False. REST is the only
    source with real names AND real merge state.
    """
    import mosaera_api.routes._branch_guards as bg_mod

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {"id": "p1", "source_repo": "https://gitlab.rengifo.me/g/p.git", "backlog": []}

        def get_project_api_token(self, pid: str) -> str | None:
            return "api-tok"

    monkeypatch.setattr(
        bg_mod.glw,
        "list_branches",
        lambda url, token, project, **kw: (
            [
                {"name": "main", "merged": False, "protected": True},
                {"name": "mosaera/item-9", "merged": True, "protected": False},
            ],
            None,
        ),
    )
    body = _client_with(_Mem()).get("/api/projects/p1/branches").json()
    assert body["source"] == "gitlab"
    # The mosaera/* branch is present at all — impossible from the clone — and carries a TRUE
    # merged flag, the dead constant this replaces.
    assert {"name": "mosaera/item-9", "merged": True, "protected": False} in body["branches"]


def test_branches_list_falls_back_to_the_clone_when_gitlab_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mosaera_api.routes._branch_guards as bg_mod
    import mosaera_api.routes.project_delivery as pd_mod

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {"id": "p1", "source_repo": "https://gitlab.rengifo.me/g/p.git", "backlog": []}

        def get_project_api_token(self, pid: str) -> str | None:
            return "api-tok"

    monkeypatch.setattr(bg_mod.glw, "list_branches", lambda *a, **k: (None, "401 unauthorized"))
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w")
    )
    monkeypatch.setattr(
        pd_mod,
        "local_branches",
        lambda *a, **k: [{"name": "main", "merged": False, "protected": True}],
    )
    # Degraded, not broken — and honest about which it is.
    assert _client_with(_Mem()).get("/api/projects/p1/branches").json()["source"] == "clone"


def _delete_mem(backlog: list[dict[str, Any]]) -> Any:
    """A project memory for the A3 single-branch delete cases — GitLab source + a push token."""

    class _Mem(_FakeMemoryWithDiff):
        def __init__(self) -> None:
            super().__init__()
            self.audits: list[tuple[str, str, str]] = []

        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": backlog,
                "runs": [{"id": "run-1"}],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
            self.audits.append((run_id, event, detail))

    return _Mem()


def test_single_branch_delete_removes_and_audits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Branch destruction is admin-only by default (ADR-0004 amendment); this test asserts
    # MECHANICS, so it runs with admin authority. Authorization has its own tests.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    # A3: delete ONE remote branch — rides write_repository, records a branch.deleted audit
    # with the actor.
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    deleted: list[str] = []
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")

    def _del(root: Any, br: str, **k: Any) -> None:
        deleted.append(br)  # success = None, like the real connector

    monkeypatch.setattr(pd_mod, "delete_remote_branch", _del)

    mem = _delete_mem([{"id": 1, "branch": "mosaera/item-1", "mr_state": "merged"}])
    r = _client_with(mem).post("/api/projects/p1/branches/mosaera/item-1/delete")
    assert r.status_code == 200 and r.json() == {"deleted": "mosaera/item-1"}
    assert deleted == ["mosaera/item-1"]
    assert mem.audits and mem.audits[0][1] == "branch.deleted"
    assert "actor=" in mem.audits[0][2] and "mosaera/item-1" in mem.audits[0][2]


def test_single_branch_delete_refuses_an_open_mr_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Branch destruction is admin-only by default (ADR-0004 amendment); this test asserts
    # MECHANICS, so it runs with admin authority. Authorization has its own tests.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    # A3 guard: refuse to delete the SOURCE or the stacked TARGET of an open item MR — either
    # would orphan a live MR (the open-MR-target case the last live validation surfaced).
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(
        pd_mod,
        "delete_remote_branch",
        lambda *a, **k: pytest.fail("must not delete a protected branch"),
    )
    # Two open items, item-2 STACKED on item-1 → item-1 is both an open source AND item-2's
    # target; item-2 is an open source. Deleting either orphans a live MR.
    backlog = [
        {"id": 1, "branch": "mosaera/item-1", "mr_state": "opened", "position": 1},
        {"id": 2, "branch": "mosaera/item-2", "mr_state": "opened", "position": 2},
    ]
    for branch in ("mosaera/item-1", "mosaera/item-2"):
        r = _client_with(_delete_mem(backlog)).post(f"/api/projects/p1/branches/{branch}/delete")
        assert r.status_code == 409, branch


def test_resolve_mr_url_falls_back_via_read_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_api.delivery as dmod
    from mosaera_core.config import Settings

    monkeypatch.setattr(
        dmod.glc,
        "list_merge_requests",
        lambda *a, **k: ([{"web_url": "https://gl/x/-/merge_requests/4"}], None),
    )
    assert (
        dmod.resolve_mr_url(Settings.from_env(), "tok", "g/p", "mosaera/item-4")
        == "https://gl/x/-/merge_requests/4"
    )
    monkeypatch.setattr(dmod.glc, "list_merge_requests", lambda *a, **k: (None, "boom"))
    assert dmod.resolve_mr_url(Settings.from_env(), "tok", "g/p", "b") == ""


class _FakeMemoryItemMr(_FakeMemoryWithDiff):
    """A project with one backlog item whose MR is open — the mr-status poll cases."""

    def __init__(self) -> None:
        super().__init__()
        self.item_updates: list[dict[str, Any]] = []

    def project_detail(self, project_id: str) -> dict[str, Any] | None:
        if project_id != "p1":
            return None
        return {
            "id": "p1",
            "status": "in_review",
            "source_repo": "https://gitlab.rengifo.me/mosaera/demo.git",
            "mr_url": "",
            "backlog": [
                {
                    "id": 7,
                    "status": "in_review",
                    "mr_url": "https://gitlab.rengifo.me/m/d/-/merge_requests/12",
                    "mr_state": "opened",
                }
            ],
        }

    def get_project_token(self, project_id: str) -> str | None:
        return "tok"

    def update_backlog_item(self, item_id: int, **kwargs: Any) -> None:
        self.item_updates.append({"id": item_id, **kwargs})


def test_mr_status_polls_item_mrs_and_persists_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR-0102 slice O: item mr_urls were stored and never polled — a merged item MR
    # stayed "in review" forever. The poll now covers items and persists what it saw.
    import mosaera_api.mr_status as ms_mod

    monkeypatch.setattr(
        ms_mod.glc, "get_merge_request", lambda *a, **k: ({"state": "merged"}, None)
    )
    mem = _FakeMemoryItemMr()
    r = _client_with(mem).get("/api/projects/p1/mr-status")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [
        {"id": 7, "state": "merged", "url": "https://gitlab.rengifo.me/m/d/-/merge_requests/12"}
    ]
    assert {"id": 7, "mr_state": "merged"} in mem.item_updates
    # A second poll with the state already persisted must NOT re-hit GitLab.
    monkeypatch.setattr(
        ms_mod.glc,
        "get_merge_request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("polled a terminal item MR")),
    )
    mem2 = _FakeMemoryItemMr()

    def detail_merged(project_id: str) -> dict[str, Any] | None:
        d = _FakeMemoryItemMr.project_detail(mem2, project_id)
        if d is not None:
            d["backlog"][0]["mr_state"] = "merged"
        return d

    mem2.project_detail = detail_merged  # type: ignore[method-assign]
    r2 = _client_with(mem2).get("/api/projects/p1/mr-status")
    assert r2.json()["items"][0]["state"] == "merged"
    assert mem2.item_updates == []


def test_open_mr_project_run_never_falls_back_to_global_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-0102: a project run with no project token is refused — the global token
    # must never quietly serve a project push.
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "global-tok")
    r = _client_with(_FakeMemoryProjectRun(None)).post("/api/runs/r1/open-mr")
    assert r.status_code == 400 and "project has no GitLab token" in r.json()["detail"]


def test_open_mr_uses_scoped_token_and_writes_no_approval_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import mosaera_api.routes.runs as runs_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "global-tok")
    (tmp_path / "workspaces" / "r1" / ".git").mkdir(parents=True)
    seen: dict[str, str] = {}

    def fake_open(_root: Any, _plan: Any, **kwargs: Any) -> Any:
        seen["token"] = kwargs["token"]
        return SimpleNamespace(opened=True, url="https://gl/mr/1", error="")

    monkeypatch.setattr(runs_mod, "open_merge_request", fake_open)
    mem = _FakeMemoryProjectRun("proj-tok")
    r = _client_with(mem).post("/api/runs/r1/open-mr")
    assert r.status_code == 200 and r.json()["url"] == "https://gl/mr/1"
    assert seen["token"] == "proj-tok"  # the project-scoped token, not the global one
    # The pre-ADR-0102 endpoint fabricated an open_pr approval row here. Never again:
    # the authenticated call is the approval; only the audit event records the act.
    assert mem.approvals == []
    assert any("mr.opened" in a for a in mem.audits)


def test_a_closed_item_mr_still_protects_its_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Red-team 2026-08-18 finding 4. `closed` was treated as terminal, so closing an MR dropped
    protection on BOTH its source and its target. GitLab reopens merge requests — and the poll
    itself only treats `merged` as final — so the reopen would land on deleted branches."""
    # Branch destruction is admin-only by default (ADR-0004 amendment); this test asserts
    # MECHANICS, so it runs with admin authority. Authorization has its own tests.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    deleted: list[str] = []
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w/s")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(pd_mod, "delete_remote_branch", lambda root, br, **k: deleted.append(br))

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": [
                    {"id": 99, "branch": "mosaera/item-99", "mr_state": "merged", "mr_target": ""},
                    {
                        "id": 100,
                        "branch": "mosaera/item-100",
                        "mr_state": "closed",
                        "mr_target": "mosaera/item-99",
                    },
                ],
                "runs": [{"id": "run-1"}],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, *a: Any, **k: Any) -> None: ...

    assert _client_with(_Mem()).post("/api/projects/p1/branches/prune").json() == {"pruned": []}
    assert deleted == []
    d = _client_with(_Mem()).post("/api/projects/p1/branches/mosaera%2Fitem-100/delete")
    assert d.status_code == 409


def _branch_mem(merged: bool = True) -> Any:
    """A GitLab project whose api token can report branch merge state."""

    class _Mem(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": [],
                "runs": [{"id": "run-1"}],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def get_project_api_token(self, pid: str) -> str | None:
            return "api-tok"

        def add_audit_event(self, *a: Any, **k: Any) -> None: ...

    _Mem._merged = merged  # type: ignore[attr-defined]
    return _Mem()


def _wire_branch_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, merged: bool) -> list[str]:
    import mosaera_api.routes._branch_guards as bg_mod
    import mosaera_api.routes.project_delivery as pd_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    deleted: list[str] = []
    monkeypatch.setattr(
        pd_mod, "open_project_workspace", lambda *a, **k: SimpleNamespace(root="/w/s")
    )
    monkeypatch.setattr(pd_mod, "project_base", lambda *a, **k: "main")
    monkeypatch.setattr(pd_mod, "delete_remote_branch", lambda root, br, **k: deleted.append(br))
    monkeypatch.setattr(
        bg_mod.glw,
        "list_branches",
        lambda *a, **k: ([{"name": "mosaera/item-1", "merged": merged, "protected": False}], None),
    )
    return deleted


def test_branch_destruction_is_admin_only_until_an_admin_opts_members_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """ADR-0004 amendment / red-team 2026-08-18 finding 6.

    Installing the project token is admin-gated; spending it irreversibly on the real repository is
    the same class of authority. Default OFF. The knob must be a REAL control — the removed
    `reviewer_advisory` knob is the recorded precedent for a toggle that gated nothing.
    """
    deleted = _wire_branch_delete(monkeypatch, tmp_path, merged=True)
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)  # not admin
    c = _client_with(_branch_mem())

    r = c.post("/api/projects/p1/branches/mosaera%2Fitem-1/delete")
    assert r.status_code == 403
    assert "admin" in r.json()["detail"] and "setting" in r.json()["detail"]  # names the remedy
    assert c.post("/api/projects/p1/branches/prune").status_code == 403
    assert deleted == []

    # An admin turns it on → the same member call now works.
    monkeypatch.setenv("MOSAERA_MEMBER_BRANCH_DELETE", "1")
    assert (
        _client_with(_branch_mem())
        .post("/api/projects/p1/branches/mosaera%2Fitem-1/delete")
        .status_code
        == 200
    )
    assert deleted == ["mosaera/item-1"]


def test_a_member_may_not_delete_a_branch_carrying_unmerged_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Blast radius: the other guards stop the wrong KIND of branch; none stopped destroying
    # unmerged work. An ADMIN may still do it deliberately.
    deleted = _wire_branch_delete(monkeypatch, tmp_path, merged=False)
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)
    monkeypatch.setenv("MOSAERA_MEMBER_BRANCH_DELETE", "1")

    r = _client_with(_branch_mem()).post("/api/projects/p1/branches/mosaera%2Fitem-1/delete")
    assert r.status_code == 409 and "unmerged" in r.json()["detail"]
    assert deleted == []

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")  # admin
    assert (
        _client_with(_branch_mem())
        .post("/api/projects/p1/branches/mosaera%2Fitem-1/delete")
        .status_code
        == 200
    )


def test_without_an_api_token_a_member_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Fail CLOSED: merge state is unknowable without the api-scoped token, and an unprovable
    # answer must refuse rather than assume.
    deleted = _wire_branch_delete(monkeypatch, tmp_path, merged=True)
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)
    monkeypatch.setenv("MOSAERA_MEMBER_BRANCH_DELETE", "1")

    class _NoApi(_FakeMemoryWithDiff):
        def project_detail(self, pid: str) -> dict[str, Any] | None:
            return {
                "id": "p1",
                "source_repo": "https://gitlab.rengifo.me/g/p.git",
                "backlog": [],
                "runs": [{"id": "run-1"}],
            }

        def get_project_token(self, pid: str) -> str | None:
            return "push-tok"

        def add_audit_event(self, *a: Any, **k: Any) -> None: ...

    r = _client_with(_NoApi()).post("/api/projects/p1/branches/mosaera%2Fitem-1/delete")
    assert r.status_code == 409 and "api-scoped token" in r.json()["detail"]
    assert deleted == []
