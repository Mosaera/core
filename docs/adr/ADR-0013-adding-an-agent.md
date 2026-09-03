# ADR-0013: Adding an agent to the team — the AgentSpec registry, the SOP, and the governance flow

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0008](ADR-0008-pm-foundation.md)/[ADR-0011](ADR-0011-agent-self-awareness-and-decompose-dag.md)/[ADR-0012](ADR-0012-cohesive-team-supervision.md) (the existing agents), [ADR-0009](ADR-0009-backlog-ownership.md)/[ADR-0010](ADR-0010-backlog-structural-ops-and-chat-curation.md) (the propose-a-changeset governance model this points toward), [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (the `get_chat_model` seam)

## Context

Adding an agent used to be a coordinated edit across ~6 sites with no single source of truth:
the role universe was a hardcoded `Role = Literal[...]` duplicated in `config`, `models`, the
cost labels, the API `/providers` + `/cost-modes` role lists, and two web `ROLES` consts.
Nothing declared "the team." As Mosaera matures toward a place where Quincy (or the user) can
create a new agent or a specialized team **from the UI**, that flow needs a standardized
template, a repeatable checklist, and a governance boundary that a UI-created agent still
lands through. This ADR establishes all three, with the **tester (Proctor)** as the first
agent minted through it.

## Decision

**1. One declarative registry — `AgentSpec` (`mosaera_core/team.py`).** Each agent is one
`AgentSpec`: `role`, `label` (functional name for cost/config — PM/Coder/Reviewer/Tester),
`display_name` (persona — Quincy/Forge/Rook/Proctor), `nodes` (the graph nodes attributed to
it), `remit`, `read_only`, `temperature`. The **safe enumeration sites derive from it**:
`models._ROLE_TEMPERATURE` + `_ROLES`, `cost._AGENT_BY_NODE`, and the API `/providers` +
`/cost-modes` role bindings/validation (which also return `role_meta`, so the web renders a
row per role). A new agent therefore surfaces in those places automatically — the registry is
the single source of role metadata. It is pure data (imports only `Role`), so `config`,
`models`, and `cost` import it without a cycle.

**2. Personas as a data corpus (`mosaera_agents/personas/<name>.md` + `load_persona`).** An
agent's system prompt is loaded from a `.md` file (mirroring the doctrine loader), not hard-
coded — so a new agent's voice is editable data, the pattern a UI "create agent" flow builds
on. (Existing agents' prompts remain Python constants for now; migrating them is deferred.)

**3. The SOP — the checklist to add a role `X`.** Grounded, gated vs un-gated:

*Gated (CODEOWNERS `@Ashura` — the trust boundary; owner review required):*
- `packages/policies/mosaera_policies/allowlist.py` — add `"X": frozenset({…})` to
  `ROLE_TOOL_ALLOWLIST`. Deny-by-default: a role absent here gets **zero** tools. This is the
  one hard governance gate. (Read-only agents list only read tools; a writing agent's blast
  radius is bounded further by `build_repo_tools` `write_prefix`/`protected_paths`.)
- An **ADR** for the new agent (a design change; see `AGENTS.md`), + a `docs/adr/README.md` row.
- A **threat-model note** (`docs/threat-models/`) only if the agent widens the egress/trust
  surface (e.g. gains network or unscoped writes).

*Un-gated (normal review):*
- `config.Role` + `_ROLES` (typed `Literal` — kept hand-maintained; a runtime registry can't
  be a `Literal` member). A parity test binds it to the registry.
- `team.AGENT_REGISTRY` — the `AgentSpec` (drives temperature/cost/UI automatically).
- `config`: `X_model` + the `role_model_for` dict, an `X_step_limit` knob + Settings field +
  `settings_store._ALLOWED_KEYS`, and the `from_env` provider/model lines.
- A factory `agents/X.py` (`build_X_agent`, mirroring `coder.py`/`reviewer.py`) + a persona
  `personas/X.md`.
- `packages/core/mosaera_core/graph/build.py` (~~`graph.py`~~ — **corrected 2026-08-18**, `docs/audits/adr-corpus-review-2026-08-18.md`: the module became a package): build the agent (`get_chat_model("X")` + `scoped_tools("X", …)`), add its node,
  wire its edges/routing. Graph **topology stays code** — a specialized team is new wiring, not
  a list entry.
- `apps/web/src/components/runs/runActors.ts` — the timeline actor label (node-level UI copy).
- Tests: an allowlist scope test; a persona/factory test; a graph-build node test; behaviour.

**4. Governance flow for a future UI-created agent.** A UI "create an agent" action does **not**
mutate the trust boundary directly. It produces a **proposed** role + allowlist + `AgentSpec`
**changeset that lands through the same CODEOWNERS/ADR review path** — exactly mirroring how
Quincy proposes backlog changesets that a human approves (ADR-0009/0010). The policy allowlist
and the graph topology stay code-and-governance-gated **by design**, even in that future.

## The worked reference — the tester (Proctor)

Proctor is agent #1 added through this SOP: registry `AgentSpec` (role `tester`, node
`author_tests`), `tester` allowlist entry (read + write-`tests/` + `run_tests`, no
edit/delete), `config` role plumbing, a `personas/tester.md` corpus persona, `build_tester_agent`,
and an `author_tests` graph node (test-first, opt-in behind `tester_enabled`). Its strict
separation — write confined to `tests/`, the coder refused on its authored tests — is enforced
by the `build_repo_tools` `write_prefix`/`protected_paths` primitives.

## Options considered

- **A pure-markdown SOP with no registry.** Rejected — it neither reduces the touchpoints nor
  gives the UI something to read; the whole point is a single declarative source.
- **A full data-driven registry that also owns the `Role` type, the allowlist, and the build
  wiring.** Rejected for now: the `Role` `Literal` gives type-level exhaustiveness, the allowlist
  is the trust boundary (must stay gated), and per-agent build (coder's context-editing, the PM's
  two prompts) is genuinely bespoke. Retiring these is deferred; the registry centralizes what is
  *safely* declarative.

## Security implications

Low, and the boundary is explicit. The **only** hard security gate for a new agent is the
`packages/policies` allowlist (CODEOWNERS-gated, deny-by-default). The registry is metadata; it
grants no capability. A writing agent is further contained by `write_prefix`/`protected_paths`
and the existing human-approval gate on mutations. A UI-created agent reaches the trust boundary
only as a reviewable changeset, never as a direct write.

## Operational implications

- No migration. New roles add config knobs (allow-listed) and a registry entry; the derived
  maps and the UI role lists update themselves.
- The `Role` `Literal` and `config._ROLES` remain hand-edited (a parity test fails loudly if
  they drift from the registry).

## Consequences

Adding an agent is now a standardized flow over one registry + a documented checklist with a
clear governance boundary, and the tester proves it end to end. What remains deferred (and is
the load-bearing work toward UI-created agents): retiring the `Role` `Literal` for a runtime
registry, migrating personas to corpus files wholesale, a generic agent-node builder, and the
UI "create agent" changeset flow itself — each of which this ADR points at without building.
