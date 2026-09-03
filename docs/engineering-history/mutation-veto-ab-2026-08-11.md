# The mutation-veto A/B: a null result, and an experiment that could not have succeeded

**Status: COMPLETE. The default does NOT change — the veto stays ON.** 250 runs (125 per arm) on one
commit. The headline is not the verdict but the method failure behind it: **the effect under test
was smaller than the bench's noise floor, and that was computable before the sweep ran.**

## What was tested

`oracle_verified` ANDs a four-route independence OR with a mutation floor and a structural floor. On
the [125-run baseline](corpus-baseline-2026-08-11.md) the proven-`False` mutation veto fired **7
times: 7 parked, 7 grader-passed, 0 delivered, 0 true positives.** Every firing refused work the
hidden grader confirms was correct.

Arm B (`MOSAERA_ORACLE_MUTATION_VETOES=0`) removes exactly that veto. A sanctioned test edit still
demands a proven catch, so ADR-0087's backstop stands in both arms — the arms differ in one
behaviour, deliberately, so no result could be confounded with a weaker tamper posture.

| | arm A (veto ON) | arm B (veto OFF) | Δ |
|---|---|---|---|
| runs | 125 | 125 | |
| over-park | 39 (31.2%) | 38 (30.4%) | **−1** |
| **false ships** | **0** | **1** | +1 |
| clean-conclusion | 94.4% | 93.6% | −0.8pp |
| delivered | 71 | 75 | +4 |
| capability | 90.2 | 90.8 | +0.6 |
| mutation=`False` **delivered** | **0** | **8** | +8 |

## The experiment was underpowered, and provably so in advance

```
over-park  A=39/125  B=38/125   diff=-0.8pp   SE=5.8pp   => 0.14 standard errors
resolvable only above ~2 SE = 11.7pp = 15 runs
the direct effect under test was 7 runs = 5.6pp — BELOW the noise floor
```

Per-case movement went **both ways** — 8 cases worse in B, 9 better — which is the signature of
run-to-run variance, not a lever effect. MCB-27 moved 1→4 over-parks and MCB-13 moved 2→0, neither
for any reason connected to the mutation floor.

**This is the finding to carry.** Arm A had already told us the effect was ~7 runs. The binomial SE
at n=125 and p≈0.31 is 5.8pp. Anyone could have divided one by the other **before** spending 5.5
hours of GPU time. The A/B was not mis-run; it was mis-designed, and by the one arithmetic step that
would have shown it.

A paired design is the fix: re-run only the runs the veto actually refuses, or hold seeds fixed
across arms. An unpaired 125-vs-125 comparison cannot see a 7-run effect and never could.

## What IS established

**The direct effect, which needs no statistics.** The veto is deterministic given
`mutation_caught=False`: 0 such runs delivered in arm A, **8 delivered in arm B, and all 8 were
grader-passing.** So the veto's *cost* is real and measured — it refuses correct work every time it
fires. The aggregate metric simply cannot see a cost that small.

**The false ship is not attributable to the lever.** `bench-MCB-12-…-4a08e3` (hard tier,
`gate_reasons=[]`) carried **`mutation_caught=True`** — the suite caught a mutation and still missed
the real defect. The veto could not have prevented it; arm A would have shipped it too. That is the
executed-but-unasserted class the comprehensive-mutation knob targets, not the mutation floor.

It is recorded as a **failed prediction anyway.** The pre-registered rule said "false ships must stay
at 0", it did not, and the rule was fixed in code precisely so it could not be renegotiated after
the fact. Both the rule *and* the null over-park result point the same way: **do not flip the
default.**

**ADR-0087's backstop is load-bearing, not defensive.** Sanctioned test edits fire on **21 of 125**
runs (17%) — an earlier n=5 read that said "never" was wrong. Six arm-B runs still park on mutation,
all `sanctioned=True, mutation_raw=None`: the branch doing exactly its job. **All 6 are over-parks**,
which is a separate finding and unexamined.

## The decision

**Keep `oracle_mutation_vetoes` defaulting to True.** The knob stays as the documented lever with a
recorded measurement; removing it would discard the ability to re-run this cheaply. No ADR is owed,
because no durable decision changed — an ADR becomes owed only if the default flips.

The veto's **benefit remains unmeasured, not disproven.** A corpus with 0 false ships cannot
demonstrate a true positive for any veto — the critic's 0/408 problem, one more time. Given a
measured cost of ~5.6% over-park against an unmeasured benefit, leaving a safety control ON is the
correct posture under uncertainty.
