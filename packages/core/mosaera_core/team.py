"""The agent team registry — the single declarative source for each agent's
role-level metadata.

Adding an agent to Mosaera is a coordinated change across several layers (the
tool allowlist / trust boundary, the model seam, the graph, prompts, and the UI).
This registry centralizes the parts that are safely *declarative* — name, the
graph nodes it owns, its remit, whether it is read-only, and its sampling
temperature — so the model gateway, cost attribution, and the config/UI role
lists all derive from ONE place and a new agent surfaces automatically.

Deliberately NOT owned here (they stay typed / gated — see docs/adr/ADR-0013):
- ``config.Role`` / ``_ROLES`` — a type-level ``Literal`` (can't derive at runtime);
- ``mosaera_policies.ROLE_TOOL_ALLOWLIST`` — the trust boundary, CODEOWNERS-gated;
- the per-agent build/wiring in ``graph.py`` — genuine per-agent construction.

This module is pure data: it imports only the ``Role`` type, so ``config``,
``models``, and ``cost`` can all import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from mosaera_core.config import Role


@dataclass(frozen=True)
class AgentSpec:
    """The declarative, role-level definition of one team member.

    ``label`` is the functional name used for cost attribution and the config/UI
    role bindings (PM / Coder / Reviewer / …); ``display_name`` is the persona
    shown in the run timeline (Quincy / Forge / Rook / …). ``nodes`` are the graph
    nodes whose model spend is attributed to this agent. A new agent = one new
    ``AgentSpec`` here + the gated/typed touchpoints listed in ADR-0013.
    """

    role: Role
    label: str
    display_name: str
    nodes: tuple[str, ...]
    remit: str
    read_only: bool
    temperature: float


# The team. Order is the canonical role order used by the config/UI role lists.
# `nodes` reproduces the existing cost-attribution map exactly (design/hygiene_fix/
# review_fix/quality_revise spend attributes to their own node labels today).
AGENT_REGISTRY: tuple[AgentSpec, ...] = (
    AgentSpec(
        role="pm",
        label="PM",
        display_name="Quincy",
        nodes=("plan",),
        remit="Plans and designs the work, owns the backlog, and supervises escalations.",
        read_only=True,
        temperature=0.2,
    ),
    AgentSpec(
        role="coder",
        label="Coder",
        display_name="Forge",
        nodes=("implement", "capture", "fix"),
        remit="Implements the plan via surgical edits and runs the tests.",
        read_only=False,
        temperature=0.1,
    ),
    AgentSpec(
        role="reviewer",
        label="Reviewer",
        display_name="Rook",
        nodes=("review",),
        remit="Read-only critic that verifies acceptance, design conformance, and evidence.",
        read_only=True,
        temperature=0.2,
    ),
    AgentSpec(
        role="tester",
        label="Tester",
        display_name="Proctor",
        nodes=("author_tests",),
        remit="Authors the acceptance tests from the spec BEFORE the coder builds (test-first).",
        read_only=False,
        temperature=0.1,
    ),
    AgentSpec(
        role="critic",
        label="Critic",
        display_name="Judge",
        nodes=("critic",),
        remit="Held-out, veto-only judge of the delivered outcome against the spec.",
        read_only=True,
        temperature=0.1,
    ),
)


def team_roles() -> tuple[Role, ...]:
    """The canonical role list, in order — the single source the config/UI derive."""
    return tuple(spec.role for spec in AGENT_REGISTRY)


def spec_for(role: str) -> AgentSpec | None:
    """The spec for ``role``, or None if it is not a registered team member."""
    return next((spec for spec in AGENT_REGISTRY if spec.role == role), None)


def temperature_map() -> dict[Role, float]:
    """role -> sampling temperature (drives ``models._ROLE_TEMPERATURE``)."""
    return {spec.role: spec.temperature for spec in AGENT_REGISTRY}


def agent_by_node() -> dict[str, str]:
    """graph node -> functional agent label (drives ``cost._AGENT_BY_NODE``)."""
    return {node: spec.label for spec in AGENT_REGISTRY for node in spec.nodes}
