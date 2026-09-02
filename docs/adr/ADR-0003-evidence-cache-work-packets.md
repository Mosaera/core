# ADR-0003: Evidence cache and durable work packets

- Status: accepted (within-run MVP shipped; the durable cross-run store is deferred — issue `#23`;
  ~~roadmap `#23`~~ **corrected 2026-08-18** — `docs/roadmap.md` carries no `#23`, so the durable
  store is untracked there, see `docs/audits/adr-corpus-review-2026-08-18.md`)
- Date: 2026-07-10
- Owners: Alejandro Rengifo
- Related issue: #23 (evidence cache / work packets), #19 (cost epic), #22 (deterministic-first discipline)
- Related threat model: docs/threat-models/TM-0001

## Context

ADR-0002 names **cached evidence** as the first tier of the deterministic-first escalation
ladder (`cached evidence → deterministic tool → local small model → … → human`), but #23 was
only named there, never specified. Its intent: a run should never recompute — or re-prompt a
model to re-derive — deterministic facts about a repo that have not changed.

Two costs motivate it:

- **Recompute cost.** Each planning iteration re-walks the file tree for the repo overview
  (`plan_node`), and each test iteration re-derives which manifests/tests exist
  (`detect_validation_plan`). Both are pure functions of repo state, yet run every loop.
- **Re-derivation cost.** Across separate *runs* of the same backlog item (a retry after
  feedback, a re-run of a "done" item), the same deterministic evidence — repo overview,
  validation plan, scanner findings, diff stats — is recomputed from scratch, and any model
  prompt that embeds it pays tokens to re-read unchanged context.

The correctness trap is staleness: reusing evidence after the tree changed produces silently
wrong plans (the original reason `plan_node`/`test_node` recompute *inside* the node). Any
cache must key strictly on repo state and recompute on change.

## Decision

Split #23 into a **within-run MVP (build now)** and a **durable cross-run store (specify, defer)**.

### Delivered — within-run memoization (MVP)

A run-scoped, content-addressed memo keyed by a cheap working-tree hash:

- `Workspace.tree_hash()` (`packages/core/mosaera_core/tools/repo.py`) — a stat-only hash over
  the sorted `(path, size, mtime)` of the listed files. It changes on any add/remove/edit and
  never reads file contents, so it is cheap on the hot path.
- `build_graph` (`packages/core/mosaera_core/graph.py`) holds an `evidence_memo: dict[(kind,
  tree_hash) → evidence]`. `plan_node` memoizes the repo overview; `test_node` memoizes the
  detected `ValidationPlan`. Because `build_graph` is per-run, the memo is run/process-scoped —
  there is **no cross-run staleness risk** by construction.

Invariant (pinned by tests): computed once per unchanged tree hash; recomputed when the hash
changes (so a test file the coder just wrote still upgrades the plan on the next loop).

### Deferred — durable work packets (spec)

A **work packet** is a per-backlog-item, content-addressed bundle of durable deterministic
evidence — repo overview, validation plan, scanner findings, diff stats — reused across *runs*
of that item so a repeat hits "cached evidence" instead of recomputing or re-prompting.

Proposed shape:

- Table `work_packet` (Alembic migration), rows keyed by `(item_id, content_hash, kind)` with a
  JSON/text `evidence` payload and `created_at`. `content_hash` is a durable repo-state hash of
  the item's base tree (a committed `git rev-parse HEAD^{tree}`, not the mtime hash above, which
  is process-local and unstable across machines/clones).
- Store methods `get_work_packet(item_id, content_hash, kind)` / `put_work_packet(...)` in
  `packages/memory`.
- Seams: `plan_node` (overview), `test_node` (validation plan), `scan_node` (findings) read the
  packet before computing and write it after. Invalidation is implicit — a changed base tree
  yields a new `content_hash`, so stale rows are simply never read (a TTL/GC job can prune them).

## Options considered

- **Reuse the intake `Project.repo_overview` across re-plans.** Rejected — it is captured once at
  intake and goes stale the moment the coder writes a file; naively reusing it is the staleness
  bug this ADR exists to avoid.
- **Build the durable work-packet table now.** Deferred — the within-run MVP captures the
  cheap, high-frequency recompute wins with zero schema and zero staleness surface; the durable
  store needs a stable cross-machine content hash and cache-invalidation/GC policy that warrant
  their own review. Ship the MVP, specify the rest.
- **Memoize on a listing hash only (paths).** Rejected for validation detection — detection
  reads manifest *contents*, so the key must be content-sensitive; the `(path, size, mtime)`
  hash covers edits to existing files, a paths-only hash would not.

## Security implications

Cached evidence is derived from untrusted repo content and must stay **data, never
instruction** — it is deterministic tool output, not a model directive, and is never executed.
The durable store persists repo-derived text; it inherits the project's tenancy scoping
(`item_id` → project) and must not become a cross-project leak. No secrets belong in a packet.
The content hash keys the cache but is not a security boundary.

## Operational implications

- MVP: no schema, no migration, no new ops surface; the memo lives and dies with the run.
- Durable store: one new table + Alembic migration (memory schema changes go through Alembic,
  never `create_all`/hand-rolled `ALTER`), plus a prune/GC policy for superseded packets.
- Both are observable through the existing #22 metrics — a working cache lowers
  LLM-calls-per-delivered-item and the recompute contribution to interactive latency.

## Consequences

- Good: closes the ladder's first tier with a correct, staleness-free MVP; cuts recompute and
  planner-token cost across the implement/fix and gate→plan loops; gives the durable design a
  written spec so #19 has one clearly-scoped remaining follow-up rather than an open question.
- Cost: the MVP's mtime-based hash is process-local (intentionally — it must not be reused
  across runs); the durable store deliberately uses a different, committed-tree hash.
- Follow-up: implement the `work_packet` table + seams to realize durable cross-run reuse;
  extend memoization to `scan_node` findings within a run if profiling shows it pays.
