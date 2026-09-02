"""GitLab integration status/checklist view-builders (read-only introspection).

Extracted from ``routes/settings.py`` (it sat at the 500-line ceiling and the ADR-0104 OAuth-config
addition pushed it over). These build the Integrations card's read models — connection/identity
status, the OAuth "Connect" app-config state, and the per-project secure-dev checklist. Pure
projections over ``Settings`` + read-only ``gitlab_client`` calls; every secret is presence-only or
masked (a raw token/secret is never returned).
"""

from __future__ import annotations

import os
from typing import Any

from mosaera_connectors import gitlab_client as glc
from mosaera_core.config import Settings
from mosaera_core.settings_store import mask_secret

# The OAuth env vars: if ANY is set, config resolves env > stored, so the UI can't change it —
# the card must say so (and disable editing) instead of silently ignoring a save.
_OAUTH_ENV_VARS = (
    "MOSAERA_GITLAB_OAUTH_CLIENT_ID",
    "MOSAERA_GITLAB_OAUTH_CLIENT_SECRET",
    "MOSAERA_BASE_URL",
)


def gitlab_oauth_status(settings: Settings) -> dict[str, Any]:
    """The OAuth "Connect" app config state (ADR-0104), for the Integrations card. Reports whether
    all three are set + a masked client_id + the base_url — NEVER the client secret (presence only,
    same discipline as every other secret read). ``oauth_env_pinned`` tells the UI the value comes
    from an env var (env > stored), so it must be edited in the environment, not here."""
    return {
        "oauth_configured": bool(
            settings.gitlab_oauth_client_id
            and settings.gitlab_oauth_client_secret
            and settings.base_url
        ),
        "oauth_client_id_masked": (
            mask_secret(settings.gitlab_oauth_client_id)
            if settings.gitlab_oauth_client_id
            else None
        ),
        "oauth_secret_set": bool(settings.gitlab_oauth_client_secret),
        "base_url": settings.base_url,
        "oauth_env_pinned": any(os.environ.get(v, "").strip() for v in _OAUTH_ENV_VARS),
    }


def gitlab_status(settings: Settings) -> dict[str, Any]:
    oauth = gitlab_oauth_status(settings)
    if not settings.gitlab_token:
        return {"configured": False, "url": settings.gitlab_url, **oauth}
    out: dict[str, Any] = {
        "configured": True,
        "url": settings.gitlab_url,
        "token_masked": mask_secret(settings.gitlab_token),
        **oauth,
    }
    user, err = glc.get_user(settings.gitlab_url, settings.gitlab_token)
    if err or not isinstance(user, dict):
        return {**out, "ok": False, "error": err or "unexpected response"}
    out["ok"] = True
    out["user"] = {
        "username": user.get("username"),
        "name": user.get("name"),
        "is_admin": bool(user.get("is_admin")),
    }
    tok, _ = glc.get_token_info(settings.gitlab_url, settings.gitlab_token)
    if isinstance(tok, dict):
        out["scopes"] = tok.get("scopes", [])
        out["expires_at"] = tok.get("expires_at")
    return out


def gitlab_checklist(settings: Settings, project: str) -> list[dict[str, Any]]:
    url, token = settings.gitlab_url, settings.gitlab_token or ""
    tok, _ = glc.get_token_info(url, token)
    scopes = tok.get("scopes", []) if isinstance(tok, dict) else []
    proj, _ = glc.get_project(url, token, project)
    proj = proj if isinstance(proj, dict) else {}
    pbs, _ = glc.get_protected_branches(url, token, project)
    pbs = pbs if isinstance(pbs, list) else []
    default = proj.get("default_branch") or "main"
    prot = next((b for b in pbs if b.get("name") == default), None)
    push_levels = [a.get("access_level") for a in (prot or {}).get("push_access_levels", [])]

    def row(label: str, ok: bool, detail: str) -> dict[str, Any]:
        return {"label": label, "ok": ok, "detail": detail}

    return [
        row(
            "Token can push (write_repository / api)",
            "write_repository" in scopes or "api" in scopes,
            "required to push branches",
        ),
        row(
            "Token scope not overly broad",
            "sudo" not in scopes,
            "avoid sudo/admin-wide tokens for automation",
        ),
        row(
            "Token has an expiry",
            bool(isinstance(tok, dict) and tok.get("expires_at")),
            "rotate on a schedule",
        ),
        row(
            f"Default branch '{default}' is protected",
            prot is not None,
            "protect the branch you merge into",
        ),
        row(
            "Direct pushes to default blocked (MR-only)",
            prot is not None and (not push_levels or push_levels == [0]),
            "force all changes through merge requests",
        ),
        row(
            "Pipeline must pass before merge",
            bool(proj.get("only_allow_merge_if_pipeline_succeeds")),
            "require green CI to merge",
        ),
    ]
