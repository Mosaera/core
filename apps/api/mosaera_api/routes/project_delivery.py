"""Project delivery routes: MR opening (project + per-item) and MR-state polling.

Extracted from ``routes/projects.py`` (ADR-0102 slice O — that file sat at 489/500 and
the delivery surface is a cohesive unit of its own). The openers live in
``mosaera_api.delivery`` (the shared outcome layer both humans and the sweep use);
these routes only map outcomes to HTTP and persist what the poll saw.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import delete_remote_branch, is_gitlab_source, project_from_source
from mosaera_core.config import Settings
from mosaera_core.tools.repo import (
    commit_list,
    local_branches,
    open_project_workspace,
    project_base,
)
from mosaera_memory import SecretKeyError

from mosaera_api.auth import current_user
from mosaera_api.delivery import (
    MrOutcome,
    open_item_mr,
    open_project_mr,
    retarget_item_mr,
)
from mosaera_api.mr_lifecycle import MrAction, set_item_mr_state, set_project_mr_state
from mosaera_api.mr_status import poll_mr_status
from mosaera_api.routes._branch_guards import (
    _branch_ops_allowed,
    _caller_is_admin,
    _project_mr_branches,
    _protected_branches,
    _rest_branches,
)
from mosaera_api.routes._delivery_capability import register_delivery_capability_routes
from mosaera_api.routes._delivery_check import register_delivery_check_routes
from mosaera_api.routes._delivery_merge import register_merge_routes
from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import (
    MrComposeBody,
    MrStateBody,
    ProjectBusy,
    RetargetBody,
)


def _actor(ctx: AppContext, request: Request) -> str:
    """Who drove this call, for the audit trail (ADR-0102): the authenticated user's
    name, or 'endpoint' when auth is open (dev/loopback, no users configured)."""
    user = current_user(request, ctx.history)
    return f"user:{user['username']}" if user and user.get("username") else "endpoint"


def _audit_mr(ctx: AppContext, project_id: str, detail: str, event: str = "mr.opened") -> None:
    """Record a delivery action against the project's newest run (the same anchor the autonomous
    sweep uses) so it lands in project_activity. Best-effort — an audit write must never fail the
    operator-authorized action."""
    if ctx.history is None:
        return
    try:
        pdetail = ctx.history.project_detail(project_id)
        runs = (pdetail or {}).get("runs") or []
        if runs:
            ctx.history.add_audit_event(str(runs[0]["id"]), event, detail)
    except Exception:  # noqa: S110 — audit is best-effort, never blocks delivery
        pass


# Why a call did not open an MR → the endpoint's HTTP code (shared by both openers).
_SKIP_HTTP: dict[str, tuple[int, str]] = {
    "unknown_project": (404, "unknown project"),
    "not_gitlab": (
        400,
        "project source is not on the configured GitLab; merge targets GitLab "
        "repos you can push to",
    ),
    # ADR-0112: a GitHub project's source is not wrong, it is unconnected. The old
    # not_gitlab wording sent those operators to re-check a URL that was fine.
    "github_not_connected": (
        400,
        "this project's source is on GitHub, and the Mosaera GitHub App is not installed on "
        "that repository yet; install it, then use Connect (ADR-0114)",
    ),
    # Distinct from the above because the remedy is different: the INSTANCE has no App, which
    # an admin fixes once in settings, rather than this one repo lacking an installation.
    # Never reached over HTTP (the endpoint passes allow_github), but the map must stay total
    # or an unmapped skip becomes a KeyError instead of a refusal.
    "github_endpoint_only": (
        400,
        "GitHub delivery is available only from the authenticated endpoint, not the "
        "autonomous sweep",
    ),
    "github_app_unconfigured": (
        400,
        "this project's source is on GitHub, and this Mosaera instance has no GitHub App "
        "configured; an admin sets one up before GitHub delivery is available",
    ),
    "no_token": (
        400,
        "this project has no GitLab token; add one (Update token) to open a merge request",
    ),
    "no_project": (400, "could not derive a GitLab project from the source"),
    "no_clone": (409, "project clone not found"),
    "empty_diff": (409, "no commits ahead of the target to merge"),
    "no_item": (404, "unknown backlog item"),
    "already_open": (409, "this item's merge request is already open"),
}


def _outcome_http(outcome: MrOutcome) -> dict[str, Any]:
    if outcome.opened:
        return {"opened": True, "url": outcome.url}
    if outcome.skip is not None:
        code, msg = _SKIP_HTTP[outcome.skip]
        raise HTTPException(status_code=code, detail=msg)
    raise HTTPException(status_code=502, detail=outcome.error or "merge request not opened")


def make_project_delivery_router(
    ctx: AppContext, require_admin: Callable[[Request], None]
) -> APIRouter:
    api = APIRouter()

    def _compose_needs_clone_lock(compose: MrComposeBody | None) -> bool:
        # A2: only a commit-subset compose mutates the shared clone (cherry-pick); everything
        # else just reads + pushes. Hold the project mutex ONLY for the mutating case.
        return bool(compose and compose.commit_shas)

    @api.post("/projects/{project_id}/merge")
    def merge_project(
        project_id: str, request: Request, compose: MrComposeBody | None = None
    ) -> dict[str, Any]:
        # Shared, guarded opener (ADR-0019): same implementation the autonomous last-mile
        # uses. The authenticated call IS the human approval (ADR-0102) — so it must be
        # RECORDED with the actor, or "the authenticated call is the approval" is a claim
        # nothing on the record can back (red-team 2026-08-13). `compose` (ADR-0103) is the
        # operator's optional edits (faithful body/target/squash via REST when an api token exists).
        locked = _compose_needs_clone_lock(compose)
        if locked:
            try:
                ctx.reserve_project(project_id)  # A2: exclusive clone access for the cherry-pick
            except ProjectBusy as exc:
                raise HTTPException(
                    status_code=409,
                    detail="a run is active on this project; try again after it finishes",
                ) from exc
        try:
            # allow_github: this IS the authenticated endpoint, the human control ADR-0102
            # names. The autonomous sweep calls the same function without it (ADR-0114 §5).
            outcome = open_project_mr(
                ctx.require_memory(), Settings.from_env(), project_id, compose, allow_github=True
            )
        finally:
            if locked:
                ctx.release_project(project_id)
        if outcome.opened:
            how = "composed" if compose else "default"
            _audit_mr(
                ctx, project_id, f"actor={_actor(ctx, request)}; project MR ({how}); {outcome.url}"
            )
        return _outcome_http(outcome)

    @api.get("/projects/{project_id}/commits")
    def list_project_commits(project_id: str) -> dict[str, Any]:
        # A2: the commit-picker's material — commits on the project branch ahead of the base,
        # read from the local clone (no token).
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        try:
            workspace = open_project_workspace(
                Settings.from_env().projects_dir, project_id, project_id
            )
        except FileNotFoundError:
            return {"commits": []}
        return {"commits": commit_list(workspace, project_base(workspace))}

    @api.post("/projects/{project_id}/items/{item_id}/open-mr")
    def open_item_merge_request(
        project_id: str, item_id: int, request: Request, compose: MrComposeBody | None = None
    ) -> dict[str, Any]:
        # The manual per-item opener (ADR-0102 slice O): before this, with the default
        # mr_granularity="item" and auto_open_mr off, a human had NO way to open an
        # item MR at all — ADR-0021's delivery model was unreachable by hand.
        outcome = open_item_mr(
            ctx.require_memory(), Settings.from_env(), project_id, item_id, compose
        )
        if outcome.opened:
            how = "composed" if compose else "default"
            _audit_mr(
                ctx,
                project_id,
                f"actor={_actor(ctx, request)}; item {item_id} MR ({how}); {outcome.url}",
            )
        return _outcome_http(outcome)

    register_merge_routes(api, ctx, require_admin, _actor, _audit_mr)
    register_delivery_check_routes(api, ctx)
    register_delivery_capability_routes(api, ctx)

    @api.post("/projects/{project_id}/items/{item_id}/retarget")
    def retarget_item_merge_request(
        project_id: str, item_id: int, body: RetargetBody, request: Request
    ) -> dict[str, Any]:
        """Repoint a stuck item MR at another branch — the recovery path (0028).

        Deleting a merged predecessor's branch orphans its successor's open MR, and until now
        NOTHING in the product could repair that: the opener refuses `already_open`, there is no
        close/reopen, and the MR columns are not patchable. Audited like every other outward-facing
        delivery action.
        """
        target = body.target_branch.strip()
        if not target:
            raise HTTPException(status_code=400, detail="target_branch is required")
        outcome = retarget_item_mr(
            ctx.require_memory(), Settings.from_env(), project_id, item_id, target
        )
        if outcome.opened:
            _audit_mr(
                ctx,
                project_id,
                f"actor={_actor(ctx, request)}; item {item_id} MR retargeted to {target}",
                event="mr.retargeted",
            )
        return _outcome_http(outcome)

    # Past tense spelled out, not derived. `f"{action}d"` reads fine for "close" and produces
    # "reopend" for "reopen" — and an audit event name is a queryable contract, so a typo in it
    # is a silently wrong record, not a cosmetic slip. Caught in live validation 2026-08-18.
    _PAST = {"close": "closed", "reopen": "reopened"}

    def _mr_action(body: MrStateBody) -> MrAction:
        action = body.action.strip().lower()
        if action not in _PAST:
            raise HTTPException(status_code=400, detail="action must be close or reopen")
        return action  # type: ignore[return-value]

    @api.post("/projects/{project_id}/items/{item_id}/mr-state")
    def set_item_merge_request_state(
        project_id: str, item_id: int, body: MrStateBody, request: Request
    ) -> dict[str, Any]:
        """Close or reopen an item's merge request.

        The missing half of the lifecycle: the product could only ever open one, so an obsolete
        MR stayed live here forever and `closed` was a state nothing could produce or clear.
        Member-available like `retarget` and unlike branch destruction — closing destroys
        nothing and reopen undoes it.
        """
        action = _mr_action(body)
        outcome = set_item_mr_state(
            ctx.require_memory(), Settings.from_env(), project_id, item_id, action
        )
        if outcome.opened:
            _audit_mr(
                ctx,
                project_id,
                f"actor={_actor(ctx, request)}; item {item_id} MR {_PAST[action]}",
                event=f"mr.{_PAST[action]}",
            )
        return _outcome_http(outcome)

    @api.post("/projects/{project_id}/mr-state")
    def set_project_merge_request_state(
        project_id: str, body: MrStateBody, request: Request
    ) -> dict[str, Any]:
        """Close or reopen the project-wide merge request (see the item route)."""
        action = _mr_action(body)
        outcome = set_project_mr_state(
            ctx.require_memory(), Settings.from_env(), project_id, action
        )
        if outcome.opened:
            _audit_mr(
                ctx,
                project_id,
                f"actor={_actor(ctx, request)}; project MR {_PAST[action]}",
                event=f"mr.{_PAST[action]}",
            )
        return _outcome_http(outcome)

    @api.get("/projects/{project_id}/branches")
    def list_project_branches(project_id: str) -> dict[str, Any]:
        """The branch list, from GitLab when we can and the clone when we can't.

        ADR-0103 §4 decided that branch READ rides the api token; the implementation had drifted to
        a local-clone enumeration, which cannot serve the delete/prune surface: ``local_branches``
        excludes ``mosaera/*`` by design and hardcodes ``merged: False``, and pushes go BY URL
        rather than to the named remote, so ``refs/remotes/origin/mosaera/*`` is never created.
        (CORRECTION to an earlier version of this comment: the clone DOES hold ``mosaera/*`` as
        local heads — ``clone.py`` checks them out — it is only the remote-tracking refs that are
        absent. Believing otherwise made local recovery look impossible.) The result was an
        always-empty delete list and a prune confirmation that could never name its own targets.

        REST gives real names AND a real ``merged`` flag. Without an api token we fall back to the
        clone and SAY SO (``source``) — a degraded list that looked authoritative would be the same
        defect in a new place. Still no fetch on this path (ADR-0102): the fallback reads only what
        the clone already has.
        """
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        settings = Settings.from_env()
        source = str(detail["source_repo"])
        rest = _rest_branches(mem, settings, project_id, source)
        if rest is not None:
            return {"source": "gitlab", "branches": rest}
            # else: fall through to the clone — the caller is told which it got.
        try:
            workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        except FileNotFoundError:
            return {"source": "clone", "branches": []}
        return {"source": "clone", "branches": local_branches(workspace)}

    @api.post("/projects/{project_id}/branches/prune")
    def prune_merged_branches(project_id: str, request: Request) -> dict[str, Any]:
        # ADR-0103 Phase 4: delete the branches of MERGED items (their remote branch is dead
        # weight). Rides write_repository (git push --delete), no api scope. Fail-safe: skip any
        # branch still targeted by an OTHER item's open MR, so a stacked chain can't be orphaned.
        _branch_ops_allowed(require_admin, request, Settings.from_env())
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        settings = Settings.from_env()
        source = str(detail["source_repo"])
        if not is_gitlab_source(source, settings.gitlab_url):
            raise HTTPException(
                status_code=400, detail="project source is not on the configured GitLab"
            )
        gl_project = project_from_source(source)
        try:
            token = mem.get_project_token(project_id)
        except SecretKeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not (token and gl_project):
            raise HTTPException(status_code=400, detail="this project has no GitLab token")
        backlog = detail.get("backlog") or []
        try:
            workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        protected = _protected_branches(backlog, project_base(workspace)) | _project_mr_branches(
            detail
        )
        pruned: list[str] = []
        for item in backlog:
            branch = str(item.get("branch") or "")
            if not branch or item.get("mr_state") != "merged" or branch in protected:
                continue
            err = delete_remote_branch(
                workspace.root,
                branch,
                project=gl_project,
                gitlab_url=settings.gitlab_url,
                token=token,
            )
            if err is None:
                pruned.append(branch)
        if pruned:
            _audit_mr(
                ctx,
                project_id,
                f"actor={_actor(ctx, request)}; pruned {', '.join(pruned)}",
                event="branch.pruned",
            )
        return {"pruned": pruned}

    @api.post("/projects/{project_id}/branches/{branch:path}/delete")
    def delete_project_branch(project_id: str, branch: str, request: Request) -> dict[str, Any]:
        # A3: delete ONE remote branch (write_repository, no api scope). Refuses a branch that is
        # the SOURCE or TARGET of an open item MR — deleting either orphans a live MR (the
        # open-MR-target case the last live validation surfaced). Local checkout/rename is NOT
        # exposed — it would race the shared clone's run lifecycle.
        #
        # The `mosaera/` restriction and the never-the-base rule are enforced HERE, not only in
        # the UI. They used to live solely in the web client, which made the API a way around the
        # product's own safety rule — a control that only exists in the surface that offers it is
        # not a control.
        if not branch.startswith("mosaera/"):
            raise HTTPException(
                status_code=400,
                detail="only Mosaera's own mosaera/* branches may be deleted from here",
            )
        is_admin = _caller_is_admin(require_admin, request)
        _branch_ops_allowed(require_admin, request, Settings.from_env())
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        settings = Settings.from_env()
        source = str(detail["source_repo"])
        if not is_gitlab_source(source, settings.gitlab_url):
            raise HTTPException(
                status_code=400, detail="project source is not on the configured GitLab"
            )
        gl_project = project_from_source(source)
        try:
            token = mem.get_project_token(project_id)
        except SecretKeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not (token and gl_project):
            raise HTTPException(status_code=400, detail="this project has no GitLab token")
        try:
            workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        base = project_base(workspace)
        if branch == base:
            raise HTTPException(status_code=409, detail="the base branch is never deletable")
        if branch in _project_mr_branches(detail):
            raise HTTPException(
                status_code=409, detail="branch is the source of this project's open merge request"
            )
        if branch in _protected_branches(detail.get("backlog") or [], base):
            raise HTTPException(
                status_code=409, detail="branch is the source or target of an open merge request"
            )
        if not is_admin:
            # Blast radius: a member may delete only a branch GitLab reports as MERGED. The other
            # guards stop the wrong KIND of branch; none of them stop destroying unmerged work.
            # Fail CLOSED — without an api-scoped token nothing is provable, so nothing is
            # deletable by a member (red-team 2026-08-18 finding 6).
            known = _rest_branches(mem, settings, project_id, source)
            if known is None:
                raise HTTPException(
                    status_code=409,
                    detail="cannot confirm this branch is merged (no api-scoped token), so only "
                    "an admin may delete it",
                )
            if not any(b["name"] == branch and b["merged"] for b in known):
                raise HTTPException(
                    status_code=409,
                    detail="only a merged branch may be deleted by a member — this one still "
                    "carries unmerged work",
                )
        err = delete_remote_branch(
            workspace.root, branch, project=gl_project, gitlab_url=settings.gitlab_url, token=token
        )
        if err is not None:
            raise HTTPException(status_code=502, detail=err)
        _audit_mr(
            ctx,
            project_id,
            f"actor={_actor(ctx, request)}; deleted {branch}",
            event="branch.deleted",
        )
        return {"deleted": branch}

    @api.get("/projects/{project_id}/mr-status")
    def project_mr_status(project_id: str, force: bool = False) -> dict[str, Any]:
        """`force` re-reads items already recorded `merged` — the correction path for a wrong
        record, which is otherwise permanent AND makes the branch prunable."""
        return poll_mr_status(ctx.require_memory(), Settings.from_env(), project_id, force=force)

    return api
