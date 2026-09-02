# Red team — delivery in the PM context (ADR-0105 slice 2, 2026-08-19)

**Status:** `red-team: done`. Target: `2de2aa8` — the `## Delivery` context block, the
`delivered_no_mr` decision kind, the ban→deadline change on the chat path, and the `quote_repo_text`
routing for remote-derived strings. **Scoped to that commit.**

**Method.** One round across four lenses: prompt injection via remote content, honesty of the
degraded path, the new network coupling, and *"what does this look like to someone actually using
it?"* — the last of which is where the dominant finding came from, and it came from the owner, not
from me.

## Verdict

**Two FIX-NOW, both fixed and mutation-tested; one ACCEPT with a corrected claim; one DEFER.**
The injection surface held. The honesty of the *surface* did not.

| # | Finding | Disposition |
|---|---|---|
| 1 | **A project not on GitLab was told to install a token.** `delivery_prompt_block` renders "Branches: NOT CHECKED (no api-scoped token, or GitLab did not answer in time)" whenever the read is absent — including for a project whose source is a local path, where there is no remote to inspect at all. Quincy would then coach the operator to provision a credential for a repository that has none. Two different unknowns collapsed into one sentence. | **FIX-NOW — fixed.** The renderer takes `on_gitlab` and names the real reason. Both branches still say NOT CHECKED, because both are still unknowns. |
| 2 | **A card that resolves nothing was labelled "Waiting on you."** Every decision rendered under the same banner, and `delivered_no_mr`'s only action is a *link* — clicking it changes nothing, so the card sits there until the operator hand-opens six merge requests. **Found by the owner**, who clicked through, came back, and asked "does that card never leave?" This is the performative-control class this project keeps hunting, and my own slice-2 test docstring had warned about it in the other direction ("a permanent nag the operator learns to ignore") while I shipped exactly that here. | **FIX-NOW — fixed.** Decisions now carry a server-owned `tier`. It describes the CONDITION, not the button — **every** card links out, including `gate_pending` and `mr_stuck`, so "clearable from the card" would have been a false distinction. `blocking` = delivery cannot proceed until a human acts (parked run, missing credential, an MR that cannot merge); `standing` = nothing is broken, work is outstanding. Standing cards render calmly and say "Standing". |
| 3 | **"Bounded wait" overstates what the deadline buys.** `urlopen(timeout=…)` bounds each socket operation's IDLE time, not the total wall clock. A GitLab that accepts the connection and then trickles bytes just under the deadline holds the turn for longer than 3s — the classic slowloris shape. | **ACCEPT, claim corrected.** The peer is the operator's own configured instance, the response is a single `per_page=100` page, and the alternative is a watchdog thread whose abandoned workers accumulate under exactly the fault it defends against. The ADR and code comments now say *bounds idle time per socket operation*, not "bounded wait". |
| 4 | **`delivered_no_mr` cannot tell "not proposed yet" from "never needed an MR."** An item completed without code — a decision, a spike, something done by hand — is `done` with no `mr_url` and counts as stranded forever. | **DEFER.** No field distinguishes them today; inventing one is backlog-schema work, not a chat-context fix. Finding 2's re-tiering removes the harm (it reads as a standing observation, not an unanswered summons) without pretending to a precision the data does not support. |

## Claims that did NOT survive verification

- **"A crafted branch name can forge a context section."** It cannot. All three print sites route
  through `quote_repo_text` (`pm_sections.py:207,209,222`), which flattens newlines, so no remote
  string can start a line. `live_targets`/`live_sources` are set-membership only and never printed.
  Verified by rendering a branch literally named `evil\n## Project charter…` — one `##` heading
  survives, ours.
- **"The `except Exception` around the branch read hides failures silently."** It degrades to the
  same NOT CHECKED wording the no-token path uses, which IS the operator-visible signal. It cannot
  distinguish a bug from a missing token — but it never claims a clean repo, which is the property
  that matters.
- **"The delivery block leaks item titles or task text into the model context."** It prints ids,
  statuses and branch names only.

## Evidence

Two regression tests, each **mutation-checked individually** — the standing tier flipped back to
blocking, and the non-GitLab wording collapsed back into one sentence. Four gates + six guards
green; full suite green with the DB gate genuinely open (confirmed by a zero `requires_db` skip
count, after an earlier run silently skipped 104 of them); vitest and web build clean.

## What a Round 2 should attack

Whether a standing card that never clears is still worth showing after the operator has seen it
once — the fix stops it shouting, but it does not stop it accumulating. And whether `blocking` is
load-bearing anywhere beyond presentation: today it is a label, and a label that no control reads is
the same class as finding 2 one level up.
