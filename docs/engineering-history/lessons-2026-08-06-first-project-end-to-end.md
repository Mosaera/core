# Lessons — the first project driven end to end (2026-08-06)

**What this is.** The synthesis of one operator session: 24 runs against the LedgerCLI specimen,
~11M tokens, 29 findings (F35–F63), four delivered slices and one item that still hasn't landed.
The [friction log](ledgercli-friction-log-2026-08-05.md) holds each finding; the
[run ledger](ledgercli-run-ledger-2026-08-06.md) holds the data. This holds what they mean.

Read this before planning the next arc.

---

## 1. The coding was never the problem

The single most repeated assumption going in — that the producer would cheat, cut corners, or need
policing — was **measured false**.

- `#64`, six runs on a corpus of deliberately broken acceptance tests: **0 corruption**, proposed
  *and* approved. The producer diagnosed the broken bar, twice naming the exact contradiction
  unprompted, and raised its hand.
- Across every live run, no tampering with a protected test that wasn't caught, and in the one case
  it did weaken an oracle (F59) it did so *while implementing the requirement correctly*.
- Faced with a red bar it had authored and **no operator watching**, it left the bar standing and
  stopped honestly (`20260806-225706`). The opposite of the feared behaviour.

Every delivery blocker this session was **upstream** of implementation (the acceptance bar) or
**downstream** of it (a control, a gate, or a screen). None was "the model wrote bad code."

> **Build from this:** stop spending design effort on producer restraint. Spend it on bar quality and
> on the controls that judge the bar.

## 2. The oracle is the bottleneck, and it fails in *both* directions

| pole | what it looks like | findings |
|---|---|---|
| **Over-strict** | a bar no correct implementation can satisfy | F36, F43, F44, F49 |
| **Vacuous** | a bar nothing can fail | F51, F52 |

Both were observed on the same project, same model, within three hours. The over-strict pole fails
*loudly* — it burns budget and parks. The vacuous pole fails *silently* — it manufactures green.

The second is the dangerous one, and it was closed only by accident of a human reading a diff. A
green signal that can be hollow degrades every green that follows: after F52 there was no way to say
Slice 2 was correct, only that nobody had read it.

> **Build from this:** the two poles need *different* controls. "Can this bar fail?" (F52's fix) and
> "can this bar be satisfied?" (F49's arm) are separate questions, and neither answers the third one
> below.

## 3. The Proctor is high-variance, not incapable — and that is the headline

Same model (`qwen3-coder:30b`), same project, one afternoon:

- three `assertTrue(True)` placeholder bodies (F52);
- a first-draft bar that avoided the F44 date pin **unprompted**, commenting that the date is dynamic;
- an attempt to gut its own already-approved bar because the module didn't exist yet (F53);
- a summary test that **deliberately declined to over-specify** — *"order of categories in output is
  not specified"* — and compared order-independently.

That range is the finding. It is not a capability ceiling; a ceiling doesn't produce the fourth
example. **Variance is what to measure next**, and it is why a single good run proves nothing:
Slice 2's clean autonomous delivery and Slice 1's vacuous first draft are the same system.

> **Build from this:** any future claim about the Proctor needs n>1 *across* runs. Within-run
> repetition is not independent evidence — see §7.

## 4. Individually-correct controls compose into a system that cannot finish

This is the deepest lesson, and F63 is its clearest case.

Item #87 is a **five-line deletion**. Three runs, ~4M tokens, never shipped. And nothing malfunctioned:

- the producer made the correct fix and hand-raised correctly about a conflicting test;
- the tamper guard correctly blocked an edit to a protected test;
- the delivery gate correctly refused to ship failing tests;
- the escalation correctly reached the operator.

Every control did its job, and the honest work could not complete. The item's *purpose* was to change
behaviour, which necessarily invalidates the test encoding the old behaviour — a trap no single
control can see, because each is locally right.

The same shape appears in F57: intake, red phase, assertion floor, coverage and mutation **all
passed**, and a requirement shipped unimplemented because producer and oracle shared one misreading.

> **Build from this:** start reviewing controls for *interaction*, not just correctness. The
> question "what does this refuse, and can anything else then proceed?" is not currently asked
> anywhere.

## 5. Several controls measure the wrong property

Not bugs in implementation — bugs in *what was chosen to measure*.

- **The tamper guard detects edits, not weakening.** Run `215759` **deleted** an assertion and
  shipped; run `232524` **restored** it and was blocked (F63). It missed the dishonest change and
  caught the honest one.
- **The assertion floor checked syntax, not semantics** — it rejected `assert True` and accepted
  `self.assertTrue(True)`, and the product's charter mandates the syntax that slipped through (F52).
- **Coverage and mutation validate the tests that exist**, never whether they cover what was asked.
  Both passed on a suite that never mentions the word carrying the requirement (F57).

Each is answerable with a better question: *did assertion count go down?*, *are all operands
literals?*, *does every criterion have a test that can fail on it?*

> **Build from this:** when a control fires or stays silent, ask what property it actually tests. Two
> of these three were one-line conceptual fixes hiding behind a year of confidence.

## 6. Evidence surfaces are controls, and ours were lying

An operator who cannot see cannot govern. This session, the screen was wrong in ways that changed
decisions:

- **F58** — runs that never reached a test phase rendered as red `TESTS FAIL`; the roster grew as
  work landed, so a control switched **off** was indistinguishable from one not yet reached. That is
  how `critic_enabled` sat at its highest proven liveness rung and **OFF** all day, unremarked.
- **F54** — the delivery gate truncates its diff at 6000 chars; here it hid an entire test file the
  operator was being asked to approve.
- **F50** — every cancelled run recorded a blank diagnosis, so the PM invented causal stories about
  twelve runs of empty history.
- **F61/F63** — "deny with feedback" silently becomes "terminate" at the iteration cap, and again on
  a tamper verdict, with no signal either way.

> **Build from this:** the gate's *presentation* is part of the trust boundary. Treat a lossy or
> misleading evidence surface as a control defect, not a UI polish item.

## 7. Human authority has no artifact — and that is architectural

At the escalation gate the operator wrote *"You are AUTHORIZED to update that test — this is a
requirement change I own."* It **went nowhere**. The authorization lived in a prompt string handed to
the producer; the deterministic guard that blocked delivery never saw it (F63).

The North Star says decisions and evidence are versioned artifacts. **Operator authorization is not
one.** It is conversation, and conversation cannot reach a deterministic control by design.

This is the gap that makes §4 unfixable by tuning: as long as human authority is prose, any control
strict enough to be useful is also strict enough to deadlock honest work.

> **Build from this:** a recorded, per-item, file-scoped authorization artifact that the tamper guard
> *reads*. ADR-scale, trust-boundary, red-team required. This is the highest-value next change.

## 8. Verification discipline — mostly lessons about my own work

Recorded because these are the errors most likely to recur:

- **Verify against the actual case, not the schema.** F50 was "fixed" twice: the first fix wrote to
  the in-memory session while the durable row the PM reads stayed null. Both times the assertion
  looked right against the *shape* of the data.
- **Two halves of one mechanism must be checked for agreement.** F49's predicate was unit-tested and
  its ask tested against a fake memory — never together on a real terminal run. First time both ran,
  they disagreed (F62).
- **A shipped fix is not evidence the fix worked.** F52 was deployed and **never fired**; the bar was
  real from the first draft. The delivery that followed was not caused by it.
- **Within-run repetition is not independent evidence.** F51 was written up as a system property from
  three rounds inside one run; the next run refuted it and it was withdrawn.
- **An instrument that passes before its fix exists is not an instrument.** Three did this session;
  every new test since has been confirmed failing first.

> **Build from this:** "confirmed failing without the fix" is now non-negotiable, and it should
> extend to *mechanisms*, not just functions — exercise both ends on one real run.

## 9. What actually worked

Worth naming, because the finding count skews pessimistic:

- **The deterministic gate refused a run both model signals approved.** `tests_passed: true`,
  reviewer `APPROVE`, and it still returned `require_human` on `oracle_unverified`. Deterministic
  Final Authority, working unprompted, on a real case.
- **Intake refused an under-specified item at 0 tokens** — the cheapest possible park, before any
  spend, naming the offending criterion.
- **The ESCALATE arm fired live** and turned a `thrash_park` into an `honest_park` naming the
  blocking tests.
- **Guided posture earns its cost.** Slice 1's four operator denials — a bare `python` interpreter,
  an unsatisfiable quoting contradiction, a gutted bar, an un-installable `pyproject.toml` — were
  **all invisible to every automated check**. Autonomous delivered Slices 2 and 3 cleanly, and the
  one item needing judgement took guided to solve.

## 10. Cost shape

| | |
|---|---|
| input:output | **~35:1** — cost tracks **round trips**, not output volume |
| Slice 1 (guided, 9 gates) | 764k tokens |
| Slice 2 (autonomous) | 435k |
| Slice 3 (autonomous) | 665k |
| Item #87 (3 attempts, undelivered) | ~4M |

The per-run token default (200k) cannot finish a real item, and each raise grants ~+200k anchored to
current spend, so a 700k item needs three human interventions — an unattended run stalls at the first
(F56). **A failed run costs as much as a successful one**, which makes bar quality an economic
question, not just a correctness one.

---

## The through-line

**Honest failure is not delivery.** Every park this session was correct, every refusal was
justified, and the system still could not finish a five-line change without a human. That gap — between
*controls behaving correctly* and *work completing* — is the thing to close next, and §7 is where it
starts.

The encouraging half: nothing here requires better models. The producer is already good enough to
diagnose broken requirements, decline to over-specify, and stop honestly when it cannot proceed. What
it lacks is a way for a human to hand it authority, and a set of controls that measure the properties
they claim to.
