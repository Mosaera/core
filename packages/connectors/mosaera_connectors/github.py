"""GitHub PR flow — two callers, two transports, deliberately not merged.

``open_pull_request`` is the **CLI** path (ADR-0001): it shells out to ``gh``, honoring
whatever auth the operator's machine already has, and its authorizing control is the CLI's
interactive confirm (ADR-0102). It has no API/web caller and gains none here.

``push_branch`` is the **server** path (ADR-0114): git transport authenticated by a
short-lived GitHub App installation token, with the pull request itself opened over REST in
``github_write.py``. It is the direct analogue of ``gitlab.open_merge_request(push_only=True)``
— the seam ADR-0102 named for a future GitHub port.

They stay separate on purpose. ADR-0112 §5 anticipated hardening the ``gh`` path for a server
caller; the server never got one, because a subprocess that can hang has no business inside a
request and ambient CLI auth is a host-global credential where a project-scoped one belongs.

The ``dry_run`` mode on both returns the exact commands without running them, so the wiring is
verifiable without a live GitHub remote.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from mosaera_connectors._shared import push_repository_to, request_body, request_title
from mosaera_connectors.redact import scrub_credentials

# Bounded like every GitLab counterpart (gitlab.py uses 25/60/120). The CLI path predates this
# and runs attended; the server path must never occupy a worker indefinitely.
_LS_TIMEOUT = 60
_PUSH_TIMEOUT = 120


@dataclass(frozen=True)
class PullRequestPlan:
    title: str
    body: str
    branch: str
    base: str
    draft: bool


@dataclass(frozen=True)
class GitHubPRResult:
    opened: bool
    url: str = ""
    dry_run: bool = False
    commands: list[list[str]] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class GitHubPushResult:
    """The outcome of the server-path branch push (ADR-0114).

    ``pushed`` rather than ``opened``: this half only puts the branch on the remote, and the
    pull request is opened over REST afterwards — the same division ``MergeRequestResult.pushed``
    draws for GitLab's ``push_only`` path.

    ``push_cmd`` is a DISPLAY command built from the tokenless URL. The credentialed URL exists
    only inside the argv actually executed and never reaches this object.
    """

    pushed: bool
    dry_run: bool = False
    push_cmd: list[str] = field(default_factory=list)
    error: str = ""


def push_url(owner_repo: str, token: str, *, host: str = "github.com") -> str:
    """The credentialed push URL: ``https://x-access-token:<token>@github.com/owner/repo.git``.

    ``x-access-token`` is the literal username GitHub requires for an installation token, and
    this exact shape is already what ``redact.scrub_credentials`` was written to strip.

    The token is percent-encoded: it lands in the userinfo component, and an unescaped ``/``
    or ``@`` there would silently retarget the push at a different host — the same class of
    defect host-equality checking exists to prevent, one layer down.
    """
    return f"https://x-access-token:{urllib.parse.quote(token, safe='')}@{host}/{owner_repo}.git"


def assemble_pull_request(
    task: str,
    run_id: str,
    branch: str,
    report_text: str,
    base: str = "main",
    draft: bool = True,
) -> PullRequestPlan:
    """Build the PR title and body for a completed run."""
    return PullRequestPlan(
        title=request_title(task),
        body=request_body(task, run_id, branch, report_text),
        branch=branch,
        base=base,
        draft=draft,
    )


def gh_available(gh_bin: str = "gh") -> bool:
    return shutil.which(gh_bin) is not None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — argv list, no shell
        cmd, cwd=cwd, capture_output=True, text=True
    )


def open_pull_request(
    workspace_root: Path,
    plan: PullRequestPlan,
    *,
    remote: str = "origin",
    gh_bin: str = "gh",
    dry_run: bool = False,
) -> GitHubPRResult:
    """Push the branch and open a draft PR. Returns the commands run (or planned).

    Authorization is the caller's (ADR-0102) — the CLI confirms interactively
    before calling this with ``dry_run=False``.
    """
    push_cmd = ["git", "push", "-u", remote, plan.branch]
    gh_cmd = [
        gh_bin,
        "pr",
        "create",
        "--base",
        plan.base,
        "--head",
        plan.branch,
        "--title",
        plan.title,
        "--body",
        plan.body,
    ]
    if plan.draft:
        gh_cmd.append("--draft")
    commands = [push_cmd, gh_cmd]

    if dry_run:
        return GitHubPRResult(opened=False, dry_run=True, commands=commands)
    if not gh_available(gh_bin):
        return GitHubPRResult(opened=False, commands=commands, error=f"{gh_bin} not found on PATH")

    push = _run(push_cmd, workspace_root)
    if push.returncode != 0:
        return GitHubPRResult(
            opened=False, commands=commands, error=scrub_credentials(push.stderr.strip())
        )
    created = _run(gh_cmd, workspace_root)
    if created.returncode != 0:
        return GitHubPRResult(
            opened=False, commands=commands, error=scrub_credentials(created.stderr.strip())
        )
    return GitHubPRResult(opened=True, url=created.stdout.strip(), commands=commands)


def push_branch(
    workspace_root: Path,
    *,
    owner_repo: str,
    branch: str,
    base: str,
    token: str,
    host: str = "github.com",
    ensure_base: bool = False,
    dry_run: bool = False,
) -> GitHubPushResult:
    """Push ``branch`` to the GitHub remote with an installation token (ADR-0114).

    The direct analogue of ``gitlab.open_merge_request(push_only=True)``, and deliberately a
    copy of its hygiene rather than a fresh implementation — each of these was learned the
    hard way on the GitLab side:

    * the credentialed URL is built separately from ``push_cmd_display``, so the token cannot
      reach a returned object, a log line, or an exception message;
    * every subprocess is bounded, because an unbounded one holds a request worker forever;
    * ``git`` is resolved through ``shutil.which``;
    * stderr is scrubbed AND capped before it becomes an error string.

    ``ensure_base`` pushes the base branch first when the remote lacks it — the greenfield
    case, where the target repository is empty and a PR would have nothing to target.

    The clone's ``origin`` is deliberately tokenless (``clone.py`` resets it after cloning),
    which is exactly why the URL is passed explicitly here instead of pushing to ``origin``.
    """
    display_remote = f"https://{host}/{owner_repo}.git"
    push_cmd_display = ["git", "push", display_remote, branch]
    if ensure_base:
        push_cmd_display = ["git", "push", display_remote, f"{base}:{base} (if missing)", branch]
    if dry_run:
        return GitHubPushResult(pushed=False, dry_run=True, push_cmd=push_cmd_display)

    git = shutil.which("git") or "git"
    url = push_url(owner_repo, token, host=host)
    try:
        if ensure_base:
            existing = subprocess.run(  # noqa: S603 — argv list, no shell
                [git, "ls-remote", "--heads", url, base],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=_LS_TIMEOUT,
            )
            if existing.returncode == 0 and not existing.stdout.strip():
                base_push = subprocess.run(  # noqa: S603 — argv list, no shell
                    [git, "push", url, f"{base}:{base}"],
                    cwd=workspace_root,
                    capture_output=True,
                    text=True,
                    timeout=_PUSH_TIMEOUT,
                )
                if base_push.returncode != 0:
                    return GitHubPushResult(
                        pushed=False,
                        push_cmd=push_cmd_display,
                        error=f"base push failed: "
                        f"{scrub_credentials(base_push.stderr.strip())[:200]}",
                    )
        push = subprocess.run(  # noqa: S603 — argv list, no shell
            [git, "push", url, branch],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=_PUSH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return GitHubPushResult(pushed=False, push_cmd=push_cmd_display, error="git push timed out")
    except OSError as exc:
        return GitHubPushResult(
            pushed=False, push_cmd=push_cmd_display, error=scrub_credentials(str(exc))[:200]
        )
    if push.returncode != 0:
        return GitHubPushResult(
            pushed=False,
            push_cmd=push_cmd_display,
            error=scrub_credentials(push.stderr.strip())[:200],
        )
    return GitHubPushResult(pushed=True, push_cmd=push_cmd_display)


def push_existing_repository(
    source_path: Path, *, owner_repo: str, token: str, host: str = "github.com"
) -> tuple[str | None, str | None]:
    """Push a project's existing history into a repository just created for it (ADR-0120 A1).

    The GitHub spelling of the credentialed URL; the push itself is `_shared.push_repository_to`,
    shared with GitLab. The two forges differ only in how the credential goes into the URL
    (``x-access-token:`` here, ``oauth2:`` there), and a second copy of the hygiene is how one
    of them quietly loses a protection the other has.
    """
    return push_repository_to(source_path, push_url(owner_repo, token, host=host))
