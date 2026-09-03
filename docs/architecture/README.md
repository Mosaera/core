# Architecture

One-page component overview of the **current system** — the software-engineering team
("Mosaera Lite"), which is the first and hardest team of the larger firm. For the **end goal
and direction** (the firm of hireable teams, Quincy as the operator interface, project
onboarding + map, and the Free/Business/Regulated posture model), see
[`north-star.md`](north-star.md) — the authority on direction and invariants (build status lives in
[`../roadmap.md`](../roadmap.md)).

Mosaera plans work, operates on an **isolated clone** of a target repo, validates in a sandbox,
and pauses at a human approval gate before opening a merge request. It runs locally: BYO models
(Ollama by default), Docker for the sandbox, Postgres for durable memory.

## Run graph

The LangGraph orchestrator (`packages/core/mosaera_core/graph/build.py`, `build_graph`) is a
15-node `StateGraph` (plus three opt-in nodes: `author_tests` when the tester is enabled,
`reason` for the reasoning-escalation ladder, and `critic` — the held-out veto spliced between
`review` and `gate`, ADR-0065). `plan → design` seed the coder; `implement →
capture → test` build and validate; three self-heal loops (test-fix, hygiene, reviewer) close
back onto `implement`, an agent hand-raise diverts to `supervise`, all before the human `gate`:

```
START
  └→ plan → design → implement → capture ─┬─(hand-raise)→ supervise ─┬─(re-scope)→ plan
                        ▲                  │                          └─(give up)──→ gate
        (fix loop)      │                  └─(no raise)→ test
                        │                                  │
                        │                    ┌─(fail, budget left)→ fix ─┘
                        │                    │
                        │                    └─(pass)→ hygiene ─(lint/type fail)→ hygiene_fix ─┐
                        │                                  │                                    │
                        ├──────────────────────────────────┼────────────────────────────────────┘
                        │                                  │(clean)
                        │                                  ▼
                        │                                scan → review
                        │                                          │
   quality_revise ◄─────┤   (opt-in, below-bar craftsmanship)      ├─(REQUEST_CHANGES)→ review_fix ─┐
                        └──────────────────────────────────────────┼─────────────────────────────────┘
                                                                    │(approve/clean)
                                                                    ▼
                                                                  gate ──(approve | stalled | cap)→ deliver → END
                                                                    └──────(deny)──────────────────→ plan
(opt-in nodes, omitted above: author_tests before implement when the tester is on; reason on
 stall; critic spliced on the review→gate edge when a held-out model is bound)
```

- **plan / design** (`packages/agents/pm/`) — PM plans, then elaborates an
  architecture grounded in the actual contents of the files the plan names.
- **implement** (`packages/agents/coder.py`) — coder agent with allowlisted repo tools,
  working only on the clone under `.mosaera/workspaces/<run-id>/`.
- **capture / test** — snapshot the coder summary; two-phase install→test in the sandbox
  (`sandbox/`, `validation.py`). A real failure self-heals via **fix**.
- **supervise** — when an agent raises its hand (blocked / escalate), `capture` diverts here
  before the test path: the supervisor re-scopes back to `plan` (autonomous) or parks for a
  human (guided/HA), bounded by `max_escalations` so it can't run away (ADR-0012).
- **hygiene / hygiene_fix** — deterministic format + safe autofixes, then coder repair of
  residual blocking lint/type findings (`hygiene.py`).
- **scan** — security scanners (Gitleaks + Semgrep) in a network-off sandbox.
- **review / review_fix / quality_revise** — read-only tool-using reviewer verifies
  acceptance against real files; `REQUEST_CHANGES` loops a targeted coder fix, and an
  opt-in per-dimension quality revise polishes craftsmanship. Never gates delivery.
- **critic** (opt-in, ADR-0065) — a HELD-OUT model (`held_out_ok()` requires a critic binding
  distinct from the coder's) reviews the delivered tree once, memoized on its tree hash. It is
  veto-only and downgrade-only: it can add `critic_vetoed` to the gate's reasons, never clear one.
  A fault returns no verdict rather than a silent pass.
- **gate** — `evaluate_gate` computes the evidence decision, then the run **interrupts**
  for a human — the LangGraph `interrupt()` is raised via `request_approval` in
  `packages/policies/mosaera_policies/approval.py` (not inline in `graph/`), for any
  `GATED_ACTIONS` member. Deny loops back to `plan` with feedback; approve/stall/cap → `deliver`.
- **deliver** — commit on the run branch, write the report, persist the run. A merge
  request is opened only after approval.

All loops share one `max_iterations` budget with per-loop sub-caps; a per-kind
no-progress circuit breaker parks honestly instead of thrashing.

## Components (monorepo, `uv` workspace)

- **`packages/core`** — the engine: graph, hardened `DockerSandbox` (default; subprocess
  fallback), two-phase validation, agent tools/scanners, `Settings.from_env` config, and
  the `mosaera` CLI.
- **`packages/agents`** — model-facing agents: PM (`pm/`), coder, reviewer, critic (held-out veto), tester.
- **`packages/policies`** — deny-by-default tool allowlist + the delivery gate (the trust
  boundary; CODEOWNERS-protected).
- **`packages/memory`** — durable Postgres + pgvector store via Alembic migrations
  (in `mosaera_memory/migrations/versions/` — the current head is the latest file there).
  No DB configured is a legitimate in-memory fallback; but when a DB **is** configured yet
  unreachable, `guard_memory` refuses to start rather than silently degrading (ADR-0035).
- **`packages/connectors`** — GitLab client + merge-request assembly/opening (the wired
  delivery path), plus a `gh`-CLI GitHub draft-PR flow (`github.py` — exported and tested,
  CLI-only caller; ADR-0001). Opening an MR/PR is **not** graph-gated (ADR-0102): the
  human control is the authenticated endpoint or the `auto_open_mr` opt-in.
  `provider.py` names the **two** delivery providers Mosaera recognizes and derives which
  one a project uses from its `source_repo` by host equality (ADR-0112) — no registry, no
  plugin seam, and no stored copy. An unrecognized source is refused **on the Delivery page
  before the work**, not by a 400 at the finish line.
  `github_app.py` + `github_write.py` deliver to GitHub on a per-repo, 1-hour App installation
  token (ADR-0114), resolved by asking GitHub which installation owns the project's repo —
  never read from a redirect, whose `installation_id` GitHub documents as spoofable. Public
  repositories only for now. `github.py`'s `gh`-CLI flow remains CLI-only.
- **`apps/api`** — FastAPI: submit runs, stream progress over SSE, resolve the approval
  gate over HTTP, multi-user auth (sessions + admin roles), config-in-UI settings, and
  serve the SPA. A durable checkpointer lets a parked run survive restart and rehydrate.
- **`apps/web`** — React + TypeScript dashboard SPA (Vite), served by the API at the same
  origin.

**Claim contract (Wave 1, ADR-0079)** — `mosaera_core/claims.py` derives structured acceptance
claims (versioned schema; provenance ENTAILED / REPOSITORY_INVARIANT / INFERRED; a bound
`oracle_kind` or an honest `none`) from a backlog item's acceptance text at launch. Claims ride
`RunState["claims"]` alongside the unchanged task string and render in the delivery report;
`spec_lint.checkability` classifies items CHECKABLE / PARTIALLY_CHECKABLE / UNDER_SPECIFIED and
feeds under-specified ones into Quincy's existing re-curate pass. The gate does not consume
claims yet — that is a later wave with its own red-team.

**Control liveness (ADR-0081)** — `bench/liveness.py` + the harness's execution fingerprint
(nodes entered, state keys written, interrupt kinds, terminal disposition — never prompts or
model payloads) judge whether an A/B experiment's arms actually executed different code
(`INVALID_EXPERIMENT_IDENTICAL_EXECUTION` otherwise); a per-knob registry records each posture
knob's highest *proven* liveness rung, reported by `scripts/check_control_liveness.py`.

**Model gateway** — `get_chat_model` (`mosaera_core/models.py`) is the single role seam.
BYO models: each role (PM / coder / reviewer / …) maps to any provider — Ollama by
default, or any hosted/custom endpoint — so no provider is ever hardwired.

**Sandbox** — every tool command runs in a throwaway container: `--network none`,
read-only rootfs, `--cap-drop ALL`, resource caps, one writable `/work` mount. The
install phase is the sole egress exception; the test phase runs network-off.

## Roadmap / not yet

Major arcs and their **live status** are in [`../roadmap.md`](../roadmap.md); the enduring direction
is [`north-star.md`](north-star.md). Smaller current-system gaps:

- LiteLLM / OpenAI-compatible proxy and vLLM serving in front of the model gateway.
- Egress-allowlisted install proxy (the `INDEX_URL` seam exists; the proxy does not).
- Durable work-packet cache (specced in ADR-0003; only the within-run memo ships today).

## Pointers

Decisions: see the ADR index `docs/adr/README.md` (ADR-0001 stack, ADR-0002 deterministic-first
+ model-agnostic, ADR-0003 evidence cache, ADR-0004 auth/sessions, ADR-0005 config-in-UI,
ADR-0006 durable transcript + honest outcomes). Threat models: `docs/threat-models/TM-0001`
(the agent loop / repo agent) and `TM-0002` (the API/web server). Overrides for AI agents:
`AGENTS.md`.
