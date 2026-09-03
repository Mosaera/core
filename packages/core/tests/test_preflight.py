"""Preflight: can this instance run, and does every failure name its fix? (#119)

The properties that matter, in the order they matter:

1. **`unknown` is never a pass.** "We could not tell" reading as ok is the whole defect class.
2. **The required-model set is DERIVED.** `scripts/dev-up.sh` hardcodes three tags, so an operator
   who rebinds the coder gets a green check for a model nothing uses and no warning about the one
   that is missing. Rebinding a role here must change what is required.
3. **A validated key is not a validated model.** The documented BYOK failure is a working key plus
   a model id the provider does not offer, which otherwise surfaces on the first real call.
4. **Every `fail` carries a fix.** Naming a problem nobody can act on is what this replaces.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from mosaera_core.config import Settings
from mosaera_core.preflight import (
    Check,
    Inventory,
    Preflight,
    check_database,
    check_docker,
    check_hosted_providers,
    check_images,
    check_ollama,
    required_ollama_models,
    run_preflight,
)


def _settings(**over: Any) -> Settings:
    return dataclasses.replace(Settings(), **over)


# --- the honesty contract -------------------------------------------------------------------


def test_unknown_is_not_ok() -> None:
    # Deny-by-default on the two-state view the SPA renders: a check we could not evaluate must
    # never present as a pass.
    assert Check("k", "L", "unknown", "d").ok is False
    assert Check("k", "L", "fail", "d").ok is False
    assert Check("k", "L", "ok", "d").ok is True
    # `note` IS ok — an in-memory store is a legitimate state, not a broken one.
    assert Check("k", "L", "note", "d").ok is True


def test_every_failure_names_a_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    # The bar the module sets for itself. A `fail` with no `fix` is a bug, not a style choice.
    monkeypatch.setattr("mosaera_core.preflight_host._run", lambda *a, **k: (-1, "no such binary"))
    settings = _settings(db_url="postgresql://u:p@127.0.0.1:1/nope")
    report = run_preflight(settings, verify_keys=False)
    for check in report.checks:
        if check.status == "fail":
            assert check.fix, f"{check.key} failed without telling the operator what to do"


# --- the derived required set (the dev-up.sh defect) ----------------------------------------


def test_required_models_follow_the_active_bindings() -> None:
    # A name unique to the coder, so the assertion is about the coder's binding and not about
    # `tester_model` happening to share the default.
    rebound = _settings(coder_model="my-own-coder:7b")
    assert "my-own-coder:7b" in required_ollama_models(rebound)
    # And it is genuinely derived: the default is not required once nothing is bound to it.
    assert "my-own-coder:7b" not in required_ollama_models(_settings())


def test_the_embedding_model_is_required_too() -> None:
    # Ollama-only by construction (`models.get_embeddings`) and durable memory needs it, so it
    # belongs in the set whatever the chat roles are bound to.
    assert _settings().embed_model in required_ollama_models(_settings())


def test_a_hosted_role_contributes_nothing_to_the_ollama_set() -> None:
    # Unique per role again — `tester_model` shares the coder's default, so a shared name would
    # make this pass for the wrong reason.
    local = _settings(coder_model="only-the-coder:1b")
    assert "only-the-coder:1b" in required_ollama_models(local)
    hosted = _settings(coder_model="only-the-coder:1b", role_providers={"coder": "anthropic"})
    assert "only-the-coder:1b" not in required_ollama_models(hosted)


def test_no_ollama_roles_means_no_ollama_check() -> None:
    # A green row for a dependency this deployment does not use is noise, not reassurance.
    settings = _settings(
        role_providers={r: "anthropic" for r in ("pm", "coder", "reviewer", "tester", "critic")},
        embed_model="",
    )
    assert check_ollama(settings, Inventory(ollama_reachable=False)) is None


# --- ollama ----------------------------------------------------------------------------------


def test_unreachable_ollama_fails_with_the_url_and_a_fix() -> None:
    check = check_ollama(_settings(), Inventory(ollama_reachable=False, ollama_error="refused"))
    assert check is not None and check.status == "fail"
    assert "refused" in check.detail  # the cause, not a shrug
    assert "ollama serve" in check.fix


def test_reachable_but_unpulled_names_every_missing_model() -> None:
    settings = _settings()
    check = check_ollama(settings, Inventory(ollama_reachable=True, ollama_tags=()))
    assert check is not None and check.status == "fail"
    for model in required_ollama_models(settings):
        assert model in check.detail
        assert f"ollama pull {model}" in check.fix


def test_reachable_and_pulled_is_ok() -> None:
    settings = _settings()
    tags = tuple(required_ollama_models(settings))
    check = check_ollama(settings, Inventory(ollama_reachable=True, ollama_tags=tags))
    assert check is not None and check.status == "ok"


def test_an_untagged_binding_matches_the_latest_tag() -> None:
    # A binding may omit `:tag`; Ollama resolves that to `:latest` and reports it that way. Calling
    # a legitimately-pulled model missing would send the operator to re-pull what they already have.
    settings = _settings(coder_model="mymodel", embed_model="", role_providers={})
    settings = dataclasses.replace(
        settings,
        pm_model="mymodel",
        reviewer_model="mymodel",
        tester_model="mymodel",
        critic_model="mymodel",
    )
    inv = Inventory(ollama_reachable=True, ollama_tags=("mymodel:latest",))
    check = check_ollama(settings, inv)
    assert check is not None and check.status == "ok"


# --- hosted providers ---------------------------------------------------------------------


def _hosted(**over: Any) -> Settings:
    return _settings(role_providers={"coder": "anthropic"}, **over)


def test_a_hosted_role_with_no_key_fails_and_names_the_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    checks = check_hosted_providers(_hosted())
    assert [c.status for c in checks] == ["fail"]
    assert "ANTHROPIC_API_KEY" in checks[0].fix
    assert "coder" in checks[0].detail  # WHICH role is stranded


def test_a_rejected_key_is_a_named_failure_not_a_shrug(monkeypatch: pytest.MonkeyPatch) -> None:
    # The 45-of-61 defect class at the setup seam: priced is not funded, and presence is not
    # acceptance. The key is put to the provider's own endpoint and its answer is reported.
    from mosaera_core.models import ProviderAuthError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bogus")

    def _reject(*_a: Any, **_k: Any) -> list[str]:
        raise ProviderAuthError("401 invalid x-api-key")

    monkeypatch.setattr("mosaera_core.models.fetch_provider_models", _reject)
    checks = check_hosted_providers(_hosted())
    assert checks[0].status == "fail"
    assert "REJECTED" in checks[0].detail and "401" in checks[0].detail
    assert checks[0].fix


def test_an_unreachable_provider_is_unknown_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    # "The key is bad" and "we could not ask" are different facts and must not be collapsed —
    # telling an operator to replace a working key because their DNS blipped is its own harm.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")

    def _boom(*_a: Any, **_k: Any) -> list[str]:
        raise TimeoutError("connect timed out")

    monkeypatch.setattr("mosaera_core.models.fetch_provider_models", _boom)
    checks = check_hosted_providers(_hosted())
    assert checks[0].status == "unknown"
    assert checks[0].ok is False  # still not a pass


def test_a_working_key_bound_to_a_model_the_provider_lacks_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The documented BYOK trap: the Test button validates the key, not the model id, so a typo
    # surfaces only on the first real call. Here it surfaces at setup.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    monkeypatch.setattr(
        "mosaera_core.models.fetch_provider_models", lambda *a, **k: ["claude-sonnet-5"]
    )
    settings = _hosted()
    settings = dataclasses.replace(settings, coder_model="claude-sonnet-5-typo")
    checks = check_hosted_providers(settings)
    assert checks[0].status == "fail"
    assert "claude-sonnet-5-typo" in checks[0].detail


def test_a_working_key_and_a_real_model_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    settings = dataclasses.replace(_hosted(), coder_model="claude-sonnet-5")
    monkeypatch.setattr(
        "mosaera_core.models.fetch_provider_models", lambda *a, **k: ["claude-sonnet-5"]
    )
    checks = check_hosted_providers(settings)
    assert checks[0].status == "ok"


def test_verify_false_never_egresses(monkeypatch: pytest.MonkeyPatch) -> None:
    # The offline path a caller can rely on: presence only, no network.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")

    def _explode(*_a: Any, **_k: Any) -> list[str]:
        raise AssertionError("verify=False must not call the provider")

    monkeypatch.setattr("mosaera_core.models.fetch_provider_models", _explode)
    assert check_hosted_providers(_hosted(), verify=False)[0].status == "ok"


# --- database ---------------------------------------------------------------------------


def test_no_database_is_a_note_not_a_failure() -> None:
    # Running without Postgres is supported. Calling it broken would be as dishonest as calling
    # it fine — the operator is told what they lose, and the instance still counts as usable.
    check = check_database(_settings(db_url=None))
    assert check.status == "note" and check.ok is True
    assert "will NOT survive a restart" in check.detail


def test_a_configured_but_unreachable_database_fails() -> None:
    check = check_database(_settings(db_url="postgresql://u:p@127.0.0.1:1/nope"))
    assert check.status == "fail" and check.fix


# --- docker + images --------------------------------------------------------------------


def test_a_missing_docker_binary_is_distinguished_from_a_dead_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mosaera_core.preflight_host._run", lambda *a, **k: (-1, "not found"))
    absent = check_docker(_settings())
    monkeypatch.setattr("mosaera_core.preflight_host._run", lambda *a, **k: (1, "Cannot connect"))
    dead = check_docker(_settings())
    assert absent.status == dead.status == "fail"
    assert absent.detail != dead.detail  # different problems, different fixes
    assert "systemctl" in dead.fix and "systemctl" not in absent.fix


def test_missing_images_name_the_exact_build_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mosaera_core.preflight_host._run", lambda *a, **k: (1, "No such image"))
    check = check_images(_settings())
    assert check.status == "fail"
    assert "infra/docker/sandbox.Dockerfile" in check.fix
    assert check.fix.count("docker build") == 4  # every missing image, not just the first


# --- can_run ----------------------------------------------------------------------------


def test_can_run_turns_only_on_the_backend() -> None:
    # Docker/images/database block a run LATER and are reported on their own rows; gating the whole
    # application on them would lock a newcomer out of the product while they fix a daemon.
    report = Preflight(
        checks=[
            Check("docker", "Docker", "fail", "down", fix="x"),
            Check("images", "Images", "fail", "missing", fix="x"),
            Check("backend.ollama", "Ollama", "ok", "fine"),
        ]
    )
    ready, reason = report.can_run()
    assert ready is True and reason == ""


def test_can_run_is_false_and_says_why_when_no_backend_answers() -> None:
    report = Preflight(
        checks=[Check("backend.ollama", "Ollama", "fail", "not reachable at :11434", fix="x")]
    )
    ready, reason = report.can_run()
    assert ready is False
    assert "not reachable" in reason  # the banner and the 503 both render THIS string


def test_an_unknown_backend_does_not_count_as_runnable() -> None:
    report = Preflight(checks=[Check("backend.anthropic", "k", "unknown", "could not reach")])
    assert report.can_run()[0] is False


def test_the_payload_is_serialisable_and_carries_the_verdict() -> None:
    payload = Preflight(checks=[Check("backend.x", "X", "ok", "d")]).as_dict()
    assert payload["can_run"] is True
    assert payload["checks"][0]["status"] == "ok" and payload["checks"][0]["ok"] is True
    assert "inventory" in payload


def test_dev_up_no_longer_hardcodes_a_model_list() -> None:
    """The drift this module exists to end, pinned at its origin.

    `scripts/dev-up.sh` used to check `gpt-oss:20b qwen3-coder:30b nomic-embed-text` literally, so
    an operator who rebound a role got a green note about a model nothing uses and no warning about
    the one actually missing. It now calls `mosaera doctor`, which derives the set. Comments may
    still mention the old tags — the executable lines may not.
    """
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "dev-up.sh"
    code = [
        line
        for line in script.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    body = "\n".join(code)
    for tag in ("gpt-oss:", "qwen3-coder:", "nomic-embed-text"):
        assert tag not in body, (
            f"dev-up.sh names {tag!r} in an executable line — the required models must be DERIVED "
            "from the active bindings (`mosaera doctor`), not listed here."
        )
    assert "mosaera doctor" in body, "dev-up.sh no longer delegates its readiness checks"


def test_every_failure_carries_a_command_never_prose() -> None:
    """The module's own contract: "``fix`` is a command the operator can paste — never prose."

    The docker row broke it with "see https://docs.docker.com/engine/install/", which is the one
    check most likely to fail on a fresh machine and the one an operator could not act on.
    """
    from mosaera_core.preflight import check_docker
    from mosaera_core.preflight_host import _install_command

    settings = Settings.from_env().__class__(docker_bin="/nonexistent/docker")
    fix = check_docker(settings).fix
    assert fix, "a failing check with no fix is a bug in the module"
    assert not fix.lower().startswith("see "), fix
    assert "http" not in fix or fix.startswith("curl "), fix  # a URL only inside a real command

    # And the command names a package manager this machine could actually run.
    cmd = _install_command("docker")
    assert any(cmd.startswith(p) for p in ("sudo apt-get", "sudo dnf", "sudo pacman", "curl ")), cmd
