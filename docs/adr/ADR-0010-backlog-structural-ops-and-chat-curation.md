# ADR-0010: Backlog structural ops + Quincy owns the backlog in chat

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0009](ADR-0009-backlog-ownership.md) (the changeset/soft-lock model this extends), [ADR-0008](ADR-0008-pm-foundation.md) (the PM foundation), [`docs/design/quincy-pm-case-study.md`](../design/quincy-pm-case-study.md) (§Phase 2)

## Context

ADR-0009 ("Phase 2a") gave Quincy interactive backlog ownership — reorder / enhance /
set-dependencies / soft-lock — as a **proposed changeset** a deterministic applier
validates and applies. It deferred two things it named explicitly:

1. **Dependency-graph surgery** — `split`, `merge`, `deduplicate`, and single-item
   `delete` — the depth needed to actually *reshape* a backlog, not just reorder it.
2. Closing the gap the case study flagged: the **PM chat still ran the old propose-only
   contract**. `_CHAT_SYSTEM` literally told Quincy *"Your ONLY backlog power is proposing
   NEW items… You CANNOT modify, reorder, or delete existing backlog items… say plainly
   that you cannot do that directly yet."* So when a stakeholder asked him **in
   conversation** to reprioritize, split, or lock something, he **deferred with text
   instead of producing an approvable action card** — the new curation power lived only
   behind a separate "Curate backlog" button, and Quincy didn't know he had it. Per direct
   feedback: *"make sure with all these added capabilities that Quincy knows he's capable
   to do them… he just sends text without an action card as if he doesn't know he's able
   to do what's being asked of him with human approval."*

This ADR records "Phase 2b", which lands both together.

## Decision

**1. Structural ops as store primitives (the DAG surgery).** Three new
`MemoryStore` methods, each one transaction, reusing `_would_cycle` + a shared `_renumber`:

- `delete_backlog_item(item_id)` — deletes the item (edge FKs are `ondelete=CASCADE`,
  `Run.item_id` is `SET NULL` so run history survives) and renumbers survivors; refuses an
  `in_progress` item.
- `split_backlog_item(item_id, parts)` — N children inherit the parent's `depends_on`;
  **every parent `dependent` is rewired onto ALL children** (a dependent waits for every
  piece), each new edge cycle-guarded; parent deleted; children take the parent's slot.
- `merge_backlog_items(target_id, source_ids, …)` — unions the sources' deps onto the
  target (excluding the dead set = sources ∪ target), repoints each source's dependents
  onto the target (rebuilt as a **distinct** list → no composite-PK duplicate,
  cycle-guarded), optional content fold-in, deletes sources, renumbers.

Pitfalls handled: self-edge, cycle, dangling edge, duplicate-PK, position collision.
The DAG rewiring is verified against real Postgres in `test_store.py`. **No schema
migration** — these operate on the existing `backlog_items` + edge tables.

**2. Structural ops in the changeset vocabulary + the no-mixing rule.** `_CURATE_SYSTEM`
gains `split` / `merge` / `delete` grammar and a **deduplicate clause** (heuristic:
detect overlapping title/description/acceptance → propose a `merge`; no embeddings).
`apply_backlog_changeset` validates + dispatches them and enforces two guards, because
structural ops renumber positions and mint/remove ids:
  - a changeset **may not mix** a structural op (`split`/`merge`/`delete`) with `reorder`
    or `set_dependencies` (those reference a now-stale id/position snapshot); and
  - no two structural ops may touch the same item (disjoint-`touched` guard).

**3. Quincy owns the backlog in chat — one unified changeset.** The add + curation flows
collapse into **one op vocabulary** proposed on both surfaces:
  - A shared `_CHANGESET_OPS` grammar constant (used by both `_CURATE_SYSTEM` and
    `_CHAT_SYSTEM`) gains an **`add`** op (`{"op":"add","title",…,"why"}`).
    `apply_backlog_changeset` applies `add` **last** — appended at `max(position)+1` — so a
    same-changeset reorder/structural op keeps operating on the id/position snapshot it was
    validated against.
  - `_CHAT_SYSTEM` is **rewritten**: the propose-only contract is gone. Quincy is told he
    **owns the backlog** and can propose *any* change (add / reorder / enhance / split /
    merge / dedupe / lock / unlock / delete / set-dependencies), **all pending stakeholder
    approval** — "I've prepared a proposal for your approval", never a claim that a change
    happened. Intake behaviour is preserved (empty backlog → shape it → "Build the
    backlog"). `pm.chat` now returns `(reply, changeset)`; `pm_chat` returns
    `{reply, changeset}`.
  - **UI:** a proposed changeset in chat renders as an **approvable action card**
    (`PmChangesetCard`) reusing the curation panel's `describeOp` presentation with the full
    approve / request-edits / deny / ask-why workflow — **Approve applies the whole
    changeset** via `…/curate/apply`. The add-only `PmProposalCard` is retired.

## Options considered

- **Live backlog-mutation tools with per-op `interrupt` gating** (the "backlog is a tool he
  wields" design from ADR-0009's options). Still deferred — it needs new interrupt/resume UI
  in the PM chat and inverts the contract in more places; the unified *changeset proposal*
  is the lower-friction step that already makes Quincy self-aware in chat.
- **Semantic deduplicate** (a `backlog_items.embedding Vector(768)` column + migration +
  backfill + similarity search). Deferred; heuristic PM-proposed merges cover the common
  duplicate-intake case without new infra.
- **Split rewires dependents onto only the "primary" child.** Rejected — ambiguous and
  lossy; a dependent of the original work depends on *all* the pieces it was split into.
- **Let `add` ops apply in document order.** Rejected — applying them last is what lets a
  single changeset safely carry an `add` alongside a `reorder` without a stale snapshot.

## Security implications

Low, and unchanged in kind from ADR-0009. **No trust-boundary (`packages/policies`)
change** — the LLM only *proposes* a changeset; a deterministic applier validates
(deny-by-default: unknown id, non-permutation reorder, blank `add` title, op-mixing, and
non-disjoint structural ops all reject the **whole** set) and mutates. `delete` is a hard
capability, so it is gated the same way (valid id, not `in_progress`) and only ever runs
after explicit human approval of the changeset. Run history survives item deletion
(`Run.item_id` `SET NULL`).

## Operational implications

- **No migration.** Structural ops use the existing tables; edge FKs already `CASCADE`.
- `…/backlog/curate/apply` now also dispatches `add`/`split`/`merge`/`delete`; the PM chat
  turn returns a `changeset` the dashboard renders as an action card.
- Deterministic-first holds: rendering, validation, DAG rewiring, renumbering, and
  application are code; the model only produces the proposed changeset.

## Consequences

Quincy can now **reshape** a backlog — break bundled items apart, fold duplicates together,
drop obsolete work — and he does it **conversationally**, surfacing an approvable action
card the moment a stakeholder asks, instead of deferring with "I can't do that yet." Add
and curation are one vocabulary, one applier, one review card. What remains deferred:
semantic dedupe, ~~autonomous between-item curation in the sweep~~ (**corrected 2026-08-18**, `docs/audits/adr-corpus-review-2026-08-18.md` — it landed in a narrower stuck-item form via ADR-0023's opt-in `resilient_recuration`), live per-op mutation-tools,
and manual (non-Quincy) split/merge UI actions.
