# LedgerCLI friction log — case study #2, driven from the UI (2026-08-23)

**What this is.** A record of driving the live LedgerCLI project toward a finished product while
acting as a **non-technical operator**, using **only the Mosaera console UI**. No CLI, no API
writes, no file edits, no repo knowledge used to route around a gap. Findings continue the
numbering from [`ledgercli-friction-log-2026-08-05.md`](ledgercli-friction-log-2026-08-05.md)
(F0–F63) because ADRs cite F-numbers as stable identifiers.

**Status: incomplete, deliberately.** The board moved from *9 in review · 5 deferred · 1 stuck* to
**13 done · 1 in review · 2 to-do**. Delivery and the merge were **not** reached; the owner halted
the run to fix what it had already surfaced. The ADR-0102 finish line — *"the LedgerCLI case-study
merge driven entirely from the Delivery page"* — remains unmet, and no prior record shows it ever
being met.

**The rule this log obeys.** Its predecessor reached 47 open findings with **zero** tracked as
issues, and F58/F62 were later rediscovered from scratch at real cost. Every finding below carries
a work item, filed as it was found.

---

## Method

One operator (Claude, in the operator's chair), one live instance, one afternoon. The API was used
**read-only and only to explain a hurdle the UI had already put in front of me** — twice: once to
learn whether an api-scoped token existed (which became F64), and once to confirm board counts.
Every action that changed the project went through the console: PM chat, changeset approvals, item
review, run launch, write approvals, an escalation authorisation, a send-back, and a gate override.

---

## Verdict

| # | Finding | Disposition | Item |
|---|---|---|---|
| F64 | The Delivery page never says whether an **api-scoped token** exists, yet that bit alone decides whether a project can reach "Delivered" | FIX | #98 |
| F65 | Backlog items are created that violate the brief's **own written prohibitions**; #113 burned 8 runs before anyone noticed the item was the defect | FIX | #99 |
| F66 | **Deferred is a trap state** — only *Edit* and *Ask PM*; no run, no un-defer, no status control | FIX-NOW | #93 |
| F67 | Acceptance criteria render as a **raw Python list literal** | FIX-NOW | #95 |
| F68 | Review asks for approval **without showing the change** | FIX-NOW | #94 |
| F69 | Item cards show the **latest** run, not the **delivering** run | FIX | #97 |
| F70 | A `.gitignore` cost **1.34M tokens, 7 revisions, ~$3.52** and an override | DEFER (engine) | #101 |
| F71 | Reviewer misreads a run's **cumulative diff** as duplicate files, driving the revision loop | DEFER (engine) | #102 |
| F72 | Escalation shows **raw chain-of-thought** before the question | FIX | #100 |
| F73 | **PM prefill caret trap** garbles the operator's first message | FIX-NOW | #96 |
| F74 | The proof spider chart reads as sidelined; owner directive to make it a **centerpiece** | FIX-NOW | *(owner directive, not a defect)* |

---

## What the product did well

A log of only failures is not a measurement. These are the places the product carried the operator,
and they are the parts worth defending in any redesign.

1. **The brief told me what "done" means without my asking anyone.** Its Acceptance Criteria table
   is testable, specific, and ends with *"All items above are testable and must be satisfied for
   the project to be considered complete."* Every scope judgement below traces to it.

2. **Quincy is the strongest component in the system.** Given the item that had failed eight times,
   and told only that it seemed to contradict the brief, it read the brief, agreed, and proposed a
   scoped deletion **with the specific reason** — gated on my approval, never acting unilaterally.

3. **It refused a bad instruction.** I explicitly offered it the option to *re-scope* the two
   charter-violating items. It declined, because a pandas dependency and a live API call cannot be
   made compliant with a brief that forbids both, and proposed deletion instead. A PM that says
   "this cannot be rescued" when that is the truth is worth more than one that always complies.

4. **The escalation was a real question, not a stall.** The run stopped and told me its own
   acceptance tests demanded a byte-exact `.gitignore` with no comments — stricter than the item
   required. It offered three options with one recommended, required a written reason, and recorded
   that reason in the run's decision log where it remains readable.

5. **Guided mode's write approvals are well judged.** Each write named its file and size, with an
   opt-in to allow the remaining test-file writes for that run. The decision log afterwards
   distinguishes *auto-allowed (operator opt-in this run)* from *auto-accepted (mode: accept)* — the
   operator's own delegation is on the record, not just the outcome.

6. **The gate refused to lie.** It would not call the work proven with a reviewer objection and no
   bound claims outstanding, offered an override, and recorded the override on the receipt.

---

## Run ledger

| Run | Item | Outcome | Wall | Revisions | Tokens | Shadow |
|---|---|---|---|---|---|---|
| `20260823-160332-163373` | add a `.gitignore` file | Delivered (operator override over 2 unresolved gate reasons) | 8m | 7 of 8 | 1,340,031 | ~$3.52 |

Interventions in that single run: **1** write approval + batch opt-in, **1** escalation authorising
the tester to re-author three over-strict tests, **1** send-back with notes, **1** gate override.
Projection shown before launch: **~$1.03**. Actual: **3.4×** that.

Board work completed without new runs: 9 items reviewed and approved, 3 items deleted as
brief-violating (#92, #93, #113), 3 items rescued from Deferred (via delete-and-recreate, F66).

---

## Claims that did NOT survive verification

- **"The review sheet gives you no way to see the change."** Wrong as stated, and the owner
  corrected it mid-session: the run *is* reachable by clicking the run id in the sheet's RUNS list,
  which opens the full run page with the summary, verdict and diffs. The real defect is narrower and
  is what F68 records: the affordance is an unlabelled mono id adjacent to the approve button, so it
  is neither discoverable nor safe to aim at.
- **"Clicking the notification bell freezes the renderer."** Recorded during the previous session
  and only half true. The component is sound; a probe of mine that awaited `requestAnimationFrame`
  was itself the hang. The genuine defect was a repaint cost from the panel being trapped inside the
  header's `backdrop-filter` layer — fixed and proven separately.
- **"Deferred items are simply unrunnable."** Also too strong: they *can* be returned to work, but
  only by the PM deleting and re-creating them, which is why F66 is filed as a missing operator
  verb rather than an impossibility.

---

## What this says about the product

The engine's judgement is better than its ergonomics. Every governance moment in this session
worked: the PM defended the brief, the escalation asked a real question, the gate refused to call
unverified work proven, and every operator decision landed on a record. What cost the operator time
was never the reasoning — it was **states with no exit** (F66), **decisions asked without evidence
attached** (F68), **raw internals leaking into the interface** (F67, F72), and **effort with no
relationship to the size of the task** (F70).

The one finding that should worry a reader most is **F65**: a backlog can be generated that
contradicts the project's own brief, and nothing catches it until a human reads both. Eight runs
died against that contradiction, and the operator — not the system — is what finally noticed.

---

## Session 2 — driving to a clonable product (2026-08-23, later)

**Scope.** The owner's bar moved from "merged" to *"something I can run on my own machine just by
pulling it from GitLab"*. Verification therefore became a fresh `git clone` + `pip install -e .` +
`budget --version` + `python -m unittest discover`, run outside the product. That single change of
oracle is what surfaced every finding below — none of them were visible from the console.

| # | Finding | Disposition |
|---|---|---|
|  F75 | Three test files (`test_version_flag.py`, `test_ordinal_functionality.py`, `test_utils_ordinal.py`) `import pytest` while the brief mandates zero dependencies, so `python -m unittest discover` ends `FAILED (errors=3)` on a clean checkout. | FIX (item #120) |
|  F76 | The product did not run for a user who cloned it: no `[project.scripts]` entry point and no installation section in the README. Fixed by items #117/#118 — but **only a clone test could see it**; every in-product signal read green. | FIXED |
|  F77 | **Validation cannot distinguish an infrastructure kill from a test failure.** The sandbox SIGKILLed the test step (`exit code 137` — the 1g `--memory` cap or the 256 `--pids-limit` in `sandbox/_docker.py`), and `validation.py` reported it to the coder as failing tests. `run_plan` special-cases `TIMED OUT` but nothing else, so `result.ok` is false and the graph routes to `fix`. The coder then burned **3 iterations / ~794k tokens / 25 min** trying to repair code that was passing — the captured output shows 69 passing dots and no failures before the kill. An unwinnable loop, and the operator's only escape was to cancel. | FIX (engine) |
|  F78 | **The engine's real reason for parking is recorded but never surfaced.** Three consecutive runs died instantly at `plan → gate` having done nothing. State held `plan_unworkable_reason: "under_specified: no material acceptance claim is checkable as written"`. The run page showed only downstream absences — "no checks were attempted", "the reviewer's verdict couldn't be read", "the run ended before the security scan could run" — none of which name the cause. Reading the API was the only way to learn it. | FIX-NOW |
|  F79 | Delivery has no combined merge request. 16 done items each carry their own **Open MR** button and the header reads "16 deliverable without an MR", while the work is in fact cumulative on the newest branch — so the count overstates what is actually undelivered, and one MR silently carries sixteen items. | FIX |
|  F80 | Stage chips do not show validation. During the two-phase install→test cycle the token counter is flat (deterministic work, no model calls) and the chip stays on `Build`, so a live run is indistinguishable from a hung one. The owner asked "what's going on?" for exactly this reason. | FIX |

### The one that matters

**F78 is the same failure as F72, one layer down.** The system *had* the answer, phrased well enough
for a non-technical reader, and showed a wall of absences instead. This is the repo's own
**green-by-vacancy** class inverted: not absence counted as proof, but **a recorded cause displayed
as a set of absences**. It is also the closest thing this session found to a breach of
*Unsuppressible Ask* — the ask existed, and the interface did not carry it.

Once item #120's acceptance criteria were rewritten into mechanically checkable claims
(`grep -c pytest … returns 0`; `python -m unittest discover` exits 0), the identical run started
working immediately. The engine was right to refuse; it just refused silently.

### Claims that did NOT survive verification (session 2)

- **"Switching write mode from ask to accept collapses the run."** Both dead runs carried my own
  ask→accept switch five seconds in, and it was the only recorded decision. A third run with the
  mode untouched died identically. The correlation was mine, not the engine's.
- **"The Proctor is duplicating the test files instead of converting them."** The `*_unittest.py`
  writes were the Proctor authoring acceptance tests **test-first** (ADR-0013), exactly as designed.
  The coder edited the three real files afterwards. Rejecting those writes would have broken the
  intended flow.
- **"The validation kill is a fork bomb from the acceptance criterion I suggested."** Plausible —
  a test that shells out to `python -m unittest discover` would recurse — but **false**: no written
  test invokes discover as a subprocess. The cause of the SIGKILL remains unestablished; what is
  established is that the harness reports it as a test failure.
- **"The Open MR button is inert."** It opens a compose panel (title, description, target branch,
  squash, delete-source). My text-only page reads missed it, twice.
- **"MR !2 merged the combined LedgerCLI work."** It carried item **#104** alone. Recorded here
  because the previous session's write-up implies otherwise.
- **"An ended run strands its item in `in_progress` with no operator exit."** The item returns to
  `todo` once the run is properly resolved. The narrower true statement: while a run sits
  unresolved, its item's sheet offers only *Ask PM* and *Close*, with no link to the run holding it.

### Outcome of session 2

**Fixed and on `staging`** (commit `f901c788`, four gates + six guards green): F77, F78, F80. Both
new pins were **mutation-checked** — reverting either fix fails them. The F78 suite carries a
separate wiring test because the method-level tests all survive deleting the call site; that is the
"pin that cannot fail" class this repo has paid for four times in this session alone.

**Merged to `main`:** MR !3 (`mosaera/item-118`) — the console-script entry point and the README
installation section. Verified by fresh clone of `main`:

| check | result |
|---|---|
| `pip install -e .` | passes |
| `budget --version` | `0.1.0` |
| `python -m unittest discover` | 44 tests, **`FAILED (errors=3)`** |

So LedgerCLI is **installable and runnable, and its documented test command still fails on a clean
checkout**. The remaining three errors are F75, which item #120 exists to fix and which could not
be delivered until F77 was fixed — the conversion run was killed mid-suite and looped.

**A correction to the earlier record:** MR !2 carried item **#104 alone**, not the combined work.
The previous write-up implied otherwise, and the Delivery page still reads "15 deliverable without
an MR" over items whose commits are already on `main`. That is F79.

---

## Addendum — the hardening pass, and the finding that outlived it (2026-08-23, later)

After the brief was met, a hardening round was driven through the UI for three gaps found by
stress-testing beyond the brief. **Two delivered and merged; one parked honestly.**

| # | Gap | Outcome |
|---|---|---|
| #124 | a corrupt data row crashed `summary` with a raw traceback | FIXED — clean error, exit 1 |
| #125 | `budget add -5.00` / `add 0` accepted silently | FIXED — rejected, exit 1 |
| #126 | a missing/unreadable file is indistinguishable from an empty one | **PARKED** |

**F81 — the producer invents an external cause when it cannot self-diagnose**
(#114). On #126 the coder hit an
`UnboundLocalError` in a function it had just written and concluded *"there is a discrepancy between
what I am editing and what is being executed — likely due to Python caching or installation
issues"*, escalating twice on that theory. It is the **second** invented external cause for the same
missing instrument: F87 spent **291,846 coder tokens** on *"network issues installing dependencies"*
while validation ran the same suite to 79 passed. A producer facing a question it has no instrument
to answer invents an answer rather than parking. This is the observable
[ADR-0110](../adr/ADR-0110-agent-ownership-and-environment-truth.md) is judged against.

The same session also showed the **inverse working**: on #122 the coder met an acceptance test whose
assertion could never pass (`assertNotIn('', content)` on an empty CSV), named the contradiction, and
escalated — and the **Proctor**, not the producer, rewrote it. That boundary is encoded three times
over; the other is encoded nowhere. **The difference is a control, not intelligence** — which is the
whole argument of ADR-0110.

The gate also earned its keep: #126 reached it with four unresolved failures (checks failed, reviewer
objected, a claim failed, tests modified) and was refused. That refusal is the reason the two items
that passed can be trusted, and it is why ADR-0110 records **no gate relaxation** as an explicit
non-goal — autonomy grows on the posture axis, never the gate's authority.

### Claims that did NOT survive verification (addendum)

- **"The escalation's recommended Authorise button is permanently disabled."** Wrong twice over. It
  requires ticking the specific test AND writing the reason in the notes box — a deliberate red-team
  guard (2026-08-21) so the button cannot mean less than its label. My scripted clicks had also
  desynced the checkbox from the UI's state, which made it look stuck. The product was right; it was
  being driven wrong.
- **"The F78 fix means the park reason now shows on the page."** Half true, and corrected in
  #108: the diagnosis is now *recorded* at
  the pause (`park_cause: "under_specified"` where it was `null`), but the gate panel still renders
  only the absence list. The recording was fixed; the rendering was not.

---

## Addendum 2 — building the fix, and what using it taught (2026-08-24)

[ADR-0110](../adr/ADR-0110-agent-ownership-and-environment-truth.md) slice 1 shipped: a **fact
surface** giving the producer the interpreter in use, the editable-install target, the sha/mtime of
the files it changed, and `__pycache__` staleness — computed host-side, attached on failure only.
Three things were learned by *using* it, none of which were visible from the code.

**F83 — an instrument whose firing cannot be observed is not measurable.** The first live A/B looked
spectacular (coder tokens 1,131,762 → 92,466 on the identical item) and was **unattributable**: the
run's single validation PASSED, so the path built for the defect never fired. Worse, "did the block
fire?" had no obtainable answer — a tool's RETURN VALUE reaches no durable record, not the
transcript, report, artifacts, messages nor events endpoint, none of which carry even `run_tests`'
unconditional `validation plan:` prefix. An initial reading of *"the facts never appeared"* was
therefore **unsound**: it searched a surface that could not have shown them either way. Fixed by
emitting one activity event per attachment. `note_degradation`'s lesson, one file over: *a count with
no denominator is not a measurement.*

**F84 — repeating unchanged facts is noise.** Run `20260824-015015-43a966`: a coder probing in
circles failed 16 times and received **16 near-identical blocks** — sixteen copies of one paragraph
into the context of an agent already struggling. The block now speaks when the facts MOVE and stays
quiet when they do not, recording the suppression either way so *"fired but suppressed"* and *"never
fired"* stay distinguishable. **Found only by using it**; nothing in the code or its tests suggested
it.

**F82 — the stop control is gated behind the thing you are stopping**
([#116). `cancel run` renders only while a
run is WORKING; while paused, a write gate offers only *Allow* / *Reject*. So you must answer a gate
— spending another turn — before cancel reappears. A thrashing run spends its life paused, which is
exactly when the stop does not exist. Two more of the same family the same session: the write-mode
toggle silently does nothing while paused (no `mode_change` recorded, no error shown), and the run
page's live stream dies after every approval, forcing a reload per decision.

### The measurement is OWED, and deliberately not forced

ADR-0110 gates slice 2 on measuring slice 1. **The population does not yet exist:** across every run
on 2026-08-24 the fact block fired **zero times on a failing suite** — runs either passed first try
or never reached validation at all. The benchmark corpus is the wrong instrument (its broken-oracle
failures are graders, not environment confusion), so a sweep would produce a confident null about
the wrong population. **Stopped rather than spend**, which is the lesson
[the mutation-veto A/B](mutation-veto-ab-2026-08-11.md) paid 5.5 hours to write down.

The gate has now refused two unearned conclusions in one day: the −92% that the mechanism did not
cause, and a measurement whose population is missing. That is the rule working, not the rule
obstructing.

### LedgerCLI, final state

**24 of 25 items done.** The product meets its brief in full and carries two robustness fixes beyond
it (a corrupt row no longer crashes `summary`; missing and unreadable files are distinguished from
empty ones). Verified on a fresh clone of `main`: `pip install -e .` · `budget --version` ·
`python -m unittest discover` → **77 tests, OK**.

**#127 (CSV formula injection) is parked**, not abandoned: real hardening, out of the brief's scope,
and it consumed **~1.6M tokens across two attempts without ever reaching a passing suite** — both
died in test-authoring churn rather than implementation. Whether that is the item or the engine is
**unmeasured**, and worth its own look before anyone spends on it again.
