"""Merging an item's merge request from the console (ADR-0102 amendment, 2026-08-24).

**This is the only path in Mosaera that changes the target branch of a real repository.** Opening a
merge request proposes; merging delivers. Driving LedgerCLI to completion needed nine merges and
every one of them happened in GitLab, because the console could open and close a merge request and
not merge one — ADR-0102 slice P's finish line ("the case-study merge driven entirely from the
Delivery page") had never been met.

**What keeps "a human still merges" true** (ADR-0102), now that the click lives here:

1. **Admin-gated at the route**, on this codebase's own stated principle — `_branch_ops_allowed`:
   *"Installing the project token is admin-gated (ADR-0004, secret write); spending it irreversibly
   on the real repository is the same class of authority."* Merging spends it irreversibly.
2. **A session, never the bare service token.** If ``MOSAERA_API_TOKEN`` could merge, automation
   could merge and "operator-initiated" would be a word rather than a property.
3. **Nothing in `graph/` or the sweep imports this module.** Pinned by a test, because that is the
   difference between a property and an intention.

**Readiness is read fresh, at the moment of the ask.** A verdict computed at the last poll describes
the merge request as it was, and the operator is about to act on it as it is — ADR-0108's rule
("evidence describes a tree, or it is not evidence") applied to mergeability. The ``sha`` the
operator was shown rides the merge, so a branch that moved between the read and the click is
REFUSED by GitLab rather than merged blind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from mosaera_connectors.gitlab_client import get_merge_request
from mosaera_connectors.gitlab_write import merge_merge_request
from mosaera_core.config import Settings
from mosaera_memory import MemoryStore

from mosaera_api.delivery import is_gitlab_source, project_from_source

MergeSkip = Literal[
    "unknown_project",
    "not_gitlab",
    "no_item",
    "no_mr",
    "no_api_token",
    "not_open",
]

_IID_RE = re.compile(r"/merge_requests/(\d+)")


@dataclass(frozen=True)
class MergeReadiness:
    """What GitLab says right now. ``status`` is its own ``detailed_merge_status`` token, carried
    verbatim so the SPA's sentence can be reconciled against the source rather than trusted."""

    status: str = ""
    sha: str = ""
    source_branch: str = ""
    target_branch: str = ""
    web_url: str = ""
    skip: MergeSkip | None = None
    error: str | None = None


@dataclass(frozen=True)
class MergeOutcome:
    merged: bool = False
    #: Queued behind the pipeline (GitLab's merge-when-pipeline-succeeds), not merged yet.
    queued: bool = False
    error: str | None = None
    skip: MergeSkip | None = None


def _resolve(
    mem: MemoryStore, settings: Settings, project_id: str, item_id: int
) -> tuple[str, str, int, str] | MergeSkip:
    """``(gl_project, api_token, iid, mr_url)`` or the reason it cannot be attempted."""
    detail = mem.project_detail(project_id)
    if detail is None:
        return "unknown_project"
    source = str(detail["source_repo"])
    if not is_gitlab_source(source, settings.gitlab_url):
        return "not_gitlab"
    item = next((i for i in (detail.get("backlog") or []) if i["id"] == item_id), None)
    if item is None:
        return "no_item"
    mr_url = str(item.get("mr_url") or "")
    match = _IID_RE.search(mr_url)
    if not match:
        return "no_mr"
    # The api scope, never the write_repository push token: ADR-0103 §1 keeps the unattended path
    # off `api` deliberately, and merging is a REST write. No api token means no merge — and the
    # UI says so rather than presenting a control that cannot work.
    api_token = mem.get_project_api_token(project_id) or ""
    if not api_token:
        return "no_api_token"
    gl_project = project_from_source(source)
    if not gl_project:
        return "not_gitlab"
    return gl_project, api_token, int(match.group(1)), mr_url


def item_mr_readiness(
    mem: MemoryStore, settings: Settings, project_id: str, item_id: int
) -> MergeReadiness:
    """Read GitLab's live verdict for this item's merge request.

    Never guesses: a failed read returns ``error`` and an empty ``status``, which the SPA maps to
    "GitLab has not said whether this can merge" — not to ready.
    """
    resolved = _resolve(mem, settings, project_id, item_id)
    if isinstance(resolved, str):
        return MergeReadiness(skip=resolved)
    gl_project, api_token, iid, mr_url = resolved
    mr, err = get_merge_request(settings.gitlab_url, api_token, gl_project, iid)
    if err or not isinstance(mr, dict):
        return MergeReadiness(web_url=mr_url, error=err or "no merge request data")
    if str(mr.get("state") or "") != "opened":
        return MergeReadiness(
            status=str(mr.get("detailed_merge_status") or "not_open"),
            web_url=str(mr.get("web_url") or mr_url),
            skip="not_open",
        )
    return MergeReadiness(
        status=str(mr.get("detailed_merge_status") or ""),
        sha=str(mr.get("sha") or ""),
        source_branch=str(mr.get("source_branch") or ""),
        target_branch=str(mr.get("target_branch") or ""),
        web_url=str(mr.get("web_url") or mr_url),
    )


def merge_item_mr(
    mem: MemoryStore,
    settings: Settings,
    project_id: str,
    item_id: int,
    *,
    when_pipeline_succeeds: bool = False,
    sha: str = "",
) -> MergeOutcome:
    """Merge this item's MR, or queue it behind the pipeline.

    ``sha`` is the head the operator was shown in the confirmation. It is passed through to GitLab,
    which refuses if the branch has moved — so approving a diff and merging a different one is not
    reachable from here.
    """
    resolved = _resolve(mem, settings, project_id, item_id)
    if isinstance(resolved, str):
        return MergeOutcome(skip=resolved)
    gl_project, api_token, iid, _ = resolved
    data, err = merge_merge_request(
        settings.gitlab_url,
        api_token,
        gl_project,
        iid,
        when_pipeline_succeeds=when_pipeline_succeeds,
        sha=sha or None,
    )
    if err:
        return MergeOutcome(error=err)
    state = str((data or {}).get("state") or "") if isinstance(data, dict) else ""
    if state == "merged":
        return MergeOutcome(merged=True)
    # Accepted but not merged: GitLab queued it behind the pipeline. Reported as QUEUED, never as
    # merged — the operator asked whether it landed, and "accepted" is a different answer.
    if when_pipeline_succeeds:
        return MergeOutcome(queued=True)
    return MergeOutcome(error=f"GitLab did not merge it (state: {state or 'unknown'})")


def merged_state(outcome: MergeOutcome) -> dict[str, Any]:
    return {"merged": outcome.merged, "queued": outcome.queued}
