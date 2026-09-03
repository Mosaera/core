# ADR-0012: Cohesive-team supervision — deterministic guards + structured yield + a mode-gated supervisor

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes + run_events), [ADR-0008](ADR-0008-pm-foundation.md)/[ADR-0011](ADR-0011-agent-self-awareness-and-decompose-dag.md) (the PM/agent foundation), [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (deterministic-first)
- Amended by: [ADR-0101](ADR-0101-run-interaction-modes.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

A real run exposed how the fixed relay fails. On a task that changed a persistence
contract, the coder re-ran the **same failing tests ~25 times**, rationalizing failure as
success ("the tests are testing the old behavior, my implementation is correct"), wrote
scratch files and an unasked-for README, and only stopped when the operator cancelled —
burning ~50+ model calls. The root causes are **not routing**:

1. **Within-node loop.** The coder can re-run `run_tests` itself inside one implement-node
   visit, bounded only by `coder_step_limit`; the no-progress breaker only fires *between*
   visits, so the bleed happens before it ever sees a second outcome.
2. **Siloed relay.** The coder hit a decision above its pay grade — *the task changes a
   contract the existing tests encode; rewrite them or not?* — with **no way to raise its
   hand**. Its `SUMMARY: blocked —` convention existed but was **never parsed**.
3. **Lost insight.** The planner (Quincy) actually identified the tension ("the existing
   tests encode the OLD contract"), then lost it: his plan hit the step budget and emitted
   `Model call limits exceeded` as the plan text.

The agents run as a **relay that only passes state forward**, never back, with no supervisor
watching. That is the gap between "a pipeline" and "a team."

## Decision

Make them a team via **exception-driven supervision** — deterministic guards that stop the
bleed and make agents **yield a structured signal**, resolved by a **mode-gated decider** —
rather than live, per-hop LLM routing.

**1. Deterministic guards + structured yield (P1).** Cheap, always-on, no model call:
- `run_tests` refuses to keep returning the SAME failure within one implement session (keyed
  on the normalized failure output, so different wrong edits don't evade it; any accepted
  write clears the counter). After a small limit it hands the coder a STOP directive to yield.
- The coder's `SUMMARY: blocked — …` / `SUMMARY: escalate — …` convention is finally **parsed**
  into structured state. `blocked` = it hit a wall it can't pass; `escalate` = it needs a
  decision or scope change.
- Planner budget-exhaustion degrades to a real fallback plan (never the error string).

**2. Mode-gated supervisor (P2).** A `supervise` node raises an escalation, resolved by the
run mode — **the same runner-side `autonomous`/`_high_assurance` split the delivery gate
already uses**:
- **Autonomous → Quincy re-scopes, recorded and NON-BLOCKING.** The escalation resumes with
  re-scope feedback that loops back to planning; the run keeps moving.
- **Guided / High-Assurance → park for a human**, exactly like the delivery gate.
Bounded by `max_escalations` so a re-scope↔re-block cycle can't run away.

**3. Contradiction governance (P3).** A failing **existing** test is a **STOP by default** —
the coder must yield, not declare victory over it. A test may be **updated only when the plan
explicitly states the task changes the contract that test encodes** (doctrine + `AGENTS.md` +
the coder prompt). This is what lets a re-scoped plan legitimately authorize "update
`test_overwrite_*` to the new contract."

**Everything is recorded and auditable.** Escalations and supervisor decisions are durable
transcript events (`escalation`) surfaced in `GET /runs/{id}/transcript`; an unresolved
escalation terminates honestly as `incomplete` with a `termination_reason` (ADR-0006).

## Options considered

- **Live (mid-token) LLM supervision** — Quincy watching the coder's stream and interrupting
  mid-loop. **Rejected.** On a self-hosted single-GPU box it means running two models at once
  (VRAM contention, doubled latency on the interactive path — against deterministic-first and
  the cost story), and mid-stream course changes are hard to render legibly. We already stream
  live *visibility* (`subgraphs=True` milestones); the missing piece is checkpoint *control*,
  not mid-token steering. **Live visibility ≠ live control.**
- **Per-hop LLM routing** (a full hub-and-spoke where Quincy re-decides after every stage).
  Deferred: it adds a PM model call to every hop — potentially *more* expensive than today on
  the happy path. The exception channel here is its precursor; the hub can come later.
- **Raising the escalation through `GATED_ACTIONS`** (the approval gate's mechanism).
  Rejected — that would edit the CODEOWNERS-gated `packages/policies`. The escalation is
  orchestration, not a trust boundary, so it is a plain `interrupt` consumed runner-side.

## Product rationale (why this shape for our market)

Mosaera's buyer runs it **self-hosted, model-agnostic, on their own infra**, behind approval
gates, with budgets and honest outcomes. They optimize for **control, trust, and cost** — not
a maximally autonomous black box; they delegate backlog items and review MRs, and pay for
every token in GPU-time. For that buyer, **between-packets supervision + always-on
deterministic guards is the product; live LLM control is a demo:**
1. **Legibility sells trust** — every intervention is a reviewable event with a reason (the
   same property that makes the approval gate and honest-outcome work compelling).
2. **Cost is a feature** — a second model babysitting the first, on their hardware, is the
   opposite of the cost story; guards cost nothing and the smart call happens once, at the
   exception.
3. **One mental model everywhere** — *autonomous acts, guided asks* — at the delivery gate and
   mid-run alike.

## Security implications

**No trust-boundary change.** `packages/policies` is untouched: the escalation is a plain
LangGraph `interrupt` (action `"escalation"`), not a `GATED_ACTIONS` entry, and the deny-by-
default write/deliver gates are unchanged. In guided/HA the escalation parks a human exactly
like the delivery gate; in autonomous it records a non-blocking decision and continues.
No new external surface and no threat-model change (TM-0002 unchanged).

## Operational implications

- **No migration** across all phases. P1 adds a config knob (`coder_test_repeat_limit`); P2
  adds `max_escalations` and the durable `escalation` transcript event (its `type` fits the
  existing `run_events.type` column). P3 touches only prompts/doctrine/`AGENTS.md`.
- Deterministic-first holds: the guards, the yield parser, the routing, and the audit are all
  code; a model call happens only at an actual exception, and only for the re-scope decision.

## Consequences

The password-generator-style loop ends in ~5 model calls instead of ~50, honestly, the moment
P1 lands. With P2 the run is supervised — Quincy re-scopes in autonomous mode (recorded), a
human decides in guided/HA — and with P3 a task that legitimately changes a test contract
actually **resolves** instead of ending in a bounded honest give-up.

**Coupling to hold in mind:** P2 without P3 is a bounded token-saver, not a resolver — the
coder's "never weaken tests" rule blocks the re-scope from fixing a task-vs-tests contradiction
until P3 authorizes the narrow test-update exception, so P2 and P3 ship together.

This is deliberately the **exception-channel precursor** to a future flow-orchestrator (Quincy
routing agents dynamically via work packets, `Command(goto)`/`Send`) — but it earns its keep on
its own by turning a siloed relay into a supervised team.
