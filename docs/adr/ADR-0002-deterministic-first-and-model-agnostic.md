# ADR-0002: Deterministic-first execution and model-agnostic model access

- Status: accepted
- Date: 2026-07-09
- Owners: Alejandro Rengifo
- Related issue: #22 (deterministic-first discipline), #21 (bring-your-own-model), #1 (cost accounting), #7 (model routing)
- Related threat model: docs/threat-models/TM-0001

## Context

Mosaera is an AI product, but the AI is the most expensive and slowest part of every
interaction. Two hard requirements drive the product's economics and its feel:

- **Cost.** The business thesis is "cost per delivered, validated outcome," not "cost per
  model call." A cheap run that fails three times is not cheap; unbounded agent chatter and
  context duplication are the biggest hidden costs.
- **Speed / UX.** The dashboard must feel fast and smooth. Perceived latency is a feature.
  Blocking an interactive surface on a model call is a defect, not a trade-off.

Separately, "self-hosted and model-agnostic / bring-your-own-model" is a core market wedge.
Any provider coupling that leaks out of a single seam makes that wedge impossible to deliver
and makes cost/routing policy impossible to enforce.

These were already implicit in the strategy (Rule 4 "cheap deterministic tools before
expensive reasoning"; §14.6). This ADR makes them binding engineering principles so they are
front-and-center while implementing, not aspirations recovered after the fact.

## Decision

**1. Deterministic-first.** Reach for deterministic code, automation, and cached evidence
before an LLM call. An LLM call is justified only for reasoning/synthesis/generation that
deterministic code genuinely cannot do. The default escalation ladder is:

```
cached evidence → deterministic tool → local small model → local coder/reasoning model → cloud → human
```

Escalate only when confidence is low, risk is high, validation is ambiguous, security is
involved, scope is cross-cutting, the cheaper tier failed, or the user chose a
higher-assurance mode. The interactive path must never block on a model call — stream,
optimistic-update, and keep the poll authoritative (as the run workbench already does).

**2. Model-agnostic.** All model access flows through the single role seam
`get_chat_model` (`packages/core/mosaera_core/models.py`). Providers/SDKs are not referenced
anywhere else. Roles map to configurable models so users can bring their own provider and
keys; any role may be backed by Ollama, a hosted API, or a custom endpoint.

**Enforcement.** New features carry a one-line deterministic-first justification (can this be
code? interactive-path latency? token/$ cost?). Cost accounting (#1) exposes the metrics that
keep us honest: LLM-calls-per-delivered-item, deterministic:LLM ratio, and p50/p95 interactive
latency. Provider/model selection is policy at the seam (#7 routing, #21 BYOM), never inline.

**Delivered (#21 BYOM, #7 routing).** The seam constraint held: BYOM made each role bindable
to a `(provider, model)` and #7 added selectable **cost-modes** (Economy/Balanced/Premium) — a
named per-role model profile chosen per run — both resolved entirely inside `get_chat_model`
via `Settings.role_model`, with agents/orchestrator untouched. This realizes "the user chose a
higher-assurance mode" from the ladder as *static* routing (deterministic, applied before graph
build). The ladder's *dynamic* "the cheaper tier failed" escalation ~~remains future work~~ **was subsequently built** —
ADR-0016 (diagnose the bottleneck role, `bench/escalation.py::escalate_role`) and ADR-0022 (the live
path, `app_context/_escalation.py::_try_model_escalation`); corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`. #7 also
returns the pre-run cost estimate (#5), now honestly conditioned on the chosen tier rather than a
blended average.

**Delivered (#22 discipline metrics).** All three enforcement metrics are now surfaced on the
project Overview: **LLM-calls-per-delivered-item**, the **deterministic:LLM ratio** (deterministic
tool ops per model call), and **p50/p95 interactive latency**. The first two compute from the
durable cost rollup (`RunSession` → `decisions.kind='cost'`) with no new table. The latency metric
times the one interactive path that blocks a human synchronously on a model call (`pm_chat`) and
stores samples in a `latency_samples` table (Alembic `0003`); p50/p95 are nearest-rank in Python.
Recording is best-effort — it never breaks the chat. The **discipline checklist** (the one-line
deterministic-first justification) is now a `CONTRIBUTING.md` PR-checklist item, closing #22.

**Delivered (#23 cached evidence — MVP).** The "cached evidence" tier of the ladder now exists as
*within-run, content-addressed memoization*: the repo overview (plan loop) and the validation-plan
detection (test loop) are keyed by a cheap working-tree hash (`Workspace.tree_hash`) and reused
across iterations while the tree is unchanged, recomputed when it changes. This is run/process-scoped
(no cross-run staleness). The durable, cross-run **work-packet** design — content-addressed evidence
bundles reused across *runs* of a backlog item — is specified in ADR-0003 and deferred.

## Options considered

- **"AI-first, optimize later."** Rejected — it bakes in cost and latency that are extremely
  hard to remove after features depend on model calls in the hot path, and it erodes the
  product's core differentiators (cost control, smooth UX).
- **Hardwire the current provider (Ollama) and generalize later.** Rejected as a *pattern*;
  the single-seam constraint keeps "later" cheap. The current Ollama binding is fine precisely
  because it is confined to `get_chat_model`.

## Security implications

Model-agnostic access with BYO keys requires a secure key vault and per-role scoping (#21);
keys are secrets and never logged or echoed. Confining provider access to one seam also
confines egress and auditability. Deterministic-first reduces the surface where untrusted
repo/tool content reaches a model.

## Operational implications

Requires cost/token accounting (#1) and the metrics above to verify adherence. Deterministic
components are cheaper to run, faster, and easier to test than model calls, lowering sandbox
and inference cost. Routing/escalation policy lives with the other governance policy.

## Consequences

- Good: lower cost per outcome, faster UI, real BYO-model support, testable/deterministic
  behavior, cleaner audit and egress boundaries.
- Cost: some features take more up-front engineering to do deterministically instead of
  "just ask the model."
- Follow-up: #1 accounting + metrics ✓, #7 routing ✓, #21 BYOM provider layer ✓, #22 the
  discipline (budgets ✓, checklist ✓, dashboard metrics ✓ — full latency triad), #23 evidence
  cache — the within-run MVP is delivered; the durable cross-run **work-packet** table is specified
  and deferred (ADR-0003). With these, cost epic **#19 is effectively complete** (all children
  delivered or, for the work-packet store, specified as the single remaining follow-up).
