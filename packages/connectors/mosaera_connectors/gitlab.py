"""GitLab MR flow: push the branch and open a merge request via git push-options.

Push uses a one-off token URL (the token is never written to the clone's git
config), and the MR is created with ``-o merge_request.create`` push options so
the token needs only ``write_repository`` — no ``api`` scope. Opening an MR is
authorized by the caller's own control (ADR-0102): the authenticated API endpoint
for a human, or the explicit ``auto_open_mr`` opt-in for the sweep — it is NOT a
graph-gated action. ``dry_run`` returns the planned push command without
executing it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from mosaera_connectors._shared import host_of, request_body, request_title
from mosaera_connectors.redact import scrub_credentials

_DESC_MAX = 800
_MR_URL_RE = re.compile(r"https?://\S+?/-/merge_requests/\d+")


@dataclass(frozen=True)
class MergeRequestPlan:
    title: str
    body: str
    branch: str
    base: str


@dataclass(frozen=True)
class MergeRequestResult:
    opened: bool
    url: str = ""
    dry_run: bool = False
    push_cmd: list[str] = field(default_factory=list)
    mr_endpoint: str = ""
    error: str = ""
    # `push_only` success: the branch was pushed but NO MR was opened via push-options —
    # the caller opens it via the REST API instead (ADR-0103). Distinct from `opened`.
    pushed: bool = False


def project_from_source(source_url: str) -> str | None:
    """Derive the GitLab project path (``group/name``) from a repo URL, or None.

    Handles https and scp-style (``git@host:group/name.git``) URLs.
    """
    url = source_url.strip()
    if url.startswith(("http://", "https://")):
        path = urllib.parse.urlparse(url).path
    elif "@" in url and ":" in url:
        path = url.split(":", 1)[1]
    else:
        path = url
    path = path.strip("/").removesuffix(".git")
    return path or None


# The host parser moved to ``_shared`` when provider detection needed the same parse
# (ADR-0112). Kept under the old private name so this module's callers and the prose
# below still read as they did; there is exactly one implementation.
_host_of = host_of


def is_gitlab_source(source_url: str, gitlab_url: str) -> bool:
    """Whether ``source_url`` lives on the configured GitLab.

    Host EQUALITY, not the old substring test: ``host in source_url`` let a look-alike host
    (``gitlab.example.com.evil.io``, or ``…/gitlab.example.com/…`` in the path) match, so
    ``check_repo_access`` would inject the scoped PAT into an attacker-chosen host and
    ``git ls-remote`` it — leaking the token off-box. Equality closes that; scp/ssh sources
    still resolve correctly via ``_host_of``."""
    host = _host_of(gitlab_url)
    return bool(host) and _host_of(source_url) == host


def assemble_merge_request(
    task: str, run_id: str, branch: str, report_text: str, base: str = "main"
) -> MergeRequestPlan:
    return MergeRequestPlan(
        title=request_title(task),
        body=request_body(task, run_id, branch, report_text),
        branch=branch,
        base=base,
    )


def _push_url(gitlab_url: str, project: str, token: str) -> str:
    host = urllib.parse.urlparse(gitlab_url).netloc
    scheme = urllib.parse.urlparse(gitlab_url).scheme or "https"
    return f"{scheme}://oauth2:{token}@{host}/{project}.git"


def delete_remote_branch(
    workspace_root: Path, branch: str, *, project: str, gitlab_url: str, token: str
) -> str | None:
    """Delete a branch on the remote via ``git push --delete`` (ADR-0103) — rides the
    ``write_repository`` token, no ``api`` scope. Returns None on success, else a scrubbed
    error. Bounded; a wedged push returns an error rather than hanging the endpoint."""
    git = shutil.which("git") or "git"
    push_url = _push_url(gitlab_url, project, token)
    try:
        result = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
            [git, "push", push_url, "--delete", branch],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "git push --delete timed out"
    if result.returncode != 0:
        return scrub_credentials(result.stderr.strip())[:200] or "branch delete failed"
    return None


_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def inject_repo_token(source: str, token: str) -> str:
    """Inject ``oauth2:<token>@`` into a repo URL's netloc — but ONLY over https, or over http to
    a LOOPBACK host (local dev). A PAT in a cleartext http URL to a NETWORKED host rides
    MITM-capturable Basic-auth, so a plain-http networked source is returned UNCHANGED (ADR-0042).
    Non-http or tokenless sources are unchanged. This is the SINGLE scheme-safe injection sink
    shared by the clone path and the ls-remote check (finding M-1 unified the two divergent
    copies); HOST trust is the caller's job (``is_gitlab_source``)."""
    if not token:
        return source
    parts = urllib.parse.urlparse(source)
    if not parts.netloc:
        return source
    is_loopback_http = parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTNAMES
    if parts.scheme == "https" or is_loopback_http:
        return f"{parts.scheme}://oauth2:{token}@{parts.netloc}{parts.path}"
    return source  # http to a networked host → don't put the PAT on the wire in cleartext


def _auth_source_url(source: str, token: str) -> str:
    """Token-auth a source URL for the ls-remote check — scheme-guarded via the shared sink."""
    return inject_repo_token(source, token)


def check_repo_access(source: str, token: str) -> str | None:
    """Verify a scoped token can reach ``source`` (``git ls-remote``). Returns an
    error string, or None on success. Used to fail fast on a bad project token."""
    git = shutil.which("git") or "git"
    try:
        result = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
            [git, "ls-remote", "--heads", _auth_source_url(source, token)],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        # Honor the contract (return an error string, never raise) — a hung
        # ls-remote must not 500 the create-project request.
        return "timed out reaching the repository"
    except OSError as exc:  # git binary missing / unusable
        return scrub_credentials(str(exc))[:200] or "cannot run git"
    if result.returncode == 0:
        return None
    return (
        scrub_credentials(result.stderr.strip())[:200] or "cannot access repository with this token"
    )


def open_merge_request(
    workspace_root: Path,
    plan: MergeRequestPlan,
    *,
    project: str,
    gitlab_url: str,
    token: str,
    remote: str = "origin",
    ensure_base: bool = False,
    remove_source_branch: bool = True,
    dry_run: bool = False,
    push_only: bool = False,
) -> MergeRequestResult:
    """Push the branch and open an MR **via git push-options** — so the token needs
    only ``write_repository`` (no ``api`` scope). Authorization is the caller's
    (ADR-0102): an authenticated endpoint or the ``auto_open_mr`` opt-in.

    ``ensure_base`` pushes the base branch first when it's missing on the remote (a
    greenfield project whose target repo was empty), so the MR has a target.

    ``remove_source_branch`` (default True) sets the MR to delete its source branch on
    merge. It MUST be False for a **stacked** MR whose target is another MR's source
    branch — merging the target would otherwise delete a branch a later MR still points
    at, orphaning it (see the per-item stacked-MR model, ADR-0021).

    ``push_only`` (ADR-0103) pushes the branch WITHOUT the ``merge_request.*`` push-options
    and returns ``pushed=True`` — the caller then opens the MR via the REST API with a
    faithful multi-line body. Everything else (ensure_base, timeouts) is identical.
    """
    opts: list[str] = []
    if not push_only:
        opts = [
            "-o",
            "merge_request.create",
            "-o",
            f"merge_request.target={plan.base}",
            "-o",
            f"merge_request.title={plan.title}",
        ]
        if remove_source_branch:
            opts += ["-o", "merge_request.remove_source_branch"]
        # Push options can't contain newlines — collapse whitespace to a single line
        # (the full brief lives in the repo/commit history anyway).
        description = " ".join(plan.body.split())[:_DESC_MAX]
        if description:
            opts += ["-o", f"merge_request.description={description}"]

    remote_repo = f"{gitlab_url}/{project}.git"
    push_cmd_display = ["git", "push", remote_repo, plan.branch, *opts]
    if ensure_base:
        push_cmd_display = [
            "git",
            "push",
            remote_repo,
            f"{plan.base}:{plan.base} (if missing)",
            plan.branch,
            *opts,
        ]
    if dry_run:
        return MergeRequestResult(
            opened=False, dry_run=True, push_cmd=push_cmd_display, mr_endpoint="(push-options)"
        )

    git = shutil.which("git") or "git"
    push_url = _push_url(gitlab_url, project, token)
    # Every network call is bounded: a wedged push must not hang the delivery
    # endpoint's thread forever — return opened=False on timeout instead.
    try:
        if ensure_base:
            existing = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
                [git, "ls-remote", "--heads", push_url, plan.base],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if existing.returncode == 0 and not existing.stdout.strip():
                base_push = subprocess.run(  # noqa: S603 — full path; no shell
                    [git, "push", push_url, f"{plan.base}:{plan.base}"],
                    cwd=workspace_root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if base_push.returncode != 0:
                    return MergeRequestResult(
                        opened=False,
                        push_cmd=push_cmd_display,
                        error=f"base push failed: {scrub_credentials(base_push.stderr.strip())}",
                    )

        push = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
            [git, "push", push_url, plan.branch, *opts],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return MergeRequestResult(
            opened=False, push_cmd=push_cmd_display, error="git push timed out"
        )
    if push.returncode != 0:
        return MergeRequestResult(
            opened=False, push_cmd=push_cmd_display, error=scrub_credentials(push.stderr.strip())
        )
    if push_only:
        # Branch pushed; the caller opens the MR via REST (ADR-0103). No URL to scrape.
        return MergeRequestResult(opened=False, pushed=True, push_cmd=push_cmd_display)
    # GitLab prints the MR URL on stderr ("View merge request for <branch>: <url>").
    match = _MR_URL_RE.search(push.stderr) or _MR_URL_RE.search(push.stdout)
    return MergeRequestResult(
        opened=True, url=match.group(0) if match else "", push_cmd=push_cmd_display
    )
