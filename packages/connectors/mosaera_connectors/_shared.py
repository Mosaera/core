"""Shared PR/MR assembly + repo-URL helpers (GitHub + GitLab connectors).

The GitHub PR and GitLab MR flows build an identical title and body from a
completed run; kept here so the two connectors can't drift apart.

``host_of`` lives here for the same reason. It began as ``gitlab._host_of``, the
parser behind ``is_gitlab_source``'s host-EQUALITY test; provider detection needs
exactly the same parse, and a second copy is how a look-alike-host defect comes
back (see ``gitlab.is_gitlab_source`` for what the equality test prevents).
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.parse
from pathlib import Path

from mosaera_connectors.redact import scrub_credentials

_HEAD_TIMEOUT = 60
_PUSH_TIMEOUT = 120
TITLE_MAX = 72


def host_of(url: str) -> str:
    """The bare host of a repo URL — lowercased, without userinfo or port. Handles both
    ``https://[user@]host[:port]/g/r.git`` and scp-style ``git@host:g/r.git`` (which
    ``urlparse`` leaves with an empty netloc, so it must be parsed by hand)."""
    u = url.strip()
    if u.startswith(("http://", "https://", "ssh://")):
        netloc = urllib.parse.urlparse(u).netloc
    elif "@" in u and ":" in u and "://" not in u:
        # scp-style: git@host:group/name.git → the segment between '@' and ':'.
        netloc = u.split("@", 1)[1].split(":", 1)[0]
    else:
        netloc = urllib.parse.urlparse(u if "://" in u else f"//{u}", scheme="").netloc
    host = netloc.rsplit("@", 1)[-1]  # strip any remaining userinfo
    host = host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") else host  # strip port
    return host.strip("[]").lower()  # strip IPv6 brackets, normalize case


def first_line(text: str) -> str:
    """The first non-empty, de-hashed line of ``text`` (a task's subject line)."""
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s
    return ""


def request_title(task: str) -> str:
    """The ``mosaera: <subject>`` PR/MR title, truncated to ``TITLE_MAX`` with an ellipsis."""
    title = f"mosaera: {first_line(task) or 'Mosaera change'}"
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rstrip() + "…"
    return title


def request_body(task: str, run_id: str, branch: str, report_text: str) -> str:
    """The shared PR/MR description body for a completed run."""
    return (
        f"Automated change from Mosaera run `{run_id}` on branch `{branch}`.\n\n"
        f"**Task:** {task}\n\n"
        "---\n\n"
        f"{report_text}\n\n"
        "---\n"
        "_Opened by Mosaera after passing the human approval gate. "
        "Review per `AGENTS.md`; do not self-merge._"
    )


def push_repository_to(source_path: Path, credentialed_url: str) -> tuple[str | None, str | None]:
    """Push a project's existing history into a repository just created for it.

    Provider-neutral on purpose: GitHub and GitLab differ only in how the credential is spelled
    into the URL (``x-access-token:`` vs ``oauth2:``), and duplicating the hygiene below per
    provider is how one copy quietly loses a protection the other has.

    **Reads the source; writes only to the remote.** The push targets an explicit URL rather than
    a named remote, so nothing is added to the source repository's config and no remote-tracking
    ref is created — the operator's own checkout is left exactly as found. That matters here more
    than usual: ``source_path`` is a real directory of theirs, not a throwaway workspace.

    Returns ``(branch_pushed, None)`` or ``(None, error)``. The URL carrying the credential is
    never returned or logged, every subprocess is bounded, and stderr is scrubbed and capped.
    """
    git = shutil.which("git") or "git"
    try:
        head = subprocess.run(  # noqa: S603 — argv list, no shell
            [git, "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=source_path,
            capture_output=True,
            text=True,
            timeout=_HEAD_TIMEOUT,
        )
        if head.returncode != 0:
            # Not a git repository, or one with no commit yet. Either way there is nothing to
            # push, and saying so beats pushing nothing and calling it a sync.
            return None, (
                "this project's source is not a git repository with any commits, "
                "so there is nothing to push"
            )
        branch = head.stdout.strip() or "main"
        if branch == "HEAD":  # detached — name the destination rather than guess
            branch = "main"

        pushed = subprocess.run(  # noqa: S603 — argv list, no shell
            [git, "push", credentialed_url, f"HEAD:refs/heads/{branch}"],
            cwd=source_path,
            capture_output=True,
            text=True,
            timeout=_PUSH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, "git push timed out"
    except OSError as exc:
        return None, scrub_credentials(str(exc))[:200]
    if pushed.returncode != 0:
        return None, scrub_credentials(pushed.stderr.strip())[:200]
    return branch, None
