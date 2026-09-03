"""``Settings.from_env`` layering, extracted so ``_settings.py`` stays under the god-file ceiling.

The env > stored (``settings.json``) > default precedence lives here as a module-scope builder that
takes the ``Settings`` class (avoids a circular import) and returns a built instance. Behaviour is
identical to the former inline classmethod; ``Settings.from_env`` is now a thin delegator.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from mosaera_core.config._env import resolve_docker_bin
from mosaera_core.config._knobs import layer_knobs
from mosaera_core.config._parsing import (
    _parse_cost_modes,
    _parse_providers,
    _parse_reason_escalation,
    _parse_role_escalation,
    _parse_role_models,
    parse_price_map,
)
from mosaera_core.config._profiles import PROFILE_DERIVED

if TYPE_CHECKING:
    from mosaera_core.config._settings import Settings


def build_settings(cls: type[Settings], env: Mapping[str, str] | None = None) -> Settings:
    """Build a ``Settings`` from ``env`` (default ``os.environ``): env > stored > default."""
    e = os.environ if env is None else env
    home = Path(e.get("MOSAERA_HOME", ".mosaera"))
    # UI-managed settings file is a fallback below real env vars (env wins).
    # Lazy (like read_settings above): keep the base config module free of the memory
    # package's SQLAlchemy import at load time. Decrypts the at-rest global PAT (ADR-0039);
    # from_env runs on EVERY request (incl. /healthz), so a locked PAT (missing/wrong
    # MOSAERA_SECRET_KEY) must degrade to "no token" — never 500 the whole API (M-2).
    from mosaera_memory.secrets import try_decrypt

    from mosaera_core.settings_store import read_settings

    stored = read_settings(home)
    # Prices: stored table, then per-model env override (MOSAERA_MODEL_PRICES).
    prices = parse_price_map(stored.get("model_prices"))
    env_prices_raw = e.get("MOSAERA_MODEL_PRICES", "")
    if env_prices_raw.strip():
        try:
            prices.update(parse_price_map(json.loads(env_prices_raw)))
        except ValueError:
            pass
    # BYOM (#21): per-role provider + model and provider creds. Stored under
    # env — MOSAERA_MODEL_* and MOSAERA_PROVIDER_* always win over settings.json.
    stored_role_providers, stored_role_models = _parse_role_models(stored.get("role_models"))
    providers = _parse_providers(stored.get("providers"))
    role_providers = dict(stored_role_providers)
    for role, var in (
        ("pm", "MOSAERA_PROVIDER_PM"),
        ("coder", "MOSAERA_PROVIDER_CODER"),
        ("reviewer", "MOSAERA_PROVIDER_REVIEWER"),
        ("tester", "MOSAERA_PROVIDER_TESTER"),
    ):
        if e.get(var):
            role_providers[role] = e[var]
    # Cost-modes (#7): stored profiles + a default-mode override via env.
    cost_modes = _parse_cost_modes(stored.get("cost_modes"))
    default_cost_mode = (
        e.get("MOSAERA_COST_MODE") or str(stored.get("default_cost_mode") or "") or "balanced"
    )
    # Model escalation ladder (ADR-0016): stored map, with MOSAERA_ROLE_ESCALATION
    # (JSON) winning — so a headless bench run can set the ladder without a settings file.
    role_escalation = _parse_role_escalation(stored.get("role_escalation"))
    env_esc_raw = e.get("MOSAERA_ROLE_ESCALATION", "")
    if env_esc_raw.strip():
        try:
            role_escalation = _parse_role_escalation(json.loads(env_esc_raw)) or role_escalation
        except ValueError:
            pass
    # Reasoning-escalation ladder (ADR-0018): stored list, MOSAERA_REASON_ESCALATION JSON wins.
    reason_escalation = _parse_reason_escalation(stored.get("reason_escalation"))
    env_re_raw = e.get("MOSAERA_REASON_ESCALATION", "")
    if env_re_raw.strip():
        try:
            reason_escalation = (
                _parse_reason_escalation(json.loads(env_re_raw)) or reason_escalation
            )
        except ValueError:
            pass
    sandbox_backend = e.get("MOSAERA_SANDBOX", cls.sandbox_backend)
    allow_subprocess_install = e.get("MOSAERA_ALLOW_SUBPROCESS_INSTALL", "0") not in (
        "0",
        "false",
        "no",
        "",
    )
    # Env-only, and deliberately not a GENERAL_KNOB: this RELAXES a delivery-gate veto, so putting
    # it on the settings UI would let a safety control be switched off from the dashboard. Default
    # ON = today's behaviour, so its presence changes nothing until an experiment sets it.
    oracle_mutation_vetoes = e.get("MOSAERA_ORACLE_MUTATION_VETOES", "1") not in (
        "0",
        "false",
        "no",
        "",
    )
    # Env-only and diagnostic: it changes what gets RECORDED, never what gets decided, so it has
    # no place on the settings UI either. Default OFF = today's behaviour and today's cost.
    oracle_record_all_legs = e.get("MOSAERA_ORACLE_RECORD_ALL_LEGS", "") in ("1", "true", "yes")
    # Operational knobs, layered env > settings.json > profile > default (GENERAL_KNOBS).
    knobs = layer_knobs(e, stored)
    # The intent profiles (ADR-0122) are INPUTS to that layering, not runtime settings: their
    # whole effect is already present in the derived values above, and no engine code reads
    # "which profile was this". Giving `Settings` a field nothing reads is how this repo has
    # twice produced a decorative control (the charter posture; the removed `reviewer_advisory`),
    # so they are dropped here rather than carried. A run stays reconstructable from the derived
    # values, which are what actually governed it.
    for profile_field in PROFILE_DERIVED:
        knobs.pop(profile_field, None)
    # Subprocess backend: the dependency-install phase runs the TARGET repo's build
    # code (setup.py / pip hooks) on the HOST — there is no container to contain it.
    # Force install OFF on subprocess unless explicitly allowed, whatever the knob says.
    if (
        knobs["sandbox_install"]
        and sandbox_backend == "subprocess"
        and not allow_subprocess_install
    ):
        knobs["sandbox_install"] = False
        print(
            "  WARNING: dependency-install is DISABLED on the subprocess sandbox — it "
            "would run the target repo's build code on the host. Use the Docker sandbox "
            "for dependency repos, or set MOSAERA_ALLOW_SUBPROCESS_INSTALL=1 to accept "
            "the risk on trusted repos."
        )
    return cls(
        pm_model=e.get("MOSAERA_MODEL_PM") or stored_role_models.get("pm") or cls.pm_model,
        coder_model=(
            e.get("MOSAERA_MODEL_CODER") or stored_role_models.get("coder") or cls.coder_model
        ),
        reviewer_model=(
            e.get("MOSAERA_MODEL_REVIEWER")
            or stored_role_models.get("reviewer")
            or cls.reviewer_model
        ),
        tester_model=(
            e.get("MOSAERA_MODEL_TESTER") or stored_role_models.get("tester") or cls.tester_model
        ),
        critic_model=(
            e.get("MOSAERA_MODEL_CRITIC") or stored_role_models.get("critic") or cls.critic_model
        ),
        embed_model=e.get("MOSAERA_MODEL_EMBED", cls.embed_model),
        home=home,
        sandbox_backend=sandbox_backend,
        oracle_mutation_vetoes=oracle_mutation_vetoes,
        oracle_record_all_legs=oracle_record_all_legs,
        sandbox_image=e.get("MOSAERA_SANDBOX_IMAGE", cls.sandbox_image),
        scan_image=e.get("MOSAERA_SCAN_IMAGE", cls.scan_image),
        # Env wins over the persisted settings.json toggle (admin-set via the UI).
        # ADR-0094 measurement widening. ENV-ONLY BY DESIGN: no UI toggle and no settings.json
        # entry, because the production rung deliberately never reads it. Surfacing a dashboard
        # switch wired to nothing is this repo's most-repeated defect (F74), so it is not surfaced.
        layer2_admit_structural_claim=e.get("MOSAERA_LAYER2_ADMIT_STRUCTURAL_CLAIM", "")
        not in ("", "0", "false", "no"),
        delete_tool_enabled=(
            e["MOSAERA_DELETE_TOOL"] not in ("0", "false", "no")
            if e.get("MOSAERA_DELETE_TOOL")
            else bool(stored.get("delete_tool_enabled", False))
        ),
        docker_bin=resolve_docker_bin(e.get("MOSAERA_DOCKER_BIN")),
        db_url=e.get("MOSAERA_DB_URL") or None,
        gitlab_url=(
            e.get("MOSAERA_GITLAB_URL") or stored.get("gitlab_url") or cls.gitlab_url
        ).rstrip("/"),
        gitlab_token=(
            e.get("MOSAERA_GITLAB_TOKEN") or try_decrypt(stored.get("gitlab_token"))[1] or None
        ),
        # ADR-0104 OAuth "Connect" (amended): env OR stored, same layering as gitlab_token above —
        # the client SECRET is encrypted at rest (try_decrypt), client_id + base_url are not secret
        # so they store plaintext. Env wins so a deployment can still pin these. base_url is the
        # public origin for the exact redirect_uri (trailing slash stripped).
        gitlab_oauth_client_id=(
            e.get("MOSAERA_GITLAB_OAUTH_CLIENT_ID") or stored.get("gitlab_oauth_client_id") or None
        ),
        gitlab_oauth_client_secret=(
            e.get("MOSAERA_GITLAB_OAUTH_CLIENT_SECRET")
            or try_decrypt(stored.get("gitlab_oauth_client_secret"))[1]
            or None
        ),
        base_url=(e.get("MOSAERA_BASE_URL") or stored.get("base_url") or "").rstrip("/") or None,
        # GitHub App (ADR-0114) — same env-over-stored layering as the OAuth creds above. The
        # PRIVATE KEY is encrypted at rest (try_decrypt); app id, slug and api url are not
        # secret and store plaintext.
        github_app_id=(e.get("MOSAERA_GITHUB_APP_ID") or stored.get("github_app_id") or None),
        github_app_private_key=(
            e.get("MOSAERA_GITHUB_APP_PRIVATE_KEY")
            or try_decrypt(stored.get("github_app_private_key"))[1]
            or None
        ),
        github_app_slug=(e.get("MOSAERA_GITHUB_APP_SLUG") or stored.get("github_app_slug") or None),
        github_api_url=(
            e.get("MOSAERA_GITHUB_API_URL") or stored.get("github_api_url") or cls.github_api_url
        ).rstrip("/"),
        # ADR-0120: the same App's user-authorization pair. Secret is env OR stored-encrypted,
        # env wins — the precedence every other credential here follows (ADR-0005).
        github_oauth_client_id=(
            e.get("MOSAERA_GITHUB_OAUTH_CLIENT_ID") or stored.get("github_oauth_client_id") or None
        ),
        github_oauth_client_secret=(
            e.get("MOSAERA_GITHUB_OAUTH_CLIENT_SECRET")
            or try_decrypt(stored.get("github_oauth_client_secret"))[1]
            or None
        ),
        github_web_url=(
            e.get("MOSAERA_GITHUB_WEB_URL") or stored.get("github_web_url") or cls.github_web_url
        ).rstrip("/"),
        model_prices=prices,
        role_providers=role_providers,
        providers=providers,
        cost_modes=cost_modes,
        default_cost_mode=default_cost_mode,
        role_escalation=role_escalation,
        reason_escalation=reason_escalation,
        **knobs,
    )
