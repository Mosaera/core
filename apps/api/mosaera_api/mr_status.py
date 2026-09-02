"""Polling GitLab for what actually happened to the merge requests we opened.

Extracted from ``routes/project_delivery.py`` when that file reached the 500-line ceiling.
Cohesive by subject: this is the one place the product reconciles its RECORD of a merge request
against GitLab's own answer — the state, the target it really points at (0028), and the branch it
really sources from (0029). Those records are what branch protection reads, so the reconciliation
is a safety mechanism, not a display refresh.

Every call here is a REST READ and needs the `api` scope. Spending the `write_repository` push
token on them made the whole poll inert on a push-only project, which is why records never
self-healed and items ended up stranded with a branch and no URL.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from mosaera_connectors import gitlab_client as glc
from mosaera_connectors import is_gitlab_source, project_from_source
from mosaera_core.config import Settings
from mosaera_memory import MemoryStore, SecretKeyError

from mosaera_api import github_delivery as ghd
from mosaera_api.delivery import resolve_mr_url


def _mr_is_gone(settings: Settings, token: str, gl_project: str, err: str | None) -> bool:
    """Whether a recorded merge request genuinely no longer exists — TWO facts, not one.

    GitLab answers 404 for *unauthorized* as well as *absent*, so a bare 404 would let a token
    that merely lost access clear the record and with it the branch protection that record
    carries. Requiring the project itself to answer 200 with the SAME token separates the two:
    reachable project + missing MR means the MR is gone; anything else fails closed and the
    record stands.
    """
    if glc.http_status(err) != 404:
        return False
    _, project_err = glc.get_project(settings.gitlab_url, token, gl_project)
    return project_err is None


def _clear_phantom(mem: MemoryStore, item_id: int, mr_url: str, run_id: str | None) -> None:
    """Forget an MR that no longer exists. Without this a deleted MR is permanent: the poll
    errors forever, the row keeps a state of "opened", its branches stay protected, and the
    backlog row cannot be deleted, split, or merged — with no in-product exit.

    ``branch`` is cleared too, and that is not incidental. It is the opener's idempotency
    marker — `open_item_mr` refuses `already_open` on it and the UI hides "Open MR" while it is
    set — so clearing only the MR columns would swap one terminal state for another: an item
    with a branch, no merge request, and no way to obtain one. Releasing the marker is the whole
    point of forgetting the MR; the branch itself still exists on the remote, so a re-open pushes
    to it again.
    """
    mem.update_backlog_item(item_id, branch="", mr_url="", mr_state="", mr_target="")
    # Automatic, and it strips branch protection — so it MUST leave a trace (Capability through
    # Auditability). `audit_events.run_id` is a FOREIGN KEY to `runs.id`: a synthetic id here
    # raises, the best-effort guard swallows it, and the action is silently unaudited.
    add_audit = getattr(mem, "add_audit_event", None)
    if add_audit is not None and run_id:
        try:
            add_audit(run_id, "mr.vanished", f"cleared record of deleted MR {mr_url}")
        except Exception:  # noqa: S110 — an audit write must never fail the reconciliation
            pass


def _github_status(
    mem: MemoryStore, settings: Settings, project_id: str, detail: dict[str, Any]
) -> dict[str, Any]:
    """The GitHub project pull request's state, reconciled into the store (ADR-0114).

    Deliberately narrower than the GitLab path: there are no per-item pull requests to poll
    (that slice was not built), and no phantom-clearing — the two-fact "has it vanished" check
    exists because a GitLab MR can be deleted outright, whereas a GitHub PR cannot be. Guessing
    a GitHub equivalent would be inventing a mechanism for a failure that does not occur.

    Every failure degrades to the stored state. A poll that cannot read must never overwrite a
    real record with an absence.
    """
    pr_url = str(detail.get("mr_url") or "")
    if not pr_url or not detail.get("has_github_connection"):
        return {"state": None, "url": pr_url, "items": []}
    state, err = ghd.read_pr_state(mem, settings, project_id, detail, pr_url)
    if state is None:
        return {"state": None, "url": pr_url, "items": [], **({"error": err} if err else {})}
    if state == "merged" and str(detail.get("status") or "") != "merged":
        mem.update_project(project_id, status="merged")
    return {"state": state, "url": pr_url, "items": []}


def poll_mr_status(
    mem: MemoryStore, settings: Settings, project_id: str, *, force: bool = False
) -> dict[str, Any]:
    """The project MR's state plus each item MR's, reconciling the stored records as it goes.

    ``force`` re-reads items whose stored state is already ``merged``. That state is normally
    terminal and skipped to bound REST cost, but it is also the state that makes a branch
    prunable — so a wrongly-recorded ``merged`` was both destructive and permanently
    uncorrectable. This is the correction path.
    """
    detail = mem.project_detail(project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown project")
    runs = detail.get("runs") or []
    audit_run = str(runs[0]["id"]) if runs else None  # same anchor _audit_mr uses
    settings = Settings.from_env()
    if ghd.is_github_project(settings, detail):
        # ADR-0114. Without this a GitHub project could open a pull request and never read as
        # delivered — the F64 gap, reopened on the other provider. Returns the same shape.
        return _github_status(mem, settings, project_id, detail)
    mr_url = str(detail.get("mr_url") or "")
    match = re.search(r"/merge_requests/(\d+)", mr_url)
    try:
        token = mem.get_project_token(project_id)
    except SecretKeyError:
        token = None  # locked token (wrong/missing key) → no MR status, never a 500 (M-2)
    settings = Settings.from_env()
    source = str(detail["source_repo"])
    # Host equality (ADR-0042/0102 red-team): only ever spend the project token
    # against the configured GitLab — never a project path derived from an
    # off-host source_repo, even for a read.
    gl_project = (
        project_from_source(source) if is_gitlab_source(source, settings.gitlab_url) else None
    )

    # Per-item MR states (ADR-0102 slice O): the item mr_urls were stored and never
    # polled, so a merged item MR stayed "in review" forever. Only non-terminal items
    # are polled (merged is final); failures degrade to the stored state, never a 500.
    # Every call below is a REST READ, which needs the `api` scope — the push token cannot
    # do it (ADR-0103 §1). Spending the push token here made the whole poll inert on a
    # push-only project, which is why records never self-healed. Falls back to the push
    # token because an OAuth-minted project token carries both scopes as one string.
    read_token = mem.get_project_api_token(project_id) or token
    items: list[dict[str, Any]] = []
    if read_token and gl_project:
        for item in detail.get("backlog") or []:
            item_url = str(item.get("mr_url") or "")
            item_match = re.search(r"/merge_requests/(\d+)", item_url)
            if not item_match:
                # A branch with no usable MR URL is the terminal stranded row: nothing
                # polls it (no iid), the opener refuses `already_open`, and retarget has
                # no MR to edit — yet its branch stays protected. Recover the URL from the
                # source branch, which is exactly what the opener's fallback failed to do
                # when it was handed the push token.
                branch = str(item.get("branch") or "")
                found = resolve_mr_url(settings, read_token, gl_project, branch) if branch else ""
                if found:
                    mem.update_backlog_item(int(item["id"]), mr_url=found)
                    items.append({"id": item["id"], "state": None, "url": found})
                continue
            stored = str(item.get("mr_state") or "")
            if stored == "merged" and not force:
                items.append({"id": item["id"], "state": stored, "url": item_url})
                continue
            mr, err = glc.get_merge_request(
                settings.gitlab_url, read_token, gl_project, int(item_match.group(1))
            )
            if _mr_is_gone(settings, read_token, gl_project, err):
                _clear_phantom(mem, int(item["id"]), item_url, audit_run)
                items.append({"id": item["id"], "state": None, "url": ""})
                continue
            state = mr.get("state") if not err and isinstance(mr, dict) else None
            # The same JSON carries `target_branch`, so the recorded target self-heals here
            # with no extra call — including for MRs opened before 0028 existed.
            tgt = mr.get("target_branch") if not err and isinstance(mr, dict) else None
            fields: dict[str, Any] = {}
            if isinstance(state, str) and state and state != stored:
                fields["mr_state"] = state
            if isinstance(tgt, str) and tgt and tgt != str(item.get("mr_target") or ""):
                fields["mr_target"] = tgt
            if fields:
                mem.update_backlog_item(int(item["id"]), **fields)
            items.append({"id": item["id"], "state": state or stored or None, "url": item_url})

    if not (mr_url and match and read_token and gl_project):
        return {"state": None, "url": mr_url, "items": items}
    mr, err = glc.get_merge_request(
        settings.gitlab_url, read_token, gl_project, int(match.group(1))
    )
    if err or not isinstance(mr, dict):
        return {"state": None, "url": mr_url, "error": err, "items": items}
    state = mr.get("state")
    # The same JSON carries `source_branch`, so the recorded project-MR source self-heals
    # here with no extra call — including for MRs opened before 0029 existed.
    src = mr.get("source_branch")
    proj_fields: dict[str, Any] = {}
    if state == "merged" and detail["status"] != "merged":
        proj_fields["status"] = "merged"
    if isinstance(src, str) and src and src != str(detail.get("mr_source") or ""):
        proj_fields["mr_source"] = src
    if proj_fields:
        mem.update_project(project_id, **proj_fields)
    return {"state": state, "url": mr_url, "items": items}
