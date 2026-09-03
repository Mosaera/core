# Red team — the delivery-pipeline completion (2026-08-18)

**Status:** `red-team: done`. Target: the five commits on `staging` that finished the delivery
pipeline — `37f23d0` (Alembic 0029, the project MR's recorded source), `defe5fd` (MR close/reopen,
the api-token move, the empty-diff ordering), `13b76ce` (split/merge guards, `?force=`, the
phantom-MR rule), `08b4e30` (the `mr.reopend` audit-name fix). **Scoped to those commits**, not the
codebase.

**Method.** One round, run directly rather than through subagents, across four lenses:
authorization, integrity/destruction, auditability, and *"did these fixes create a new stuck
state?"* Every finding below was confirmed by reading the code path end to end before being
written down — the standing rule in this repo after an unverified "not implemented" assertion once
cost a day, and after the previous round's headline agent claim failed verification.

**Why one round.** The findings did not scatter: three of four land in the newest and least
exercised code, and two of those are in the same twenty lines (`_clear_phantom`). That is a
substantiated signal about *where* the risk is, not a reason to keep sampling elsewhere. Round 2
should attack these fixes.

## Verdict

**Three FIX-NOW, all fixed and mutation-tested in this pass; two ACCEPT; one doc correction.**
The dominant finding is self-inflicted: the fix for one terminal state introduced another.

| # | Finding | Disposition |
|---|---|---|
| 1 | **`_clear_phantom` swapped one terminal state for another.** Forgetting a deleted MR cleared `mr_url`/`mr_state`/`mr_target` but left `branch` — which is the opener's idempotency marker. `open_item_mr` refuses `already_open` on it and the UI's `canOpen` requires `!branch`, so the item was left with a branch, no merge request, and **no way to obtain one**. That is precisely the state `defe5fd` was written to eliminate, reintroduced by `13b76ce`. | **FIX-NOW — fixed.** `branch` is cleared too; the branch still exists on the remote, so a re-open pushes to it again. |
| 2 | **`clear_todo_backlog` is a fourth row-deleting door.** `13b76ce` guarded delete/split/merge and asserted that was all of them. It was not: "Generate backlog" bulk-deletes every `todo` row, and `todo` does **not** imply "no merge request" — `runner/_loop.py` resets an item to `todo` on cancel, timeout, and crash while `branch`/`mr_url` persist in their own columns. Re-run an item with an open MR, cancel it, regenerate the backlog: the row is destroyed, the MR orphaned, and the record branch protection reads goes with it. | **FIX-NOW — fixed.** Skips (never deletes) a row with a live MR and returns the count kept. |
| 3 | **The phantom clearing was silently unaudited.** `audit_events.run_id` is a **foreign key to `runs.id`**; `_clear_phantom` passed the synthetic `f"item-{id}"`, so the insert raised and the best-effort `except` swallowed it. An automatic action that strips branch protection and erases an MR record left no trace, and the swallow guaranteed nobody would notice. Violates *Capability through Auditability*. | **FIX-NOW — fixed.** Audited against the project's newest run, the same anchor `_audit_mr` uses. |
| 4 | Closing the project MR moves `in_review` → `active`, which re-opens the `approve_project` endpoint that `in_review` refuses. | **ACCEPT.** `active` is the honest status for a project with no open MR, `start_decompose` only fires on an empty backlog, and `_project_mr_branches` keys off `mr_url` + not-`merged` rather than `active`, so no protection is lost. |
| 5 | `MrComposeBody`'s docstring still says the compose fields "are ignored" without an api token. Since `defe5fd`, `target_branch` is applied before the diff check and therefore reaches the push-options path too. | **Doc correction.** The behaviour is an improvement; the contract text is now stale. |
| 6 | **Is there a fifth row-deleting path?** Asked because finding 2 was the second time this enumeration came up short. Enumerated exhaustively (`s.delete` across the whole store): five paths remove a backlog row — `delete_backlog_item`, `split_backlog_item`, `merge_backlog_items`, `clear_todo_backlog`, and `delete_project`'s cascade. The first four are now guarded. | **ACCEPT (the fifth).** `delete_project` is a whole-scope, explicitly operator-authorized destruction of the project itself, not an edit *within* a live project — Mosaera stops claiming to manage those merge requests rather than silently orphaning them under a project that still exists. Recorded so the enumeration is closed rather than open-ended. |

## Claims that did NOT survive verification

Recorded so they are not re-investigated, and because a log that lists only hits is not a
measurement.

- **"Narrowing `_project_mr_branches` to the single recorded source loses protection the old
  two-guess set provided."** It does not. The cherry-pick path records `mosaera/combined-<id>`, so
  that case is still covered; the non-compose path records the real source, where the old set
  protected the *wrong* branch and missed the right one. A stale `combined-*` that is no longer any
  MR's source becomes deletable, which is correct.
- **"The poll's `source_branch` backfill makes remote content an authorization input"** — the same
  shape as last round's finding 7, which was ACCEPTed for `target_branch`. Weaker here: GitLab does
  not permit changing a merge request's source branch after creation, so unlike the target it is
  not attacker-editable.
- **"With only a push token, a 404 from `get_merge_request` could clear a record."** The paired
  check saves it: the same token also fails `get_project`, so `_mr_is_gone` returns False. Fails
  closed as designed.
- **"A member can close another project's MR."** True, but not introduced here — ADR-0004's roles
  are global, and every delivery endpoint already has this property.

## Evidence

Three regression tests, each **mutation-checked individually** — the fix reverted, the test
confirmed to fail on its own, never as a batch. Finding 1's mutation reinstates the exact bug
(drop `branch=""`); finding 3's disables the audit write; finding 2's reopens the fourth door.
Store tests ran against a **throwaway** pgvector container, never `mosaera-postgres`.

`fmt-check`, `lint` (six guards), `typecheck`, full pytest with the DB gate open, vitest, web
build — all green.

## What a Round 2 should attack

These fixes, not the original change. Specifically: whether clearing `branch` in `_clear_phantom`
can race a run that is mid-delivery on that same item (the poll is a GET any member can trigger);
whether `clear_todo_backlog` silently keeping rows makes "Generate backlog" look like it worked
when it partly did not; and whether `_refuse_if_mr_live` belongs at the store boundary at all, given it is now
duplicated in `clear_todo_backlog` as a skip rather than a raise (two spellings of one rule).
The enumeration question is closed — see finding 6.
