# ADR-0102 — Delivery-spine truth-up: endpoint-as-approval for MR opening, scoped-token posture, base-drift fail-closed, unpushed-state honesty, operable item MRs

- **Status:** accepted (owner-approved 2026-08-13, in-session)
- **Scope:** policies + core + api + web + memory (Alembic 0025) · threat model TM-0002 updated
- **Amends:** [ADR-0019](ADR-0019-autonomous-mr-last-mile.md) (its human control is now
  named precisely), [ADR-0021](ADR-0021-revertable-per-item-merge-requests.md) (the
  per-item model becomes human-operable), supersedes
  [ADR-0001](ADR-0001-stack-and-architecture.md)'s "opening a PR is gated on `open_pr`"
  framing for GitLab (the GitHub CLI's interactive confirm is unchanged)
- **Amended by:** [ADR-0103](ADR-0103-mr-rest-metadata-api-token.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.
  Also [ADR-0112](ADR-0112-two-named-delivery-providers.md) — narrowly, and only the consequence
  "no forge abstraction is introduced by this ADR, **and none is authorized**": that sentence
  withheld authorization pending a decision, and ADR-0112 is that decision (two named providers,
  no seam). The spine below — `push`/`open_pr` outside `GATED_ACTIONS`, endpoint-as-approval — is
  unchanged and reaffirmed there.

## Context — the measured defects

1. `push` and `open_pr` sat in `GATED_ACTIONS` with a documented approval contract while
   **no code path ever called `request_approval()` for them** — an inert control whose
   non-firing was invisible (this repo's most-measured defect class), and
   `POST /runs/{id}/open-mr` *retroactively fabricated* an `open_pr` approval row that no
   one had granted.
2. That same endpoint pushed with the **global** GitLab token while every other MR path
   uses the project-scoped `write_repository` token.
3. `deliver` ends at a local commit; with defaults (`auto_open_mr=False`) nothing pushes,
   and the readiness model had no "delivered but unpushed" state — local-only work read
   as `ready`.
4. The default delivery model (per-item stacked MRs, ADR-0021) was unreachable by hand:
   no manual item-MR endpoint, and item merged-state was never polled.
5. Item branches are cut with `checkout -B` from the current local tip with **no fetch** —
   after a merge lands on the remote base, the next item stacks on a stale tip and its MR
   diff is wrong.

## Decision

1. **`push`/`open_pr` leave `GATED_ACTIONS`.** Remote operations happen outside the graph,
   where `interrupt()` is unreachable; inventing a second interrupt machinery for them
   would be architecture without a caller. The human control for opening an MR **is the
   authenticated endpoint** (session/service auth, ADR-0004) or the explicit
   `auto_open_mr` opt-in (ADR-0019 — a human still merges). No retroactive approval rows
   are ever recorded; the audit event (`mr.opened`/`mr.failed`, with the actor) is the
   record. `test_approval.py` pins the set: growing it requires wiring the interrupt.
2. **Scoped-token posture.** A project-associated MR open always uses the project's
   `write_repository` token and fails closed (400) when the project has none — never a
   global-token fallback. The global token serves only ad-hoc (project-less) runs, which
   have no other credential home — a documented residual, not an oversight.
3. **Base-drift fail-closed.** The item-branch cut is preceded by a bounded fetch and
   classification: a diverged base **refuses the launch** (park with the reason surfaced);
   a cleanly-behind base fast-forwards; an unreachable remote proceeds with a recorded
   warning — this is a correctness aid, not a security control, and offline/local-dir use
   must keep working. No knob: there is one honest behavior.
4. **Unpushed-state honesty.** The API exposes `remote_synced` (true/false/null — null is
   an honest unknown, never rendered as synced) and "delivered but unpushed" becomes a
   first-class readiness state with the MR-open action as its exit.
5. **Operable item MRs.** A manual endpoint opens an item MR over the same outcome layer
   the sweep uses; item merged-state is tracked per item (`BacklogItem.mr_state`, Alembic
   0025 — the `status` enum is deliberately untouched: the sweep's completeness logic
   consumes it); a banner-less push is resolved to a real MR URL via the read-only REST
   client. A new **Delivery** page is the single operator surface for all of it
   (configure `auto_open_mr`/`mr_granularity`, per-item branch → MR → state, actions).

## Consequences

- The `approvals` table stops receiving `open_pr` rows; historical rows remain and are
  labeled as pre-0102 fabrications in the model comment.
- Stacked MRs can no longer silently target a stale base; the failure is a surfaced park,
  not a wrong diff.
- A future GitHub port reuses the `delivery.py` outcome layer (the seam) — no forge
  abstraction is introduced by this ADR, and none is authorized.
- **TM-0002** gains a row (endpoint-as-approval authority + token routing).
- **Red-team (slice T):** one scoped verification pass over the merged trust-boundary
  change — (a) nothing relied on `push`/`open_pr` gating for containment, (b) token
  routing cannot cross project↔global, (c) the approval record is truthful end-to-end;
  escalate to ~3 rounds only on a real finding.

## Red-team disposition (2026-08-13, one scoped pass — DONE)

Claim (a) HOLDS: the only four `request_approval` callers pass string literals
(`write_file`/`edit_file`/`delete_file`/`deliver`); no caller of `"push"`/`"open_pr"`
ever existed (git history confirms), and no reader iterates `GATED_ACTIONS` for behavior.
Claim (b) HOLDS on the host axis (the push URL is built from `gitlab_url`, never the run
`source`); one latent posture bug DEFERRED (below). Claim (c) was REFUTED and FIXED.

**FIX-NOW (this commit):**
- The invisible-control class had relocated into prose: `docs/architecture/README.md`,
  `packages/connectors/README.md`, and `cli.py` still called PR-opening "a gated action."
  Corrected — the same defect the ADR exists to kill.
- The two manual openers (`POST /projects/{id}/merge`, `.../items/{id}/open-mr`) wrote
  NO audit event, so "the authenticated call IS the approval" was a claim nothing on the
  record could back. Both now record `mr.opened` with the actor (`user:<name>` or
  `endpoint` when auth is open).
- The item-MR poll spent the project token deriving a project path from `source_repo`
  with no host check; added the `is_gitlab_source` guard (ADR-0042 parity).

**DEFER-TO-SUCCESSOR** (tracked, not this arc): a project run whose project was deleted
(`project_id` → NULL via `ondelete=SET NULL`) falls back to the global token in
`/runs/{id}/open-mr` — currently unexploitable (a project run has no per-run clone, so
the push 409s first), becomes live only if that endpoint learns to resolve a project
clone; the run→project source-match validation in `_launch`; per-path actor identity
(`actor=endpoint` is a constant, and the `Approval` row has no actor column — the
auto-accept "You approved" mislabel is a pre-existing ADR-0101 concern). **ACCEPT
(documented):** the CLI `--approve-all` bypass of the interactive confirm (CI/testing
only, predates this change). **FALSE-POSITIVE:** `mr_state` writes (a display cache the
live poll overrides; no decision logic reads it).

## Amendment — the human's click may live in the product (2026-08-24)

**Status:** accepted (owner-requested, 2026-08-24) · scope: connectors + api + web

This ADR records that *"a human still merges"*. Until now that was true by absence: the console
could open and close a merge request and had no way to merge one, so every merge happened in
GitLab. Driving LedgerCLI to a finished product needed **nine merges, all of them performed
outside the product** — and slice P's own finish line, *"the LedgerCLI case-study merge driven
entirely from the Delivery page"*, was never met because the Delivery page could not do it.

**The distinction this amendment draws is between AUTHORITY and LOCATION.** An operator clicking
Merge in Mosaera is still a human merging. What must never exist is a graph path, a sweep, or a
schedule that merges. So the click moves into the product and the authority does not move at all.

Three properties make that a fact rather than an intention:

1. **Admin-gated**, reusing the principle this repo already wrote down for branch deletion
   (`routes/_branch_guards.py::_branch_ops_allowed`): *"Installing the project token is admin-gated
   (ADR-0004, secret write); spending it irreversibly on the real repository is the same class of
   authority."* Merging spends it irreversibly. Same class, same gate.
2. **The admin gate excludes the bare service token** (ADR-0004 — the token is not admin).
   Automation holds that token, so automation cannot reach the endpoint. Without this,
   "operator-initiated" would be a word rather than a property.
3. **No engine package may reach the merge path**, pinned by a test that fails if any file under
   `packages/core|agents|policies` so much as names it. That is the first thing that would change
   if someone wired a sweep to it, which is the review the test exists to force.

**Automatic merge authority remains on the North Star's *Not Yet* list**, unchanged. There is no
`auto_merge` knob, and this amendment authorizes none.

**Readiness is read fresh, at the moment of the ask.** GitLab's `detailed_merge_status` is fetched
when the confirmation opens, never served from cache or from the row's poll — [ADR-0108](ADR-0108-evidence-describes-a-tree.md)'s
rule (*evidence describes a tree, or it is not evidence*) applied to mergeability, on the one action
in this product that cannot be undone from it. The verdict **fails toward not-ready**: an
unrecognised or absent status quotes GitLab verbatim and offers no merge, because the tempting bug —
treating "not obviously blocked" as permission — would put a green button over an unchecked claim.

**The head `sha` the operator was shown rides the merge**, so a branch that moved between the read
and the click is refused by GitLab rather than merged unseen.

**Auto-merge is offered only when a running pipeline is the sole thing outstanding**, and reports
QUEUED rather than merged — the operator asked whether it landed, and *"accepted, will merge when CI
passes"* is a different answer. It is not a route past a red pipeline; GitLab still refuses.

**Scope stays with `api`.** Merging is a REST write and rides the optional `api`-scoped token
([ADR-0103](ADR-0103-mr-rest-metadata-api-token.md) §1), preserving that ADR's property that *the
most-automated, unattended path never gains `api` scope*. Without an api token the control is
**absent**, not disabled — an operator never meets a button that cannot work.

