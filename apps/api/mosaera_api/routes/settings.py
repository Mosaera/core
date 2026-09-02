"""Settings / configuration routes: app config, models, pricing, providers,
cost-modes, and GitLab integration (read-only introspection; token write-only).

Extracted from ``create_app`` verbatim (Phase 2 router split). Config/secret
writes are admin-gated via the ``require_admin`` dependency threaded in from
``app.py`` (which owns the shared ``_require_admin`` — projects reuses it too).
No shared app state: every handler reads live config from ``Settings.from_env``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import gitlab_client as glc
from mosaera_connectors import gitlab_write as glw
from mosaera_connectors import is_gitlab_source, project_from_source
from mosaera_core import __maturity__ as _ENGINE_MATURITY
from mosaera_core import __version__ as _ENGINE_VERSION
from mosaera_core.config import (
    Role,
    Settings,
    coerce_general_patch,
    general_settings_view,
)
from mosaera_core.models import (
    COST_MODES,
    ProviderAuthError,
    fetch_provider_models,
    list_model_sources,
    provider_catalog,
    provider_has_env_key,
    provider_is_local,
)
from mosaera_core.settings_store import mask_secret, read_settings, write_settings
from mosaera_core.team import AGENT_REGISTRY, team_roles
from mosaera_memory import encrypt_secret, try_decrypt

from mosaera_api.schemas import (
    CostModesBody,
    DeleteToolBody,
    GeneralSettingsBody,
    GitlabConfig,
    PricingBody,
    ProvidersBody,
    TestProviderBody,
)

from ._providers import merge_provider_entry
from .gitlab_status import gitlab_checklist as _build_checklist
from .gitlab_status import gitlab_status as _build_status


def _role_meta() -> list[dict[str, Any]]:
    """Per-role display metadata for the Settings UI (functional label, persona,
    remit), from the agent registry (mosaera_core.team) so a new agent's model
    bindings render without a hand edit to the web."""
    return [
        {
            "role": s.role,
            "label": s.label,
            "display_name": s.display_name,
            "remit": s.remit,
            # The graph node this role owns. The run timeline names and draws its actors per NODE,
            # so this is the bridge that lets a role card carry the same face and name the operator
            # will see during a run — derived here rather than hardcoded a fourth time in the web.
            "node": s.nodes[0] if s.nodes else "",
            # Whether this role only READS the repo. Every role needs a tool-calling model (all
            # five are built with `create_agent(tools=…)`); what separates them is that the coder
            # and the tester also write files and run tests. Saying "does not need tools" of the
            # others would be false against ROLE_TOOL_ALLOWLIST.
            "read_only": s.read_only,
        }
        for s in AGENT_REGISTRY
    ]


def make_settings_router(require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

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
        """Every UI-managed operational knob with its effective value and source
        (``env`` = pinned by an env var, read-only in the UI | ``stored`` | ``default``)."""
        return {"knobs": general_settings_view()}

    @api.put("/settings/general")
    def set_general_settings(body: GeneralSettingsBody, request: Request) -> dict[str, Any]:
        """Persist a patch of operational knobs (admin-gated). Validated/coerced against
        the knob spec; a null value unsets a key. Applies to subsequent runs (no restart)."""
        require_admin(request)
        try:
            patch = coerce_general_patch(body.values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        write_settings(Settings.from_env().home, patch)
        return {"knobs": general_settings_view()}

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

    def _pricing() -> dict[str, Any]:
        prices = Settings.from_env().model_prices
        return {
            "prices": {
                m: {
                    "input": r[0],
                    "output": r[1],
                    # Only when actually configured — None keeps "no cache rate set" distinct
                    # from "set to zero", which would price every cache hit as free.
                    "cache_write": r[2] if len(r) == 4 else None,
                    "cache_read": r[3] if len(r) == 4 else None,
                }
                for m, r in sorted(prices.items())
            }
        }

    @api.get("/models")
    def available_models() -> dict[str, list[dict[str, Any]]]:
        """Models available to bind, grouped by provider source (e.g. Ollama).
        Powers the pricing card's model picker so prices attach to real models,
        not typos, with a heading showing where each model came from."""
        return {"sources": list_model_sources(Settings.from_env())}

    @api.get("/pricing")
    def get_pricing() -> dict[str, Any]:
        """Configured per-model API prices ($/1M input, $/1M output)."""
        return _pricing()

    @api.put("/pricing")
    def set_pricing(body: PricingBody, request: Request) -> dict[str, Any]:
        """Replace the model price table (persisted to settings; admin-gated like
        the GitLab config). Applies to subsequent runs."""
        require_admin(request)

        def _rate(e: Any) -> list[float]:
            # 4 elements only when BOTH cache rates are given and valid — a half-filled pair
            # would be stored as a length-3 entry, which `parse_price_map` drops whole, silently
            # leaving the model with no price at all.
            if e.cache_write is not None and e.cache_read is not None:
                if e.cache_write >= 0 and e.cache_read >= 0:
                    return [e.input, e.output, e.cache_write, e.cache_read]
            return [e.input, e.output]

        table = {
            m: _rate(e)
            for m, e in body.prices.items()
            if m.strip() and e.input >= 0 and e.output >= 0
        }
        write_settings(Settings.from_env().home, {"model_prices": table})
        return _pricing()

    # --- BYOM providers (#21): per-role provider/model + provider keys ---

    def _providers_view(settings: Settings) -> dict[str, Any]:
        """The providers page state. API keys are NEVER returned raw — only a
        masked hint (mirrors the GitLab token discipline)."""

        def role_view(role: Role) -> dict[str, str]:
            binding = settings.role_model(role)
            return {"provider": binding.provider, "model": binding.model}

        providers = []
        for entry in provider_catalog():
            pid = str(entry["id"])
            cfg = settings.providers.get(pid)
            key = cfg.api_key if cfg else None
            env_ok = not entry["local"] and provider_has_env_key(pid)
            providers.append(
                {
                    **entry,
                    "configured": bool(key) or env_ok or bool(entry["local"]),
                    "has_key": bool(key),
                    "uses_env_key": env_ok and not key,
                    # Mask the PLAINTEXT hint, not the ciphertext — a Fernet tail is meaningless
                    # and changes every save, defeating the "recognise your own key" purpose. Never
                    # 500 the providers view if one key can't be decrypted (M-2): a locked key just
                    # loses its hint (has_key stays true, key_masked empty).
                    "key_masked": mask_secret(try_decrypt(key)[1] or None),
                    "base_url": cfg.base_url if cfg else None,
                    "on_box": bool(cfg.on_box) if cfg else False,
                }
            )
        return {
            "providers": providers,
            # Role bindings + role metadata both derive from the agent registry
            # (mosaera_core.team), so a new agent surfaces in the UI automatically.
            "roles": {role: role_view(role) for role in team_roles()},
            "role_meta": _role_meta(),
            "sources": list_model_sources(settings),
        }

    @api.get("/providers")
    def get_providers() -> dict[str, Any]:
        """Configured model providers (masked keys) + per-role model bindings."""
        return _providers_view(Settings.from_env())

    @api.put("/providers")
    def set_providers(body: ProvidersBody, request: Request) -> dict[str, Any]:
        """Update provider credentials and/or per-role model bindings (admin-gated
        like pricing). A blank api_key keeps the saved one; a non-local provider
        bound to a role must have a key (stored or via its native env var)."""
        require_admin(request)
        home = Settings.from_env().home
        stored = read_settings(home)
        valid = {str(p["id"]) for p in provider_catalog()}

        providers_raw: dict[str, Any] = dict(stored.get("providers") or {})
        for pid, cred in body.providers.items():
            if pid not in valid:
                raise HTTPException(status_code=422, detail=f"unknown provider '{pid}'")
            entry, bad = merge_provider_entry(providers_raw.get(pid) or {}, cred)
            if bad:
                raise HTTPException(status_code=422, detail=f"provider '{pid}': {bad}")
            providers_raw[pid] = entry

        role_models_raw: dict[str, Any] = dict(stored.get("role_models") or {})
        for role, binding in body.roles.items():
            if role not in team_roles():
                raise HTTPException(status_code=422, detail=f"unknown role '{role}'")
            if binding.provider not in valid:
                raise HTTPException(
                    status_code=422, detail=f"unknown provider '{binding.provider}'"
                )
            if not binding.model.strip():
                raise HTTPException(status_code=422, detail=f"model required for role '{role}'")
            role_models_raw[role] = {"provider": binding.provider, "model": binding.model.strip()}

        # A role bound to a hosted provider must have a key somewhere, else the
        # run would fail fast at build time — reject the save with a clear reason.
        for role, spec in role_models_raw.items():
            provider = str(spec.get("provider") or "ollama")
            if provider_is_local(provider):
                continue
            has_key = bool((providers_raw.get(provider) or {}).get("api_key"))
            if not has_key and not provider_has_env_key(provider):
                raise HTTPException(
                    status_code=422,
                    detail=f"role '{role}' → '{provider}' needs an API key for that provider",
                )

        write_settings(home, {"providers": providers_raw, "role_models": role_models_raw})
        return _providers_view(Settings.from_env())

    @api.post("/providers/test")
    def test_provider(body: TestProviderBody, request: Request) -> dict[str, Any]:
        """Validate a hosted provider's API key and return the models it grants (BYOM
        live discovery, #21). Uses the just-typed key (so you can test before saving),
        else the saved/env key. Admin-gated like the other provider writes; the key is
        used against the provider's own API and is never returned or logged. Never 500s
        on a provider hiccup — a bad key or unreachable provider comes back as
        ``{ok: false, error}`` so the UI shows it inline."""
        require_admin(request)
        settings = Settings.from_env()
        entry = next((p for p in provider_catalog() if p["id"] == body.provider), None)
        if entry is None or entry["local"]:
            raise HTTPException(
                status_code=422, detail=f"'{body.provider}' is not a testable hosted provider"
            )
        pcfg = settings.provider_config(body.provider)
        base_url = (body.base_url or pcfg.base_url or "").strip() or None
        env_val = (
            os.environ.get(str(entry.get("env_key") or ""), "") if entry.get("env_key") else ""
        )
        # decrypt the stored key — pcfg.api_key is the at-rest ciphertext (ADR-0039); without
        # this the "Test" button would send `enc:v1:…` to the provider and reject a valid key. A
        # locked stored key (missing/wrong MOSAERA_SECRET_KEY) degrades to a clear error, not a
        # 500 (M-2) — the operator can still test by pasting a fresh key in the body.
        stored_ok, stored_key = try_decrypt(pcfg.api_key)
        key = (body.api_key or stored_key or env_val or "").strip()
        if not key:
            reason = (
                "stored API key can't be decrypted — check MOSAERA_SECRET_KEY (or paste the key)"
                if pcfg.api_key and not stored_ok
                else "no API key to test"
            )
            return {"ok": False, "count": 0, "models": [], "error": reason}
        try:
            models = fetch_provider_models(body.provider, key, base_url, force=True)
        except ProviderAuthError as exc:
            return {"ok": False, "count": 0, "models": [], "error": f"invalid API key ({exc})"}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return {
                "ok": False,
                "count": 0,
                "models": [],
                "error": f"couldn't reach {body.provider}: {exc}",
            }
        return {"ok": True, "count": len(models), "models": models}

    # --- Cost-modes (#7): per-role model routing tiers (Economy/Balanced/Premium) ---

    def _cost_modes_view(settings: Settings) -> dict[str, Any]:
        """Cost-mode profiles + the default mode. Each role shows both its explicit
        override (if any) and the EFFECTIVE binding (override else base fallback),
        so the UI can render fallbacks as placeholders. No secrets — bindings only."""
        modes: dict[str, Any] = {}
        for mode in COST_MODES:
            overrides = settings.cost_modes.get(mode, {})
            roles: dict[str, Any] = {}
            for role in team_roles():
                override = overrides.get(role)
                effective = settings.role_model_for(mode, role)  # type: ignore[arg-type]
                roles[role] = {
                    "provider": override.provider if override else None,
                    "model": override.model if override else None,
                    "effective_provider": effective.provider,
                    "effective_model": effective.model,
                    "overridden": override is not None,
                }
            modes[mode] = roles
        return {
            "modes": modes,
            "default_cost_mode": settings.default_cost_mode,
            "available": list(COST_MODES),
            "role_meta": _role_meta(),
            "sources": list_model_sources(settings),
        }

    @api.get("/cost-modes")
    def get_cost_modes() -> dict[str, Any]:
        """Cost-mode routing profiles + the default mode."""
        return _cost_modes_view(Settings.from_env())

    @api.put("/cost-modes")
    def set_cost_modes(body: CostModesBody, request: Request) -> dict[str, Any]:
        """Replace the cost-mode profiles and/or default mode (admin-gated like
        pricing/providers). Validates providers/models and enforces that a hosted
        binding has a key (stored or via env), so a routed run never fails at build."""
        require_admin(request)
        settings = Settings.from_env()
        valid_providers = {str(p["id"]) for p in provider_catalog()}
        cost_modes_raw: dict[str, Any] = {}
        for mode, roles in body.modes.items():
            if mode not in COST_MODES:
                raise HTTPException(status_code=422, detail=f"unknown cost mode '{mode}'")
            bindings: dict[str, Any] = {}
            for role, binding in roles.items():
                if role not in team_roles():
                    raise HTTPException(status_code=422, detail=f"unknown role '{role}'")
                if binding.provider not in valid_providers:
                    raise HTTPException(
                        status_code=422, detail=f"unknown provider '{binding.provider}'"
                    )
                if not binding.model.strip():
                    raise HTTPException(status_code=422, detail=f"model required for role '{role}'")
                if not provider_is_local(binding.provider):
                    cfg = settings.providers.get(binding.provider)
                    stored_key = cfg.api_key if cfg else None
                    if not stored_key and not provider_has_env_key(binding.provider):
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"{mode} · '{role}' → '{binding.provider}' needs an API key "
                                "for that provider (set it in Model providers)"
                            ),
                        )
                bindings[role] = {"provider": binding.provider, "model": binding.model.strip()}
            if bindings:
                cost_modes_raw[mode] = bindings
        updates: dict[str, Any] = {"cost_modes": cost_modes_raw}
        if body.default_cost_mode is not None:
            if body.default_cost_mode not in COST_MODES:
                raise HTTPException(
                    status_code=422, detail=f"unknown default cost mode '{body.default_cost_mode}'"
                )
            updates["default_cost_mode"] = body.default_cost_mode
        write_settings(settings.home, updates)
        return _cost_modes_view(Settings.from_env())

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
