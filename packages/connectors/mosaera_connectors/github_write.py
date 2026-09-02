"""GitHub REST calls made with an installation token — pull request create + read (ADR-0114).

The GitLab side splits reads (``gitlab_client.py``) from writes (``gitlab_write.py``) because
they need different token scopes, and an operator should be able to tell at a glance which
credential a surface spends. GitHub has no such split to mirror: one installation token
carries both, scoped by *permission* rather than by scope string. So this is one module, and
the honest thing is to say why rather than mirror a division that would mean nothing here.

Every call is authenticated by an installation token minted moments earlier by
``github_app.mint_installation_token`` — never by the App JWT, which identifies the App and
must not be handed to a repository operation.

Same defensive shape as its GitLab counterparts: bounded timeout, returns ``(data, error)``,
never raises into the request, credentials scrubbed from any error text.
"""

from __future__ import annotations

import re
from typing import Any

from mosaera_connectors.github_app import _api

# A GitHub PR web URL ends in `/pull/<n>`; GitLab's ends in `/-/merge_requests/<n>`. The two
# never overlap, which is why the existing GitLab regexes stay untouched.
_PR_URL_RE = re.compile(r"/pull/(\d+)")


def pr_number_from_url(url: str) -> int | None:
    """The PR number in a GitHub pull-request URL, or None."""
    match = _PR_URL_RE.search(url or "")
    return int(match.group(1)) if match else None


def create_pull_request(
    api_base: str,
    token: str,
    owner_repo: str,
    *,
    head: str,
    base: str,
    title: str,
    body: str,
    draft: bool = True,
) -> tuple[Any, str | None]:
    """Open a pull request. Returns the created PR JSON (``html_url``, ``number``) or an error.

    ``draft`` defaults true — delivery opens something a human reviews, never something that
    looks ready to merge. Note GitHub refuses draft PRs on PRIVATE repositories under Free
    plans; ADR-0114 scopes this path to public repositories, so that restriction is out of
    reach here rather than silently downgraded.
    """
    return _api(
        "POST",
        api_base,
        token,
        f"repos/{owner_repo}/pulls",
        {"head": head, "base": base, "title": title, "body": body, "draft": draft},
    )


def get_pull_request(
    api_base: str, token: str, owner_repo: str, number: int
) -> tuple[Any, str | None]:
    """Read one pull request — the poll's source of truth for state."""
    return _api("GET", api_base, token, f"repos/{owner_repo}/pulls/{number}")


def list_pull_requests(
    api_base: str, token: str, owner_repo: str, *, head_branch: str, state: str = "open"
) -> tuple[Any, str | None]:
    """Pull requests opened FROM ``head_branch``.

    Two jobs, both of which the GitLab path also needs: recovering a PR whose URL we failed to
    record (the ``resolve_mr_url`` analogue), and making the open idempotent — a second Open
    press should find the existing PR rather than 422 on a duplicate.

    GitHub wants ``head`` qualified as ``owner:branch``; the owner is taken from ``owner_repo``
    so the caller cannot get the two out of step.
    """
    owner = owner_repo.split("/", 1)[0]
    path = f"repos/{owner_repo}/pulls?head={owner}:{head_branch}&state={state}"
    return _api("GET", api_base, token, path)


def pull_request_state(pr: dict[str, Any]) -> str:
    """GitHub's PR state expressed in the vocabulary the store already uses.

    The mapping is written out rather than inferred because the two forges disagree in a way
    that is easy to get wrong: GitLab has a single ``state`` that can be ``merged``, while
    GitHub reports ``state: closed`` for a merged PR and distinguishes it only by a separate
    ``merged`` boolean. Reading ``state`` alone would record every merged PR as closed — the
    project would never reach Delivered, which is the exact failure this slice exists to fix.
    """
    if bool(pr.get("merged")):
        return "merged"
    return "opened" if str(pr.get("state") or "") == "open" else "closed"


def create_public_repo(
    api_base: str, user_token: str, name: str, *, description: str = ""
) -> tuple[dict[str, Any] | None, str | None]:
    """Create a PUBLIC repository on the authenticated user's account (ADR-0120).

    Authenticated by a **user** token, not an installation token — GitHub's repository-creation
    endpoints do not accept the latter (`github_app.exchange_user_code` explains why).

    ``private`` is hardcoded ``False`` and is not a parameter, which is the honest shape for what
    Mosaera can currently deliver: `clone.py::_auth_url` injects a credential only for the
    configured GitLab host, so a private GitHub repository cannot be cloned and its runs would
    never start. Offering a visibility toggle would let an operator create a repository this
    system then cannot use. Private support is a later slice that has to extend the clone
    credential path first — until then the limit is enforced here rather than described in a doc.

    ``auto_init`` is False: Mosaera pushes the project's own history, and an auto-created README
    would put an unrelated root commit in front of it.
    """
    return _api(
        "POST",
        api_base,
        user_token,
        "user/repos",
        {"name": name, "private": False, "auto_init": False, "description": description},
    )
