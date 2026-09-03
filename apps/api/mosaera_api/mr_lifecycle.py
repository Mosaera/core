"""Ending and reviving a merge request — the half of the MR lifecycle the product never had.

Until now Mosaera could only ever OPEN a merge request. An MR that turned out to be obsolete —
its work already landed by another route, a duplicate, one opened against the wrong target —
could be resolved only in GitLab's own UI, and the product went on reporting it as live. That
also made ``mr_state == "closed"`` a state nothing here could produce or clear, while branch
protection (correctly) treats closed as non-terminal because GitLab can reopen.

Close and reopen are a pair on purpose. Closing is only safe to offer because reopening undoes
it: nothing is destroyed, no branch is touched, no commit is lost. That is why this is not gated
like branch destruction (ADR-0004) — it is the same class as ``retarget``, a recovery action a
member may take on their own delivery.

Kept out of ``delivery.py`` and ``routes/project_delivery.py``: both are near the modularity
ceiling, and this is a cohesive subject of its own.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from mosaera_connectors import gitlab_write as glw
from mosaera_connectors import is_gitlab_source, project_from_source
from mosaera_core.config import Settings
from mosaera_memory import MemoryStore

from mosaera_api.delivery import MrOutcome

# GitLab's own lifecycle verbs. Constrained here so no caller can smuggle another state_event
# through to the API.
MrAction = Literal["close", "reopen"]
_ACTIONS: dict[str, str] = {"close": "closed", "reopen": "opened"}


def _mr_iid(mr_url: str) -> int | None:
    match = re.search(r"/merge_requests/(\d+)", mr_url)
    return int(match.group(1)) if match else None


def _rest_context(
    mem: MemoryStore, settings: Settings, project_id: str
) -> tuple[dict[str, Any], str, str] | MrOutcome:
    """The (detail, gitlab project path, api token) every lifecycle edit needs, or the outcome
    explaining why the edit cannot be attempted."""
    detail = mem.project_detail(project_id)
    if detail is None:
        return MrOutcome(False, skip="unknown_project")
    source = str(detail["source_repo"])
    if not is_gitlab_source(source, settings.gitlab_url):
        return MrOutcome(False, skip="not_gitlab")
    gl_project = project_from_source(source)
    api_token = mem.get_project_api_token(project_id)
    if not (gl_project and api_token):
        # Editing an existing MR is a REST operation; the push token cannot do it (ADR-0103 §1).
        return MrOutcome(
            False, error="closing or reopening a merge request needs the project's api-scoped token"
        )
    return detail, gl_project, api_token


def _apply(
    settings: Settings, api_token: str, gl_project: str, iid: int, action: MrAction
) -> MrOutcome:
    data, err = glw.update_merge_request(
        settings.gitlab_url, api_token, gl_project, iid, state_event=action
    )
    if err:
        return MrOutcome(False, error=err)
    return MrOutcome(True, url=str((data or {}).get("web_url") or ""))


def set_item_mr_state(
    mem: MemoryStore, settings: Settings, project_id: str, item_id: int, action: MrAction
) -> MrOutcome:
    """Close or reopen one backlog item's merge request, and record the resulting state.

    The recorded state is what branch protection reads, so it is written from OUR action rather
    than left for the next poll — a closed MR must not look open to the guards for however long
    it takes /mr-status to run.
    """
    ctx = _rest_context(mem, settings, project_id)
    if isinstance(ctx, MrOutcome):
        return ctx
    detail, gl_project, api_token = ctx
    item = next((i for i in detail["backlog"] if int(i["id"]) == int(item_id)), None)
    if item is None:
        return MrOutcome(False, skip="no_item")
    iid = _mr_iid(str(item.get("mr_url") or ""))
    if iid is None:
        return MrOutcome(False, error="this item has no merge request to close or reopen")
    outcome = _apply(settings, api_token, gl_project, iid, action)
    if outcome.opened:
        mem.update_backlog_item(int(item_id), mr_state=_ACTIONS[action])
    return outcome


def set_project_mr_state(
    mem: MemoryStore, settings: Settings, project_id: str, action: MrAction
) -> MrOutcome:
    """Close or reopen the PROJECT-wide merge request.

    The project MR has no ``mr_state`` column — its liveness is read off ``status`` — so closing
    returns the project to ``active`` (it is no longer in review) and reopening restores
    ``in_review``. A ``merged`` project is never moved by this: merged is genuinely terminal, and
    reopening an MR whose commits already landed is not a state the product should manufacture.
    """
    ctx = _rest_context(mem, settings, project_id)
    if isinstance(ctx, MrOutcome):
        return ctx
    detail, gl_project, api_token = ctx
    if str(detail.get("status") or "") == "merged":
        return MrOutcome(False, error="this project's merge request is already merged")
    iid = _mr_iid(str(detail.get("mr_url") or ""))
    if iid is None:
        return MrOutcome(False, error="this project has no merge request to close or reopen")
    outcome = _apply(settings, api_token, gl_project, iid, action)
    if outcome.opened:
        mem.update_project(project_id, status="active" if action == "close" else "in_review")
    return outcome
