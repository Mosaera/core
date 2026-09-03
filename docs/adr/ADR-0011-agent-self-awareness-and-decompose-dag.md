# ADR-0011: Agent self-awareness (capability manifest) + decomposition authors the DAG

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0008](ADR-0008-pm-foundation.md) (PM foundation), [ADR-0009](ADR-0009-backlog-ownership.md) / [ADR-0010](ADR-0010-backlog-structural-ops-and-chat-curation.md) (backlog ownership + chat curation), [`docs/design/quincy-pm-case-study.md`](../design/quincy-pm-case-study.md)

## Context

A grounded four-agent audit (PM, coder, reviewer, and the tool/policy + engine layers)
surfaced a consistent gap: **agents don't fully know what they're capable of**, and the
knowledge that does exist reaches them unevenly.

- **Quincy (PM)** now owns a large surface — read-only repo tools (plan/design), full
  backlog ownership as an approvable changeset (add/reorder/enhance/split/merge/dedupe/
  lock/delete/set-deps), doctrine, and pre-mortem foresight — but **no single prompt tells
  him all of it**. Each entry point revealed only its own sliver, so he under-acted:
  in chat he would defer with text ("I can't do that directly yet") on things he can in
  fact do with approval. Worse, his most consequential act — `decompose_brief` — was
  **doctrine-blind** and **emitted a flat list with no dependency edges**, even though the
  edge table and `set_dependencies` exist.
- **The coder** is told (correctly) about surgical `edit_file` vs whole-file `write_file`,
  but its prompt was **silent on `delete_file`** when that tool is built and **silent on
  its capability boundaries** (no git/shell/network/installs) — it learned its ceiling only
  reactively, by failing.
- **The reviewer** could emit `BLOCK` (the parser and the delivery gate both already handle
  it → `reviewer_blocked` → park), but its prompt only offered `APPROVE`/`REQUEST_CHANGES`.

These are cheap, high-leverage fixes and the **prerequisite groundwork** for the larger
"Quincy as flow orchestrator" direction (deferred): an agent can't be trusted to decide and
delegate work if it doesn't reliably know its own remit.

## Decision

**1. One PM capability manifest, injected into every Quincy entry point.** A single
`PM_CAPABILITIES` block (`prompts.py`) states Quincy's full remit — plan/design grounded in
the repo + pre-mortem, end-to-end backlog ownership as an approvable changeset, and
"follow the doctrine when provided" — with the explicit instruction *never tell the
stakeholder you are unable to do something on this list (at most it needs their approval)*.
It is prepended to **plan, design, curate, chat, decompose, and synthesize** so the model
is told its whole role in one place; each prompt's own imperative ("produce a plan",
"propose a changeset") still governs what to output that turn.

**2. Doctrine reaches the three paths that were blind to it.** `synthesize_understanding`,
`decompose_brief`, and the chat context builder now take/inject the trusted global doctrine
(gated by `doctrine_enabled`), so Quincy's methodology informs intake, decomposition, and
conversation — not just plan/design/curate.

**3. Decomposition authors the dependency DAG.** `decompose_brief` now returns
`{title, description, acceptance, depends_on}`, where `depends_on` holds **1-based positions
in the returned list, strictly backward** (an item may depend only on earlier items). The
parser remaps references across any filtered-out (titleless) entries and drops
forward/self/unknown refs, so **the graph is acyclic by construction**. `run_decompose`
maps those positions onto the freshly-minted item ids and wires the edges via
`set_item_dependencies` (which re-validates same-project/no-cycle as a backstop). Quincy now
produces a dependency-ordered backlog at intake instead of a flat list a human must wire.

**4. Coder prompt matches its real toolset.** `CODER_SYSTEM` states the **capability
boundaries** up front (only the file tools; no git/shell, no rename/move, no network,
installs, or migrations — do the part you can and say what's left). A `coder_system(allow_delete)`
helper appends the `delete_file` clause **only when that tool is actually built**
(`delete_tool_enabled`), so the coder is never told about a tool it doesn't have.

**5. Reviewer prompt offers `BLOCK`.** `REVIEWER_SYSTEM` now presents all three verdicts and
scopes `BLOCK` to genuine stop-the-line problems (introduced secret/vulnerability, deleted/
weakened tests, destructive/out-of-scope change) vs `REQUEST_CHANGES` for ordinary gaps.
This completes an **already-wired** path — no routing or gate change.

## Options considered

- **A lighter, per-surface manifest** (tell each entry point only its slice). Rejected — that
  is exactly today's under-selling failure mode; the point is one place that states the whole
  remit.
- **Model-authored dependencies by title/name matching.** Rejected in favour of **1-based
  backward indices** — unambiguous, trivially acyclic, and robust to duplicate titles.
- **Semantic-similarity dedupe / wiring the dead `similar_artifacts` recall.** Out of scope
  here; tracked separately (still deferred).

## Security implications

None. No trust-boundary (`packages/policies`) change and **no change to the threat surface**:
prompt text is advisory, the coder's boundary text mirrors the enforced allowlist (real
enforcement stays in the tools + gate), the `delete_file` clause appears only when the
admin-gated tool is already built, and `BLOCK` completes a gate path that already existed.
Doctrine is trusted, first-party content loaded from the repo, framed as data.

## Operational implications

- No migration. `decompose_brief` returns an extra `depends_on` key; `run_decompose` wires
  edges with the existing store method. Doctrine injection is gated by `doctrine_enabled`.
- New backlogs generated from intake arrive **dependency-ordered**; combined with soft-lock
  (ADR-0009), dependent items can be held with a caveat out of the box.

## Consequences

Every agent now knows what it can do: Quincy is told his full remit everywhere (and stops
deferring on capabilities he has), decomposition yields a real DAG, the coder designs within
a stated ceiling, and the reviewer can call a hard stop. This is deliberately the
**foundation** for the orchestrator direction — an agent that reliably knows its own remit is
the precondition for one that can decide and delegate work. Still deferred (**updated 2026-08-18**, `docs/audits/adr-corpus-review-2026-08-18.md` — autonomous between-item curation has since shipped as ADR-0023's `_try_recurate_or_defer`; the two below stand): the hub-and-spoke
orchestrator itself (Quincy routing agents dynamically via work packets), autonomous
between-item curation, and wiring or removing the dead semantic recall.
