# The mutation gate does not discriminate — a partial sweep, stopped deliberately (2026-08-09)

**Status: DEFERRED, not abandoned.** The measurement was stopped at 58% by owner decision, on the
reasoning that later verb-arc slices are likely to produce the infrastructure that makes this
question cheaper to answer. This record exists so nothing has to be re-derived.

## How to re-read the data (the part that would otherwise be lost)

The 112 scorecards are durable under `<MOSAERA_HOME>/benchmarks/<CASE>/*.json`, mixed in with
~2,400 older cards. They are only distinguishable by an **mtime window**, so both ends are recorded
here:

| | |
|---|---|
| Repo commit under test | `4bcaa77` (staging) |
| Window start (unix) | `1786317156` = 2026-08-09 18:12:36 CDT |
| Window end | when the sweep was stopped, ~4.5 h later |
| Command | `MOSAERA_LAYER2_ADMIT_STRUCTURAL_CLAIM=1 mosaera-bench --all --repeat 8 --layer2` |
| Coverage | MCB-01…13 complete (8 repeats each), MCB-14 partial. **11 cases never ran.** |

Select with `p.stat().st_mtime > 1786317156`. Do **not** use the report tool's `--since`, which is
date-granular and cannot separate this sweep from the two earlier ones the same day — that filter
has misled this project three times.

The relevant card fields: `layer2_class`, `layer2_verdict`, `layer2_mutation_caught`,
`grader_mutation_caught`, `grader_passed`, `security_unavailable_reason`, `layer2_source`.

## What it measured

**112 runs · 25 honest parks · 13 eligible · 13 attempted · 0 converted · 0 false ships.**

### 1. The question it was launched for is still unanswered

Zero conversions, so the rule of three bounds the false-ship rate at nothing. This is the **third**
consecutive attempt to bound it and the third to come back empty. Continuing was unlikely to change
that: nothing converted in 108 runs, and eligibility was concentrated in a way that makes the
denominator unrepresentative anyway (see the caveat below).

### 2. The finding that did land: mutation survival does not distinguish a good test from a bad one

The grader probe (added this session) re-runs the **same** mutation check on the **same** changed
lines with the hidden acceptance suite — a human-authored answer key, written in advance by someone
who knew the correct solution — in place of the model's authored test.

| authored | grader | n | cases |
|---|---|---|---|
| **survived** | **survived** | **5** | MCB-03, MCB-05, MCB-08, MCB-13 |
| survived | no verdict | 2 | MCB-05 |
| no verdict | no verdict | 6 | MCB-05, MCB-06 |

**In every case where both checks produced a verdict, the human answer key survived exactly as the
model's test did. Zero cases where the grader caught what the authored test missed.**

The dominant Layer-2 refusal — *"the authored test does not catch a mutation of the change"* — has
been read as *"the model writes weak tests"*. On this evidence that reading is wrong. The gate's
second pillar (green + comprehensive mutation) is not separating rubber stamps from real oracles; it
is failing nearly everything, including work written by a human who knew the answer.

**Caveats, stated because the result is load-bearing:**
- n = 5 informative cells. Small.
- **Eligibility was badly concentrated: MCB-05 alone produced 8 of the 13 eligible parks.** Any
  *rate* derived from the 13 is unrepresentative. The parity finding survives this, because its 5
  cells span **four distinct cases** — checked specifically because the concentration was noticed.
- 6 of 13 attempts produced no verdict on **either** side. Even after F83 added arithmetic and
  constant operators, the oracle frequently still cannot form a question.

### 3. F84's measurement came back empty, and that is itself a result

**0 scanner failures in 112 runs**, against **17% (33/193)** in the 2026-08-09 morning sweep. The
earlier rate was transient or environmental, not a standing defect. F84's instrumentation is in
place and cost nothing; the hypothesis it was built to test did not reproduce. Recorded rather than
quietly dropped — a prediction that fails is evidence.

### 4. The eligibility widening (ADR-0094) worked as designed

**6 wrong deliveries reached the gate** — the WRONG column, empty across 193 prior runs, is now
populated — and **all 6 were refused**. That is necessary but not sufficient evidence of
discrimination: a mechanism that refuses everything scores identically, and with 0 conversions the
data remains consistent with exactly that.

## What is deferred, and why that is reasonable

**The mutation gate needs rethinking rather than tuning.** It is simultaneously Layer 2's second
pillar and verb-arc **slice 5**'s proposed oracle (diff-scoped mutation testing), which is why
slice 5 is blocked rather than merely unscheduled.

Deferring is defensible: slices 1–4 delivered four deterministic oracles that owe nothing to
mutation, and the remaining slices (6 comprehension apparatus, 7 project lifecycle, 8 doctrine) are
likely to produce reference-level and structural machinery that makes a mutation replacement cheaper
to design than it would be today. Designing that replacement now, on 5 data points, would be the
same premature move this session already made twice.

## Open, carried forward

- **The false-ship rate remains unbounded** after three attempts. Before a fourth, fix the
  denominator: eligibility concentrated in one case is not a corpus.
- **Is Layer 2 worth its complexity?** 13 eligible parks and 0 conversions in 112 runs, with
  eligibility dominated by a single case. Worth asking directly rather than continuing to tune.
- **Slice 5 is blocked** on the mutation question above.
- **Owed sandbox validation** for slices 1–4: item 88 + LedgerCLI item 4 (slice 1), MCB-27, MCB-28,
  and the corpus counts for slices 2.1 and 3. None of these depend on the mutation question.
