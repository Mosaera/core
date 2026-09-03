"""GitHub delivery — resolve the installation, push, open the PR, read it back (ADR-0114).

A sibling of ``delivery.py`` rather than a branch inside it: that module is at its god-file
ceiling, and the two forges share an outcome type (``MrOutcome``) but almost no mechanics.

Three properties this module is responsible for, each of which has a test:

* **The installation is re-resolved, never trusted.** ``projects.github_installation_id`` is a
  cache of a fact GitHub owns. Reporting a stored id as a working connection would be the
  second-origin defect; ``_resolve_installation`` asks GitHub whenever the stored id is absent
  or stops working, and rewrites it.
* **The token is minted per delivery, scoped to one repo.** It lives an hour, so minting at
  connect time and storing it would hand out a credential that is usually already dead.
* **Endpoint-only.** Nothing here is reachable from the autonomous sweep, mirroring ADR-0103's
  rule that the unattended path never touches ``gitlab_write.py``. The sweep calls
  ``delivery.open_project_mr``, which refuses a GitHub source before reaching this module.

ADR-0102's spine is untouched: opening a PR is not graph-gated, and the human control is the
authenticated endpoint. A human still opens, and a human still merges — nothing here merges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mosaera_connectors import assemble_pull_request, push_branch
from mosaera_connectors import github_app as gapp
from mosaera_connectors import github_write as gwrite
from mosaera_connectors.provider import detect_delivery_provider
from mosaera_core.config import Settings
from mosaera_core.tools.repo import open_project_workspace, project_diff
from mosaera_memory import MemoryStore

if TYPE_CHECKING:
    from mosaera_api.schemas import MrComposeBody


@dataclass(frozen=True)
class GitHubAccess:
    """A minted, ready-to-spend credential for one project's repository."""

    owner_repo: str
    token: str
    installation_id: int


def owner_repo_from_source(source_url: str) -> str | None:
    """``owner/repo`` from a GitHub source URL, or None.

    Only ever called after ``detect_delivery_provider`` has already established the host is
    github.com by EQUALITY, so this parses a path it has been told to trust — it is not itself
    a trust decision, and must not be used as one.
    """
    url = (source_url or "").strip()
    if url.startswith(("http://", "https://")):
        path = url.split("://", 1)[1].split("/", 1)[-1] if "/" in url.split("://", 1)[1] else ""
    elif "@" in url and ":" in url:
        path = url.split(":", 1)[1]
    else:
        return None
    parts = [p for p in path.strip("/").removesuffix(".git").split("/") if p]
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None


def app_configured(settings: Settings) -> bool:
    return bool(settings.github_app_id and settings.github_app_private_key)


def install_url(settings: Settings) -> str:
    """Where the operator installs the App. Empty when no slug is configured."""
    slug = (settings.github_app_slug or "").strip()
    return f"https://github.com/apps/{slug}/installations/new" if slug else ""


def list_installations(settings: Settings) -> tuple[list[dict], str | None]:
    """Where this App is installed — for the Git settings panel, never for delivery.

    Read-only and spends nothing: delivery continues to resolve its installation from the
    project's own ``source_repo`` (``resolve_installation``), which is the property that makes
    a forged id useless. This exists so the not-installed case reads as a next step instead of
    an error at the finish line.
    """
    try:
        jwt = gapp.app_jwt(str(settings.github_app_id), str(settings.github_app_private_key))
    except ValueError as exc:
        return [], str(exc)
    return gapp.list_installations(settings.github_api_url, jwt)


def resolve_installation(
    mem: MemoryStore, settings: Settings, project_id: str, owner_repo: str
) -> tuple[int | None, str | None]:
    """Which installation can reach ``owner_repo`` — always asked of GitHub, then cached.

    **It never short-circuits on the stored id, and that is deliberate** (red-team round 1).
    The id is cached against a project, but the thing it must match is the project's CURRENT
    `source_repo`, and those can diverge: change a project's source from ``acme/widget`` to
    ``other/widget`` and a cached lookup would mint against ``acme``'s installation scoped to
    a repository named ``widget`` — i.e. a credential for the WRONG repository, which is then
    sent to the new repo's push URL. Nothing is written across repositories (the push is
    rejected), but minting a credential for a repository nobody asked about is not a state to
    reason about later.

    So the stored id is what it claims to be: a record that a resolution once succeeded, read
    by the UI as a presence bit and never spent as proof. Delivery is human-initiated and
    infrequent; one extra GET is the right price for the class going away.
    """
    try:
        jwt = gapp.app_jwt(str(settings.github_app_id), str(settings.github_app_private_key))
    except ValueError as exc:
        return None, str(exc)
    ident, err = gapp.installation_for_repo(settings.github_api_url, jwt, owner_repo)
    if ident is None:
        return None, err
    mem.update_project(project_id, github_installation_id=str(ident))
    return ident, None


def access_for(
    mem: MemoryStore, settings: Settings, project_id: str, detail: dict
) -> tuple[GitHubAccess | None, str | None]:
    """Mint a fresh, repo-scoped installation token for this project's delivery.

    The installation is resolved from the project's CURRENT ``source_repo`` on every call —
    see ``resolve_installation`` for why the cached id is never spent. A revoked or moved
    installation therefore surfaces as "not installed on this repository", which is both true
    and actionable, rather than as an inexplicable mint failure.
    """
    source = str(detail.get("source_repo") or "")
    owner_repo = owner_repo_from_source(source)
    if not owner_repo:
        return None, "could not derive owner/repo from the project source"
    ident, err = resolve_installation(mem, settings, project_id, owner_repo)
    if ident is None:
        return None, err
    try:
        jwt = gapp.app_jwt(str(settings.github_app_id), str(settings.github_app_private_key))
    except ValueError as exc:
        return None, str(exc)
    # Scoped to the bare repo name WITHIN the installation just resolved for this exact
    # owner/repo, so the pair cannot drift apart.
    repo = owner_repo.split("/", 1)[1]
    token, err = gapp.mint_installation_token(settings.github_api_url, jwt, ident, repo=repo)
    if token is None:
        return None, err
    return GitHubAccess(owner_repo=owner_repo, token=token, installation_id=ident), None


def is_github_project(settings: Settings, detail: dict) -> bool:
    source = str(detail.get("source_repo") or "")
    return detect_delivery_provider(source, settings.gitlab_url) == "github"


def open_github_pr(
    mem: MemoryStore,
    settings: Settings,
    project_id: str,
    detail: dict,
    *,
    branch: str,
    base: str,
    title: str,
    body: str,
    workspace_root: object,
    ensure_base: bool = True,
) -> tuple[bool, str, str]:
    """Push ``branch`` and open (or find) its draft pull request.

    Returns ``(opened, url, error)``. Idempotent by design: a second press finds the PR already
    open from this head instead of a 422 on a duplicate — the same property the GitLab REST
    path gets from listing merge requests by source branch.
    """
    access, err = access_for(mem, settings, project_id, detail)
    if access is None:
        return False, "", err or "no GitHub access"

    pushed = push_branch(
        workspace_root,  # type: ignore[arg-type]
        owner_repo=access.owner_repo,
        branch=branch,
        base=base,
        token=access.token,
        ensure_base=ensure_base,
    )
    if not pushed.pushed:
        return False, "", pushed.error or "branch push failed"

    existing, _ = gwrite.list_pull_requests(
        settings.github_api_url, access.token, access.owner_repo, head_branch=branch
    )
    if isinstance(existing, list) and existing and isinstance(existing[0], dict):
        found = existing[0]
        # S3: an existing PR used to end the call here, silently dropping any title/body/base
        # the operator had just composed — the same discard GitLab's REST path avoids by
        # unconditionally patching the existing MR (see `_open_via_rest` in delivery.py).
        # `base` here already carries the caller's compose-target overlay (see
        # `project_pr_outcome` below), so patching it too keeps a re-targeted compose from
        # silently landing against the stale base of a PR opened before the retarget.
        number = found.get("number")
        patch_err: str | None = None
        if isinstance(number, int) and (title or body or base):
            _, patch_err = gwrite.update_pull_request(
                settings.github_api_url,
                access.token,
                access.owner_repo,
                number,
                title=title or None,
                body=body or None,
                base=base or None,
            )
        # The PR still exists and its URL is still valid even if the patch failed, so `opened`
        # stays True — but a swallowed patch error is the same silent discard one layer down,
        # so it rides back in `err` instead of the empty string a bare success would return.
        return True, str(found.get("html_url") or ""), (patch_err or "")

    data, err = gwrite.create_pull_request(
        settings.github_api_url,
        access.token,
        access.owner_repo,
        head=branch,
        base=base,
        title=title,
        body=body,
    )
    if err:
        return False, "", err
    return True, str((data or {}).get("html_url") or ""), ""


def project_pr_outcome(
    mem: MemoryStore,
    settings: Settings,
    project_id: str,
    detail: dict,
    *,
    compose: MrComposeBody | None = None,
) -> tuple[bool, str, str, str]:
    """The project-level "open one combined pull request" path.

    Returns ``(opened, url, error, skip)`` — the caller maps it onto ``MrOutcome`` so both
    forges answer in one vocabulary.

    ``compose`` (ADR-0103's operator edit, mirrored here) overlays the assembled title/body —
    the GitHub REST create call always carries the caller's credential (an installation token,
    never a push-option), so unlike the GitLab push-options degradation there is no path on
    which an operator's edit is silently dropped; before this the endpoint accepted a
    ``compose`` body and threw it away (S3).

    Scope, stated because its absence would otherwise look like a bug: PER-ITEM pull requests
    are not offered for GitHub in this slice. GitLab's item MRs are *stacked* — each targets
    its predecessor via ``_stacked_target`` — and reproducing that on a second forge is a
    behaviour worth its own slice rather than a hurried copy. The capability record says so,
    and the page withholds the per-item control instead of offering one that would fail.
    """
    try:
        workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
    except FileNotFoundError:
        return False, "", "", "no_clone"
    base, diff = project_diff(workspace)
    if not diff.strip():
        return False, "", "", "empty_diff"

    done = [i["title"] for i in detail.get("backlog", []) if i["status"] in ("in_review", "done")]
    report = detail.get("brief") or "(no brief)"
    if done:
        report += "\n\n### Delivered\n" + "\n".join(f"- {t}" for t in done)
    # The SAME assembly the GitLab path and the CLI use (`_shared.request_title/body`), so a
    # pull request and a merge request are byte-identical for the same run.
    plan = assemble_pull_request(
        str(detail.get("name") or ""), project_id, workspace.branch, report, base=base
    )
    title = (compose.title if compose and compose.title else None) or plan.title
    body = (compose.body if compose and compose.body else None) or plan.body
    # The diff (and the empty-diff refusal above) stays pinned to the DETECTED base — only the
    # PR's actual base branch follows the operator's choice, same split the GitLab REST path
    # makes in `_composed()`. Leaving this unread was the other half of S3: the target-branch
    # picker in the compose sheet looked live for a GitHub project but changed nothing.
    target = (compose.target_branch if compose and compose.target_branch else None) or base
    opened, url, err = open_github_pr(
        mem,
        settings,
        project_id,
        detail,
        branch=workspace.branch,
        base=target,
        title=title,
        body=body,
        workspace_root=workspace.root,
    )
    if opened:
        mem.update_project(
            project_id, status="in_review", mr_url=(url or None), mr_source=workspace.branch
        )
    return opened, url, err, ""


def read_pr_state(
    mem: MemoryStore, settings: Settings, project_id: str, detail: dict, pr_url: str
) -> tuple[str | None, str | None]:
    """The current state of the PR at ``pr_url``, in the store's own vocabulary.

    Returns ``(state, error)`` where state is ``opened``/``closed``/``merged``. ``(None, None)``
    means the URL carried no PR number — nothing to ask, so nothing is claimed.
    """
    number = gwrite.pr_number_from_url(pr_url)
    if number is None:
        return None, None
    access, err = access_for(mem, settings, project_id, detail)
    if access is None:
        return None, err
    data, err = gwrite.get_pull_request(
        settings.github_api_url, access.token, access.owner_repo, number
    )
    if err or not isinstance(data, dict):
        return None, err or "unreadable pull request"
    return gwrite.pull_request_state(data), None
