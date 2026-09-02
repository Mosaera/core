# Process review — roles, performative surfaces, and branch standing (2026-08-18)

**Status:** audit log. Records findings only; no code changed. Fixes are a separate pass.
**Scope:** three owner questions — (1) do admin and standard users have coherent permissions, and can
a standard user drive a project from initiation to completion; (2) is anything on the platform merely
performative; (3) can an operator see where a branch/MR stands against `main`.

**What prompted it.** The 2026-08-18 live validation of the GitLab consolidation found a control
shipped four days earlier that could never fire: `local_branches` hardcodes `"merged": False`, so the
prune confirmation can never name a branch and the "· merged" badge can never render. The unit test
passed because it *mocked* the field — a constant dressed as data. That is not a one-off; it is the
shape this review went looking for.

**Prior art read before searching, per `CLAUDE.md`** — none of the below re-derives it:
`scripts/check_control_liveness.py` (posture knobs only; it cannot see UI reads, gate reasons, or
whether a stored value is honoured at run time) and
[`control-liveness-audit-2026-08-10.md`](control-liveness-audit-2026-08-10.md) (24/26 controls cannot
distinguish "ran, found nothing" from "never ran"). Two standing claims were **re-verified
mechanically and hold**: every knob in `GENERAL_KNOBS` has a real read site, and every gate-reason
token rendered by the web app has a producer.

---

## Part 1 — Roles: a member can ship, but cannot start

Two governance axes already exist and should not be conflated: **role** (ADR-0004 — admin vs member,
who may change the instance) and **posture** (ADR-0046 — how much the engine may do unattended, a
second veto that may only restrict). The gap is entirely in the first.

A member with a session can run the whole build-and-deliver loop: PM chat, backlog generation and
editing, runs, gate answers, opening item and project MRs, merging, pruning branches — and deleting
the project (`routes/projects.py:450`, auth-only). What a member cannot do is *begin*:

| Stop | Gate | Consequence |
|---|---|---|
| Seed a project token at creation | `routes/projects.py:155` | — |
| Set a project token | `routes/projects.py:180` | Their MR and prune actions remain reachable but dead: no push credential |
| Connect GitLab via OAuth | `routes/oauth.py:95` | Same |
| **Write the charter** | `routes/projects.py:296` | **The PM intake path dead-ends in a 403** |
| Ratify a governance clause | `routes/standards.py:92` | Has no UI at all |

### The charter is the real breakage

`CharterProposalCard.tsx:41` and `CharterCard.tsx:61` render for every user with no role check, so
the member's primary journey — talk to Quincy, receive a charter proposal, accept it — terminates in
`403 admin privileges required`. The North Star names that journey as the product ("the operator
collaborates with Quincy the way a founder works with a trusted senior partner"), and Mosaera's
stated audience is firms *without* an engineering background. The person the product is designed for
is the person the gate stops.

**The gate is nonetheless correct.** ADR-0047 makes charter writes a governance surface precisely
because the charter carries **posture** (ADR-0046), and posture relaxation is on the roadmap's
forbidden list. Removing the gate would be exactly the mechanism the architecture refuses.

**The defect is that one endpoint carries two different kinds of authority.** `CharterBody`
(`schemas.py:203-209`) bundles `goal` and `constraints` — freeform operator intent, which *is* the
member's job — with `posture`, the governance enum. The recommendation is to **split the write, not
move the gate**: `posture` becomes `None = unchanged` and `require_admin` fires only when posture is
present and actually changes. A member authors intent; only an admin sets posture. The same
`None = unchanged` semantics already exist at `set_project_token` (`routes/projects.py:196-214`).

⚠ **Security-relevant detail:** the field currently defaults to `posture: str = "business"`. If the
gate were split without changing that default, a member's charter write would silently *reset* the
project's posture to `business` on every save. The default must become `None` in the same change.

### Two cheaper findings

- **A false restriction.** `SettingsPage.tsx:54` computes `canConfig = isAdmin || !auth_required` and
  hides Models, Pricing, Providers, Cost-modes and GitLab status from members entirely. Every one of
  those **reads** is auth-only server-side (`routes/settings.py:182, 189, 247, 374, 94`). Members are
  denied sight of configuration the API would serve them. `KnobForm` already has the right pattern —
  `editable={isAdmin}` plus "Read-only — admins can edit these" (`KnobForm.tsx:218, 228`).
- **Inverted risk.** Project delete is auth-only; charter write is admin. Whatever boundary we settle
  on, "a member may destroy the project but not describe it" cannot be the answer.

### Recorded, not proposed for change

- The daily run quota meters members only — admins are exempt (`ratelimit.py:228`).
- `adminFetch` is a bare re-export of `apiFetch` (`api/adminAuth.ts:8`), so the browser has no path to
  send `X-Mosaera-Admin`. That makes `config.admin_required` (`client.ts:553`) a field the client
  declares, never reads, and could not act on if it did. Consistent with ADR-0004 §6 (the browser
  path is session-only by design) — but the flag is vestigial.

---

## Part 2 — Performative surfaces

Ranked by how misleading each is to an operator.

### 1. A master switch with undisclosed scope

`apply_oracle_posture` (`config/_posture.py:36-60`) returns early unless `autonomous_verified` is set,
then forces **eight** settings on: `tester_enabled`, `reason_on_stall_enabled`, `oracle_coverage`,
`oracle_mutation_check`, `tester_repairs_tests`, `proctor_faithfulness_guard`, `critic_enabled`,
`critic_claim_protocol`. It is applied to every autonomous run at `factory.py:44`.

Four of those are independently presented as operator switches in Settings → Autonomy:
"Reason on stall", "Test-first tester (Proctor)", "Coverage oracle", "Oracle mutation check"
(`AutonomySettings.tsx:93, 112, 119, 125`). Switching any of them **off** has no effect on an
autonomous run — the mode the product defaults to — because the overlay is applied afterwards and
wins.

**The override itself is correct and must not be weakened.** ADR-0046 §2 is explicit that posture
clamps knobs and may only move in the restrictive direction
(`effective(knob) = min(configured, posture_ceiling)`). Forcing verification *on* is the invariant
working as designed.

**The defect is that the clamp is invisible.** `autonomous_verified` is in the UI as "Verify
autonomous runs", but its help text describes only the tester's acceptance suite — it never says it
also forces the other seven. So the dependency is real, discoverable only in source, and the
dependent toggles give no cue. `config/_knobs.py:236-240` already records this exact hazard class for
the *removed* `reviewer_advisory` knob ("presenting an ON toggle over gate policy in the UI — an
honesty hazard, not a control"). This is the same hazard one level subtler: the toggle is genuine for
guided and ad-hoc runs, inert for autonomous ones.

**Recommended fix:** render the clamp, reusing KnobForm's existing "set via env" badge treatment for
env-pinned knobs. Do not touch the overlay.

### 2. `merged` is a dead constant with three readers

`tools/repo/diff.py:77, 84` set `"merged": False` on both return paths; nothing anywhere sets it true.
Read by the prune confirmation's branch list (`DeliveryWorkspace.tsx:144`), the "· merged" badge
(`:333`), and the "(merged)" suffix in the target dropdown (`MrComposeSheet.tsx:161`). Confirmed live
on 2026-08-18: the prune dialog fell through to its generic fallback.

This one is ours from this cycle. The unit test passed only because it mocked `merged: true` — the
mock manufactured the data the product cannot produce.

### 3. MR labels: promised, never possible

`MrComposeSheet.tsx:210` always sends `labels: []`; there is no labels input anywhere in the sheet.
Meanwhile `DeliveryWorkspace.tsx:279-281` tells the operator that "editing the MR body, **labels** and
a branch picker are unavailable until [an api token] is added" — implying labels become editable.
They never do. Either build the input or stop promising it.

**Adjacent live bug, independent of the above and worth fixing regardless:**
`gitlab_write.py:106` uses `if labels is not None` on the *update* path, so the always-empty `[]`
becomes `payload["labels"] = ""` — re-composing an already-open MR **clears whatever labels exist in
GitLab**.

### 4. A metrics chain with no consumer

`store/_projects.py:334-400` computes `det_llm_ratio`, `calls_per_delivered_item`, latency p50/p95 and
more; `routes/projects.py:73` exposes them; `client.ts:542` types the call. **Nothing calls it** —
verified by sweep, zero call sites outside the client definition. There is a dedicated Alembic
migration (`0003_latency_samples`) feeding numbers no one can see. These are the Deterministic-First
discipline metrics, which makes their invisibility more than cosmetic.

### 5. Quality-gate numbers inert at the shipped default

"Overall minimum score", "Per-dimension floor" and "Max quality revises"
(`AdvancedSettings.tsx:9-11`) are read only inside a conjunction short-circuited by
`quality_revise_enabled` (`graph/nodes_review.py:128-139`), whose default is `False`
(`config/_knobs.py:109`). At the shipped default all three are dead numbers, with no dependency cue
beyond section adjacency.

### 6. Smaller, same shape

- `ItemRow busy={false}` is hardcoded (`DeliveryWorkspace.tsx:214`), so the row's "Opening…" state can
  never render and the button never disables.
- Two components with **zero importers**: `runs/RunOutputPanel.tsx` (the transcript output drawer) and
  `settings/ModelSelect.tsx`. Unreferenced exported components are invisible to lint.
- Session archive is one-way: the store filters `archived_at IS NULL`, no caller ever passes
  `includeArchived`, so `archived` / `archived_at` (`api/sessions.ts:15-16`) can never reach a render
  and the un-archive half of the contract is unreachable.
- `"" = clear` token semantics are documented (`client.ts:688`) and implemented server-side
  (`routes/projects.py:214`) but unreachable — the UI sends `undefined` for a blank field.
- `/estimate`'s `per_role` breakdown is typed and never rendered.

### SUSPECTED — needs runtime proof, not a code change

`ManualStepsCard` fires only when the model emits an exact heading string
(`lib/manualSteps.ts:5`); the only "producer" is a prompt clause asking for it verbatim
(`pm/_backlog.py:43-48`). Its real hit rate is a model-compliance question and must be measured
before the surface is trusted. Same caveat shape as the 2026-08-10 audit's "the corpus cannot observe
it".

### The structural point

Every confirmed item above is a **read with no live producer**. `check_control_liveness.py` proves
posture knobs are wired, but by construction it cannot see UI reads, hardcoded struct fields, or
components nothing imports — which is precisely why this class survived. Extending it is worth its
own decision; the honest statement today is that the guard's blind spot and this finding list are the
same shape.

---

## Part 3 — Where a branch stands against `main`

**The data does not exist locally.** There is no `rev-list`, no `merge-base`, and no ahead/behind
count anywhere in the codebase — verified by sweep. The only commit-graph primitives are
`iter_commits` and `is_ancestor`.

There is exactly **one `git fetch` in the repository**: `tools/repo/clone.py:174`, inside
`check_base_drift`. It fires only on a fresh (non-resume) backlog-item run, holds the project mutex,
and fetches a single refspec.

Two consequences that make the local view structurally unreliable:

- **Pushes bypass `origin` entirely.** `connectors/gitlab.py:248` builds a `push_url` and pushes to
  that URL, not to the named remote, so `refs/remotes/origin/mosaera/*` is **never created** (the
clone *does* hold `mosaera/*` as local heads — corrected 2026-08-18; only the remote-tracking refs
are missing, and an earlier version of this paragraph said otherwise). This is
  the root cause of the empty branch list observed live on 2026-08-18 — a structural gap, not a data
  glitch. It also means the target-branch picker and the per-branch delete list are empty on any
  project whose item branches only ever existed via Mosaera's own pushes.
- **`origin/main` is arbitrarily stale** — fresh only as of the last fresh-item-run launch. A project
  with no runs since creation carries clone-time refs. This also explains the Changes tab reporting
  "18 files · +285 vs main" while the MR it opened carried 1 commit / 4 files: the diff base was
  behind the real `main`.

`check_base_drift` additionally *destroys* the behind state — a cleanly-behind base is hard-reset to
`origin/<base>` (`clone.py:187`) — so "behind" is never a state the system holds.

### What can be built honestly, without a fetch

The owner's constraint is: honest about staleness, no new fetch. Within it:

- **Ahead is computable now, offline.** `commit_list(workspace, base)` (`diff.py:36`) already returns
  exactly the `base..HEAD` commit list.
- **Behind is not countable** without the objects. But `remote_synced` already performs a
  non-mutating live `ls-remote` on a request path (`diff.py:101`), which yields the true remote sha of
  a ref. If we hold that sha locally, `is_ancestor` gives an exact answer; if we do not, we know we
  are behind by an *unknown* amount — which is a truthful thing to render.
- **Four states, each stamped with the base ref's age:** `ahead N` · `in sync` · `behind (amount
  unknown)` · `unknown (offline / no remote)`. Never render unknown as synced — ADR-0102 slice H
  already sets that rule for `remote_synced`, and it extends here unchanged.
- It reads naturally into the existing `base … · remoteSyncPlain(…)` line at
  `DeliveryWorkspace.tsx:238`.

A true real-time ahead/behind requires either a fetch (mutates `.git`, races live runs, needs the
project mutex) or GitLab's `repository/compare` endpoint (api-scoped, not currently wired). **Both
were deliberately excluded.** If the honest four-state indicator proves insufficient in use, wiring
`repository/compare` behind the existing api token is the next step to evaluate — it touches no local
git and degrades to the offline states when no api token exists.

---

## Considered and rejected

- **Per-project roles / a general RBAC layer** — lands adjacent to the roadmap's forbidden "generic
  Team plugin API", and the two-role model is sufficient once the boundary is drawn correctly.
- **Weakening the posture overlay** so the four toggles "work" — ADR-0046 forbids posture relaxation;
  the fix is visibility, not permission.
- **Adding a fetch to any read path** — `diff.py:62` and `routes/project_delivery.py:180` both treat
  this as an invariant because a fetch mutates `.git` and races a live run.
- **Building the labels input or the metrics UI** as part of this review — both are real product
  decisions, not audit findings.

## Recommended order

1. Charter split (`posture: None = unchanged`) — unblocks the member's primary journey; the only
   finding that makes the product unusable for its stated audience.
2. Labels-clearing bug (`gitlab_write.py:106`) — a live data-loss bug on someone else's MR.
3. Render the posture clamp in Settings — the most misleading surface still shipping.
4. `merged` — either populate it or delete the field and its three readers.
5. Members see read-only settings (`SettingsPage.tsx:54`).
6. Branch-standing indicator, four honest states.
7. The remainder of Part 2 §6, as cleanup.

Each fix must land with evidence that the control now *fires* — not that a test with a mocked field
passes. That failure mode is what produced finding 2.
