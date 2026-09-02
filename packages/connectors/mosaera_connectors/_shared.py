"""Shared PR/MR assembly + repo-URL helpers (GitHub + GitLab connectors).

The GitHub PR and GitLab MR flows build an identical title and body from a
completed run; kept here so the two connectors can't drift apart.

``host_of`` lives here for the same reason. It began as ``gitlab._host_of``, the
parser behind ``is_gitlab_source``'s host-EQUALITY test; provider detection needs
exactly the same parse, and a second copy is how a look-alike-host defect comes
back (see ``gitlab.is_gitlab_source`` for what the equality test prevents).
"""

from __future__ import annotations

import urllib.parse

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
