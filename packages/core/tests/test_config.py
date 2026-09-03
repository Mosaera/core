import dataclasses
import os
from pathlib import Path

import pytest
from mosaera_core.config import ProviderConfig, RoleModel, Settings, load_env, resolve_docker_bin


def test_defaults(tmp_path: Path) -> None:
    # Isolate MOSAERA_HOME so a real .mosaera/settings.json can't leak into these DEFAULT
    # assertions (role models + knobs are stored there). See test_allow_cloud_egress below.
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.pm_model == "gpt-oss:20b"
    assert s.coder_model == "qwen3-coder:30b"
    assert s.home == tmp_path
    assert s.workspaces_dir == tmp_path / "workspaces"
    assert s.sandbox_backend == "docker"
    # docker_bin is auto-detected (docker, else docker.exe on WSL-without-integration).
    assert s.docker_bin in ("docker", "docker.exe")
    # Lifecycle bounds default on.
    # Raised 16384 -> 32768 (2026-08-07): 16k truncated a tool-using agent mid-generation and
    # the failure read as incapacity. See `_knobs.py` for the measured token counts.
    assert s.ollama_num_ctx == 32768
    assert s.ollama_timeout == 300.0
    assert s.run_max_seconds == 3600


def test_default_home_is_dot_mosaera() -> None:
    # With no MOSAERA_HOME override the default home is `.mosaera` (relative to cwd). `home`
    # is env-derived only — never read from settings.json — so this is hermetic as written.
    assert Settings.from_env(env={}).home == Path(".mosaera")


def test_from_env_tolerates_malformed_numeric_vars(tmp_path: Path) -> None:
    # A config typo (empty / whitespace / non-numeric) must degrade to the default,
    # never raise — from_env runs at startup and on every run submit.
    s = Settings.from_env(
        env={
            "MOSAERA_HOME": str(tmp_path),  # isolate stored settings from the default asserts
            "MOSAERA_MAX_ITERATIONS": "",  # empty
            "MOSAERA_STALL_LIMIT": "x",  # non-numeric
            "MOSAERA_RUN_MAX_SECONDS": " ",  # whitespace
            "MOSAERA_OLLAMA_TIMEOUT": "abc",  # bad float
            "MOSAERA_RUN_MAX_TOKENS": "notanumber",  # bad optional ceiling → off
        }
    )
    assert s.max_iterations == 8  # the DEFAULT (raised 3->8 2026-08-07); intent = falls back
    assert s.stall_limit == 3
    assert s.run_max_seconds == 3600
    assert s.ollama_timeout == 300.0
    assert s.run_max_tokens is None  # malformed optional stays None (not a crash)


def test_delete_tool_flag_defaults_off_and_parses_env(tmp_path: Path) -> None:
    home = {"MOSAERA_HOME": str(tmp_path)}
    assert Settings.from_env(env=home).delete_tool_enabled is False  # opt-in
    assert Settings.from_env(env={**home, "MOSAERA_DELETE_TOOL": "1"}).delete_tool_enabled is True
    assert Settings.from_env(env={**home, "MOSAERA_DELETE_TOOL": "0"}).delete_tool_enabled is False


def test_allow_cloud_egress_defaults_off_and_parses_env(tmp_path: Path) -> None:
    # Isolate MOSAERA_HOME to an empty dir: `from_env(env={})` still layers the on-disk
    # .mosaera/settings.json (env > stored > default), so without this the test reads the
    # developer's real saved setting instead of the DEFAULT it means to assert.
    home = {"MOSAERA_HOME": str(tmp_path)}
    assert Settings.from_env(env=home).allow_cloud_egress is False  # local-only by default
    on = {**home, "MOSAERA_ALLOW_CLOUD_EGRESS": "1"}
    assert Settings.from_env(env=on).allow_cloud_egress is True


def test_cloud_tier_allowed_requires_consent_and_price(tmp_path: Path) -> None:
    from mosaera_core.models import cloud_tier_allowed

    # Isolate: a real settings.json with allow_cloud_egress or model_prices would flip these.
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})  # egress OFF, no prices
    # Local is always fine, no consent/price needed.
    assert cloud_tier_allowed(s, "ollama", "qwen3-coder:30b") is True
    # Cloud is blocked without consent.
    assert cloud_tier_allowed(s, "anthropic", "claude-sonnet-4-6") is False
    # Consent alone isn't enough — an unpriced cloud model evades the USD cap.
    consented = dataclasses.replace(s, allow_cloud_egress=True)
    assert cloud_tier_allowed(consented, "anthropic", "claude-sonnet-4-6") is False
    # Consent + a price → allowed.
    priced = dataclasses.replace(consented, model_prices={"claude-sonnet-4-6": (3.0, 15.0)})
    assert cloud_tier_allowed(priced, "anthropic", "claude-sonnet-4-6") is True


def test_shadow_pricing_a_local_model_does_not_widen_the_cloud_gate(tmp_path: Path) -> None:
    """Shadow pricing exists to make LOCAL burn visible. `cloud_tier_allowed` reads the same
    `model_prices` table, so pricing local models must not become a back door to autonomous cloud
    egress — a cost change quietly relaxing a security gate is the shape worth testing for."""
    from mosaera_core.models import cloud_tier_allowed

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    shadowed = dataclasses.replace(s, model_prices={"qwen3-coder:30b": (3.0, 15.0)})

    # The local model is priced; a cloud model is still refused on both counts.
    assert cloud_tier_allowed(shadowed, "anthropic", "claude-sonnet-4-6") is False
    consented = dataclasses.replace(shadowed, allow_cloud_egress=True)
    assert cloud_tier_allowed(consented, "anthropic", "claude-sonnet-4-6") is False


def test_a_priced_name_served_both_locally_and_in_the_cloud_still_needs_consent(
    tmp_path: Path,
) -> None:
    """The one way shadow pricing COULD widen the gate: an operator prices a model name for its
    local copy while the same name is also offered by a cloud provider. Consent is what still
    stops it — recorded here so the residual is a known, tested boundary rather than a surprise."""
    from mosaera_core.models import cloud_tier_allowed

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    shadowed = dataclasses.replace(s, model_prices={"gpt-oss:20b": (3.0, 15.0)})

    assert cloud_tier_allowed(shadowed, "ollama", "gpt-oss:20b") is True  # local, as before
    assert cloud_tier_allowed(shadowed, "openai", "gpt-oss:20b") is False  # egress not consented


def _with_provider(s: Settings, base_url: str | None = None, on_box: bool = False) -> Settings:
    """``s`` with the ``openai`` provider reconfigured — the local-inference-server shape."""
    return dataclasses.replace(
        s, providers={"openai": ProviderConfig(base_url=base_url, on_box=on_box)}
    )


def test_declared_loopback_endpoint_is_on_box_not_cloud(tmp_path: Path) -> None:
    """ADR-0024 (amended 2026-07-28): a local OpenAI-compatible server (vLLM) is reached via
    the `openai` provider, so it used to be classified as CLOUD and refused on autonomous runs
    unless the operator consented to off-box egress for traffic that never leaves the box."""
    from mosaera_core.models import cloud_tier_allowed

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})  # egress OFF, no prices
    declared_loopback = _with_provider(s, base_url="http://localhost:8001/v1", on_box=True)
    # The new capability: no consent, no price, still allowed — it is on this machine.
    assert cloud_tier_allowed(declared_loopback, "openai", "qwen3-coder-fp8") is True
    # Other loopback spellings: IPv6, the whole 127.0.0.0/8 block, and the IPv4-mapped
    # form (`::ffff:127.0.0.1` really does resolve to this machine — verified against
    # getaddrinfo, so classing it on-box is correct, not a parser artefact).
    for url in (
        "http://[::1]:8001/v1",
        "http://127.0.0.1:8001/v1",
        "http://127.5.5.5:8001",
        "http://[::ffff:127.0.0.1]:8001/v1",
        "http://evil.com@127.0.0.1/v1",  # userinfo is not the host; the HOST is loopback
    ):
        assert (
            cloud_tier_allowed(_with_provider(s, base_url=url, on_box=True), "openai", "m") is True
        )


def test_on_box_requires_both_conditions(tmp_path: Path) -> None:
    """Deny-by-default: loopback alone and the declaration alone each grant nothing. Loopback is
    not evidence of local execution — a LiteLLM-style proxy binds to loopback and forwards to a
    hosted API (the tracked roadmap debt item) — that would evade consent AND the USD cap."""
    from mosaera_core.models import cloud_tier_allowed

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    # Loopback WITHOUT the operator's declaration → still cloud.
    undeclared = _with_provider(s, base_url="http://localhost:8001/v1")
    assert cloud_tier_allowed(undeclared, "openai", "gpt-4o") is False
    # The declaration on a HOSTED url → grants nothing (can't tick your way to an exemption).
    hosted = _with_provider(s, base_url="https://api.openai.com/v1", on_box=True)
    assert cloud_tier_allowed(hosted, "openai", "gpt-4o") is False
    # Declared with NO endpoint at all → the provider's real cloud API; still gated.
    assert cloud_tier_allowed(_with_provider(s, on_box=True), "openai", "gpt-4o") is False
    # An unconfigured provider is untouched by any of this.
    assert cloud_tier_allowed(s, "openai", "gpt-4o") is False


def test_loopback_detection_rejects_spoofed_hosts(tmp_path: Path) -> None:
    """The check parses the URL and tests the ADDRESS — never a substring/prefix match, which
    these hosts would defeat. A false positive here is a silent egress-gate bypass."""
    from mosaera_core.models import cloud_tier_allowed, is_loopback_url

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    spoofs = (
        "http://127.0.0.1.evil.com/v1",  # loopback as a subdomain label
        "http://evil.com/?redirect=127.0.0.1",  # loopback in the query
        "http://evil.com/127.0.0.1/v1",  # loopback in the path
        "http://localhost.evil.com/v1",  # name as a subdomain label
        "http://notlocalhost/v1",
        "http://10.0.0.5:8001/v1",  # private LAN — off THIS box, so not on-box
        "http://192.168.1.20:8001/v1",
        # Loopback in the USERINFO, not the host — httpx connects to evil.com, so must we.
        "http://127.0.0.1@evil.com/v1",
        "http://localhost@evil.com/v1",
        "http://localhost:8001@evil.com/v1",
        "http://[::ffff:8.8.8.8]:8001/v1",  # IPv4-mapped, but mapped to a PUBLIC address
        "http://0.0.0.0:8001/v1",  # all-interfaces is not loopback
        "http://2130706433/v1",  # decimal-encoded 127.0.0.1 — fail closed
    )
    for url in spoofs:
        assert is_loopback_url(url) is False, url
        assert (
            cloud_tier_allowed(_with_provider(s, base_url=url, on_box=True), "openai", "m") is False
        )
    assert is_loopback_url(None) is False
    assert is_loopback_url("") is False
    assert is_loopback_url("not a url") is False


def test_disallowed_cloud_roles_enumerates_blocked_bindings(tmp_path: Path) -> None:
    # Coder bound to an unpriced cloud model, reviewer local. Only the coder is blocked.
    s = dataclasses.replace(
        Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}),
        role_providers={"coder": "anthropic"},
        coder_model="claude-x",
    )
    blocked = s.disallowed_cloud_roles(["pm", "coder", "reviewer"])
    assert blocked == [("coder", "anthropic", "claude-x")]
    # Consent + price clears it.
    ok = dataclasses.replace(s, allow_cloud_egress=True, model_prices={"claude-x": (1.0, 2.0)})
    assert ok.disallowed_cloud_roles(["pm", "coder", "reviewer"]) == []


def test_disallowed_cloud_roles_gates_a_cloud_critic(tmp_path: Path) -> None:
    # #60 (ADR-0065): a held-out critic bound to an unpriced/unconsented CLOUD model must be
    # blocked for an autonomous run — it sends repo content (spec/diff/test output) off-box, so it
    # is egress-gated exactly like the coder/tester (the _launch gate includes it when enabled).
    s = dataclasses.replace(
        Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}),
        role_providers={"critic": "anthropic"},
        critic_model="claude-sonnet-5",
    )
    assert s.disallowed_cloud_roles(["critic"]) == [("critic", "anthropic", "claude-sonnet-5")]
    ok = dataclasses.replace(
        s, allow_cloud_egress=True, model_prices={"claude-sonnet-5": (3.0, 15.0)}
    )
    assert ok.disallowed_cloud_roles(["critic"]) == []


def test_hard_budget_caps_parse_and_default_off(tmp_path: Path) -> None:
    home = {"MOSAERA_HOME": str(tmp_path)}
    assert Settings.from_env(env=home).run_hard_max_usd is None
    assert Settings.from_env(env=home).run_hard_max_tokens is None
    s = Settings.from_env(
        env={**home, "MOSAERA_RUN_HARD_MAX_USD": "5", "MOSAERA_RUN_HARD_MAX_TOKENS": "9000"}
    )
    assert s.run_hard_max_usd == 5.0 and s.run_hard_max_tokens == 9000


def test_deliver_unverified_flag_defaults_off(tmp_path: Path) -> None:
    home = {"MOSAERA_HOME": str(tmp_path)}
    assert Settings.from_env(env=home).deliver_unverified is False
    assert (
        Settings.from_env(env={**home, "MOSAERA_DELIVER_UNVERIFIED": "1"}).deliver_unverified
        is True
    )


def test_sandbox_backend_override() -> None:
    s = Settings.from_env(env={"MOSAERA_SANDBOX": "subprocess", "MOSAERA_DOCKER_BIN": "podman"})
    assert s.sandbox_backend == "subprocess"
    assert s.docker_bin == "podman"  # explicit non-default value is honored verbatim


def test_subprocess_install_disabled_by_default(tmp_path: Path) -> None:
    # Subprocess install runs the target repo's build code on the host, so it is
    # OFF by default — even though MOSAERA_SANDBOX_INSTALL defaults to on.
    env = {"MOSAERA_HOME": str(tmp_path)}
    sub = Settings.from_env(env={**env, "MOSAERA_SANDBOX": "subprocess"})
    assert sub.sandbox_backend == "subprocess" and sub.sandbox_install is False
    # ...unless explicitly opted in.
    opted = Settings.from_env(
        env={**env, "MOSAERA_SANDBOX": "subprocess", "MOSAERA_ALLOW_SUBPROCESS_INSTALL": "1"}
    )
    assert opted.sandbox_install is True
    # Docker (real containment) is unaffected — install stays on.
    docker = Settings.from_env(env=env)
    assert docker.sandbox_backend == "docker" and docker.sandbox_install is True


def test_resolve_docker_bin_explicit_wins() -> None:
    assert resolve_docker_bin("docker.exe") == "docker.exe"
    assert resolve_docker_bin("podman") == "podman"
    # None or the default "docker" triggers auto-detect (result depends on PATH).
    assert resolve_docker_bin(None) in ("docker", "docker.exe")
    assert resolve_docker_bin("docker") in ("docker", "docker.exe")


def test_load_env_reads_file_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(
        '# comment\nMOSAERA_TEST_A="from-file"\nexport MOSAERA_TEST_B=bee\n', encoding="utf-8"
    )
    monkeypatch.delenv("MOSAERA_TEST_A", raising=False)
    monkeypatch.setenv("MOSAERA_TEST_B", "real-env-wins")
    load_env(start=tmp_path)
    assert os.environ["MOSAERA_TEST_A"] == "from-file"
    assert os.environ["MOSAERA_TEST_B"] == "real-env-wins"


def test_env_overrides() -> None:
    s = Settings.from_env(
        env={
            "MOSAERA_OLLAMA_BASE_URL": "http://10.0.0.5:11434",
            "MOSAERA_MODEL_CODER": "other-model:7b",
            "MOSAERA_HOME": "/data/mosaera-home",
            "MOSAERA_SANDBOX_TIMEOUT": "60",
            "MOSAERA_MAX_ITERATIONS": "5",
            "MOSAERA_OLLAMA_NUM_CTX": "32768",
            "MOSAERA_OLLAMA_TIMEOUT": "120.5",
            "MOSAERA_RUN_MAX_SECONDS": "900",
        }
    )
    assert s.ollama_base_url == "http://10.0.0.5:11434"
    assert s.coder_model == "other-model:7b"
    assert s.home == Path("/data/mosaera-home")
    assert s.sandbox_timeout == 60
    assert s.max_iterations == 5
    assert s.ollama_num_ctx == 32768
    assert s.ollama_timeout == 120.5
    assert s.run_max_seconds == 900


def test_run_budget_from_env(tmp_path: Path) -> None:
    # Budget ceilings are opt-in: absent → None (off), present → parsed.
    off = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert off.run_max_usd is None and off.run_max_tokens is None
    assert off.run_max_tool_calls is None
    s = Settings.from_env(
        env={
            "MOSAERA_HOME": str(tmp_path),
            "MOSAERA_RUN_MAX_USD": "0.50",
            "MOSAERA_RUN_MAX_TOKENS": "200000",
            "MOSAERA_RUN_MAX_TOOL_CALLS": "40",
        }
    )
    assert s.run_max_usd == 0.50
    assert s.run_max_tokens == 200000
    assert s.run_max_tool_calls == 40


def test_model_prices_from_env(tmp_path: Path) -> None:
    s = Settings.from_env(
        env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_MODEL_PRICES": '{"gpt-4o": [2.5, 10.0]}'}
    )
    assert s.model_prices == {"gpt-4o": (2.5, 10.0)}


def test_model_prices_stored_with_env_override(tmp_path: Path) -> None:
    from mosaera_core.settings_store import write_settings

    write_settings(tmp_path, {"model_prices": {"a": [1.0, 2.0], "b": [3.0, 4.0]}})
    # env overrides model "a" per-model; stored "b" survives.
    s = Settings.from_env(
        env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_MODEL_PRICES": '{"a": [9.0, 9.0]}'}
    )
    assert s.model_prices == {"a": (9.0, 9.0), "b": (3.0, 4.0)}


def test_model_prices_tolerates_garbage(tmp_path: Path) -> None:
    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}).model_prices == {}
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_MODEL_PRICES": "not json"})
    assert s.model_prices == {}


# --- BYOM (#21): per-role provider + provider creds -----------------------


def test_role_providers_default_to_ollama(tmp_path: Path) -> None:
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    for role in ("pm", "coder", "reviewer"):
        assert s.role_model(role).provider == "ollama"  # type: ignore[arg-type]
    assert s.providers == {}
    # ollama's config falls back to the legacy base_url.
    assert s.provider_config("ollama").base_url == s.ollama_base_url


def test_role_provider_env_override(tmp_path: Path) -> None:
    s = Settings.from_env(
        env={
            "MOSAERA_HOME": str(tmp_path),
            "MOSAERA_PROVIDER_CODER": "openai",
            "MOSAERA_MODEL_CODER": "gpt-4o",
        }
    )
    assert s.role_model("coder").provider == "openai"
    assert s.role_model("coder").model == "gpt-4o"
    assert s.role_model("pm").provider == "ollama"  # others untouched


def test_providers_and_roles_from_settings_file(tmp_path: Path) -> None:
    from mosaera_core.settings_store import write_settings

    write_settings(
        tmp_path,
        {
            "role_models": {"coder": {"provider": "openai", "model": "gpt-4o"}},
            "providers": {"openai": {"api_key": "sk-1", "base_url": "https://x/v1"}},
        },
    )
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert s.role_model("coder").provider == "openai"
    assert s.role_model("coder").model == "gpt-4o"
    assert s.provider_config("openai").api_key == "sk-1"
    assert s.provider_config("openai").base_url == "https://x/v1"
    # Absent on_box reads as False → a pre-existing settings.json keeps today's
    # cloud classification unchanged (ADR-0024 compatibility).
    assert s.provider_config("openai").on_box is False


def test_on_box_parses_strictly_from_settings_file(tmp_path: Path) -> None:
    """Only a real JSON ``true`` declares an endpoint on-box. A truthy STRING must not —
    ``bool("false")`` is True, and that would hand out an egress-gate exemption by typo."""
    from mosaera_core.settings_store import write_settings

    def _on_box(value: object) -> bool:
        write_settings(
            tmp_path,
            {"providers": {"openai": {"base_url": "http://localhost:8001/v1", "on_box": value}}},
        )
        return (
            Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}).provider_config("openai").on_box
        )

    assert _on_box(True) is True
    junk_values: tuple[object, ...] = (False, "false", "true", "yes", 1, 0, None, [], "on")
    for junk in junk_values:
        assert _on_box(junk) is False, junk


def test_env_provider_wins_over_settings_file(tmp_path: Path) -> None:
    from mosaera_core.settings_store import write_settings

    write_settings(tmp_path, {"role_models": {"coder": {"provider": "openai", "model": "gpt-4o"}}})
    s = Settings.from_env(
        env={
            "MOSAERA_HOME": str(tmp_path),
            "MOSAERA_PROVIDER_CODER": "anthropic",
            "MOSAERA_MODEL_CODER": "claude-x",
        }
    )
    assert s.role_model("coder").provider == "anthropic"
    assert s.role_model("coder").model == "claude-x"


# --- Cost-modes (#7): per-role routing profiles -------------------------


def test_no_cost_modes_is_identical_to_base(tmp_path: Path) -> None:
    # Back-compat: no cost_modes configured ⇒ role_model == base BYOM binding.
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert s.cost_modes == {}
    assert s.default_cost_mode == "balanced"
    assert s.role_model("coder") == RoleModel("ollama", s.coder_model)


def test_cost_mode_overrides_role_else_falls_back() -> None:
    s = Settings(
        cost_modes={"premium": {"coder": RoleModel("anthropic", "claude-x")}},
        providers={"anthropic": ProviderConfig(api_key="sk")},
        active_cost_mode="premium",
    )
    assert s.role_model("coder") == RoleModel("anthropic", "claude-x")  # overridden
    assert s.role_model("pm").provider == "ollama"  # unset role → base fallback


def test_active_cost_mode_wins_over_default() -> None:
    s = Settings(
        cost_modes={
            "economy": {"coder": RoleModel("ollama", "tiny")},
            "premium": {"coder": RoleModel("openai", "gpt-4o")},
        },
        providers={"openai": ProviderConfig(api_key="sk")},
        default_cost_mode="economy",
    )
    assert s.role_model("coder").model == "tiny"  # default mode applies
    active = dataclasses.replace(s, active_cost_mode="premium")
    assert active.role_model("coder").model == "gpt-4o"  # per-run overlay wins


def test_cost_modes_from_settings_file_and_env_default(tmp_path: Path) -> None:
    from mosaera_core.settings_store import write_settings

    write_settings(
        tmp_path,
        {
            "cost_modes": {"premium": {"coder": {"provider": "openai", "model": "gpt-4o"}}},
            "default_cost_mode": "premium",
        },
    )
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert s.default_cost_mode == "premium"
    assert s.role_model_for("premium", "coder") == RoleModel("openai", "gpt-4o")
    # MOSAERA_COST_MODE overrides the stored default.
    s2 = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_COST_MODE": "economy"})
    assert s2.default_cost_mode == "economy"


def test_mr_granularity_defaults_item_and_rejects_out_of_set(tmp_path: Path) -> None:
    from mosaera_core.config import coerce_general_patch

    # Default is per-item stacked MRs (the reviewable/revertable shape).
    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path / "empty")}).mr_granularity == "item"
    # Env override to the whole-project shape is honored.
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_MR_GRANULARITY": "project"})
    assert s.mr_granularity == "project"
    # Enumerable → a dropdown value; a typo is rejected at the write layer (the hard rule).
    assert coerce_general_patch({"mr_granularity": "item"}) == {"mr_granularity": "item"}
    with pytest.raises(ValueError, match="mr_granularity"):
        coerce_general_patch({"mr_granularity": "per-file"})


def test_run_quota_per_day_layers_and_rejects_negative(tmp_path: Path) -> None:
    """#37: the daily run quota is a UI knob (env > stored > default). A bounded quantity — 0 = no
    cap, negatives rejected at the write layer — not an enumerable dropdown."""
    from mosaera_core.config import coerce_general_patch
    from mosaera_core.settings_store import write_settings

    # Default off (no cap).
    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path / "empty")}).run_quota_per_day == 0
    # Stored (UI) value applies with the env unset.
    write_settings(tmp_path, {"run_quota_per_day": 50})
    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}).run_quota_per_day == 50
    # Env wins over stored.
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_RUN_QUOTA_PER_DAY": "10"})
    assert s.run_quota_per_day == 10
    # Bounded: the write path rejects a negative (coerce), 0 is a legal explicit "no cap".
    assert coerce_general_patch({"run_quota_per_day": 0}) == {"run_quota_per_day": 0}
    with pytest.raises(ValueError, match="run_quota_per_day"):
        coerce_general_patch({"run_quota_per_day": -5})


def test_general_knobs_layer_env_over_stored_over_default(tmp_path: Path) -> None:
    from mosaera_core.config import GENERAL_KNOBS
    from mosaera_core.settings_store import _ALLOWED_KEYS, write_settings

    # every surfaced knob is on the persistence allow-list (no silent drop)
    assert {k.field for k in GENERAL_KNOBS} <= _ALLOWED_KEYS

    # stored value applies when the env var is unset (incl. a bool False and an optional)
    write_settings(
        tmp_path,
        {"max_iterations": 7, "run_max_usd": 2.5, "stall_detection_enabled": False},
    )
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert s.max_iterations == 7
    assert s.run_max_usd == 2.5
    assert s.stall_detection_enabled is False

    # env always wins over stored
    s2 = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_MAX_ITERATIONS": "9"})
    assert s2.max_iterations == 9

    # neither set → class default
    s3 = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path / "empty")})
    assert s3.review_max_fixes == 2
    assert s3.run_max_usd is None


def test_reason_on_stall_knobs(tmp_path: Path) -> None:
    # Reason-before-park (ADR-0017): opt-in, single pass by default.
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert s.reason_on_stall_enabled is False
    assert s.max_reason_attempts == 1
    s2 = Settings.from_env(
        env={
            "MOSAERA_HOME": str(tmp_path),
            "MOSAERA_REASON_ON_STALL": "1",
            "MOSAERA_MAX_REASON_ATTEMPTS": "2",
        }
    )
    assert s2.reason_on_stall_enabled is True
    assert s2.max_reason_attempts == 2


def test_reason_escalation_ladder(tmp_path: Path) -> None:
    from mosaera_core.settings_store import _ALLOWED_KEYS, write_settings

    # Default: empty (opt-in), and on the persistence allow-list.
    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}).reason_escalation == []
    assert "reason_escalation" in _ALLOWED_KEYS

    # Env JSON parses an ordered list of tiers.
    s = Settings.from_env(
        env={
            "MOSAERA_HOME": str(tmp_path),
            "MOSAERA_REASON_ESCALATION": (
                '[{"provider":"ollama","model":"deepseek-r1:32b"},'
                ' {"provider":"ollama","model":"qwen2.5-coder:32b"}]'
            ),
        }
    )
    assert s.reason_escalation == [
        RoleModel(provider="ollama", model="deepseek-r1:32b"),
        RoleModel(provider="ollama", model="qwen2.5-coder:32b"),
    ]

    # Malformed JSON → [] (tolerant, never crashes a run submit).
    bad = Settings.from_env(
        env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_REASON_ESCALATION": "not json"}
    )
    assert bad.reason_escalation == []

    # settings.json round-trip (env unset).
    write_settings(
        tmp_path, {"reason_escalation": [{"provider": "ollama", "model": "gpt-oss:20b"}]}
    )
    stored = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    assert stored.reason_escalation == [RoleModel(provider="ollama", model="gpt-oss:20b")]


def test_pm_step_limit_knob(tmp_path: Path) -> None:
    # default, then env override (bounds the tool-using planner's read-tool loop).
    # The DEFAULT was raised 12 -> 20 on 2026-08-07 (F39/#71): at 12 the planner spent the whole
    # budget reading the repo and never wrote a plan. The override value is deliberately NOT the
    # default, or the second assertion would pass without the env var doing anything.
    assert Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)}).pm_step_limit == 20
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_PM_STEP_LIMIT": "30"})
    assert s.pm_step_limit == 30


def test_coerce_general_patch_validates(tmp_path: Path) -> None:
    import pytest
    from mosaera_core.config import coerce_general_patch

    assert coerce_general_patch({"max_iterations": "5", "bogus": 1}) == {"max_iterations": 5}
    assert coerce_general_patch({"run_max_usd": None}) == {"run_max_usd": None}  # unset
    with pytest.raises(ValueError, match="run_max_usd"):
        coerce_general_patch({"run_max_usd": -1})


def test_coerce_general_patch_report_names_what_it_dropped() -> None:
    """#task-9/S4: the honest variant never raises for a benign skip — it REPORTS why, so a
    caller can tell the operator instead of silently applying a partial patch as "Saved"."""
    from mosaera_core.config import coerce_general_patch_report

    applied, rejected = coerce_general_patch_report(
        {"max_iterations": "5", "bogus": 1, "run_max_usd": "not-a-number"}
    )
    assert applied == {"max_iterations": 5}
    assert rejected == {
        "bogus": "unknown setting",
        "run_max_usd": "blank or invalid value — left unchanged",
    }
    # A genuinely INVALID value (negative / out-of-choices) is still named, not silently
    # dropped — the route layer is what decides to 400 on it instead of applying the rest.
    applied2, rejected2 = coerce_general_patch_report({"run_max_usd": -1, "max_iterations": 5})
    assert applied2 == {"max_iterations": 5}
    assert rejected2 == {"run_max_usd": "must be >= 0"}


def test_general_settings_view_reports_source(tmp_path: Path) -> None:
    from mosaera_core.config import general_settings_view
    from mosaera_core.settings_store import write_settings

    write_settings(tmp_path, {"max_iterations": 7})
    view = general_settings_view(env={"MOSAERA_HOME": str(tmp_path), "MOSAERA_STALL_LIMIT": "4"})
    assert view["max_iterations"]["value"] == 7 and view["max_iterations"]["source"] == "stored"
    assert view["stall_limit"]["value"] == 4 and view["stall_limit"]["source"] == "env"
    assert view["review_max_fixes"]["source"] == "default"


def test_knob_choices_reject_out_of_set_and_expose(tmp_path: Path) -> None:
    import pytest
    from mosaera_core.config import coerce_general_patch, general_settings_view

    # a valid enum value passes; an invalid one is rejected (no typos reach config)
    assert coerce_general_patch({"sandbox_install_network": "none"}) == {
        "sandbox_install_network": "none"
    }
    with pytest.raises(ValueError, match="must be one of"):
        coerce_general_patch({"sandbox_install_network": "wifi"})
    # "host" is GONE (ADR-0035): --network host shares the host network namespace with the
    # target repo's install code, which then reaches the loopback API, Ollama, and the DB.
    # It used to be an ordinary dropdown option, and this test used to assert it was ACCEPTED.
    with pytest.raises(ValueError, match="must be one of"):
        coerce_general_patch({"sandbox_install_network": "host"})
    # the view exposes the supported set so the UI renders a dropdown; free fields → None
    view = general_settings_view(env={"MOSAERA_HOME": str(tmp_path / "x")})
    assert view["sandbox_install_network"]["choices"] == ["bridge", "none"]
    assert view["ollama_base_url"]["choices"] is None


def test_from_env_degrades_on_locked_gitlab_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # from_env runs on EVERY request; a stored global PAT encrypted under a key we no longer
    # have must degrade to "no token" (gitlab_token=None), NEVER raise and 500 the API (M-2).
    from cryptography.fernet import Fernet
    from mosaera_core.settings_store import write_settings
    from mosaera_memory import encrypt_secret

    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    write_settings(tmp_path, {"gitlab_token": encrypt_secret("glpat-real")})
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())  # wrong key
    monkeypatch.delenv("MOSAERA_GITLAB_TOKEN", raising=False)
    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})  # must NOT raise
    assert s.gitlab_token is None


def test_secrets_never_render_in_a_repr() -> None:
    """A config repr is a disclosure channel, not a debugging convenience.

    The ones that matter are the reprs nobody chose to write: an exception message, a log
    line, a crash report. Observed 2026-08-04 — a live provider key printed inside a
    `TypeError` traceback raised by an unrelated call, because Settings was an argument.
    """
    from dataclasses import replace

    from mosaera_core.config._types import ProviderConfig

    settings = replace(
        Settings(),
        gitlab_token="glpat-SECRET-TOKEN-VALUE",
        db_url="postgresql://mosaera:SECRET-DB-PASSWORD@localhost:5432/mosaera",
        providers={"anthropic": ProviderConfig(api_key="sk-ant-SECRET-KEY-VALUE")},
    )
    rendered = repr(settings)
    for secret in ("SECRET-TOKEN-VALUE", "SECRET-DB-PASSWORD", "SECRET-KEY-VALUE"):
        assert secret not in rendered, f"{secret} leaked into repr(Settings)"

    # Presence is still stated — a masked field must not become an invisible one, or the
    # repr starts lying about whether a key is configured at all.
    assert "api_key=<set>" in repr(ProviderConfig(api_key="sk-ant-SECRET-KEY-VALUE"))
    assert "api_key=<unset>" in repr(ProviderConfig())


def test_grader_outcome_names_its_failing_tests() -> None:
    """ "7/8 passed" cannot be reconciled against a delivered tree; the names can."""
    from mosaera_core.bench.grade import GraderOutcome

    out = GraderOutcome(
        ran=True,
        passed=7,
        failed=1,
        errors=0,
        output=(
            "........F\n=== short test summary info ===\n"
            "FAILED _mcb_grader/test_acceptance.py::test_is_a_short_orchestrator - assert 9 <= 6\n"
            "1 failed, 7 passed in 0.06s\n"
        ),
    )
    assert out.failed_test_ids == ["_mcb_grader/test_acceptance.py::test_is_a_short_orchestrator"]
    # A diagnostic must never break a measurement: unparseable output yields nothing, not a raise.
    assert GraderOutcome(ran=False, passed=0, failed=0, errors=0, output="").failed_test_ids == []


def test_the_mutation_veto_lever_is_env_only_and_never_a_dashboard_toggle() -> None:
    """`oracle_mutation_vetoes` RELAXES a delivery-gate veto, so it must not reach the settings UI.

    Surfacing it in `GENERAL_KNOBS` would let an admin switch off a safety control from the
    dashboard — a product-surface decision with its own ADR bar, not something an A/B lever should
    acquire as a side effect. Pinned in both directions: absent from the UI surface, present and
    functional from the environment.
    """
    from mosaera_core.config import GENERAL_KNOBS, Settings
    from mosaera_core.settings_store import _ALLOWED_KEYS

    assert "oracle_mutation_vetoes" not in {k.field for k in GENERAL_KNOBS}
    assert "oracle_mutation_vetoes" not in _ALLOWED_KEYS, (
        "a stored settings.json value would be a second, persistent way to disable the veto"
    )

    base = {"MOSAERA_HOME": "/nonexistent-for-this-test"}
    assert Settings.from_env(env=base).oracle_mutation_vetoes is True, "default = today's behaviour"
    off = Settings.from_env(env={**base, "MOSAERA_ORACLE_MUTATION_VETOES": "0"})
    assert off.oracle_mutation_vetoes is False, "the A/B arm must be reachable from the env"


def test_on_box_models_covers_every_binding_a_run_could_reach(tmp_path: Path) -> None:
    """A model reachable only through an ESCALATION ladder is still on-box.

    The ladders (`role_escalation`, ADR-0016/0022; `reason_escalation`, ADR-0018) are configured
    separately from cost modes, so enumerating modes alone misses them — and a local model missed
    here has its IMPUTED dollars counted as real, which is the direction that trips a usd budget
    cap over money nobody spent. Found by reading a bench rollup that reported a local model as
    billable, not by a test.
    """
    from mosaera_core.config._types import RoleModel
    from mosaera_core.models import on_box_models

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    s = dataclasses.replace(
        s,
        coder_model="local-base:8b",
        role_escalation={"coder": [RoleModel(provider="ollama", model="local-bigger:70b")]},
        reason_escalation=[RoleModel(provider="ollama", model="local-reasoner:32b")],
    )

    names = on_box_models(s)
    assert "local-base:8b" in names  # the plain binding
    assert "local-bigger:70b" in names  # only reachable after a role escalation
    assert "local-reasoner:32b" in names  # only reachable after a reasoning escalation


def test_a_hosted_escalation_tier_is_not_marked_shadow(tmp_path: Path) -> None:
    """The inverse must hold too, or real spend would be reported as imaginary — the direction
    that hides a bill instead of inventing one."""
    from mosaera_core.config._types import RoleModel
    from mosaera_core.models import on_box_models

    s = Settings.from_env(env={"MOSAERA_HOME": str(tmp_path)})
    s = dataclasses.replace(
        s, role_escalation={"coder": [RoleModel(provider="anthropic", model="claude-sonnet-4-6")]}
    )

    assert "claude-sonnet-4-6" not in on_box_models(s)


def test_resolve_docker_bin_probes_rather_than_asking_the_platform(monkeypatch) -> None:
    """The WSL fact now exists on `Platform`, and this must NOT start reading it.

    A Docker Desktop shim is on PATH inside a WSL distro whether or not integration is enabled, and
    only running it tells you which. `_cli_works` asks that question; a platform bit cannot. The
    flag chooses the right ADVICE, this chooses a working binary — collapsing the two would
    reintroduce the shim bug.
    """
    from mosaera_core.config import _env

    tried: list[str] = []

    def fake_works(name: str) -> bool:
        tried.append(name)
        return name == "docker.exe"

    monkeypatch.setattr(_env, "_cli_works", fake_works)
    assert _env.resolve_docker_bin(None) == "docker.exe"
    assert tried == ["docker", "docker.exe"], "it stopped probing, or asked something else first"
