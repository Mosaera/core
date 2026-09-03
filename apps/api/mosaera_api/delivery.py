"""The project merge-request opener — the shared, guarded last-mile (ADR-0019).

One implementation, two callers: the human ``POST /projects/{id}/merge`` endpoint
and the autonomous sweep's backlog-complete hook. It only ever OPENS the project MR
(a human still merges), and it uses the project's own scoped ``write_repository``-only
token via git push-options — never a global token, never the ``api`` scope.

Kept in its own module (not ``routes/projects.py``) so ``routes/context.py`` can reuse
it without an import cycle (``projects`` already imports ``context``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mosaera_connectors import (
    MergeRequestPlan,
    assemble_merge_request,
    detect_delivery_provider,
    is_gitlab_source,
    open_merge_request,
    project_from_source,
)
from mosaera_connectors import gitlab_client as glc
from mosaera_connectors import gitlab_write as glw
from mosaera_core.config import Settings
from mosaera_core.tools.repo import (
    Workspace,
    cherry_pick_into_branch,
    open_project_workspace,
    project_base,
    project_diff,
    project_item_diff,
)
from mosaera_memory import MemoryStore

from mosaera_api import github_delivery as ghd
from mosaera_api.github_delivery import app_configured as github_app_configured
from mosaera_api.schemas import MrComposeBody

# Why a call did not open an MR — lets the endpoint map to the right HTTP code and the
# sweep decide whether it's a benign skip (no work / no config) or a real failure.
SkipReason = Literal[
    "unknown_project",
    "not_gitlab",
    "github_not_connected",
    "github_app_unconfigured",
    "github_endpoint_only",
    "no_token",
    "no_project",
    "no_clone",
    "empty_diff",
    "no_item",
    "already_open",
]


@dataclass(frozen=True)
class MrOutcome:
    """The result of an ``open_project_mr`` attempt. ``opened`` with a possibly-empty
    ``url`` on success; ``skip`` set when a precondition wasn't met (not attempted);
    ``error`` set when the connector was called but the push/MR failed."""

    opened: bool
    url: str | None = None
    error: str | None = None
    skip: SkipReason | None = None


def unsupported_source_skip(source: str, settings: Settings) -> SkipReason:
    """Which refusal a non-GitLab source earns (ADR-0112, extended by ADR-0114).

    Naming the provider is the whole point. "not on the configured GitLab" reads as
    *your URL is wrong*, and for a GitHub project that is false — it sends the operator
    to fix something that isn't broken, at the finish line, after the work is done. This
    is the F64 defect class: the bit that decides whether a project can finish was never
    stated. The refusal itself is unchanged; only its honesty is.

    Since ADR-0114 a GitHub source may be deliverable, so this is reached only when it is
    NOT — and it distinguishes the two reasons, because they have different remedies: the
    instance has no App configured (an admin sets one up once) versus this project's repo has
    no installation (the operator installs the App on that repo).
    """
    if detect_delivery_provider(source, settings.gitlab_url) != "github":
        return "not_gitlab"
    return "github_not_connected" if github_app_configured(settings) else "github_app_unconfigured"


def _composed(compose: MrComposeBody | None, plan: MergeRequestPlan, default_remove: bool) -> dict:
    """Overlay an operator's compose fields onto the assembled-plan defaults (ADR-0103).
    Each field falls back to the default when the operator left it unset."""
    c = compose
    return {
        "title": (c.title or plan.title) if c else plan.title,
        "body": (c.body or plan.body) if c else plan.body,
        "target": (c.target_branch or plan.base) if c and c.target_branch else plan.base,
        "squash": bool(c.squash) if c and c.squash is not None else False,
        "remove": c.remove_source_branch
        if c and c.remove_source_branch is not None
        else default_remove,
        "labels": c.labels if c else None,
    }


def _open_via_rest(
    settings: Settings,
    push_token: str,
    api_token: str,
    gl_project: str,
    workspace: Workspace,
    branch: str,
    fields: dict,
) -> MrOutcome:
    """The faithful path (ADR-0103): push the branch (write_repository), then create — or
    edit an already-open MR — via the REST API with the operator's full multi-line body."""
    plan = MergeRequestPlan(
        title=fields["title"], body=fields["body"], branch=branch, base=fields["target"]
    )
    pushed = open_merge_request(
        workspace.root,
        plan,
        project=gl_project,
        gitlab_url=settings.gitlab_url,
        token=push_token,  # transport stays write_repository — never the api token
        ensure_base=True,
        remove_source_branch=fields["remove"],
        push_only=True,
    )
    if not pushed.pushed:
        return MrOutcome(False, error=pushed.error or "branch push failed")
    # Idempotent: edit an already-open MR for this source branch instead of a duplicate create.
    mrs, _ = glc.list_merge_requests(
        settings.gitlab_url, api_token, gl_project, source_branch=branch
    )
    existing = mrs[0] if isinstance(mrs, list) and mrs and isinstance(mrs[0], dict) else None
    common = dict(
        title=fields["title"],
        description=fields["body"],
        squash=fields["squash"],
        remove_source_branch=fields["remove"],
        labels=fields["labels"],
    )
    if existing and existing.get("iid"):
        data, err = glw.update_merge_request(
            settings.gitlab_url,
            api_token,
            gl_project,
            int(existing["iid"]),
            target_branch=fields["target"],
            **common,
        )
    else:
        data, err = glw.create_merge_request(
            settings.gitlab_url,
            api_token,
            gl_project,
            source_branch=branch,
            target_branch=fields["target"],
            **common,
        )
    if err:
        return MrOutcome(False, error=err)
    url = str((data or {}).get("web_url") or (existing or {}).get("web_url") or "")
    return MrOutcome(True, url=url)


def resolve_mr_url(settings: Settings, api_token: str | None, gl_project: str, branch: str) -> str:
    """Look up an MR's real URL by source branch (read REST) — the fallback for a push
    whose banner carried no URL (ADR-0102 slice O). Empty string when nothing is found;
    callers keep their previous no-URL behavior then.

    This is a REST READ and needs the `api`-scoped token, NOT the `write_repository` push token
    (ADR-0103 §1). Both callers used to pass the push token, so on the common configuration the
    lookup could only ever fail — which is exactly how items ended up recorded with a branch, a
    state of "opened", and no URL: a terminal row the poll skips (no iid to poll) and no action
    can repair. No api token means nothing is askable, so say so by returning empty rather than
    spending a call that cannot succeed.
    """
    if not api_token:
        return ""
    mrs, err = glc.list_merge_requests(
        settings.gitlab_url, api_token, gl_project, source_branch=branch
    )
    if err or not isinstance(mrs, list) or not mrs:
        return ""
    url = mrs[0].get("web_url") if isinstance(mrs[0], dict) else None
    return str(url or "")


def open_project_mr(
    mem: MemoryStore,
    settings: Settings,
    project_id: str,
    compose: MrComposeBody | None = None,
    *,
    allow_github: bool = False,
) -> MrOutcome:
    """Open (or refresh) the merge request for a project's single shared branch, using the
    project's scoped token. Faithful to the manual endpoint's checks; returns a structured
    outcome instead of raising, so both the endpoint and the autonomous sweep can use it.

    ``compose`` (ADR-0103, operator-only) + an api token routes through the REST path for a
    faithful multi-line body / target / squash; absent ⇒ the unchanged push-options path."""
    detail = mem.project_detail(project_id)
    if detail is None:
        return MrOutcome(False, skip="unknown_project")
    source = str(detail["source_repo"])
    if not is_gitlab_source(source, settings.gitlab_url):
        # ADR-0114: a connected GitHub project delivers here instead of being refused. The
        # refusal below still stands for every source that cannot.
        if ghd.is_github_project(settings, detail) and detail.get("has_github_connection"):
            # ENDPOINT-ONLY, and enforced here rather than merely documented (red-team round
            # 3). This function has two callers: the authenticated endpoint, which passes
            # allow_github, and the autonomous sweep's `_maybe_open_project_mr`, which does
            # not. The most-automated, unattended path does not gain a second forge's
            # credentials — the same rule ADR-0103 sets for `gitlab_write.py`. Fails closed:
            # a future caller that forgets the flag gets a skip, not an unattended push.
            if not allow_github:
                return MrOutcome(False, skip="github_endpoint_only")
            opened, url, err, skip = ghd.project_pr_outcome(
                mem, settings, project_id, detail, compose=compose
            )
            if skip:
                return MrOutcome(False, skip=skip)  # type: ignore[arg-type]
            return MrOutcome(opened, url=url, error=err or None)
        return MrOutcome(False, skip=unsupported_source_skip(source, settings))
    # Zero-trust: this project's own scoped token does the push/MR — never a global one.
    token = mem.get_project_token(project_id)
    if not token:
        return MrOutcome(False, skip="no_token")
    gl_project = project_from_source(source)
    if not gl_project:
        return MrOutcome(False, skip="no_project")
    try:
        workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
    except FileNotFoundError:
        return MrOutcome(False, skip="no_clone")
    base, diff = project_diff(workspace)
    if not diff.strip():
        return MrOutcome(False, skip="empty_diff")

    done = [i["title"] for i in detail["backlog"] if i["status"] in ("in_review", "done")]
    report = detail["brief"] or "(no brief)"
    if done:
        report += "\n\n### Delivered\n" + "\n".join(f"- {t}" for t in done)
    plan = assemble_merge_request(detail["name"], project_id, workspace.branch, report, base=base)
    api_token = mem.get_project_api_token(project_id)
    if compose is not None and api_token:  # ADR-0103 faithful REST path (operator only)
        # A2: a commit subset → cherry-pick those onto a fresh branch and open the MR from it.
        # The endpoint holds the project mutex around this (it mutates the shared clone).
        source_branch = workspace.branch
        if compose.commit_shas:
            picked = cherry_pick_into_branch(
                workspace, base, compose.commit_shas, f"mosaera/combined-{project_id}"
            )
            if picked.error:
                return MrOutcome(
                    False,
                    error=f"cherry-pick failed at {picked.conflict_sha or '?'}: {picked.error}",
                )
            source_branch = picked.branch
        outcome = _open_via_rest(
            settings,
            token,
            api_token,
            gl_project,
            workspace,
            source_branch,
            _composed(compose, plan, default_remove=True),
        )
        if outcome.opened:
            # Record the branch the MR ACTUALLY sources from (0029). On the cherry-pick path
            # that is the combined branch, not `workspace.branch` — protection must read this,
            # never re-derive it from the clone's checkout state.
            mem.update_project(
                project_id,
                status="in_review",
                mr_url=(outcome.url or None),
                mr_source=source_branch,
            )
        return outcome
    result = open_merge_request(
        workspace.root,
        plan,
        project=gl_project,
        gitlab_url=settings.gitlab_url,
        token=token,  # the project's own scoped token (write_repository push-options)
        ensure_base=True,  # greenfield: push the base branch if the target repo had none yet
    )
    if not result.opened:
        return MrOutcome(False, error=result.error or "merge request not opened")
    # A re-push of an already-open MR (or a banner with no URL) returns opened=True with an
    # empty url — resolve the REAL URL by source branch (ADR-0102); `or None` still leaves
    # a previously stored mr_url intact when the lookup finds nothing either.
    url = result.url or resolve_mr_url(settings, api_token, gl_project, workspace.branch)
    mem.update_project(
        project_id, status="in_review", mr_url=(url or None), mr_source=workspace.branch
    )
    return MrOutcome(True, url=url)


def _stacked_target(backlog: list[dict], item: dict, base: str) -> str:
    """The branch a just-delivered item's MR should target — its stacked predecessor.

    Linear delivery-order stacking (ADR-0021): the predecessor is the already-delivered
    item (one that has its own branch) with the greatest ``position`` still below this
    item's. Its branch carries all prior work, so targeting it makes this MR's diff show
    *only* this item's change. No earlier delivered item → target the source base.
    """
    prior = [
        i
        for i in backlog
        if i.get("branch")
        and i.get("mr_state") != "merged"  # ADR-0103: a merged predecessor's branch is gone —
        and i["id"] != item["id"]  # target base (or an earlier unmerged item), not a dead branch
        and i["position"] < item["position"]
    ]
    if not prior:
        return base
    return str(max(prior, key=lambda i: i["position"])["branch"])


def open_item_mr(
    mem: MemoryStore,
    settings: Settings,
    project_id: str,
    item_id: int,
    compose: MrComposeBody | None = None,
) -> MrOutcome:
    """Open one stacked merge request for a single delivered backlog item (ADR-0021).

    The item ran on its own branch ``mosaera/item-<id>`` (cut from the predecessor's
    tip); this opens an MR from that branch **targeting the predecessor's branch** (or the
    source base for the first item), so each MR is a small, independently reviewable +
    revertable change. Same zero-trust posture as ``open_project_mr`` — the project's own
    scoped ``write_repository``-only token via push-options, opens never merges — plus
    ``remove_source_branch=False`` so merging one item can't orphan the next's target.
    """
    detail = mem.project_detail(project_id)
    if detail is None:
        return MrOutcome(False, skip="unknown_project")
    source = str(detail["source_repo"])
    if not is_gitlab_source(source, settings.gitlab_url):
        return MrOutcome(False, skip=unsupported_source_skip(source, settings))
    item = next((i for i in detail["backlog"] if i["id"] == item_id), None)
    if item is None:
        return MrOutcome(False, skip="no_item")
    # `branch` is written only here, when the MR opens — so a set branch means "already
    # opened", the idempotency guard even if the URL couldn't be parsed from the banner.
    if item.get("branch"):
        return MrOutcome(False, skip="already_open")
    token = mem.get_project_token(project_id)
    if not token:
        return MrOutcome(False, skip="no_token")
    gl_project = project_from_source(source)
    if not gl_project:
        return MrOutcome(False, skip="no_project")
    try:
        # No reset: the item's run left its own branch checked out with its commits.
        workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
    except FileNotFoundError:
        return MrOutcome(False, skip="no_clone")

    base = project_base(workspace)
    item_branch = f"mosaera/item-{item_id}"
    # The operator's chosen target must be applied BEFORE the empty-diff check, not after.
    # `_stacked_target` answers "what SHOULD a new MR target?", and when its answer is a
    # predecessor branch that already contains this item's commits the diff is empty and the
    # call refuses — permanently. Compose used to be consulted only further down, so picking a
    # different target could not rescue it and the item could never get an MR at all. Same shape
    # as the 0028/0029 defects: a recomputed answer overriding the recorded/chosen one.
    chosen = (compose.target_branch or "").strip() if compose is not None else ""
    if chosen and chosen != base and not chosen.startswith("mosaera/"):
        # The same allowlist retargeting uses (red-team 2026-08-18, finding 3): an item MR is
        # deliberately stacked, and an arbitrary target makes it propose the whole history.
        return MrOutcome(
            False, error=f"an item merge request may only target {base} or a mosaera/* branch"
        )
    target = chosen or _stacked_target(detail["backlog"], item, base)
    diff = project_item_diff(workspace, target)
    if not diff.strip():
        return MrOutcome(False, skip="empty_diff")

    report = f"{item['description'] or item['title']}".strip()
    if item.get("acceptance"):
        report += "\n\n### Acceptance\n" + str(item["acceptance"])
    plan = assemble_merge_request(
        item["title"], f"item-{item_id}", item_branch, report, base=target
    )
    api_token = mem.get_project_api_token(project_id)
    if compose is not None and api_token:  # ADR-0103 faithful REST path (operator only)
        fields = _composed(compose, plan, default_remove=False)  # stacked: keep the source branch
        outcome = _open_via_rest(
            settings, token, api_token, gl_project, workspace, item_branch, fields
        )
        if outcome.opened:
            mem.update_backlog_item(
                item_id,
                branch=item_branch,
                mr_url=(outcome.url or ""),
                mr_state="opened",
                # Record the target the MR was ACTUALLY opened against — the compose may have
                # overridden it. Protection reads this, never a recomputation (0028).
                mr_target=str(fields["target"]),
            )
        return outcome
    result = open_merge_request(
        workspace.root,
        plan,
        project=gl_project,
        gitlab_url=settings.gitlab_url,
        token=token,  # the project's own scoped token (write_repository push-options)
        ensure_base=True,  # push the target branch if the remote lacks it (first item: the base)
        remove_source_branch=False,  # stacked: a later item may target this branch
    )
    if not result.opened:
        return MrOutcome(False, error=result.error or "merge request not opened")
    # Record the item's branch (the idempotency marker) + MR URL so the sweep won't reopen
    # it and the UI can link it. A banner without a parseable URL is resolved to the real
    # URL by source branch (ADR-0102); the branch marker is set either way.
    url = result.url or resolve_mr_url(settings, api_token, gl_project, item_branch)
    mem.update_backlog_item(
        item_id, branch=item_branch, mr_url=(url or ""), mr_state="opened", mr_target=target
    )
    return MrOutcome(True, url=url)


def retarget_item_mr(
    mem: MemoryStore, settings: Settings, project_id: str, item_id: int, target: str
) -> MrOutcome:
    """Repoint an item's ALREADY-OPEN merge request at another branch.

    The recovery path for a stuck MR. Deleting a merged predecessor's branch orphans its
    successor's open MR ("The target branch X does not exist"), and before this nothing in the
    product could fix it: `open_item_mr` refuses with ``already_open`` before reaching the REST
    path, there is no close/reopen endpoint, and the item's MR columns are not patchable. The only
    escape was GitLab's own UI.

    Deliberately NOT routed through ``open_item_mr`` — its ``already_open`` guard is precisely what
    blocks recovery, and this is a different operation: it edits one field of an existing MR and
    never pushes, creates, or merges anything. Narrower than the rebase/amend primitives ADR-0103
    still refuses.
    """
    detail = mem.project_detail(project_id)
    if detail is None:
        return MrOutcome(False, skip="unknown_project")
    item = next((i for i in detail["backlog"] if int(i["id"]) == int(item_id)), None)
    if item is None:
        return MrOutcome(False, skip="no_item")
    mr_url = str(item.get("mr_url") or "")
    match = re.search(r"/merge_requests/(\d+)", mr_url)
    if not match:
        return MrOutcome(False, error="this item has no merge request to retarget")
    source = str(detail["source_repo"])
    if not is_gitlab_source(source, settings.gitlab_url):
        return MrOutcome(False, skip=unsupported_source_skip(source, settings))
    gl_project = project_from_source(source)
    api_token = mem.get_project_api_token(project_id)
    if not (gl_project and api_token):
        # Editing an existing MR is a REST operation; the push token cannot do it (ADR-0103 §1).
        return MrOutcome(False, error="retargeting needs the project's api-scoped token")
    # An item MR is deliberately STACKED — it targets its predecessor so its diff is just this
    # item's change. Repointing it at an arbitrary branch would make it propose the whole stacked
    # history under a small-item title, carrying any approval already on the MR. Recovery only
    # ever needs the project base or another Mosaera branch (red-team 2026-08-18, finding 3).
    try:
        workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        base = project_base(workspace)
    except Exception:
        base = "main"
    if target != base and not target.startswith("mosaera/"):
        return MrOutcome(
            False,
            error=f"a merge request may only be retargeted at {base} or a mosaera/* branch",
        )
    data, err = glw.update_merge_request(
        settings.gitlab_url, api_token, gl_project, int(match.group(1)), target_branch=target
    )
    if err:
        return MrOutcome(False, error=err)
    mem.update_backlog_item(int(item_id), mr_target=target)
    url = str((data or {}).get("web_url") or mr_url)
    return MrOutcome(True, url=url)
