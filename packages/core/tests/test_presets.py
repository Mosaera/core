"""Preset policy: objective axes only, and never a guess (#119).

The properties, in the order they matter:

1. **No model name is shipped.** Mosaera is BYOM; a preset that names a model pushes every
   newcomer at one vendor's choice.
2. **No quality ranking is asserted.** The corpus was measured on ONE binding and
   `docs/engineering-history/` holds no per-model comparison, so "your strongest model" is a claim
   nobody can back.
3. **An unsatisfiable role resolves to NOTHING, with a reason.** A silently-substituted model is a
   run whose producer was not the one the operator picked.
4. **An unpriced model is not a free one.** Absent price data must not win a cheapest-first sort —
   that is a cost gate failing open.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from mosaera_core.config import Settings
from mosaera_core.models import COST_MODES
from mosaera_core.presets import (
    PRESET_POLICY,
    Candidate,
    as_cost_mode,
    inventory_from,
    resolve_preset,
)


def _settings(**over: Any) -> Settings:
    return dataclasses.replace(Settings(), **over)


def _local(model: str) -> Candidate:
    return Candidate(provider="ollama", model=model, on_box=True, price=None)


def _hosted(model: str, price: float | None) -> Candidate:
    return Candidate(provider="anthropic", model=model, on_box=False, price=price)


# --- what a preset is allowed to say -------------------------------------------------------


def test_every_shipped_cost_mode_has_a_policy() -> None:
    # A mode the UI offers with no policy behind it is the state this replaces: a preset switcher
    # that assigns nothing.
    assert set(PRESET_POLICY) == set(COST_MODES)


def test_no_model_name_is_shipped() -> None:
    """BYOM, enforced. If a policy ever names a model, this fails and says why."""
    blob = " ".join(f"{p.locality} {p.prefer} {p.summary}" for p in PRESET_POLICY.values()).lower()
    for smell in (":", "gpt", "claude", "llama", "qwen", "mistral", "gemini"):
        assert smell not in blob, (
            f"a preset policy mentions {smell!r} — presets route on objective axes, they do not "
            "name models (BYOM)"
        )


def test_no_policy_claims_a_capability_ranking() -> None:
    # The unmeasured axis. Routing on "strongest"/"best" would assert something no evidence in this
    # repo supports.
    blob = " ".join(p.summary.lower() for p in PRESET_POLICY.values())
    for claim in ("strongest", "best", "smartest", "most capable", "highest quality"):
        assert claim not in blob


# --- resolution ---------------------------------------------------------------------------


def test_an_on_box_policy_never_selects_a_hosted_model() -> None:
    # The privacy guarantee is the whole point of this preset; a hosted fallback would silently
    # break the one promise it makes.
    out = resolve_preset(PRESET_POLICY["economy"], [_hosted("cloud-a", 1.0), _local("local-a")])
    assert {r.binding.provider for r in out if r.binding} == {"ollama"}


def test_an_on_box_policy_with_nothing_local_resolves_to_nothing() -> None:
    out = resolve_preset(PRESET_POLICY["economy"], [_hosted("cloud-a", 1.0)])
    assert all(r.binding is None for r in out)
    assert all("on this machine" in r.reason for r in out)  # named, not blank


def test_cheapest_prefers_a_local_model_over_any_paid_one() -> None:
    out = resolve_preset(PRESET_POLICY["balanced"], [_hosted("cloud-a", 0.01), _local("local-a")])
    assert all(r.binding and r.binding.model == "local-a" for r in out)
    assert all("nothing leaves the box" in r.reason for r in out)


def test_cheapest_picks_the_lowest_price_among_hosted() -> None:
    out = resolve_preset(PRESET_POLICY["balanced"], [_hosted("dear", 15.0), _hosted("cheap", 3.0)])
    assert all(r.binding and r.binding.model == "cheap" for r in out)
    assert all("cheapest" in r.reason for r in out)


def test_an_unpriced_model_never_wins_the_cheapest_sort() -> None:
    # Absent price data is not evidence of a low price. Treating it as zero would make the
    # cheapest-policy pick the model whose cost we know LEAST about — a cost gate failing open,
    # which is exactly why `cloud_tier_allowed` requires a price entry.
    out = resolve_preset(
        PRESET_POLICY["balanced"], [_hosted("unpriced", None), _hosted("priced", 9.0)]
    )
    assert all(r.binding and r.binding.model == "priced" for r in out)


def test_the_operator_preset_resolves_nothing_and_says_so() -> None:
    out = resolve_preset(PRESET_POLICY["premium"], [_local("local-a"), _hosted("cloud-a", 1.0)])
    assert all(r.binding is None for r in out)
    assert all("you choose" in r.reason for r in out)


def test_resolution_is_deterministic() -> None:
    inv = [_hosted("b", 2.0), _hosted("a", 2.0)]
    first = resolve_preset(PRESET_POLICY["balanced"], inv)
    assert [r.binding for r in first] == [
        r.binding for r in resolve_preset(PRESET_POLICY["balanced"], inv)
    ]


def test_every_role_gets_a_row_even_when_unresolved() -> None:
    # The wizard renders one row per role; a role dropped from the list is a role the operator is
    # never told about.
    roles = ("pm", "coder", "reviewer", "tester", "critic")
    assert tuple(r.role for r in resolve_preset(PRESET_POLICY["economy"], [])) == roles


# --- persistence shape ---------------------------------------------------------------------


def test_unresolved_roles_are_omitted_not_defaulted() -> None:
    # An omitted role falls back to the base BYOM binding — the documented behaviour of
    # `cost_modes`. Writing a guess would hide the gap the wizard just showed the operator.
    out = resolve_preset(PRESET_POLICY["premium"], [_local("x")])
    assert as_cost_mode(out) == {}


def test_resolved_roles_land_in_the_existing_cost_mode_shape() -> None:
    out = resolve_preset(PRESET_POLICY["economy"], [_local("local-a")])
    mode = as_cost_mode(out)
    assert set(mode) == {"pm", "coder", "reviewer", "tester", "critic"}
    assert mode["coder"].provider == "ollama" and mode["coder"].model == "local-a"


# --- inventory -----------------------------------------------------------------------------


def test_inventory_reports_ollama_tags_as_on_box() -> None:
    inv = inventory_from(_settings(), ("a:1b", "b:2b"))
    assert {c.model for c in inv} >= {"a:1b", "b:2b"}
    assert all(c.on_box for c in inv if c.provider == "ollama")


def test_a_configured_hosted_binding_joins_the_inventory_priced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A KEY is what makes a hosted binding available. Without one it is configuration, not
    # inventory — see `test_a_hosted_binding_with_no_key_is_not_available`.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    settings = _settings(
        role_providers={"coder": "anthropic"},
        coder_model="claude-x",
        model_prices={"claude-x": (3.0, 15.0)},
    )
    hosted = [c for c in inventory_from(settings, ()) if c.provider == "anthropic"]
    assert len(hosted) == 1
    assert hosted[0].on_box is False and hosted[0].price == 3.0


def test_a_configured_but_unpulled_ollama_model_is_not_available() -> None:
    """The bug this caught, live on a fresh instance (2026-08-25).

    The stock defaults are Ollama bindings. Unioning them into the inventory made them candidates
    marked `on_box=True`, so a machine with NOTHING pulled and Ollama unreachable was told
    *"all 5 roles -> gpt-oss:20b - runs on this machine, so nothing leaves the box"*. Every word of
    that was false. Ollama's tags are the authoritative availability list; config is not.
    """
    settings = _settings(coder_model="never-pulled:70b")
    assert all(c.model != "never-pulled:70b" for c in inventory_from(settings, ()))


def test_an_unreachable_ollama_yields_no_local_candidates_at_all() -> None:
    # The fresh-machine case end to end: no tags -> no inventory -> the on-box preset resolves to
    # NOTHING with a reason, rather than to a model that is not there.
    settings = _settings()
    assert inventory_from(settings, ()) == []
    out = resolve_preset(PRESET_POLICY["economy"], inventory_from(settings, ()))
    assert all(r.binding is None for r in out)
    assert all("on this machine" in r.reason for r in out)


def test_a_hosted_binding_with_no_key_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    # The same defect wearing a different provider: a binding we cannot serve is not a candidate.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = _settings(role_providers={"coder": "anthropic"}, coder_model="claude-x")
    assert [c for c in inventory_from(settings, ()) if c.provider == "anthropic"] == []


def test_the_inventory_does_not_duplicate_a_bound_local_model() -> None:
    settings = _settings(coder_model="dupe:1b")
    models = [c.model for c in inventory_from(settings, ("dupe:1b",))]
    assert models.count("dupe:1b") == 1
