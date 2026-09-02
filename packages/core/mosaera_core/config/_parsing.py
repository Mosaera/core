"""Parsers coercing stored/env config blobs into typed structures (leaf-ish)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mosaera_core.config._types import _ROLES, ProviderConfig, RoleModel


def _parse_role_models(data: Any) -> tuple[dict[str, str], dict[str, str]]:
    """Split a stored ``{role: {provider, model}}`` map into ``(role→provider,
    role→model)``; ignores unknown roles and malformed entries."""
    providers: dict[str, str] = {}
    models: dict[str, str] = {}
    if isinstance(data, Mapping):
        for role, spec in data.items():
            if role in _ROLES and isinstance(spec, Mapping):
                provider = spec.get("provider")
                model = spec.get("model")
                if isinstance(provider, str) and provider:
                    providers[role] = provider
                if isinstance(model, str) and model:
                    models[role] = model
    return providers, models


def _parse_providers(data: Any) -> dict[str, ProviderConfig]:
    """Coerce a stored ``{provider: {api_key, base_url, on_box}}`` map into typed
    ``ProviderConfig`` entries; drops malformed entries. A missing/malformed
    ``on_box`` reads as False, so a pre-existing settings.json keeps today's
    cloud classification (ADR-0024)."""
    out: dict[str, ProviderConfig] = {}
    if isinstance(data, Mapping):
        for pid, spec in data.items():
            if isinstance(pid, str) and pid and isinstance(spec, Mapping):
                key = spec.get("api_key")
                base = spec.get("base_url")
                out[pid] = ProviderConfig(
                    api_key=str(key) if key else None,
                    base_url=str(base) if base else None,
                    on_box=spec.get("on_box") is True,
                )
    return out


def _parse_cost_modes(data: Any) -> dict[str, dict[str, RoleModel]]:
    """Coerce a stored ``{mode: {role: {provider, model}}}`` map (cost-modes #7)
    into typed per-mode role overrides; drops malformed entries. A role a mode
    omits falls back to the base BYOM binding at resolution time."""
    out: dict[str, dict[str, RoleModel]] = {}
    if isinstance(data, Mapping):
        for mode, roles in data.items():
            if not (isinstance(mode, str) and mode and isinstance(roles, Mapping)):
                continue
            bindings: dict[str, RoleModel] = {}
            for role, spec in roles.items():
                if role in _ROLES and isinstance(spec, Mapping):
                    provider = spec.get("provider")
                    model = spec.get("model")
                    if isinstance(provider, str) and provider and isinstance(model, str) and model:
                        bindings[role] = RoleModel(provider=provider, model=model)
            if bindings:
                out[mode] = bindings
    return out


def _parse_role_escalation(data: Any) -> dict[str, list[RoleModel]]:
    """Coerce a stored/env ``{role: [{provider, model}, ...]}`` map into typed,
    ORDERED escalation ladders — tier 0 is the cheapest starting model, the last
    entry the strongest fallback. Drops malformed entries and unknown roles; a role
    with no valid tiers is omitted (never escalates)."""
    out: dict[str, list[RoleModel]] = {}
    if isinstance(data, Mapping):
        for role, tiers in data.items():
            if not (role in _ROLES and isinstance(tiers, list)):
                continue
            ladder: list[RoleModel] = []
            for spec in tiers:
                if isinstance(spec, Mapping):
                    provider = spec.get("provider")
                    model = spec.get("model")
                    if isinstance(provider, str) and provider and isinstance(model, str) and model:
                        ladder.append(RoleModel(provider=provider, model=model))
            if ladder:
                out[role] = ladder
    return out


def _parse_reason_escalation(data: Any) -> list[RoleModel]:
    """Coerce a stored/env ``[{provider, model}, ...]`` list into an ORDERED list of
    reasoning tiers (ADR-0018). Tier index maps to ``reason_attempts - 1`` — index 0 is
    the FIRST escalation above the coder's own-model reason pass. Drops malformed entries;
    a fully-malformed input → ``[]`` (never escalates). Unlike ``role_escalation`` this is a
    flat list, not role-keyed — it binds a one-off reasoner, not an agent role."""
    ladder: list[RoleModel] = []
    if isinstance(data, list):
        for spec in data:
            if isinstance(spec, Mapping):
                provider = spec.get("provider")
                model = spec.get("model")
                if isinstance(provider, str) and provider and isinstance(model, str) and model:
                    ladder.append(RoleModel(provider=provider, model=model))
    return ladder


def parse_price_map(data: Any) -> dict[str, tuple[float, ...]]:
    """Coerce a ``{model: [input, output]}`` — or ``[input, output, cache_write, cache_read]`` —
    mapping into a validated price table; silently drops malformed entries.

    The 4-element form is the one `.env.example` documents and `cost._rate` has always understood.
    This function accepted ONLY length 2, so a documented 4-element entry was dropped whole and the
    model ended up with NO price at all — priced as free, and `_rate`'s cache handling unreachable.
    Measured on run 20260821-153142: the Haiku coder billed $0.0729 with cache rates and reported
    $0.2118 without them, a 2.9x overstatement that hid the entire caching saving.
    """
    out: dict[str, tuple[float, ...]] = {}
    if isinstance(data, Mapping):
        for model, rate in data.items():
            if isinstance(rate, (list, tuple)) and len(rate) in (2, 4):
                try:
                    out[str(model)] = tuple(float(v) for v in rate)
                except (TypeError, ValueError):
                    pass
    return out


def _env_int(e: Mapping[str, str], key: str, default: int) -> int:
    """Parse an int env var, falling back to ``default`` on absent/empty/malformed —
    a config typo must degrade to the default, never crash startup or a run submit."""
    raw = e.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default
