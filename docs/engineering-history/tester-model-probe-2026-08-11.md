# ADR-0062 MR-D measured: a stronger tester model does NOT fix over-strict tests

**Status: REFUTED. The config does not ship.** 30 runs, enriched design,
`MOSAERA_MODEL_TESTER=qwen3.6:35b` against `qwen3-coder:30b` (which is also the coder). This is
MR-D's first measurement in the ~4 weeks since ADR-0062 named it, and the answer is no.

## What was tested

[The attribution](over-park-attribution-2026-08-11.md) found the dominant over-park cause: **26 of
38 over-parks are runs whose own tests failed while the hidden grader passed**, and 16/16 of those
authored ≥1 test the case's correct `reference/` solution fails.
[ADR-0062](../adr/ADR-0062-proctor-faithfulness-detector.md) diagnosed that mechanism a month
earlier, red-teamed and **reverted** the obvious fix (auto-loosening reopened false-ship), and named
an untried lever — **MR-D: route the TESTER role to a stronger model**, on the reasoning that a
shared coder/Proctor model coincides on the incidental choice and hides the fragility.

Enriched, case-paired: the 6 cases where over-strictness recurs, 5 runs each, against 10 control
runs per case (both mutation-veto arms pooled — they measured null against each other).

## The result

Primary metric — mean `overstrict_vs_ref`, tests a **known-correct** solution fails:

| case | control | probe | change |
|---|---|---|---|
| MCB-06 | 5.20 | 1.80 | **−65%** |
| MCB-13 | 1.00 | 1.00 | +0% |
| MCB-17 | 2.10 | 1.00 | **−52%** |
| MCB-18 | 10.78 | 5.20 | **−52%** |
| MCB-21 | 6.90 | 6.40 | −7% |
| MCB-22 | 5.60 | **17.00** | **+204%** |
| **POOLED** | **5.17** | **5.40** | **+4%** |

**+4% is nothing** — the measured null-control floor is +21%. The pre-registered condition was a
**≥50% reduction**; it failed outright.

Secondary metrics, none supporting the change:

| | control (n=60) | probe (n=30) |
|---|---|---|
| delivered | 55.0% | **40.0%** |
| over-park | 38.3% | **56.7%** |
| capability | 91.0 | 88.8 |
| **false ships** | **0** | **0** |

The delivery and over-park moves are ~1.7 standard errors — suggestive, not conclusive, and
**halved n** on the probe side. What is conclusive is the absence of any benefit.

## The finding is the heterogeneity, not the average

Four cases improved substantially (−52% to −65%). One was already at the floor. **One got three
times worse**, and not through one outlier: MCB-22's probe runs read `[21, 8, 17, 26, 13]` against
a control of `[9, 5, 1, 7, 3, 1, 7, 2, 15, 6]`. On that case the larger model authors *far more*
over-strict tests, and its deliveries fell from 5/10 to 1/5.

So "a stronger model is a better Proctor" is **false as a general claim**. It is true on most cases
and badly false on at least one, and the average cancels. A lever that helps four tasks and wrecks
a fifth is not a fix — and shipping it on the pooled number would have been shipping a coin-flip.

**This is why the tail matters, demonstrated for the third time in one day.** At 20 of 30 runs the
pooled figure read **−51%** and was reported as encouraging. The final case moved it to **+4%**.
The two earlier instances: a sweep reading 100% clean-conclusion at n=32 against 94.4% final, and
26.4% over-park at n=110 against 30.4% final. Partial reads of an ordered corpus have now been
wrong every single time they were taken.

## Unmeasured confound, stated rather than papered over

`overstrict_vs_ref` is a **count**, not a rate. A model that authors more tests has more chances to
be over-strict, so part of MCB-22's +204% could be "wrote many more tests" rather than "wrote worse
tests". The cards do not record an authored-test count (`layer2_authored` is empty on every run),
so this **cannot be separated from the stored evidence** and is not claimed either way.

Fixing that is cheap and worth doing before any further Proctor experiment: record the authored
suite size, and the metric becomes a rate.

## Disposition

- **Do not ship** `MOSAERA_MODEL_TESTER=qwen3.6:35b`. The default stays `qwen3-coder:30b`.
- **MR-D is refuted as a general lever** and recorded as such in ADR-0062, which had a hypothesis
  and no measurement. A null is exactly what that record was missing.
- **The mechanism is untouched.** Over-strict authored tests remain the dominant over-park cause;
  what is now known is that swapping the authoring model does not fix it.
- **Auto-loosening remains forbidden** (ADR-0062, red-teamed and reverted). The remaining named
  lever is ADR-0061's held-out critic — which the same corpus shows is *itself* now the sole cause
  of 5 over-parks, so it needs calibration before it can be leaned on.
- Corpus archived: `~/mosaera-backups/corpus-tester-probe-2026-08-11.tar.gz` (30 cards).
