"""Role-binding queries over ``Settings``, extracted so ``_settings.py`` stays under the
god-file ceiling — the same split ``_settings.py`` → ``_from_env.py`` already makes, and for
the same reason.

Free functions taking the settings object rather than methods, so this module has no import
cycle back into the dataclass. ``Settings`` keeps thin delegators, so every call site is
unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mosaera_core.config._settings import Settings
    from mosaera_core.models import Role


def disallowed_cloud_roles(settings: Settings, roles: Sequence[Role]) -> list[tuple[Any, str, str]]:
    """The active role bindings that an AUTONOMOUS run may NOT use — cloud models blocked
    because off-box egress isn't consented or the model isn't priced (ADR-0024). Returns
    ``(role, provider, model)`` for each; empty when everything is allowed. Local bindings
    are always allowed. Kept out of ``models.py`` so the run-submit gate stays a pure
    Settings query; the shared predicate lives in ``models.cloud_tier_allowed``."""
    from mosaera_core.models import cloud_tier_allowed

    blocked: list[tuple[Any, str, str]] = []
    for role in roles:
        b = settings.role_model(role)
        if not cloud_tier_allowed(settings, b.provider, b.model):
            blocked.append((role, b.provider, b.model))
    return blocked


def role_model_for(settings: Settings, mode: str, role: Role) -> Any:
    """The binding ``role`` resolves to under a SPECIFIC cost-mode (#7). The mode may override
    the binding; any role a mode omits falls back to the base BYOM binding — model name from the
    flat ``*_model`` fields (back-compat with MOSAERA_MODEL_*), provider from ``role_providers``
    (default ``ollama``)."""
    from mosaera_core.config._types import RoleModel

    override = settings.cost_modes.get(mode, {}).get(role)
    if override is not None:
        return override
    model = {
        "pm": settings.pm_model,
        "coder": settings.coder_model,
        "reviewer": settings.reviewer_model,
        "tester": settings.tester_model,
        "critic": settings.critic_model,
    }[role]
    return RoleModel(provider=settings.role_providers.get(role, "ollama"), model=model)


def held_out_ok(settings: Settings) -> bool:
    """Whether the critic is a genuinely INDEPENDENT check — a DIFFERENT model from the coder
    (#60, ADR-0065). A critic bound to the same ``(provider, model)`` as the coder is not held
    out: it shares the coder's blind spots, so its judgement adds nothing. Compares the ACTIVE
    bindings (RoleModel is frozen → value equality). The critic is veto-only, so a non-held-out
    critic is a no-op efficacy loss, never a safety hole — the run-submit path surfaces it and
    the critic node skips (never a false ship either way)."""
    return settings.role_model("critic") != settings.role_model("coder")
