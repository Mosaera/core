"""Who may destroy a delivery branch, and which branches are destroyable at all.

Extracted from ``project_delivery.py`` when that file reached the 500-line ceiling. Cohesive by
subject: everything here answers a guard question about branches — what an open merge request
depends on, what GitLab reports as merged, and whether this caller may destroy anything. The
endpoints stay in the router; these are pure decisions the router applies.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request
from mosaera_connectors import gitlab_write as glw
from mosaera_connectors import is_gitlab_source, project_from_source
from mosaera_core.config import Settings

from mosaera_api.delivery import _stacked_target


def _protected_branches(backlog: list[dict[str, Any]], base: str) -> set[str]:
    """Branches a still-open item MR depends on — deleting any orphans a live MR (A3). Covers
    both the SOURCE branch of an open item and the TARGET it actually points at.

    The target comes from the RECORDED ``mr_target`` (0028), never from ``_stacked_target``.
    That function answers "what should a NEW MR target?", and reusing it here to answer "what
    does this EXISTING MR target?" is what broke item 100 on 2026-08-18: item 99 merged, the
    recomputed target became the base, ``mosaera/item-99`` fell out of this set, and the prune
    deleted the branch a live MR still pointed at. It falls back to the recomputation only for
    rows written before 0028, which the /mr-status poll backfills.
    """
    protected: set[str] = set()
    for item in backlog:
        # "closed" is NOT terminal — GitLab reopens merge requests, and the poll itself treats
        # only "merged" as final. Dropping protection on close let a reviewer close an MR, a prune
        # delete both its source and target branch, and the reopen land on nothing
        # (red-team 2026-08-18, finding 4).
        if item.get("branch") and item.get("mr_state") not in ("merged", ""):
            protected.add(str(item["branch"]))  # an open item's source branch
            recorded = str(item.get("mr_target") or "")
            protected.add(recorded or _stacked_target(backlog, item, base))
    protected.discard(base)  # the base branch is never a deletable item branch
    return protected


def _project_mr_branches(detail: dict[str, Any]) -> set[str]:
    """The PROJECT MR's own source branch, while that MR is live. `_protected_branches` only
    ever inspects backlog items, so the project MR's source was protected by nothing — deleting
    it orphans the project-wide merge request.

    The source comes from the RECORDED ``mr_source`` (0029). Guessing it was the same defect
    0028 fixed for item MRs, one level up: ``open_project_mr`` opens from ``workspace.branch``
    — whatever the shared clone is checked out on — while this guessed ``projects.branch`` (the
    intake branch, written once at creation) and ``mosaera/combined-<id>``. Measured 2026-08-18:
    project MR !4 sourced from ``mosaera/item-102`` and neither guess covered it, so an admin
    delete would have orphaned a live MR. The guesses survive only as the fallback for rows
    written before 0029, which the /mr-status poll backfills from the MR's own JSON.
    """
    if not str(detail.get("mr_url") or "") or str(detail.get("status") or "") == "merged":
        return set()
    recorded = str(detail.get("mr_source") or "")
    if recorded:
        return {recorded}
    pid = str(detail.get("id") or "")
    return {str(detail.get("branch") or ""), f"mosaera/combined-{pid}"} - {""}


def _rest_branches(
    mem: Any,
    settings: Settings,
    project_id: str,
    source: str,
    *,
    timeout: float | None = None,
) -> list[dict[str, Any]] | None:
    """GitLab's branch list with its real ``merged`` flag, or None when we cannot ask.

    ADR-0103 §4: branch READ rides the api token. None means "not knowable" — never "no branches"
    — because callers use it to DECIDE, and a missing answer must fail closed, not open.

    ``timeout`` bounds the call for a latency-sensitive caller (the chat turn). Exceeding it is
    just another "cannot ask", so it lands on the same fail-closed path rather than a new one.
    """
    api_token = mem.get_project_api_token(project_id)
    gl_project = (
        project_from_source(source) if is_gitlab_source(source, settings.gitlab_url) else None
    )
    if not (api_token and gl_project):
        return None
    data, err = glw.list_branches(settings.gitlab_url, api_token, gl_project, timeout=timeout)
    if err or not isinstance(data, list):
        return None
    return [
        {
            "name": b.get("name", ""),
            "merged": bool(b.get("merged")),
            "protected": bool(b.get("protected")),
        }
        for b in data
        if isinstance(b, dict) and b.get("name")
    ]


def _caller_is_admin(require_admin: Callable[[Request], None], request: Request) -> bool:
    """Whether this caller would pass the admin gate — as a boolean, not a raise.

    Calls the INJECTED gate rather than re-deriving it, so the real semantics stay in one place:
    a logged-in admin, ``MOSAERA_ADMIN_TOKEN``, or the loopback dev path (ADR-0004 §6).
    """
    try:
        require_admin(request)
    except HTTPException:
        return False
    return True


def _branch_ops_allowed(
    require_admin: Callable[[Request], None], request: Request, settings: Settings
) -> None:
    """Branch DESTRUCTION is admin-only unless an admin has opted members in.

    Installing the project token is admin-gated (ADR-0004, secret write); spending it irreversibly
    on the real repository is the same class of authority. The 403 names the setting so an operator
    can act on it instead of guessing (red-team 2026-08-18 finding 6).
    """
    if _caller_is_admin(require_admin, request) or settings.member_branch_delete:
        return
    raise HTTPException(
        status_code=403,
        detail="deleting branches is admin-only on this instance — an admin can allow it with "
        "the 'Members may delete branches' setting on the Delivery page",
    )
