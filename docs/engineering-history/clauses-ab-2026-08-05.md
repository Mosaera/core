# The clause channel does not reproduce the brief edit (2026-08-05)

Status: **Historical record.** ADR-0082 DoD-1, answered — and the effectiveness prediction
**refuted**. n=12 control / n=4 treatment on two cases.

## Question

On 2026-08-04, editing the **brief** to say "at most 5 statements" moved MCB-05/15 from 0/6 to 5/6
grader-clean (Fisher p = 0.015). ADR-0082 tier 2 then built a way to record that decision once —
but a clause delivers the number through **different channels**: a "Standing decisions" block
appended to the run context, and an oracle overlay tightening `max_body`.

Same information, different input path. **Not inferable**, and pre-registered as such: a model may
weight an advisory block differently from the task text, and the overlay makes the check *stricter*,
so the clause path could plausibly land worse.

## What the instrument caught first

The A/B's first pass returned `clauses_applied: []` on **every** treatment run — the control never
fired. Cause: `clauses` was seeded into the graph at launch but **never declared in `RunState`**, so
LangGraph dropped it between nodes. The oracle overlay had therefore never run, in the bench *or*
in the product, since the day it was written.

The unit tests passed throughout, because they called `apply_to_constraints` directly rather than
through the graph. `RunState`'s own comment states the rule — *"DECLARED (ADR-0026) or LangGraph
silently drops it"* — and the omission still happened.

**This is the ADR-0081 control-liveness class, and the engagement check caught it on its first real
use, inside the feature that added it.** A test now asserts the state contract itself.

## Result, after the fix

```
                 clauses_applied                   grader   statements   outcome
control  n=12    []                                0/12 clean   8,8,9,9,8,8,9,8,8,8,9,9   honest_park x12
treatment n=4    ['structural.body_statements=5']  0/4  clean   8,9,8,10                  honest_park x4
```

`experiment_report` → **SCOREABLE** (`controls engaged differ: [] vs
['structural.body_statements=5']`), effect `{control: {honest_park: 12}, treatment: {honest_park: 4}}`.

- **Prediction 1 CONFIRMED** — control reproduces the failure (8–9 statements against limits of 6
  and 7), for the third independent time.
- **Prediction 2 CONFIRMED, but only after the state fix** — the control engages.
- **Prediction 3 REFUTED** — treatment does **not** reach grader-clean. 0/4, with statement counts
  indistinguishable from control (one run delivered *ten*).
- **Prediction 4 CONFIRMED** — the interesting failure, and the reason the experiment was worth
  running.

## What this means

**A standing decision that rides *beside* the task does not change what gets written. The same
number written *into* the brief does.** The brief edit moved 0/6 → 5/6; the clause channel moved
nothing. The oracle overlay fires and tightens the check, but tightening a check the work already
fails changes no outcome — it only makes the same park slightly better-reasoned.

**DoD-1 is satisfied, trivially and honestly:** clauses must not move `false_ship`, and they moved
nothing at all — zero false ships in both arms (16/16 `honest_park`).

**The design implication is concrete.** A clause must reach the item's **acceptance text**, the way
the operator's answer to an intake ask does — resolution rewrites the acceptance through the
validated `enhance` path, and the Proctor pins tests to that text. Appending a prompt section is not
equivalent, and this measurement is the evidence.

## What this does not establish

n=4 treatment on two cases sharing one sentence, and a null is weaker than a positive at that size.
It says the clause channel did not reproduce a large, twice-reproduced effect — not that no clause
mechanism ever could. It says nothing about the semantic/ask-only class, which no clause can reach.

Also unchanged and still owed: the clause-resolution rate as the rubber-stamping metric (DoD-2), and
C4 before any effectiveness claim (DoD-3) — this run establishes engagement (C-level evidence that
the control fires), not effectiveness, because the effect was null.
