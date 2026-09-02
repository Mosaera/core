# An unbound criterion became a non-converging reviewer veto (MCB-01, 2026-08-24)

**One line:** a ratified standing decision was rendered into briefs that had not asked for it; it
bound no oracle, so no deterministic check could ever mark it satisfied, but the reviewer enforced
it as a requirement — and `reviewer_requested_changes` can never ship.

## How it surfaced

A 0.6.3 candidate sweep was started to produce the benchmark snapshot the versioning runbook
requires before a bump. Partway through, tokens per run were **+19%** against the 2026-08-10 store
sweep on the same 11 cases. The rise was not spread across the corpus:

| | old 08-10 | new 08-24 |
|---|---|---|
| delivered runs | 363,227 tok | 343,445 tok |
| **parked runs** | 564,284 tok | **1,021,790 tok** |
| model calls, parked | 50 | **82** |

Delivering got slightly *cheaper*. Parking got 81% more expensive. **MCB-01 alone accounted for
roughly two thirds of the total increase** (5.46M → 8.58M tokens), going from **3-of-5 delivering to
0-of-5**, every one flagged `over_park` — the delivered tree passes the hidden grader.

## The mechanism

Every MCB-01 run carried an acceptance criterion its brief never contained:

```
- a function body is at most 5 statements (standing decision cl-a64637784074)
```

MCB-01 is *"build a command-line todo manager"*. It says nothing about function length,
orchestrators or delegation. The reviewer transcript is the model hand-counting statements:

> *"Thus the change fails acceptance criteria due to function body size rule. So verdict
> REQUEST_CHANGES."*

It objected to `load_tasks()` (6 statements) and `_find_and_mark_done()` (6). The coder could not
win — refactor one and another crosses the line. Three review cycles, two re-plans, give up. The
scorecard's own Governance line: *"refused to ship work that actually passes (over-conservative)."*

**Why it could never resolve.** The clause bound no oracle on this brief — the claim rendered
`task-c20 [ENTAILED → none]`, and the scorecard reported `clauses_applied: []`, i.e. *the clause
never fired*. Nothing deterministic could confirm satisfaction, so the only judge was the reviewer
LLM, whose verdict has no termination condition. `reviewer_requested_changes` is an `objection` in
`gate.py` and is never shippable. The run was therefore structurally unable to conclude.

## Root cause: two functions disagreeing about relevance

- `apply_to_constraints` (`clauses.py`) **was careful** — it binds a number only where the brief left
  that parameter open, and returns `None` when the brief states no structural shape at all.
- `weave_criteria` (`clauses.py`) **was not** — it appended the clause sentence to every brief
  unconditionally.

The registered-parameter limit in ADR-0082 §4 polices what a clause may *bind*. It says nothing
about where the rendered sentence may *appear*, and the agents read the prose.

## The clause itself was sound

`b5812d17` (2026-08-12) made `structural.body_statements=5` the bench default on real evidence, and
this same sweep confirms it where it belongs:

| capability | delivery, old → new |
|---|---|
| **refactor** (MCB-05) | 0% → **80%** |
| **robustness** (MCB-06) | 40% → **80%** |
| feature | 87% → 93% |
| bug-fix | 85% → 80% |
| **greenfield** (MCB-01/02) | 40% → **30%** |

The defect was never the value. It was the blast radius.

## Fix

Weave a clause only where it actually binds, reusing the `extract_structural_constraints →
apply_to_constraints → applied_marks` chain the claim oracle already used to decide whether a clause
*engaged*. Verified across all 26 cases: woven on **MCB-05 and MCB-15** only — exactly the two the
owner ratified it for. See the ADR-0082 amendment (2026-08-24).

## What this cost, and what caught it

~4 hours of GPU on a sweep whose results are stale for 24 of 26 cases, plus the reviewer loops
themselves. It was found by asking why token count had *risen* when the expectation was a fall —
i.e. by checking a number nobody had published before. The 0.6.2 CHANGELOG table has no cost row;
the figures existed in the scorecards all along.

**A warning existed and was not read.** `bench/_clauses.py` already said sweeps from that commit
*"are not comparable to the 130-run 26-case baseline on refactor cases"*. It understated its own
scope — the divergence was corpus-wide, not refactor-only — but it named the hazard, and the sweep
was launched anyway. That is the same prior-art failure mode recorded for F62 and F58.

## Defect class

A new instance worth naming beside the existing six: **the unfalsifiable criterion**. A requirement
enters the contract through a channel that carries prose to a model, while the deterministic checks
that would adjudicate it are not engaged. It cannot be satisfied, cannot be measured, and cannot be
appealed — and the run's own record shows the control as *not fired* the whole time it is vetoing.

The detector is cheap and general: **a criterion the gate can block on must have an oracle that can
clear it.** Where the two disagree, the record already knows — `clauses_applied: []` beside a veto on
that clause was the tell, sitting in the scorecard.
