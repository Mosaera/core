# Red team — the per-field charter gate, the branch-delete rule, and retarget (2026-08-18)

**Status:** `red-team: done`. Target: the three auth-touching changes merged to `main` in MR !344 —
the ADR-0047 per-field charter gate (`50c0d39`), and the server-side branch-delete rule plus the
retarget endpoint (`3869faf`). **Scoped to those changes**, not the codebase.

**Method.** One round, two independent adversarial passes with different lenses (authorization;
integrity/destruction), plus my own pass. **Every agent claim was re-verified by hand before being
accepted** — one of the two headline claims did not survive that check (see F1-int below), and this
project's record contains a case where an unverified "not implemented" assertion cost a day.

**Why one round and not three.** Both lenses converged on the same defect class — *the gate split
widened who reaches a path, and the guards around that path were written assuming only admins ever
did*. CLAUDE.md's STOP rule exists for repeated classes; continuing to search for more instances of
a class already substantiated would have delayed fixing it. Round 2 should re-attack **after** these
fixes, not before.

## Verdict

Five FIX-NOW findings, all fixed and regression-tested in this pass. Two accepted, three deferred.
The dominant finding is a genuine privilege escalation introduced by the charter gate split.

| # | Finding | Disposition |
|---|---|---|
| 1 | **The charter is a trusted, unhardened, unaudited prompt channel a member can now author.** `charter_prompt_block` splices `goal`/`constraints` verbatim under a header instructing the model to HONOR them, and feeds the PM intake and the ADR-0047 §3 decompose synthesis — downstream, the coder that writes code and pushes with the project token. The sibling map renderer quotes every repo-derived string precisely because it is untrusted; the charter had no such boundary because only admins could write it. `add_audit_event` appears **zero** times in `routes/projects.py`, while ADR-0047 §176 has always claimed the write is "admin-gated, audited". | **FIX-NOW — fixed** |
| 2 | **`goal`/`constraints` had no leave-unchanged sentinel.** `posture` got one specifically so a member's save could not silently reset it; the other two fields — the ones a member can actually write — were left on a full-row overwrite, so a `PUT {}` erased admin-authored intent. | **FIX-NOW — fixed** |
| 3 | **`retarget` accepted any branch name.** An item MR is deliberately stacked so its diff is one item. Repointing it at `main` makes it propose the entire stacked history under a small-item title, carrying any approval already on the MR. | **FIX-NOW — fixed** |
| 4 | **`mr_state == "closed"` stripped all protection**, for both the source and the target branch. GitLab reopens merge requests, and the poll itself treats only `merged` as terminal — the two halves disagreed. Close → prune → reopen lands a live MR on deleted branches. | **FIX-NOW — fixed** |
| 5 | **`delete_backlog_item` erased the row protection depends on.** Migration 0028 made that row load-bearing for a safety property while three store operations still delete it with no MR check — reachable from an LLM-proposed curation changeset an operator accepts. | **FIX-NOW — fixed** |
| 6 | The delivery router receives no admin dependency (`app.py:384`), so permanent remote-branch destruction and MR mutation are member-available while editing project settings is admin-only. | **DECIDED, fixed.** Not a defect — it followed from the deliberate decision that a member drives delivery end to end. The owner chose to keep the capability but make it admin-only by default, opt-in via `member_branch_delete`, plus a members-only "merged branches only, fail closed" guard. ADR-0004 amended. |
| 7 | The `/mr-status` poll copies GitLab's `target_branch` verbatim into `mr_target`, so remote content becomes an authorization input. A GitLab actor can retarget an MR, let the poll record it, prune the freed branch, and retarget back. | **ACCEPT, documented.** Requires repo write access — an actor who already has it can delete the branch directly. Fails toward over-protection in the common case. |
| 8 | An empty `mr_target` falls back to `_stacked_target` — the exact recomputation that caused the incident. | **DEFER → discharged 2026-08-18 (later same day).** The deferral rested on the backfill being unreachable, and the cause turned out to be that the poll spent the *push* token on a REST read. With the poll on the `api` token the backfill fires, and the "branch but no `mr_url`" rows it could not reach now recover by source-branch lookup. See ADR-0103 Amendment 2. |
| 9 | Posture check is read-then-write across two transactions (TOCTOU). | **ACCEPT.** Narrow race; the loss is a member reverting posture to a value that was already stored moments earlier. |
| 10 | Cross-project branch deletion where two projects share one `source_repo` — the guards are scoped to the calling project. | **DEFER.** Premise not verified live; needs an admin-installed token on both projects. |

## Claims that did NOT survive verification

Recorded so they are not re-investigated, and because a red-team log that only lists hits is not a
measurement.

- **"The backfill never fires on the default configuration, so prune destroys a live target."** The
  poll uses the *push* token for a REST call, which is real — but the poll is also the **only**
  writer of `mr_state="merged"`, and prune requires that value. The same token gap that blocks the
  backfill makes prune inert. The residual (finding 8) is narrower than claimed.
- **`mosaera/../main` traversal past the prefix rule.** Reaches the handler and passes both the
  prefix check and `branch == base`, then dies at git: `..` is illegal in a refname. No bypass —
  but the containment is textual and survives only because git is stricter than the endpoint.
- **Retarget-then-delete to strip protection.** Self-defeating: once no open MR targets a branch,
  deleting it orphans nothing.
- **A member setting posture on charter create.** Omitting posture yields the system default;
  naming *any* posture, including the default, correctly trips the admin gate.

## Evidence

Six regression tests, each **mutation-checked** — the fix was reverted and the test confirmed to
fail, individually, not as a batch (a first batch run masked a weak test behind a passing sibling).
One test initially passed under mutation because it exercises the API fake rather than the real
store; it was re-checked against a route-level mutation instead, and both layers now carry their
own test. Store tests ran against a **throwaway** pgvector container, never `mosaera-postgres` (the
2026-08-10 rule).

`make fmt-check`, `make lint` (six guards), `make typecheck`, 2697 pytest, 531 vitest — all green.
The god-file ratchet refused two grandfathered test files; the regressions were moved into their own
files rather than paid for with thinner assertions.

## What a Round 2 should attack

These fixes, not the original change: the fence in `charter_prompt_block` (can prose still forge a
boundary another way — e.g. impersonating the fence prefix?), and the retarget allowlist (is
`mosaera/*` too permissive — should it be the recorded stack only?).

**Answered later the same day.** The third question — whether finding 5's guard pushes operators
toward deleting the MR in GitLab first, creating a new stranded state — was a real gap, and it was.
It is closed by ADR-0103 Amendment 2: close/reopen means the operator no longer has to leave the
product to end an MR, and a genuinely deleted MR is now forgotten by the poll on two facts. The
same follow-up found that finding 5's guard covered one of three doors — `split_backlog_item` and
`merge_backlog_items` delete rows too, and were unguarded.
