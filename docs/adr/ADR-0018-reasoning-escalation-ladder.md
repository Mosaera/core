# ADR-0018: Reasoning-escalation ladder — escalate the thinking, keep the cheap executor

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0002](ADR-0002-deterministic-first-and-model-agnostic.md) (the DNA escalation ladder + `get_chat_model` seam), [ADR-0017](ADR-0017-reason-before-park.md) (the own-model reason pass this extends), [ADR-0016](ADR-0016-deterministic-model-escalation.md) (coder-model escalation — the deferred outer-loop layer this precedes), [ADR-0012/0015](ADR-0012-cohesive-team-supervision.md) (the `SUMMARY: escalate` valve preserved)

## Context

To solve the *hard* benchmarks autonomously we need the escalation ladder to be *live and surgical*.
Two prior halves don't connect: **reason-on-stall** (ADR-0017) runs one rethink with the coder's *own*
model then parks; **model escalation** (ADR-0016) can bump a role's model but lives only in the
benchmark harness and is *coarse* (re-runs the whole task). The hard-case demos showed the bottleneck is
often a **reasoning gap** (the coder pursues the wrong approach), which a stronger *thinker* fixes
cheaply — no need to swap the whole executor.

A decisive constraint: **the coder model is build-time-static** — bound into the `implement` agent at
`build_graph` (`get_chat_model("coder", settings)` → `create_agent(model=…)` → `add_node`) and never
re-resolved. It cannot be swapped mid-run. So *coder-model* escalation is inherently an outer re-run
(deferred). But the *reasoning* — a one-off, tool-less model call — **can** be escalated live inside the
reason node.

## Decision

**Make the ADR-0017 reason node a ladder.** On a no-progress trip the reason node runs, keyed by
`reason_attempts` as the tier index:
- **Pass 0** (`reason_attempts == 0` on entry): the coder's OWN model rethinks — ADR-0017, unchanged.
- **Pass k ≥ 1**: a one-off, **tool-less** call to a stronger reasoner (`reason_escalation[k-1]`)
  diagnoses the stuck point (`DIAGNOSIS_SYSTEM` + a task/plan/design/failure packet) and returns a
  concrete numbered plan, which is injected as the coder's next instruction
  (`reasoned_plan_instruction`) — the **same cheap coder executes it**. The reasoner is invoked via the
  established `replace(settings, pm=tier)` → `get_chat_model("pm", …)` → `robust_invoke` → `message_text`
  idiom (deepseek-r1/gpt-oss auto-route CoT to the reasoning channel, so the text is clean; a tool-less
  diagnosis makes deepseek-r1's inability to emit tool calls irrelevant).

**Config.** New `reason_escalation: list[RoleModel]` (ordered reasoning tiers), parsed from
`MOSAERA_REASON_ESCALATION` (JSON) / `settings.json`; empty default (opt-in, requires
`reason_on_stall_enabled`). The bound is an **effective floor**:
`max_reason = max(max_reason_attempts, 1 + len(reason_escalation))` — a configured ladder is always
reachable (pass 0 own-model + N tiers) without also raising the attempts knob; an empty ladder is
identical to ADR-0017.

**Local-first, enforced.** Only `ollama` tiers this cut — a non-local tier is dropped at runtime
(`provider_is_local` guard → own-model fallback), so nothing auto-egresses off-box and the `$0`-priced
USD-cap blind spot cannot bite. ~~**Cloud reason tiers are deferred**~~ **— DISCHARGED by ADR-0024** (noted 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`): the runtime guard is now `models.cloud_tier_allowed` (consented egress AND a `model_prices` entry), not `provider_is_local`, so a cloud reason tier is reachable today under that gate — `graph/nodes_reason.py`. As written, deferred until a live off-box-egress gate and
a "hosted reason tier requires a `model_prices` entry" check exist (else a $0-priced cloud call would
evade the USD cap). A future cloud tier **will require the TM-0001 model-context-egress update**.

**Metering.** `robust_invoke` gains an optional `config` threaded to `model.invoke(config=…)`, and the
reason node now takes `config: RunnableConfig` (like `review_node`), so the reasoner call is captured by
the run's `UsageCallback` and attributed to node `"reason"` (local → `$0`, tokens still counted).

**Safety of the ladder itself.** The double bound holds: `iteration` shares `max_iter`; `reason_attempts
< max_reason` bounds the climb. An empty or failed reasoner returns `""` → the pass falls back to the
own-model prompt (never wasted, never a crash — a reasoner blip cannot fail the run). The
`SUMMARY: escalate` valve is preserved in the injected instruction, so a genuinely-blocked coder still
routes to the supervisor.

## Consequences

- The escalation ladder's cheap surgical *middle rungs* are now live: deterministic (ADR-0002) →
  own-model reason (ADR-0017) → **stronger-reasoner tiers (this)** → coder-model re-run (ADR-0016,
  deferred) → human. Cloud only when local rungs are exhausted, and not on this cut.
- Cost stays disciplined: one reasoning burst per stall, the coder stays cheap, all local/free here.
- **No policy, migration, or threat-model change** for this cut (local-only, opt-in, no new egress) — but
  a future cloud tier is a threat-surface change and must update TM-0001 + add the egress/price gates.

## Alternatives considered

- **Escalate the coder's model mid-run.** Impossible without rebuilding the graph (build-time-static
  model) — that is the deferred outer-loop Layer B (promote ADR-0016 into the live runner), warranted
  only for genuine *execution*-gap cases the reasoning ladder can't close (to be measured first).
- **Overload `role_escalation` for the reasoning tiers.** Rejected: `role_escalation` mutates an agent
  binding and is gated to the four real roles; a reasoning tier is a distinct one-off, tool-less,
  non-agent call. A separate flat `reason_escalation` keeps the semantics clean.
- **Make every reason pass a stronger reasoner.** Rejected: pass 0 with the coder's own model is nearly
  free and often enough; escalate only on proven need (deterministic-first).
