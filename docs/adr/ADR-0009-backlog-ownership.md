# ADR-0009: Quincy owns the backlog — propose-a-changeset curation + soft-lock

- Status: accepted
- Date: 2026-07-11
- Owners: Alejandro Rengifo
- Related: [ADR-0008](ADR-0008-pm-foundation.md) (the PM foundation this builds on), [`docs/design/quincy-pm-case-study.md`](../design/quincy-pm-case-study.md) (§Phase 2)

## Context

ADR-0008 gave the PM ("Quincy") planning capability. The backlog, however, stayed
read-only to him: `pm.chat` could only *propose new items* — a "propose-only" contract
enforced in the chat prompt, the `pm_chat` return shape, and the proposal-card UI. He
could not reprioritize, enhance, reorder, set dependencies, or hold an item. For
autonomous whole-project delivery the PM must **own the backlog** as a working tool.
This ADR records "Phase 2a": the interactive, human-approved subset of that ownership.

## Decision

**1. Curation as a proposed changeset (apply model).** Quincy curates the *existing*
backlog by proposing a **changeset** — a JSON array of operations
(`reorder | enhance | lock | unlock | set_dependencies`), each with a `why` — that the
user reviews and approves in one action. `pm.curate_backlog` (one model call over the
brief + rendered backlog + the global doctrine) emits the changeset; a **deterministic
applier** (`apply_backlog_changeset`) validates it structurally (ids in the project,
reorder is a complete permutation, deps acyclic) — **deny-by-default, rejecting the whole
set on any bad op** — then applies each op via the store primitives. Two endpoints:
`POST …/backlog/curate` (propose, nothing applied) and `…/curate/apply` (approve). The
LLM only *proposes*; validation and mutation are code, so **no `packages/policies`
change** and no new interrupt UI.

**2. Soft-lock — an advisory, user-overridable hold.** A new `locked` + `lock_reason`
on `BacklogItem` (migration 0009) is the PM's deliberate, reasoned hold on running an
item (e.g. "wait for the schema item it depends on"). It is **distinct from the derived
`blocked_by`**: a human can override it. Enforced at the single launch choke point
(`launch_item` raises `ItemLocked`) and skipped by the autonomous picker
(`advance_project`). A manual **`override`** on the run route lets the user run a
soft-locked (or dependency-blocked) item early after reading the caveat; the **autonomous
sweep never overrides**.

**3. New store primitives.** `reorder_backlog(project_id, ordered_ids)` rewrites
positions 0..n-1 in one transaction (positions stay unique); `set_item_lock` /
`is_item_locked`. Enhance already existed (`update_backlog_item`).

**4. Scope.** High-value core first — reprioritize, enhance, set-dependencies, soft-lock —
interactive-only. Split / merge / deduplicate (dependency-graph surgery), autonomous
between-item curation, and live mutation-tools are deferred (see Consequences).

## Options considered

- **Live backlog-mutation tools** (`build_backlog_tools` + a `pm_curator` allowlist role +
  `GATED_ACTIONS`, per-op `interrupt` gating). The idiomatic "backlog is a tool he wields"
  design, but it inverts the propose-only contract in three coupled places at once and
  needs new interrupt/resume UI in the PM chat (only the run workbench has it). Deferred to
  a later phase once less approval friction is wanted; the changeset seam is the safe first
  step.
- **Autonomous between-item curation** (the curator runs in the sweep before each item).
  Deferred here — higher blast radius; land the interactive flow first. **Updated 2026-08-18**
  (`docs/audits/adr-corpus-review-2026-08-18.md`) — subsequently landed in a narrower form by ADR-0023: the
  opt-in `resilient_recuration` lever calls `curate_backlog` + `apply_backlog_changeset` inside the
  autonomous sweep for a *stuck* item (`apps/api/mosaera_api/app_context/_escalation.py`). Curation
  before *every* item remains unbuilt.
- **Make `blocked_by` directly overridable.** Rejected in favour of a *separate* advisory
  soft-lock + a run `override`, so the mechanical dependency truth stays intact for the
  autonomous sweep while the human gets a reasoned, overridable hold.

## Security implications

Low. **No trust-boundary (`packages/policies`) change** — the curator *proposes* a
changeset; a deterministic applier validates (deny-by-default on any invalid op) and
mutates. Soft-lock is advisory and the autonomous sweep never overrides it. The override
is an explicit, human-initiated, per-run action that surfaces the caveat first.

## Operational implications

- Migration **0009** adds `locked`/`lock_reason`. `POST …/backlog/curate` is synchronous
  (a model call, like `pm_chat`); `…/curate/apply` is deterministic.
- The changeset is reviewed in the dashboard (a changeset-review panel); soft-lock shows
  as a distinct badge + caveat with Unlock / "Run anyway (override)".
- Deterministic-first: rendering, validation, reorder, and application are code; the model
  only produces the proposed changeset.

## Consequences

Quincy now genuinely owns the backlog interactively — he can reprioritize, sharpen, wire
dependencies, and hold items with a rationale, all as a reviewable changeset. This is the
foundation for the deferred depth: **split / merge / deduplicate** (needs a single-item
delete + dependency-edge rewiring + dedupe detection), **autonomous between-item
curation** in the sweep, and **live mutation-tools** with per-op gating. Together with the
existing dependency DAG and the autonomous sweep, it moves Mosaera toward a PM that runs
the backlog like a boss.
