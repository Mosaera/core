"""Settings / configuration routes: app config, general operational knobs, and GitLab
integration (read-only introspection; token write-only).

Extracted from ``create_app`` verbatim (Phase 2 router split); provider/pricing/cost-mode
endpoints (models, pricing, providers, cost-modes) later moved to the cohesive
``routes/providers.py``, mounted here so every existing ``/api/...`` path is unchanged. Config/
secret writes are admin-gated via the ``require_admin`` dependency threaded in from ``app.py``
(which owns the shared ``_require_admin`` — projects reuses it too). No shared app state: every
handler reads live config from ``Settings.from_env``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import gitlab_client as glc
from mosaera_connectors import gitlab_write as glw
from mosaera_connectors import is_gitlab_source, project_from_source
from mosaera_core import __maturity__ as _ENGINE_MATURITY
from mosaera_core import __version__ as _ENGINE_VERSION
from mosaera_core.config import (
    Settings,
    coerce_general_patch_report,
    general_settings_view,
    profile_reference,
)
from mosaera_core.settings_store import write_settings
from mosaera_memory import encrypt_secret

from mosaera_api.schemas import DeleteToolBody, GeneralSettingsBody, GitlabConfig

from .gitlab_status import gitlab_checklist as _build_checklist
from .gitlab_status import gitlab_status as _build_status
from .providers import make_providers_router


def make_settings_router(require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()
    # Provider/pricing/cost-mode endpoints live in their own cohesive router (Phase 2 split, the
    # 500-line ceiling) but are still reached at their existing /api/... paths, and `app.py` still
    # calls exactly this one factory — the split is invisible to every other caller.
    api.include_router(make_providers_router(require_admin))

    @api.get("/config")
    def app_config() -> dict[str, Any]:
        return {
            # Engine version (ADR-0055) — the UI shows it so a deploy self-identifies — plus
            # the separate maturity channel (ADR-0088), the how-much-to-trust-it axis.
            "version": _ENGINE_VERSION,
            "maturity": _ENGINE_MATURITY,
            "gitlab": bool(Settings.from_env().gitlab_token),
            # Whether config/secret writes need the admin token (X-Mosaera-Admin);
            # the UI shows the Admin unlock only when true.
            "admin_required": bool(os.environ.get("MOSAERA_ADMIN_TOKEN", "").strip()),
            # Hard ceiling on per-run revisions — the UI caps its iterations slider here
            # so it can't send a value the server would reject/crash on.
            "max_iterations_ceiling": Settings.from_env().max_iterations_ceiling,
        }

    @api.get("/admin/verify")
    def admin_verify(request: Request) -> dict[str, bool]:
        """Validate the admin token (X-Mosaera-Admin) — powers the UI unlock probe."""
        require_admin(request)
        return {"ok": True}

    # --- GitLab integration (read-only introspection; token write-only) ---

    @api.get("/gitlab/status")
    def gitlab_status() -> dict[str, Any]:
        return _build_status(Settings.from_env())

    @api.post("/gitlab/config")
    def gitlab_set_config(body: GitlabConfig, request: Request) -> dict[str, Any]:
        require_admin(request)
        updates: dict[str, Any] = {}
        if body.url is not None:
            updates["gitlab_url"] = body.url.rstrip("/")
        if body.token:  # non-empty only — never clear on a blank field
            # Encrypt at rest like the per-project token + provider keys (ADR-0039): the global
            # PAT sits in the same settings.json, so it must not be the one secret left plaintext.
            updates["gitlab_token"] = encrypt_secret(body.token)
        # ADR-0104 OAuth app creds (amended: UI-settable). None → unchanged, "" → clear, val → set.
        # The client SECRET is encrypted like the token above; client_id + base_url are not secret.
        current = Settings.from_env()
        oauth_note: str | None = None
        if body.base_url is not None and body.base_url.strip():
            base = body.base_url.strip().rstrip("/")
            if not base.startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=400, detail="base URL must start with http:// or https://"
                )
            updates["base_url"] = base
        elif body.base_url is not None:
            updates["base_url"] = ""  # explicit clear
        if body.oauth_client_id is not None:
            updates["gitlab_oauth_client_id"] = body.oauth_client_id.strip()
        if body.oauth_client_secret is not None:
            secret = body.oauth_client_secret.strip()
            if secret:
                # Verify the id+secret actually authenticate BEFORE storing — catches a wrong secret
                # here instead of at the first Connect (ADR-0104 follow-up). Uses the effective
                # client_id (this write's, else the stored one) against the effective GitLab URL.
                client_id = (
                    updates.get("gitlab_oauth_client_id")
                    if body.oauth_client_id is not None
                    else current.gitlab_oauth_client_id
                ) or ""
                gl_url = updates.get("gitlab_url") or current.gitlab_url
                ok, oauth_note = glw.verify_oauth_client(gl_url, client_id, secret)
                if not ok:
                    raise HTTPException(status_code=400, detail=oauth_note)
            updates["gitlab_oauth_client_secret"] = encrypt_secret(secret) if secret else ""
        write_settings(current.home, updates)
        out = _build_status(Settings.from_env())
        if oauth_note:
            out["oauth_note"] = oauth_note  # transient verify result, for the save toast
        return out

    # --- General / operational settings (budgets, iterations, breaker, loops, …) ---

    @api.get("/settings/general")
    def get_general_settings() -> dict[str, Any]:
        """Every knob with value + source (env > stored > profile > default), plus profiles."""
        return {"knobs": general_settings_view(), **profile_reference()}

    @api.put("/settings/general")
    def set_general_settings(body: GeneralSettingsBody, request: Request) -> dict[str, Any]:
        """Persist a patch of operational knobs (admin-gated). Validated/coerced against
        the knob spec; a null value unsets a key. Applies to subsequent runs (no restart).

        A genuinely INVALID value (a negative number, an out-of-``choices`` value — ADR-0005)
        still 400s the whole request, unchanged: those are the operator's mistake to fix and
        retry, not a partial save to paper over. What used to be silent instead — an unknown
        field dropped, or a blank/unparsable value skipped, with the response saying "Saved"
        regardless (S4) — is now named in ``rejected`` alongside a 200: the good fields ARE
        persisted, and the client shows exactly which ones were not, and why."""
        require_admin(request)
        applied, rejected = coerce_general_patch_report(body.values)
        hard = {f: why for f, why in rejected.items() if "must" in why}
        if hard:
            field, why = next(iter(hard.items()))
            raise HTTPException(status_code=400, detail=f"{field} {why}")
        write_settings(Settings.from_env().home, applied)
        return {"knobs": general_settings_view(), "rejected": rejected, **profile_reference()}

    @api.get("/features")
    def get_features() -> dict[str, Any]:
        # Effective feature flags (env may override the persisted admin toggle).
        return {"delete_tool_enabled": Settings.from_env().delete_tool_enabled}

    @api.post("/features/delete-tool")
    def set_delete_tool(body: DeleteToolBody, request: Request) -> dict[str, Any]:
        # Destructive capability — admin only. Persists to settings.json; a
        # MOSAERA_DELETE_TOOL env var still wins over this at read time.
        require_admin(request)
        write_settings(Settings.from_env().home, {"delete_tool_enabled": body.enabled})
        return {"delete_tool_enabled": Settings.from_env().delete_tool_enabled}

    def _require_gitlab() -> Settings:
        settings = Settings.from_env()
        if not settings.gitlab_token:
            raise HTTPException(status_code=400, detail="GitLab not configured")
        return settings

    @api.get("/gitlab/visibility")
    def gitlab_visibility() -> dict[str, Any]:
        s = _require_gitlab()
        groups, gerr = glc.list_groups(s.gitlab_url, s.gitlab_token or "")
        projects, perr = glc.list_projects(s.gitlab_url, s.gitlab_token or "")
        return {
            "groups": [
                {"path": g.get("full_path"), "name": g.get("name")}
                for g in (groups if isinstance(groups, list) else [])
            ],
            "projects": [
                glc.project_summary(p) for p in (projects if isinstance(projects, list) else [])
            ],
            "error": gerr or perr,
        }

    @api.get("/gitlab/checklist")
    def gitlab_checklist(project: str) -> dict[str, Any]:
        return {"project": project, "checks": _build_checklist(_require_gitlab(), project)}

    @api.get("/gitlab/resolve")
    def gitlab_resolve(source: str) -> dict[str, Any]:
        s = Settings.from_env()
        if not s.gitlab_token or not is_gitlab_source(source, s.gitlab_url):
            return {"gitlab": False}
        project = project_from_source(source)
        if not project:
            return {"gitlab": False}
        proj, err = glc.get_project(s.gitlab_url, s.gitlab_token, project)
        if err or not isinstance(proj, dict):
            return {"gitlab": True, "project": project, "error": err}
        return {"gitlab": True, **glc.project_summary(proj)}

    return api
