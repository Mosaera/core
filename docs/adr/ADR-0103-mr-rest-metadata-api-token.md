# ADR-0103 — MR metadata via the GitLab REST API: an optional per-project `api`-scoped credential

- **Status:** accepted (owner-approved 2026-08-14, in-session)
- **Scope:** connectors + api + web + memory (Alembic 0026) · threat model TM-0002 updated
- **Amends:** [ADR-0102](ADR-0102-delivery-spine-truth-up.md) (adds a REST create/edit path
  beside its push-options path); references [ADR-0019](ADR-0019-autonomous-mr-last-mile.md) /
  [ADR-0042](ADR-0042-clone-token-host-equality.md) (least-privilege posture, deliberately
  preserved), [ADR-0021](ADR-0021-revertable-per-item-merge-requests.md) (the stacked model gets
  a merged-predecessor fix), [ADR-0039](ADR-0039-secrets-encrypted-at-rest.md) (secret at rest),
  [ADR-0005](ADR-0005-config-in-ui-settings.md) (branch picker is a dropdown when enumerable)

## Context — the transport is the blocker

Mosaera creates MRs by `git push -o merge_request.*` (ADR-0019/0021), so the token needs only
`write_repository`. But push-option values cannot contain newlines: `gitlab.py` flattens the
body (`" ".join(plan.body.split())`) and truncates to `_DESC_MAX=800`, `merge_request.squash`
is never sent, and there is no way to edit an MR after creation or list branches. Operator-grade
management — a faithful multi-line body, edit-before-send, labels, squash, a target-branch
picker — all require the GitLab **REST API**, which needs the broader **`api` scope**.

## Decision

1. **Push transport stays `write_repository`, unchanged.** Clone, push, and branch delete
   (`git push --delete`) keep using `gitlab_token`. The autonomous sweep's posture is untouched —
   the most-automated, unattended path never gains `api` scope.
2. **An OPTIONAL per-project `api`-scoped token** (`Project.gitlab_api_token`, Alembic 0026,
   encrypted at rest) is used **only** by operator-initiated REST metadata calls: create-with-full-
   body, edit, labels, squash, branch-list read. Absent ⇒ the compose features degrade and MR
   creation **falls back to today's push-options path** — never a global-token substitution.
3. **Create path = push-plain-then-POST.** With an api token + an operator submit: push the branch
   *without* the `merge_request.create` push-options, then `POST /merge_requests` with the faithful
   fields; if an open MR already exists for the source branch, `PUT` to edit. One authoritative
   create, no lossy-then-fix race.
4. **Branch delete rides `write_repository`** (`git push --delete`); branch *read* (the picker)
   rides the api token. Pruning merged item branches needs no new scope.
5. **`_stacked_target` skips merged predecessors** (`mr_state == "merged"`) so a new item never
   targets a merged-and-deleted branch (the ADR-0102 red-team-adjacent latent bug).
6. **A new write client** (`connectors/gitlab_write.py`) holds all POST/PUT + the `api`-scoped read,
   keeping `gitlab_client.py`'s "no writes here" invariant intact so each surface's required scope
   is legible.

### Amendment (2026-08-18) — the MR target is RECORDED, and a stuck MR is repairable

Decision 4 above gave branch delete/prune a protection rule, but the implementation asked
`_stacked_target` what an open MR points at. That function answers a *different* question — "what
should a NEW MR target?" — and it deliberately skips merged predecessors (Phase 4). The two answers
diverge the moment a predecessor merges, and on **2026-08-18** that divergence deleted a live MR's
target: item 99 merged → item 100's recomputed target became `main` → `mosaera/item-99` dropped out
of the protected set → prune deleted it → GitLab: *"The target branch mosaera/item-99 does not
exist."* Backlog reordering and predecessor-item deletion produce the same class of divergence.

1. **`backlog_items.mr_target` (Alembic 0028)** records the branch an item's MR actually targets,
   written when the MR opens and refreshed by the `/mr-status` poll (which already fetches the MR
   JSON, so the record self-heals and pre-0028 rows backfill). **Branch protection reads the record,
   never a recomputation.** `_stacked_target` keeps its one job: choosing a new MR's target.
2. **The delete rule is enforced server-side** — `mosaera/*` only, never the base, and the project
   MR's own source branch is protected while that MR is open. These lived only in the web client,
   which made the API a way around the product's own safety rule.
3. **`POST /projects/{id}/items/{item_id}/retarget`** repoints a stuck item MR. Until now nothing in
   the product could repair one: the opener refuses `already_open` before reaching the REST path,
   there is no close/reopen endpoint, and the MR columns are not patchable — the only escape was
   GitLab's own UI. It edits one field of an existing MR and never pushes, creates, or merges, so it
   stays well inside the rebase/amend primitives §Deferred still refuses. Audited like every other
   outward-facing delivery action.

Also corrected here: GitLab's branch `merged` flag means *"the commits are contained in the default
branch"*, which a stacked predecessor satisfies while its own MR is still open. It is **not** the
MR's state, and the UI now labels it "in main" and builds the prune confirmation from the same
predicate the server prunes with.

### Amendment 2 (2026-08-18) — the same rule for the PROJECT MR, and an MR can now be ended

Amendment 1 fixed the recompute-vs-record defect for *item* MRs. The identical defect sat one level
up and survived that review: `open_project_mr` opens the project MR from `workspace.branch` —
whatever the shared clone happens to be checked out on, which after an item run is
`mosaera/item-<id>` — and recorded it nowhere, so protection **guessed** the source as
`projects.branch` (the intake branch, written once at creation) or `mosaera/combined-<id>`. Measured
live the same day: project MR !4 sourced from `mosaera/item-102`, whose backlog row was empty, so
neither guard covered it — the branch a live MR depended on was protected by **nothing**.

1. **`projects.mr_source` (Alembic 0029)** records the branch the project MR actually sources from,
   written on both open paths (on the cherry-pick path that is the combined branch) and refreshed by
   the `/mr-status` poll from the MR's own `source_branch`, so pre-0029 rows self-heal. Protection
   reads the record; the old guesses survive only as the empty-record fallback.
2. **`POST …/items/{id}/mr-state` and `POST …/mr-state`** close or reopen a merge request — the half
   of the lifecycle the product never had. An obsolete MR (its work landed by another route, a
   duplicate, one opened at the wrong target) could previously be resolved only in GitLab's own UI,
   while Mosaera went on reporting it live; and `mr_state == "closed"` was a state nothing here could
   produce or clear. **Member-available**, like `retarget` and unlike branch destruction (ADR-0004):
   closing destroys nothing, touches no branch, and reopen undoes it. Only GitLab's two lifecycle
   verbs reach the API; the resulting state is recorded from our own action rather than left for the
   next poll, because branch protection reads it.
3. **An operator's chosen target is applied before the empty-diff refusal.** `open_item_mr` computed
   `_stacked_target`, refused on an empty diff, and only then consulted compose — so when the
   recomputed predecessor already contained the item's commits, the item could never get an MR *and
   choosing a different target could not rescue it*. The chosen target is held to the same
   base-or-`mosaera/*` allowlist as retargeting.
4. **Structural backlog operations may not orphan a merge request.** The delete guard was one
   door of three: `split_backlog_item` deletes the parent row and `merge_backlog_items` deletes
   every source row, both reachable from an accepted curation changeset, and both destroyed the
   only record branch protection reads. All three now share one rule.
5. **A record can be corrected, and a phantom can be forgotten.** `merged` is skipped by the poll
   to bound REST cost, but it is also the state that makes a branch prunable — so a wrong one was
   destructive *and* permanently uncorrectable; `?force=` re-reads it. And an MR deleted in GitLab
   left the record errored forever with its branches protected and its backlog row unremovable, so
   the poll now forgets it — on **two** facts, never one: GitLab answers 404 for *unauthorized* as
   well as *absent*, so clearing requires the project itself to answer 200 with the same token.
   Anything else fails closed and the record stands.
6. **Every REST read now spends the `api` token, not the push token.** `resolve_mr_url` and the whole
   `/mr-status` poll were handed the `write_repository` token for calls that scope cannot make, so on
   a push-only project they could only ever fail. That is *how* items reached the terminal state of a
   branch, `mr_state = "opened"`, and no URL: nothing polled them (no iid), the opener refused
   `already_open`, retarget had no MR to edit — while their branches stayed protected. The poll now
   also recovers such a row by looking the MR up from its source branch.

## Consequences

- Faithful, editable MR bodies + labels + squash; operable merged-branch cleanup; a real
  target-branch picker. The push-options path is retained as the honest **degraded mode** (no api
  token) — not a hard cutover.
- **TM-0002** gains a row: a per-project `api` credential exists, write-only + encrypted, spent
  only against `settings.gitlab_url` (`is_gitlab_source` parity, ADR-0042), only on operator calls,
  never the sweep, never git transport. Three-way token-routing invariant: project-write /
  project-api / global-adhoc never cross. Residual: `api` ⊃ `write_repository`, so leak blast
  radius is larger — an operator-opted-in tradeoff, held only for human-in-the-loop actions.
- **Deferred (roadmap):** arbitrary "combine items X, Y, Z into one MR" subset selection (needs
  ~~cherry-pick/rebase primitives that do not exist~~ — **CLOSED 2026-08-14** by the git-control trio (`tools/repo/cherry.py::cherry_pick_into_branch`, `GET /projects/{id}/commits`, compose-with-commits merge); corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`. Still deferred for a different and live reason (they race the shared clone) — one commit per item, no squash/rebase/amend);
  branch rename, arbitrary checkout, `git worktree`.
- **Red-team required (Phase 1):** ~3 rounds on the trust boundary — api token host-pinning,
  three-way token routing, no-token-in-payload, fail-closed-to-push-options. **DONE** — all four
  claims held (2026-08-14).

## Status of the four phases (2026-08-14)

All landed on `staging`: **1** credential model + `gitlab_write.py` (red-team done); **2** the
compose Sheet + REST create path (`push_only` then POST/PUT); **3** the "open one combined MR"
action + squash toggle (folded into 2); **4** `_stacked_target` skips merged predecessors,
`POST /branches/prune` (delete merged item branches, write_repository, open-MR-guarded),
`GET /branches` (api-token read for the picker). Deferred as stated: arbitrary commit-subset
grouping, branch rename/checkout/worktree.

## North-Star test

Artifact = the MR + its audit event; Authority = the authenticated endpoint / operator (ADR-0102,
unchanged — a human still merges); Independence = the deterministic delivery gate is untouched;
Evidence = the REST response + `mr.opened`/`branch.pruned` audit with actor; Failure = fail-closed
to push-options and refuse cross-token routing; Audit = reconstructable from the audit log; Model
substitution = no model call on this path; Scope = tied to the owner ask, subset-grouping deferred.
