# ADR-0023: The resilient autonomous sweep — one stuck item can't sink the project

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0022](ADR-0022-live-model-escalation.md) (the escalation rung this composes with), [ADR-0021](ADR-0021-revertable-per-item-merge-requests.md)/[ADR-0019](ADR-0019-autonomous-mr-last-mile.md) (per-item MRs that make a PARTIAL delivery real), [ADR-0009](ADR-0009-backlog-ownership.md)/[ADR-0012](ADR-0012-cohesive-team-supervision.md) (the autonomous backlog re-scope class the opt-in re-curation reuses), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (the honest `incomplete` it triggers on)

## Context

The autonomous backlog sweep was a **chain, not a loop**: `advance_project` launches one item, and only that
item's *clean-delivery* callback launches the next. When an item ended `incomplete` (after model escalation was
exhausted/off) or hit blocking evidence at the gate, `_after` wrote a pause note and the chain **died** — a
single stuck item halted the whole project. Worse, a blocking-evidence gate in autonomous mode **parked** the
run, which blocks the worker thread *holding the project's clone reservation*, so nothing else could run either.

For a *walk-away* autonomous run this is a bug: you come back to a project that stopped at the first item it
couldn't finish, with everything behind it undelivered. And the naive fix — just re-drive the sweep — infinite-
loops: an `incomplete` run resets the item to flat `todo`, indistinguishable from fresh, so the picker re-selects
the same stuck item forever (there was no attempt counter, no `deferred` state).

## Decision

**A stuck item is DEFERRED (surfaced with its reason) and the sweep keeps delivering the rest.** The recovery is
a ladder mirroring the DNA escalation: **model-escalate (ADR-0022) → re-curate (opt-in) → defer**, each rung
always ending in `advance_project` so the backlog keeps moving.

1. **`deferred` — a new item status value** (the `status` column is already `String(32)`, so **no migration**). A
   `deferred` item drops out of the picker (`status=="todo"` filter), keeps its dependents blocked
   (`_DELIVERED={in_review,done}`), and makes the all-delivered check for the project MR False — all existing
   filters handle it correctly, with zero new plumbing. A distinct value (not the human-facing soft-lock) keeps
   "auto-skipped by the sweep" honestly separate from "the PM held this". The board gets a fifth "Deferred /
   needs attention" lane.
2. **The ladder in `_after`** (`_try_recurate_or_defer`, modeled on `_try_model_escalation`): on `incomplete`,
   after escalation returns False — if `resilient_sweep` (default ON), optionally ask Quincy to re-curate the
   stuck item (opt-in), then **defer the item unless re-curation removed it** (split/delete → fresh children),
   and `advance_project`. Never retries the same id in-place — that keeps the ladder **provably loop-safe**: each
   stuck event terminally defers-or-removes its item, so the picker always advances to a different one.
3. **The park reroute (runner-side, gated, deliver-gate only).** A chained autonomous run marked `resilient`
   does NOT park-and-hold the clone on blocking delivery evidence — it breaks to the terminal block, which sees
   `approved=False` (the gate interrupt precedes `deliver_node`) and ends the run honestly `incomplete` with the
   gate reasons; the sweep's `_after` then defers it. The run row goes `INCOMPLETE` (not `AWAITING_APPROVAL`), so
   it can never be rehydrated into the gate. Scoped to the deliver-gate auto-park only — budget parking and the
   guided-escalation park are untouched.
4. **Honest partial completion.** When the sweep runs out of runnable items but some are `deferred`, the project
   ends with a plain summary — `"sweep complete: delivered N, deferred M (need attention): <titles>"` — not a
   silent stop and not a false "complete". In `item` MR granularity (ADR-0021) the delivered items already opened
   their per-item MRs as they went, so a partial delivery still yields real, reviewable MRs.

**Knobs:** `resilient_sweep` (`MOSAERA_RESILIENT_SWEEP`, **default ON** — halting a walk-away run on one stuck
item is the bug; `deferred` is honest + reversible, and an operator can opt out for the old park-and-halt) and
`resilient_recuration` (`MOSAERA_RESILIENT_RECURATION`, **default OFF** — a Quincy re-curation is an extra PM
model call, so it's a separate opt-in, mirroring `model_escalation_enabled`).

## Consequences

- **The sweep survives a stuck item.** A too-weak/unsatisfiable item is deferred and the rest of the backlog
  still delivers (per-item MRs open as they go) — the "walk away, come back to what could be done" behavior the
  autonomous mode promised. Deferred items surface for a human/Quincy with their reason.
- **Loop-safe by construction.** `deferred` leaves the picker permanently (until a human/Quincy revives it);
  the ladder never retries an id in-place; re-curation is one-shot per stuck event; the monthly budget cap
  remains the ultimate backstop. Provably no tight infinite loop.
- **Opt-in re-curation reuses existing machinery.** Quincy's `curate_backlog` + the deterministic deny-by-default
  `apply_backlog_changeset` are called from the sweep (a new `AppContext` capability) with autonomous auto-apply
  — the same mode-gate idiom as ADR-0012/0022. A malformed / no-mix-violating changeset raises `ValueError`,
  which is swallowed down to a plain defer so the sweep never breaks.
- **Behavior change (called out).** `resilient_sweep` ON replaces today's terminal pause for autonomous runs — a
  conservative operator can ship it OFF for a release, then flip it on.
- **Honest v1 limits.** Re-curation never retries the same id in-place (a bounded retry-with-enhance is future
  work needing an attempt counter); a *guided/high-assurance* run still parks for a human (correct — a human is
  the gate there); the D3 reroute covers the deliver-gate park only.

## Threat surface

Quincy auto-applying a changeset mid-sweep is an autonomous backlog mutation without a human — but it goes
through the deterministic, deny-by-default `apply_backlog_changeset` (the same validator the human-gated
`/curate/apply` endpoint uses), is the **same class** as the ADR-0009/0012 autonomous re-scope, and is gated
behind a default-OFF opt-in. No new outward action, no egress, no new threat class — a one-line pointer in
TM-0002 (autonomous backlog-mutation surface) suffices; no new TM file.

## Alternatives considered

- **Reuse the soft-lock to defer.** Rejected: `lock_reason` renders as a human "PM soft-lock" in the UI, blurring
  "the operator held this" with "the sweep auto-skipped it". A distinct `deferred` status is honest and free.
- **Retry the stuck item in-place after an enhance.** Rejected for v1: without an attempt counter it risks a
  loop (stuck → enhance → stuck → enhance …). Deferring the id (unless re-curation splits it into fresh children)
  is the loop-safe choice; a bounded in-place retry is future work.
- **Cancel the parked RunSession to free the clone.** Rejected: intricate (the worker is blocked on a queue). The
  D3 reroute ends the run cleanly at the interrupt instead, with no graph-state or checkpoint risk.
