# The first measured context change (2026-08-20)

**Question:** does giving Quincy the truth already recorded — claim-ledger verdicts, acceptance
text, map observations, ratified decisions, the unread authoring doctrine — change what he answers?

No agent prompt or context change in this repo had ever been measured. QMB now makes it possible.

## Design

A **code** A/B, not a model A/B: one model (`gpt-oss:20b`), one suite (11 QMB cases), 5 passes each,
paired on `(case, dimension, pass)`. The BEFORE arm reverts exactly three files —
`pm_sections.py`, `pm_context_builder.py`, `pm_turn.py` — to their state before the change, leaving
the suite, harness and scorer identical. Confirmed inert before running: zero verdict markers and no
acceptance text in the assembled context.

**Pre-registered in the plan, before the run:** *"Expect movement in `grounded` and `honest`; `safe`
and `complete` are the controls that should not move, and if they do, the change did something
unintended."*

## Result — 154 paired trials

| dimension | AFTER | BEFORE | p | |
|---|---|---|---|---|
| **grounded** | **7** | 0 | **0.016** | predicted mover |
| **honest** | **5** | 0 | 0.062 | predicted mover |
| safe (primary) | 2 | 2 | 1.000 | control — did not move |
| complete | 3 | 3 | 1.000 | control — did not move |
| consistent | 1 | 1 | 1.000 | control — did not move |
| pooled | 18 | 6 | 0.023 | leans agree, so pooling is valid here |

**The prediction holds exactly.** Both predicted dimensions moved, every win to AFTER with zero to
BEFORE, and all three controls sat still. A change that had leaked into `safe` or `complete` would
have been doing something unintended.

## What the numbers do NOT support

- **`honest` cannot reach significance at this n.** 5-0 is the most extreme result possible with
  five discordant trials, and its exact p is 0.0625. The case is power-limited, not weak: six
  discordant trials at 6-0 would give 0.031. Report it as a clean sweep that the sample size cannot
  certify, never as "not significant".
- **`grounded` clears α=0.05 but not a Bonferroni bar** across five dimensions (0.010). It was
  *pre-registered* as an expected mover, which is what makes it a confirmatory test at full α rather
  than the best of five exploratory ones — but that reading depends entirely on the prediction
  having been written first, which is why it was.
- **No claim about the primary.** `safe` did not move, so under QMB's model-ranking pre-registration
  there is no winner. That rule exists for choosing a model; this experiment asked a different,
  pre-registered question.

## The caveat that matters most

**Ten of the twelve AFTER wins come from QMB-10 and QMB-11 — cases I wrote to detect a change I
made.** They swept 5-0 each, which is what a case built for a capability does when the capability
arrives. That is close to circular and should be weighed as such.

The independent signal is **QMB-09 grounded, +2 to AFTER**: a pre-existing case, written before this
work, that improved. It is two trials. It is not nothing, and it is not much.

A fair reading: the change does what it was built to do, demonstrated mostly by instruments built
alongside it, with a small amount of independent corroboration. The way to strengthen it is
grounding cases written by someone who is not the author of the change.

## Cost

125s and 136s per arm — about five minutes total, against ~50 minutes for the paired model
comparison. The cheap check answered the question it was asked.
