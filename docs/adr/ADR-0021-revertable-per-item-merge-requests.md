# ADR-0021: Revertable per-item merge requests — stacked delivery, one MR per item

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0019](ADR-0019-autonomous-mr-last-mile.md) (the auto-open-MR this reshapes), [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (verify-before-deliver — the correctness complement), [ADR-0010](ADR-0010-backlog-structural-ops-and-chat-curation.md) (the `merge` op reused for grouping), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes)
- Amended by: [ADR-0102](ADR-0102-delivery-spine-truth-up.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The autonomous sweep now (opt-in, ADR-0019) opens **one whole-project merge request** for the entire backlog,
on a single shared branch `mosaera/project-<id>` onto which every item run accumulates commits. For a hands-off
delivery that a human is expected to *trust*, that unit is wrong on two counts:

- **Unreviewable.** A finished project is dozens of files across many items in one MR — no reviewer can
  meaningfully approve it, and the whole point of autonomous delivery is that a human wasn't watching it happen.
- **Un-revertable.** If any single item is wrong, mis-validated (by a human or by the AI), or corrupt, there is
  no clean "one step back" — the bad change is entangled with every other item on the one branch.

The delivery unit must mirror disciplined human development: **small, coherent, independently reviewable and
revertable changes, stacked by dependency, each CI-gated** — exactly how this repo itself ships (one ADR ≈ one MR).

## Decision

**One MR per backlog item, stacked in delivery order; Quincy groups tightly-coupled items into one item.**

### The stacking model — linear, delivery-order
Items deliver one at a time (the sweep is serial, in dependency-eligible order). Each delivered item gets its
own branch `mosaera/item-<id>` **cut from the current stack tip** (the previously delivered item's branch, or the
source base for the first), so the branch carries all prior work while the item's **MR diff is just its own change**:

```
base ──< item-1 >── MR-1 → base
            └──< item-2 >── MR-2 → item-1        (stacked)
                     └──< item-3 >── MR-3 → item-2
```
The human merges bottom-up; GitLab **auto-retargets** each open MR to its target's target as the predecessor
merges, so the stack collapses cleanly to base. "One step back" = close/revert the top MR; earlier MRs are intact.

Linear (not DAG-shaped) stacking is the first cut: simplest, correct, and it matches today's linear accumulation.
**Honest tradeoff:** items that are actually independent still stack (they must be merged in order). DAG-parallel
independent MRs (roots each targeting base as separate stacks) is a noted future refinement.

### Where the single-branch assumption lived, and the minimal seams
The commit path was already branch-agnostic (`deliver_node` → `commit_all` commit to *whatever branch is checked
out*, only when `approved`), and the GitLab connector already pushes an arbitrary source and targets an arbitrary
`merge_request.target` via push-options (write_repository scope only — no `api`). So the change is small and local:

1. **Per-item branch at run start** — `open_project_workspace(..., item_branch=…)` does `checkout -B
   mosaera/item-<id>` at the current tip before the existing `reset --hard`+`clean`, and stamps `Workspace.branch`.
   Read paths keep `item_branch=None` (+ `reset=False`) so a concurrent GET never re-points a live branch.
   Factory passes the item branch only on a fresh (non-resume) item run.
2. **Per-item diff** — `project_item_diff(workspace, predecessor)` = `predecessor...HEAD` (the clean single-item diff).
3. **Connector** — `open_merge_request(..., remove_source_branch=…)`, default True (unchanged for the whole-project
   MR) but **False for a stacked MR**: auto-deleting item N's branch on merge would orphan item N+1, whose target
   *is* that branch.
4. **Storage** — `BacklogItem.branch` + `mr_url` (migration 0010), threaded through `update_backlog_item` /
   `_backlog_summary`, mirroring `Project.branch`/`mr_url` one level down. The **tip pointer** reuses
   `Project.branch` = the last *delivered* item's branch (the next item's target); failed/incomplete items never
   commit, push, or advance the tip, so a failure can't corrupt the chain.
5. **The knob** — `mr_granularity` (`item` | `project`, default `item`; enum ⇒ dropdown per the hard rule),
   gated by the existing `auto_open_mr` (default OFF). `item` = per-item stacked MRs; `project` = the ADR-0019
   whole-project MR, kept. Granularity only picks the *shape* when an MR opens.

### The sweep wiring
`open_item_mr(mem, settings, project_id, item_id)` opens one item's stacked MR: it resolves the target as the
**stacked predecessor** — the already-delivered item (one with a branch) of greatest `position` below this item's,
else the source base — computes the clean `predecessor...HEAD` diff, and pushes with `remove_source_branch=False`.
It is **fired from the per-item clean-delivery path** (`AppContext._maybe_open_item_mr`, called from `_after` and
`rehydrate._after` right after an item delivers and before advancing), not from the whole-backlog-completion hook.
`_maybe_open_project_mr` (ADR-0019) now fires **only in `project` granularity**, so the two never double-open.
The **idempotency marker** is `BacklogItem.branch` — written only when the MR opens, so a set branch means "already
opened" even if the MR URL couldn't be parsed from the push banner. All of it is best-effort: audited (`mr.opened`
/ `mr.failed`), never allowed to break the sweep.

### Grouping — reuse, don't rebuild
"Quincy groups tightly-coupled items" is served by the **existing ADR-0010 `merge` op**: it collapses N coupled
items into one item → one run → one MR, with **zero schema change** and the full propose→validate→apply path
already wired. The complement is a **decompose-prompt change** (`_DECOMPOSE_SYSTEM`): Quincy sizes each item **as
one merge request** — a single coherent change a reviewer can read and merge on its own, that builds and makes
sense in isolation — to begin with, so no piece is so fine it can't stand alone (an interface + its implementation
= one item). The curator doctrine (`_CURATE_SYSTEM`) mirrors this: propose `merge` for items so tightly coupled
neither is reviewable without the other. So grouping is **decompose-sizing + the reused merge op**, not new
machinery. A dedicated `mr_group` tag (items stay separate, share one MR) was rejected: it needs a new column
*and* entirely new per-group branch orchestration for marginal gain over merge.

## Consequences

- **Reviewable + revertable delivery.** Each item is a small MR with a clean single-item diff, CI-gated, mergeable
  and revertable on its own — the trust property the whole-project MR lacked.
- **Composes with the correctness gate (ADR-0020).** Verify-before-deliver ensures each item's MR is *correct*;
  per-item MRs ensure it's *reviewable* — together, autonomous delivery is both safe and inspectable.
- **Stacked-branch lifecycle.** `remove_source_branch=False` in `item` mode is mandatory (else an orphaned target);
  branches accrue until merged — acceptable, with a future cleanup pass noted. **Update 2026-08-18 — that cleanup
  pass has SHIPPED** (the ADR-0103 "branch v1" work): remote branch list + prune-merged + single-branch delete, with
  the prune/delete guard refusing a branch that is the SOURCE *or* the stacked TARGET of an open item MR, and
  `_stacked_target` now skipping merged predecessors — `apps/api/mosaera_api/routes/project_delivery.py`,
  `apps/api/mosaera_api/delivery.py`. Recorded in `docs/audits/adr-corpus-review-2026-08-18.md`.
- **Backward compatible.** `mr_granularity=project` preserves the ADR-0019 behavior; `auto_open_mr` OFF opens
  nothing. The per-item branch model is the new internal accumulation shape regardless of granularity.

## Threat surface
No new class. Per-item MRs are the **ADR-0019 egress class ×N**: the same project-scoped `write_repository`-only
token, the same push-options path, **opens never merges** — just more branches pushed, one MR per item. Recorded
in TM-0002 with the sweep-wiring MR.

## Alternatives considered
- **Keep the whole-project MR, review it in chunks.** Doesn't give independent revert boundaries — the bad change
  stays entangled on one branch. Rejected; retained only as the opt-in `project` granularity.
- **Strictly one MR per item, no grouping.** Interdependent thin items (define-interface + implement) produce
  meaningless standalone MRs and more of them. Rejected in favor of Quincy-sized items + the merge op.
- **A new `mr_group` tag (separate items, shared MR).** Needs a schema column and net-new per-group branch
  orchestration; the merge op already yields one-MR-per-coupled-group deterministically. Deferred.
