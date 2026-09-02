"""Runtime settings, sourced from environment variables (see docs/onboarding/).

Facade over the config package: the god-file ``config.py`` was split into cohesive
modules (``_types`` leaf → ``_parsing`` → ``_knobs`` / ``_env`` → ``_settings``), and
this ``__init__`` re-exports the complete public surface so every existing
``from mosaera_core.config import …`` keeps working unchanged.
"""

from __future__ import annotations

from mosaera_core.config._env import (
    _apply_env_file,
    _cli_works,
    load_env,
    resolve_docker_bin,
    undeclared_bundled_db,
)
from mosaera_core.config._knobs import (
    GENERAL_KNOBS,
    Knob,
    _coerce_knob,
    _layer_knob,
    coerce_general_patch,
    layer_knobs,
    selected_profiles,
)
from mosaera_core.config._parsing import (
    _env_int,
    _parse_cost_modes,
    _parse_providers,
    _parse_reason_escalation,
    _parse_role_escalation,
    _parse_role_models,
    parse_price_map,
)
from mosaera_core.config._posture import apply_oracle_posture
from mosaera_core.config._profiles import (
    NEVER_DERIVED,
    PROFILE_DERIVED,
    derived_by,
    resolve_profiles,
)
from mosaera_core.config._settings import Settings
from mosaera_core.config._types import (
    _ROLES,
    DEFAULT_OLLAMA_BASE_URL,
    ProviderConfig,
    Role,
    RoleModel,
)
from mosaera_core.config._view import general_settings_view

__all__ = [
    "DEFAULT_OLLAMA_BASE_URL",
    "GENERAL_KNOBS",
    "NEVER_DERIVED",
    "PROFILE_DERIVED",
    "_ROLES",
    "Knob",
    "ProviderConfig",
    "Role",
    "RoleModel",
    "Settings",
    "_apply_env_file",
    "_cli_works",
    "_coerce_knob",
    "_env_int",
    "_layer_knob",
    "_parse_cost_modes",
    "_parse_providers",
    "_parse_reason_escalation",
    "_parse_role_escalation",
    "_parse_role_models",
    "apply_oracle_posture",
    "coerce_general_patch",
    "derived_by",
    "general_settings_view",
    "layer_knobs",
    "load_env",
    "parse_price_map",
    "resolve_docker_bin",
    "resolve_profiles",
    "selected_profiles",
    "undeclared_bundled_db",
]
