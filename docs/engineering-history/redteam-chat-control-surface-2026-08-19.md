# Red team — the chat as a control surface (2026-08-19)

**Status:** `red-team: done`. Target: `f9eace7` — ADR-0105 slice 1 (server-derived decisions, the
`[[decision:<id>]]` reference convention, the decision card, and the two refactors it forced).
**Scoped to that commit**, not the codebase.

**Method.** One round, run directly rather than through subagents, across five lenses: prompt
injection / model-summoned UI, authorization, information disclosure, side effects on a read, and
*"did the refactor silently change behaviour?"* Every finding was reproduced against running code
before being written down — finding 1 was confirmed by printing the stored row, not by reading the
call order and inferring.

**Why one round.** The findings did not scatter across the design; three of four are in the seam
between the new marker handling and the pre-existing turn, which is exactly where a bolted-on
feature is weakest. Round 2 should attack these fixes.

## Verdict

**Three FIX-NOW, all fixed and mutation-tested in this pass; one DEFER.** The headline threat the
design was built around — a model conjuring a credential prompt — held under attack. What did not
hold was the plumbing around it.

| # | Finding | Disposition |
|---|---|---|
| 1 | **The stored transcript kept the raw `[[decision:...]]` markers.** The reply was persisted at the top of the turn and the markers stripped near the bottom, so only the RETURNED copy was clean. A reload rendered `[[decision:integration:configure]]` as literal text at the reader — directly contradicting the "cards survive a reload" property this slice was built to deliver — and the markers fed back into the model's history on every later turn. Proven by printing the persisted row. | **FIX-NOW — fixed.** Strip and validate before persisting, so the stored transcript *is* the display text (matching how `pm.chat` already strips its fenced blocks). |
| 2 | **The interactive chat path blocked on GitLab.** The turn derived decisions **twice** — once for the model context, once to validate references — and `mr_stuck` makes a `list_branches` call with a **20-second timeout**. An unreachable GitLab could therefore add up to ~40s to a single chat turn, in front of and behind the model call. **Measured live afterwards: the call costs ~150ms against a healthy instance** — so the 40s is a timeout-bound worst case, not an observed cost, and the finding stands on not putting a third-party outage in the conversation's path rather than on a latency figure. (Noted because a 40s chat turn WAS observed live and turned out to be model latency; the coincidence is exactly the kind of thing that gets mistaken for confirmation.) | **FIX-NOW — fixed.** The turn derives once, with `allow_network=False`; the `/decisions` endpoint derives the full set asynchronously, where a slow GitLab delays a card instead of the chat. The now-redundant `visible_decision_ids` helper is gone rather than left as dead code. |
| 3 | **A credential pasted into the chat persists forever and is replayed to the model.** The transcript is stored verbatim, nothing redacts it, and history is re-sent on every subsequent turn. This pre-dates the change, but the change puts a GitLab setup control *in the conversation*, so the topic now arises there by design. | **FIX-NOW (partial) — mitigated.** Prefix-anchored redaction of GitLab's documented token formats on both transcript writes (`redact_chat.py`), reusing the connectors' URL scrubber. Deliberately narrow and **documented as a mitigation, not a control**: a heuristic broad enough to catch an arbitrary secret is broad enough to corrupt legitimate messages. |
| 4 | **A prompt is not a control.** The structural guard stops the model *summoning UI*; it cannot stop the model *writing a sentence* asking the operator to paste a secret, which untrusted repo content could induce. | **DEFER, documented.** The blast radius is now bounded by finding 3's redaction and by the setup control being present (no reason to type one). A real fix is output classification on model replies — a feature with its own false-positive cost, not a guard to bolt on here. Recorded as the residual in TM-0002. |

## Claims that did NOT survive verification

Recorded so they are not re-investigated, and because a log listing only hits is not a measurement.

- **"The prompt split silently changed what Quincy is told."** Checked by assembling both prompts at
  runtime: `_CHANGESET_OPS` is still present in *both* `_CHAT_SYSTEM` and `_CURATE_SYSTEM`, the
  re-exported object is identical, and the new clauses are present. No drift.
- **"The member-available `/decisions` endpoint newly discloses GitLab configuration state."** It
  does not. `make_oauth_router` receives an admin dependency but `/oauth/gitlab/status` never calls
  it, so `configured` is already member-visible — which is what lets the settings pane render a
  member's read-only status at all.
- **"Window-focus refetching amplifies the REST load."** The app sets
  `refetchOnWindowFocus: false` globally. The amplification was real but entirely server-side
  (finding 2), not client-side.
- **"A malformed marker could inject markup."** An unmatched `[[decision:` is left as literal text
  and rendered through `PmMarkdown`, which has no `rehype-raw`. Text only.

## Evidence

Four regression tests, each **mutation-checked individually**. Finding 1's first mutation
**survived** — it reinstated the persist call but left the strip above it, so the bug was never
actually restored; re-run with the ordering genuinely inverted, the test fails. That is the second
time this week a mutation harness reported a false pass, and both times the cause was the mutation
not being the bug it claimed to be.

`fmt-check`, `lint` (six guards), `typecheck`, full pytest with the DB gate open against a
throwaway pgvector container, vitest, web build — all green.

## Found later, in live validation

Recorded here because the round missed it and a test would not have caught it either.

| # | Finding | Disposition |
|---|---|---|
| 5 | **The decision card never rendered on an empty conversation.** The cards were mounted inside the non-empty branch of the chat panel's `{empty ? hero : list}` ternary, so a project with zero messages showed none — and a brand-new project both lands in that state and is exactly when "connect GitLab before you can deliver" matters most. Every unit test rendered the card in isolation or a populated panel, so nothing failed. | **FIX-NOW — fixed** (`92ad6ba`), hoisted outside the ternary, with a regression test for the empty conversation specifically. |

## What a Round 2 should attack

These fixes: whether `allow_network=False` leaves a decision kind visible in the panel but absent
from Quincy's context (an operator asking "what about that stuck MR?" and Quincy not knowing it
exists); whether the redaction can be evaded by a token split across two messages; and whether the
"strip before persist" ordering now hides a marker the operator would have wanted to see in an
exported transcript.
