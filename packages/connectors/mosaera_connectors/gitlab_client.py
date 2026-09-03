"""Read-only GitLab API introspection for the Settings/Test page.

Every call returns plain data or ``{"error": "..."}`` — network/HTTP failures are
never raised into the request. No writes to GitLab happen here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# GitLab access levels.
DEVELOPER = 30


def _get(gitlab_url: str, token: str, path: str) -> tuple[Any, str | None]:
    url = f"{gitlab_url.rstrip('/')}/api/v4/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})  # noqa: S310 — configured GitLab
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        return None, f"{exc.code}: {body}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(exc)


def http_status(err: str | None) -> int | None:
    """The HTTP status carried by an error from this module, or None for a transport failure.

    ``_get`` renders an HTTPError as ``"{code}: {body}"``. Callers that must distinguish a 404
    from a timeout should ask here rather than string-matching the message, so the encoding stays
    one function's business.
    """
    if not err:
        return None
    head = err.split(":", 1)[0].strip()
    return int(head) if head.isdigit() else None


def get_user(gitlab_url: str, token: str) -> tuple[Any, str | None]:
    return _get(gitlab_url, token, "user")


def get_token_info(gitlab_url: str, token: str) -> tuple[Any, str | None]:
    return _get(gitlab_url, token, "personal_access_tokens/self")


def list_groups(gitlab_url: str, token: str) -> tuple[Any, str | None]:
    return _get(gitlab_url, token, "groups?per_page=100&order_by=name&sort=asc")


def list_projects(gitlab_url: str, token: str) -> tuple[Any, str | None]:
    return _get(
        gitlab_url, token, "projects?membership=true&per_page=100&order_by=last_activity_at"
    )


def get_project(gitlab_url: str, token: str, project: str) -> tuple[Any, str | None]:
    return _get(gitlab_url, token, f"projects/{urllib.parse.quote(project, safe='')}")


def get_protected_branches(gitlab_url: str, token: str, project: str) -> tuple[Any, str | None]:
    enc = urllib.parse.quote(project, safe="")
    return _get(gitlab_url, token, f"projects/{enc}/protected_branches")


def get_merge_request(
    gitlab_url: str, token: str, project: str, iid: int
) -> tuple[Any, str | None]:
    """Fetch one merge request (for its ``state``: opened/merged/closed)."""
    enc = urllib.parse.quote(project, safe="")
    return _get(gitlab_url, token, f"projects/{enc}/merge_requests/{iid}")


def list_merge_requests(
    gitlab_url: str, token: str, project: str, *, source_branch: str, state: str = "opened"
) -> tuple[Any, str | None]:
    """MRs for one source branch — the URL fallback when a push banner had none (ADR-0102)."""
    enc = urllib.parse.quote(project, safe="")
    branch = urllib.parse.quote(source_branch, safe="")
    return _get(
        gitlab_url,
        token,
        f"projects/{enc}/merge_requests?source_branch={branch}&state={state}&per_page=1",
    )


def access_level(project: dict[str, Any]) -> int:
    """Highest of the project's project/group access levels for the token's user."""
    perms = project.get("permissions") or {}
    levels = [
        (perms.get(k) or {}).get("access_level", 0) for k in ("project_access", "group_access")
    ]
    return max([lvl for lvl in levels if isinstance(lvl, int)], default=0)


def project_summary(project: dict[str, Any]) -> dict[str, Any]:
    lvl = access_level(project)
    return {
        "path": project.get("path_with_namespace", ""),
        "access_level": lvl,
        "can_push": lvl >= DEVELOPER,
        "default_branch": project.get("default_branch"),
    }
