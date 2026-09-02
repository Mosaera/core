"""Model gateway: role -> chat model factory.

This is deliberately the only place that knows which provider backs a role. A
role maps to a ``(provider, model)`` binding (BYOM, #21); ``get_chat_model``
dispatches through LangChain's ``init_chat_model`` so any provider whose
integration package is installed (Ollama, OpenAI/-compatible, Anthropic, …) can
back any role without touching agents or the orchestrator (ADR-0001). Ollama is
the default → the local-first posture is unchanged until a user opts in.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import time
from typing import Any, get_args
from urllib.parse import urlparse

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import OllamaEmbeddings
from mosaera_memory import SecretKeyError, decrypt_secret, try_decrypt

from mosaera_core.config import Role, Settings
from mosaera_core.team import team_roles, temperature_map

# Low temperatures across the board (these are execution roles, not ideation) —
# derived from the agent registry (mosaera_core.team) so a new agent's temperature
# lives in ONE place. _ROLES is likewise the registry's canonical role list.
_ROLE_TEMPERATURE: dict[Role, float] = temperature_map()
_ROLES: tuple[Role, ...] = team_roles()

# Providers that run locally and need no API key.
_LOCAL_PROVIDERS = frozenset({"ollama"})

# The API-key env var each provider reads natively (init_chat_model honors these
# when we don't pass an explicit key), so power users need no UI config.
_PROVIDER_ENV_KEY: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "together": "TOGETHER_API_KEY",
}

# Curated model suggestions for hosted providers — the FALLBACK only, shown when no
# key is configured, a live fetch fails, or the provider has no list endpoint. When a
# valid key is present, the live model list from the provider's own API wins (see
# fetch_provider_models). The UI also allows free-text entry, so nothing ever blocks.
_PROVIDER_SUGGESTIONS: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "o4-mini", "o3"],
    "anthropic": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
}

# Substrings that mark a NON-chat model id (embeddings/audio/image/moderation/legacy
# completion). Best-effort filter on the live list — never blocks a real chat model.
_NON_CHAT_MARKERS = (
    "embed",
    "whisper",
    "tts",
    "audio",
    "dall-e",
    "image",
    "moderation",
    "rerank",
    "davinci",
    "babbage",
    "ada",
    "curie",
)

# In-process cache of a key's live model list, so the Test button + the settings-page
# auto-fetch don't hit the provider API on every load. Keyed by (provider, key
# fingerprint, base_url); process-scoped (a restart re-tests, which is fine).
_MODEL_CACHE: dict[tuple[str, str, str], tuple[list[str], float]] = {}
_MODEL_CACHE_TTL_S = 600.0


class ProviderAuthError(RuntimeError):
    """A provider rejected the API key (401/403). Surfaced to the UI as an honest
    'invalid API key' rather than a stack trace, so key validation is meaningful."""


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _openai_list_models(base_url: str, api_key: str) -> list[str]:
    resp = httpx.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    if resp.status_code in (401, 403):
        raise ProviderAuthError("the provider rejected this API key")
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [str(m["id"]) for m in data if isinstance(m, dict) and m.get("id")]


def _anthropic_list_models(api_key: str) -> list[str]:
    resp = httpx.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        timeout=10.0,
    )
    if resp.status_code in (401, 403):
        raise ProviderAuthError("the provider rejected this API key")
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [str(m["id"]) for m in data if isinstance(m, dict) and m.get("id")]


def fetch_provider_models(
    provider: str, api_key: str, base_url: str | None = None, *, force: bool = False
) -> list[str]:
    """The chat models an API key actually grants, from the provider's own list-models
    endpoint (OpenAI/OpenAI-compatible ``GET /v1/models``; Anthropic ``GET /v1/models``).
    Cached in-process (TTL) so validation + auto-fetch don't hammer the API. Raises
    ``ProviderAuthError`` on a rejected key; other transport errors propagate."""
    if not api_key.strip():
        raise ProviderAuthError("no API key provided")
    cache_key = (provider, _key_fingerprint(api_key), base_url or "")
    if not force:
        hit = _MODEL_CACHE.get(cache_key)
        if hit is not None and hit[1] > time.monotonic():
            return hit[0]
    if provider == "anthropic" and not base_url:
        raw = _anthropic_list_models(api_key)
    else:
        # openai + any OpenAI-compatible endpoint (a custom base_url routes here too).
        raw = _openai_list_models(base_url or "https://api.openai.com/v1", api_key)
    models = sorted({m for m in raw if not any(x in m.lower() for x in _NON_CHAT_MARKERS)})
    _MODEL_CACHE[cache_key] = (models, time.monotonic() + _MODEL_CACHE_TTL_S)
    return models


def cached_provider_models(
    provider: str, api_key: str, base_url: str | None = None
) -> list[str] | None:
    """The cached live models for a key if a prior fetch/Test populated them, else None.
    NEVER hits the network — safe to call on the interactive settings-view path."""
    if not api_key.strip():
        return None
    hit = _MODEL_CACHE.get((provider, _key_fingerprint(api_key), base_url or ""))
    if hit is not None and hit[1] > time.monotonic():
        return hit[0]
    return None


# Model families whose chain-of-thought must be routed to the separate reasoning
# channel; without this their thinking leaks into message content (observed with
# gpt-oss:20b). Coder variants (e.g. qwen3-coder) do not support thinking. This
# is Ollama-tag sniffing and is applied only on the ollama path.
_REASONING_FAMILIES = ("gpt-oss", "deepseek-r1", "qwen3", "magistral")


# Providers the app ships integration packages for and offers in the UI. Other
# init_chat_model providers still work if their package is installed and they're
# configured via env, but only these appear in the picker.
KNOWN_PROVIDERS: tuple[str, ...] = ("ollama", "openai", "anthropic")

# Cost-mode routing tiers (#7): named per-role model profiles selectable per run.
# Ordered cheapest → most capable. The binding for each is user-configured; a
# mode that omits a role falls back to the base BYOM binding (Settings.role_model).
COST_MODES: tuple[str, ...] = ("economy", "balanced", "premium")


class ModelConfigError(RuntimeError):
    """A role's model/provider is misconfigured: unknown provider, missing
    integration package, or a hosted provider with no API key. Raised with an
    actionable message so a run fails cleanly instead of with a stack trace."""


def provider_catalog() -> list[dict[str, Any]]:
    """Static description of the providers the UI can offer: id, whether it's
    local (needs no key), its native API-key env var, and curated model
    suggestions. The credential/binding *state* is layered on by the API."""
    return [
        {
            "id": pid,
            "local": pid in _LOCAL_PROVIDERS,
            "env_key": None if pid in _LOCAL_PROVIDERS else _env_key_name(pid),
            "suggestions": _PROVIDER_SUGGESTIONS.get(pid, []),
        }
        for pid in KNOWN_PROVIDERS
    ]


def provider_is_local(provider: str) -> bool:
    """Whether ``provider`` is inherently local (needs no API key). Provider-only by
    design — the API-key checks on the settings-save path depend on that. For "does
    using this binding egress off-box?" use ``endpoint_is_on_box``, which also honours
    a loopback OpenAI-compatible endpoint."""
    return provider in _LOCAL_PROVIDERS


def is_loopback_url(base_url: str | None) -> bool:
    """Whether ``base_url``'s host is a loopback address — i.e. traffic to it cannot
    leave this machine. Parses the URL and tests the ADDRESS (127.0.0.0/8, ::1);
    never substring-matches, so ``http://127.0.0.1.evil.com`` and
    ``http://evil.com/?x=127.0.0.1`` are correctly rejected."""
    if not base_url:
        return False
    try:
        host = urlparse(base_url).hostname  # strips port/credentials, unwraps [::1]
    except ValueError:
        return False
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Not a literal IP. `localhost` is the one name we trust by convention;
        # it is NOT re-resolved (a network call on a pure config path, and a TOCTOU
        # window). A remapped /etc/hosts is operator-controlled — see ADR-0024.
        return host == "localhost"  # urlparse lowercases hostname


def on_box_declaration_error(base_url: str | None, on_box: bool) -> str | None:
    """Why this on-box declaration can't be stored, or None if it's valid. Declaring a
    NON-loopback endpoint on-box is refused rather than persisted, so the flag can never
    sit in settings.json meaning nothing (and can't quietly become live if the URL later
    changes). Returns a message so the caller owns its own error type (layer direction)."""
    if on_box and not is_loopback_url(base_url):
        return (
            "'runs on this machine' requires a loopback base_url "
            "(e.g. http://localhost:8001/v1) — clear it, or untick the box"
        )
    return None


def endpoint_is_on_box(settings: Settings, provider: str) -> bool:
    """Whether using ``provider`` keeps repo content on THIS machine. True for an
    inherently-local provider (ollama), or for an OpenAI-compatible endpoint the
    operator explicitly declared on-box AND whose base_url is loopback.

    BOTH conditions are required, deny-by-default. Loopback alone is not evidence of
    local execution: a LiteLLM-style forwarding proxy also binds to loopback while
    relaying to a hosted API, and exempting it would silently defeat both the egress
    consent gate and the USD price cap. The declaration alone is not enough either —
    it grants nothing on a hosted URL. See ADR-0024 (amended 2026-07-28)."""
    if provider_is_local(provider):
        return True
    pcfg = settings.provider_config(provider)
    return pcfg.on_box and is_loopback_url(pcfg.base_url)


def on_box_models(settings: Settings) -> frozenset[str]:
    """Every model name bound to a role that runs ON THIS BOX, across all cost modes.

    Used to mark imputed ("shadow") spend apart from real spend: pricing a local model makes the
    burn visible before it is ever paid for, but those dollars are owed to nobody and must not be
    summed into the figure the budget caps read.

    Every binding a run could actually reach, not just the active one: all cost modes (#7), the
    per-role escalation ladder (ADR-0016/0022) and the reasoning ladder (ADR-0018). The ladders are
    configured SEPARATELY from cost modes, so enumerating modes alone misses a model that only
    appears after an escalation — and a model missed here has its imaginary dollars counted as
    real, which is the direction that cancels a run over money nobody spent.

    Caught by reading a bench rollup, not by a test: a scratch config that bound only two of three
    local models reported the third as billable.
    """
    names: set[str] = set()
    for mode in {*settings.cost_modes, settings.default_cost_mode, settings.active_cost_mode or ""}:
        for role in get_args(Role):
            bindings = [settings.role_model_for(mode, role)]
            bindings += list(settings.role_escalation.get(role, []))
            bindings += list(settings.reason_escalation)
            for binding in bindings:
                if endpoint_is_on_box(settings, binding.provider):
                    names.add(binding.model)
    return frozenset(names)


def cloud_tier_allowed(settings: Settings, provider: str, model: str) -> bool:
    """May an AUTONOMOUS run use this ``(provider, model)``? An on-box binding is always
    fine (ollama, or a declared loopback endpoint — ``endpoint_is_on_box``). A CLOUD
    tier requires BOTH operator consent to off-box egress (``allow_cloud_egress``) AND a
    ``model_prices`` entry — so repo content only leaves the box on purpose, and the USD
    budget cap can actually bound the spend (a $0-priced cloud model would otherwise evade
    every USD cap). Interactive / guided runs are NOT gated here: those bindings are the
    operator's watched, in-UI-consented choice. See ADR-0024."""
    if endpoint_is_on_box(settings, provider):
        return True
    return settings.allow_cloud_egress and model in settings.model_prices


def provider_has_env_key(provider: str) -> bool:
    """Whether ``provider``'s native API-key env var is set (the no-UI path)."""
    return _has_provider_env_key(provider)


def _supports_reasoning(model_name: str) -> bool:
    name = model_name.lower()
    if "coder" in name:
        return False
    return name.startswith(_REASONING_FAMILIES)


# Anthropic families that still ACCEPT an explicit ``temperature``. The current tiers — Fable/
# Mythos 5, Opus 4.7+, Sonnet 5+ — REJECT it with HTTP 400 (the adaptive-thinking models dropped
# sampling params), so we omit ``temperature`` for anthropic BY DEFAULT and send it only for
# these known-older models. Deny-by-default is deliberate: a future Anthropic release we haven't
# listed omits temperature, so it can never 400 the run (the safety the old blanket-omit gave) —
# while the models that DO accept it now get the intended low role temperature (reproducibility).
_ANTHROPIC_TEMPERATURE_OK = (
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-opus-4-0",
    "claude-sonnet-4-0",  # enumerate the VETTED sonnet-4 versions, not a bare `claude-sonnet-4`
    "claude-sonnet-4-5",  # prefix — else an unvetted future claude-sonnet-4-N (that may 400 on
    "claude-sonnet-4-6",  # temperature, like sonnet-5 does) would match and break the run (M7).
    "claude-haiku-4-5",
    "claude-3",  # the 3.x line
)


def _anthropic_accepts_temperature(model_name: str) -> bool:
    """Whether an anthropic ``model_name`` accepts an explicit ``temperature`` (vs 400-ing on it).
    Only the known-older families do; unknown/newer models omit it (deny-by-default)."""
    return model_name.lower().startswith(_ANTHROPIC_TEMPERATURE_OK)


def coder_num_ctx(settings: Settings) -> int:
    """The coder's effective context window — an opt-in override, else the global."""
    return settings.coder_num_ctx or settings.ollama_num_ctx


def _env_key_name(provider: str) -> str:
    return _PROVIDER_ENV_KEY.get(provider, f"{provider.upper()}_API_KEY")


def _has_provider_env_key(provider: str) -> bool:
    return bool(os.environ.get(_env_key_name(provider), "").strip())


def _build_model_kwargs(role: Role, settings: Settings) -> tuple[str, str, dict[str, Any]]:
    """Resolve ``role`` to ``(provider, model, kwargs)`` for ``init_chat_model``.

    Pure and provider-conditional so it is unit-testable without instantiating a
    client: the Ollama path keeps the local-specific knobs (num_ctx, reasoning,
    client_kwargs timeout); hosted providers get only kwargs their constructors
    accept (api_key, base_url, temperature, timeout) — a stray ``num_ctx`` would
    make ChatOpenAI/others raise.
    """
    binding = settings.role_model(role)
    provider, model = binding.provider, binding.model
    pcfg = settings.provider_config(provider)
    temperature = _ROLE_TEMPERATURE[role]
    if provider == "ollama":
        num_ctx = coder_num_ctx(settings) if role == "coder" else settings.ollama_num_ctx
        kwargs: dict[str, Any] = {
            "base_url": (pcfg.base_url or settings.ollama_base_url).rstrip("/"),
            "temperature": temperature,
            # Route chain-of-thought to the reasoning channel for families that
            # need it; None leaves it at the model's default.
            "reasoning": True if _supports_reasoning(model) else None,
            # Ollama's default context (2048) silently truncates our prompts.
            "num_ctx": num_ctx,
            # Per-call httpx timeout: a hung Ollama errors the run instead of
            # wedging it forever (client_kwargs is the only timeout channel).
            "client_kwargs": {"timeout": settings.ollama_timeout},
            # Keep the model resident so the automatic prefix cache survives an idle gap.
            # Ollama's 5-minute default unloads mid-run and dumps the KV cache — invisible in
            # every number we record, because `prompt_eval_count` reports context size, not
            # recomputation. `prompt_eval_ms` (cost.py) is what makes the difference visible.
            "keep_alive": settings.ollama_keep_alive,
        }
        return provider, model, kwargs
    # Hosted / OpenAI-compatible providers: only portable kwargs.
    kwargs = {"timeout": settings.ollama_timeout, "max_retries": 2}
    # The current Anthropic tiers (Fable/Mythos 5, Opus 4.7+, Sonnet 5+) REJECT an explicit
    # `temperature` with HTTP 400; older ones (Opus 4.5/4.6, Sonnet 4.x, Haiku 4.5, Claude 3.x)
    # still accept it. Send the role temperature to every non-anthropic provider and to the
    # older anthropic models that take it; omit it otherwise so the run can't 400 (M7).
    if provider != "anthropic" or _anthropic_accepts_temperature(model):
        kwargs["temperature"] = temperature
    if pcfg.api_key:
        try:
            kwargs["api_key"] = decrypt_secret(pcfg.api_key)  # decrypt the at-rest key (ADR-0039)
        except SecretKeyError as exc:
            # A locked key must surface as a clean, catchable config error at the point of USE —
            # not a raw 500 (M-2). The read/list paths degrade instead (try_decrypt).
            raise ModelConfigError(
                f"provider '{provider}' API key can't be decrypted — set MOSAERA_SECRET_KEY to "
                "the key it was encrypted with"
            ) from exc
    if pcfg.base_url:  # OpenAI-compatible endpoint / proxy
        kwargs["base_url"] = pcfg.base_url.rstrip("/")
    # Prompt caching, anthropic-only and behind the seam (ADR-0002: provider options resolve HERE,
    # never in an agent). This workload is ~96-97% input tokens and every model call is the prior
    # call's messages plus a suffix, so the prefix is re-sent whole on each turn. `model_kwargs`
    # rides into the request payload; langchain-anthropic passes the breakpoint straight through on
    # the direct API and expands it to block form on other transports. Deliberately NOT set for
    # ollama/openai — the docstring above is explicit that a kwarg their constructor does not accept
    # makes them raise, and the cost instrument (`cost.py`) only ever sees cache fields from
    # Anthropic responses anyway.
    if provider == "anthropic" and settings.prompt_cache_enabled:
        kwargs["model_kwargs"] = {"cache_control": {"type": "ephemeral"}}
    return provider, model, kwargs


def get_chat_model(role: Role, settings: Settings) -> BaseChatModel:
    provider, model, kwargs = _build_model_kwargs(role, settings)
    if not model:
        raise ModelConfigError(f"no model configured for role '{role}'")
    # Fail fast on a hosted provider with no key anywhere (settings or native env)
    # rather than letting init_chat_model raise deep in the provider SDK.
    if (
        provider not in _LOCAL_PROVIDERS
        and "api_key" not in kwargs
        and not _has_provider_env_key(provider)
    ):
        raise ModelConfigError(
            f"provider '{provider}' for role '{role}' needs an API key — set it in "
            f"Settings → Providers, or export {_env_key_name(provider)}"
        )
    try:
        return init_chat_model(model, model_provider=provider, **kwargs)
    except ImportError as exc:
        raise ModelConfigError(
            f"provider '{provider}' needs its integration package "
            f"(pip install langchain-{provider})"
        ) from exc
    except ValueError as exc:
        raise ModelConfigError(f"unknown or unsupported provider '{provider}': {exc}") from exc


def list_models(settings: Settings) -> list[str]:
    """Ollama model names available to bind, newest-first as Ollama reports them.

    Queries the Ollama server's ``/api/tags`` (the pull-able local models). The
    configured Ollama role models are always unioned in so a model in use never
    vanishes from the list if a tag query blips. Hosted providers are listed via
    ``list_model_sources`` (they have no equivalent discovery endpoint).
    """
    # Only Ollama-bound role models belong in the Ollama list.
    configured = [
        settings.role_model(role).model
        for role in _ROLES
        if settings.role_providers.get(role, "ollama") == "ollama"
    ]
    try:
        resp = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=5.0)
        resp.raise_for_status()
        tags = resp.json().get("models", [])
        names = [str(m["name"]) for m in tags if isinstance(m, dict) and m.get("name")]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        names = []
    # Preserve Ollama's order (newest first); append any configured-but-untagged.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in [*names, *configured]:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def list_model_sources(settings: Settings) -> list[dict[str, Any]]:
    """Available models grouped by the provider they come from, e.g.
    ``[{"source": "Ollama", "models": [...]}, {"source": "Openai", "models": [...]}]``.

    Ollama is discovered live; each configured hosted provider (BYOM #21)
    contributes its curated suggestions plus any model already bound to a role.
    Empty groups are omitted so the picker never shows an empty heading."""
    groups: list[dict[str, Any]] = [{"source": "Ollama", "models": list_models(settings)}]
    for pid in settings.providers:
        if pid == "ollama":
            continue
        pcfg = settings.provider_config(pid)
        # A locked key here just means no live model list — fall back to curated suggestions
        # rather than 500-ing the whole picker (M-2).
        key = (try_decrypt(pcfg.api_key)[1] or os.environ.get(_env_key_name(pid), "") or "").strip()
        # Prefer the cached LIVE list a Test / auto-fetch populated (the models this key
        # actually grants); fall back to the curated suggestions only when absent.
        live = cached_provider_models(pid, key, pcfg.base_url) if key else None
        models = list(live) if live is not None else list(_PROVIDER_SUGGESTIONS.get(pid, []))
        for role in _ROLES:
            binding = settings.role_model(role)
            if binding.provider == pid and binding.model and binding.model not in models:
                models.append(binding.model)
        groups.append({"source": pid.capitalize(), "models": models})
    return [g for g in groups if g["models"]]


def get_embeddings(settings: Settings) -> Embeddings:
    return OllamaEmbeddings(
        model=settings.embed_model,
        base_url=settings.ollama_base_url.rstrip("/"),
        client_kwargs={"timeout": settings.ollama_timeout},
    )
