# Red team — the agent prompt/packet review (2026-08-19)

**Status:** `red-team: done`. Target: `bfd5b94`, `2592ba0`, `7f22ee7`, `a3eda52` — the four commits
of the agent-wide review (fencing untrusted tool output, rendering the coder's prompt from the run's
real configuration, the reviewer verdict parse, and the curator's capability ceiling). **Scoped to
those commits**, not the codebase.

**Method.** One round, run as a subagent with the brief to attack five named seams, then **every
claim re-verified by hand against running code before acceptance**. That mattered: the round
returned seven findings and the verification changed the disposition of none but the reasoning of
two. No finding here is recorded on the agent's say-so.

## Verdict

**Seven findings, all confirmed by execution, all FIX-NOW, all fixed and mutation-tested.** Two are
serious: one is a security regression the review itself shipped, and one is a control that a routine
byte in ordinary test output walks straight through. The headline is uncomfortable and worth stating
plainly: **the commit that set out to close a trust boundary opened a permissiveness hole, and the
commit that set out to unify a capability ceiling split it.**

| # | Finding | Disposition |
|---|---|---|
| 1 | **The fence is escapable by any line terminator that is not `\n`.** `fence_tool_output` split on `"\n"`, while every downstream reader — an LLM, and Python's own `splitlines()` — also breaks on CR, VT, FF, LS and NEL. Lines after such a byte got no `| ` prefix, so a forged `## Task` landed at column 0 in the reasoner packet: exactly the forgery the commit exists to stop. CR is not exotic here — `failing_text` is captured subprocess output, where progress bars, `pytest -x` rewrites and CRLF fixtures carry it routinely. The commit's own test used `\n` only, so it passed while the control was bypassed. | **FIX-NOW — fixed.** `splitlines()`, plus a control-character strip so no terminator survives inside a prefixed line either. Verified against all five terminators. |
| 2 | **A permissiveness regression: a park became a ship.** `parse_reviewer_verdict`'s new two-pass parse scanned the fence-stripped text first and took whatever single verdict survived. A reviewer that fenced its genuine `REQUEST_CHANGES` while untrusted prose carried `VERDICT: APPROVE` therefore parsed as `APPROVE` — autonomous ship. The commit claimed "the only behaviour that changes is the intended one"; **the claim was false**, and the commit's own docstring already contained the argument against it. | **FIX-NOW — fixed.** The re-read may resolve ambiguity only toward a **non-approving** verdict. Which verdict is the echo is undecidable, so the parse may only guess where it cannot ship. ADR-0034's amendment is corrected, including the disproved claim. |
| 3 | **`diagnosis_packet` fenced one of its two untrusted sections.** Only `failing_text` was fenced; `summary` — the coder's own report, written after it read repo content and tool output — was still spliced raw. Worse, the new `DIAGNOSIS_SYSTEM` line saying the fenced lines are the untrusted ones made the *unfenced* section read as trusted. The commit made the laundered text more credible than it had been before. | **FIX-NOW — fixed.** The report is fenced too and the system line names both. Untrusted input laundered through an agent is no cleaner for having been. |
| 4 | **Dropping `move` removed the only statement that rename is unreachable.** With `delete_file` granted, the coder's ceiling lost "renaming or moving files" while the PM's rendering kept all seven entries — so intake would reject a rename item the coder believed it could do. **The justification was simply wrong:** `OUT_OF_CAPABILITY` has no `delete` entry, so the contradiction being dodged belonged to the hand-copied string the commit had already replaced. | **FIX-NOW — fixed by deletion.** Every entry renders in every configuration, and a test asserts each phrase reaches the coder. Two ceilings from one source was the defect the commit was written to close. |
| 5 | **`tester_owns_tests` read a different source than every other consumer.** The prompt read `settings.tester_enabled`; everything else reads `tester_enabled = tester_tools is not None`, set two lines below in the same factory. They agree only because `build_graph` derives both from one flag — a `team_factory` passing `tester_tools` with the setting off (bench and tests inject one) would tell the coder it owned the tests while its writes were refused. | **FIX-NOW — fixed.** Derived from `tester_tools`. Pinned by a test that drives the factory with the two sources deliberately disagreeing, the only state that shows it. |
| 6 | **The protection clause overstated what the tools enforce.** It said a write to "the acceptance tests under tests/" is refused, but `protected_tests` holds only Proctor-authored and Proctor-repaired paths, and is empty until the Proctor has written. For a pre-existing test the statement is false — and the clause told the coder to `SUMMARY: escalate` rather than touch a test it is permitted, and sometimes required, to fix. A fixable state converted into a park. | **FIX-NOW — fixed.** The clause names the protected set as the files listed in the acceptance-tests message, and says plainly that repository tests are not protected and may be fixed — without weakening or deleting one. |
| 7 | **`cap_output` returns more than it was given for any `limit < tail`.** `head = max(0, limit - tail)` with no clamp makes `dropped` negative: `cap_output("X"*1600, limit=1500)` returned 1632 chars with a "truncated -400 chars" marker. Unreachable from today's call sites, but the commit promoted `limit` to a public parameter of `fence_tool_output`. | **FIX-NOW — fixed.** `tail = min(tail, limit)`. |

Finding 8 (scanner findings flattened but not attributed — lint/type messages rendered as `- `
bullets in the same style as the trusted instruction bullets below them) was also confirmed and
fixed by fencing them; it is the mildest of the set, since line forgery was already closed.

## Claims that did NOT survive verification

Recorded so they are not re-investigated.

- **The `... (truncated N chars) ...` marker escaping the fence.** It does not: `cap_output` runs
  before the split, so the marker is its own line and gets prefixed.
- **Newline-flood budget amplification.** `strip()` reduces an all-newline payload to `""`; worst
  case is ~2×, bounded.
- **Fence breakout in the verdict scan** (re-pairing fences to swallow the real verdict). Still
  `CONFLICT`, still parks — swallowing needs a closing fence after the real verdict, which the
  reviewer's verdict placement denies.
- **A payload line already beginning with `| `.** Renders as `| | ## Task`; unambiguous.
- **`Settings.tester_enabled` diverging from the Proctor node in the shipped path.** It does not;
  the divergence is reachable only through a custom `team_factory` (which is finding 5).

## Evidence

Eight regression tests, **each mutation-checked individually** — the fence reverted to `split("\n")`,
the never-toward-`APPROVE` rule removed, the report un-fenced, the tail clamp deleted, the `move`
entry re-skipped, the flag source switched back to `settings`, and the findings re-bulleted. All
seven mutations killed their test; one first attempt produced a false SURVIVED because the mutation
string did not match after formatting and never applied — **the third false pass from this cause
this week**, and the reason every mutation here asserts its own application before running.

Four gates with the six guards run explicitly. Full suite green with the DB gate **verified open**
(zero `requires_db` skips against a throwaway pgvector container on 55433, never the live store).
`prompts.py` crossed the 500-line ratchet during the fixes and was split at its cohesive seam —
`prompts_reason.py`, the ADR-0017/0018 ladder — with the dependency running one way and no
re-export shim.

## Live validation

Item #95 on LedgerCLI, run `20260819-174135-a730a0`, autonomous controls (`tester_enabled: true`).
The run reached a normal conclusion: the Proctor authored acceptance tests, the coder implemented,
and on discovering that the acceptance test demanded the removal of `tempfile` and `os` imports that
are **genuinely used**, it refused to break the file, refused to edit the protected test, and
escalated naming the exact contradiction (`kind: blocked`, both test ids listed as amendable).

That is the `_CODER_TESTS_PROTECTED` escalate clause firing correctly on the real path, and it is
the evidence the fencing did not blind the coder to its own test output. It also demonstrates the
defect is in the *item*: #95's text lists `tempfile, os` as examples of unused imports, and the
Proctor faithfully encoded a false premise. The run remains parked for the owner.

**Not exercised live:** the reason ladder and the reviewer never fired on this run, so the fencing
changes to `diagnosis_packet`, `reason_instruction` and `reasoned_plan_instruction` have unit
evidence only.

## What a Round 2 should attack

The corrected verdict rule — specifically whether the non-approving resolution can itself be induced
(untrusted text carrying `VERDICT: BLOCK` to force a park is a denial-of-service, not a ship, but it
is still an attacker moving the outcome). And whether `fence_tool_output`'s control-character strip
now removes something an agent needed to read — the fence is applied to tracebacks, and a stripped
byte is a change to evidence, which no test currently notices.
