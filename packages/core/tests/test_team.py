"""The agent registry is the single source; the derived maps + the typed role
literal must stay in lockstep with it."""

from __future__ import annotations

from mosaera_core.config import _ROLES as CONFIG_ROLES
from mosaera_core.cost import _AGENT_BY_NODE
from mosaera_core.models import _ROLE_TEMPERATURE
from mosaera_core.models import _ROLES as MODELS_ROLES
from mosaera_core.team import AGENT_REGISTRY, agent_by_node, spec_for, team_roles


def test_registry_declares_the_current_team() -> None:
    assert team_roles() == ("pm", "coder", "reviewer", "tester", "critic")
    assert {s.role for s in AGENT_REGISTRY} == {"pm", "coder", "reviewer", "tester", "critic"}
    # every spec is complete
    for s in AGENT_REGISTRY:
        assert s.label and s.display_name and s.remit and s.nodes


def test_config_and_models_role_lists_match_the_registry() -> None:
    # config._ROLES is a hand-maintained Literal (type-level); models._ROLES derives
    # from the registry. All three must agree or role dispatch silently drifts.
    assert tuple(CONFIG_ROLES) == team_roles()
    assert MODELS_ROLES == team_roles()


def test_derived_temperature_map_matches_registry() -> None:
    assert _ROLE_TEMPERATURE == {
        "pm": 0.2,
        "coder": 0.1,
        "reviewer": 0.2,
        "tester": 0.1,
        "critic": 0.1,
    }


def test_derived_cost_attribution_matches_registry() -> None:
    assert agent_by_node() == {
        "plan": "PM",
        "implement": "Coder",
        "capture": "Coder",
        "fix": "Coder",
        "review": "Reviewer",
        "author_tests": "Tester",
        "critic": "Critic",
    }
    assert _AGENT_BY_NODE == agent_by_node()


def test_spec_for_lookup() -> None:
    coder, reviewer = spec_for("coder"), spec_for("reviewer")
    assert coder is not None and coder.read_only is False
    assert reviewer is not None and reviewer.read_only is True
    assert spec_for("nope") is None
