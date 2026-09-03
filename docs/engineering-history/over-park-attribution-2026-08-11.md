# Why the system refuses correct work: the run's own tests are wrong (2026-08-11)

**Status: ATTRIBUTED.** ~30% of runs refuse work the hidden grader confirms was correct. This names
the cause, after two wrong answers. It also records that the mechanism was **already documented in
[ADR-0062](../adr/ADR-0062-proctor-faithfulness-detector.md) on 2026-07-19** — this is a
re-measurement at scale, not a discovery.

## The attribution

From arm B of the [mutation-veto A/B](mutation-veto-ab-2026-08-11.md) — the only corpus carrying
per-leg gate records (`oracle_legs`, shipped the same day).

| over-park cause (n=38) | count |
|---|---|
| **the run's OWN tests failed while the grader passed** | **26** |
| `critic_vetoed` (sole reason) | 5 |
| `claim_structural_failed` (sole reason) | 4 |
| `oracle_unverified` | 3 |

The dominant reason set is one cluster, 16 of 38: `validation_failed` + `claim_behavioral_failed` +
`reviewer_unknown` + `security_unverified`.

## The causal link — provable, not inferred

`overstrict_vs_ref` runs the run's **own authored tests** against the case's known-good
`reference/` solution. The reference is correct by construction, so a failure proves the *test* is
wrong, not the code. This is ADR-0062's instrument, and it is decisive:

| population | share with ≥1 reference-failing test | mean per run |
|---|---|---|
| `validation_failed` over-parks | **16 of 16 — 100%** | 2.94 |
| all over-parks | 20 of 26 measurable — 77% | **3.77** |
| everything else | 23 of 78 — 29% | 1.12 |

**The run authors an acceptance test that its own correct implementation cannot pass, fails it, and
parks honestly.** The honesty machinery is working exactly as designed. The input to it is wrong.

## Two hypotheses that died first, recorded so they are not retried

1. **"mutation=`None` under a sanctioned test edit parks the run."** The code path is real. But only
   **2 of the 25** `None` over-parks carry `oracle_unverified` at all; the rest never reached green,
   so `None` was a symptom of no delivered code, not a cause of refusal.
2. **"6 arm-B runs park on the ADR-0087 absence backstop."** They carry
   `oracle_legs.blocked_by=['mutation']`, which reads like the answer. Their **`gate_reasons` never
   mention the oracle** — all six are `validation_failed` runs where the mutation check never ran
   because tests never passed. The oracle leg was a downstream artifact of the real failure.

Both were caught by querying the corpus before writing code. **Both were the same error**: reading a
field that co-occurs with the refusal as though it caused it. That error is what `oracle_legs`
exists to end, and it was still made twice on the day the field shipped — the second time using the
new field itself.

**The oracle arc was a sideshow.** It explains 3 of 38 over-parks and consumed two full sweeps.

## `overstrict_static` is nearly silent, and should be said plainly

ADR-0062 shipped a deterministic AST detector for over-strict assertions. Measured across 250 runs:

| | reads > 0 |
|---|---|
| `overstrict_static` (the detector) | 4 of 250 |
| `overstrict_vs_ref` (ground truth) | 43 of 209 measurable |

Recall is roughly **11%**. The detector is not wrong — it is conservative by design and silent when
unsure — but it is not a usable signal, and anything relying on it is relying on nothing. Recorded,
not rebuilt: ADR-0062 deliberately chose a one-sided detector over a lossy one.

## What may NOT be built

ADR-0062 built deterministic **auto-loosening**, red-teamed it, and **reverted it wholesale**:
distinguishing incidental from semantic whitespace is not decidable, and a loosened assertion is a
*widened acceptance class* that reopens false-ship. The STOP rule was tripped.

**Any "safer normalization" is the same defect with a new variant number.** This repo has now
measured re-derivation of documented prior art three times (F58, F62, and the pattern above).

## The lever being tested instead

ADR-0062's own untried recommendation (MR-D): **route the TESTER role to a stronger model** —
configuration, not an engine change, chosen that way to preserve *Model Substitutability*. The
condition it targets is live: `tester_model == coder_model == qwen3-coder:30b`. ADR-0062's diagnosis
is that a shared model makes coder and Proctor coincide on the incidental choice, which hides the
fragility rather than removing it.

Measurement in progress: an **enriched, case-paired** probe over the 6 cases where over-strictness
recurs (MCB-06/13/17/18/21/22), 30 runs, `MOSAERA_MODEL_TESTER=qwen3.6:35b`, against 10 control runs
per case. Power was computed **before** running: with per-case means of 1–11, a ≥50% reduction is
resolvable and a 10% one is not — pre-registered so a small result reads as *underpowered*, never as
*no effect*. (The mutation A/B earned that discipline by spending 5.5 GPU-hours on an effect half
its noise floor.)

## Next lead, not chased here

**5 sole-cause `critic_vetoed` over-parks.** The held-out critic was positive-controlled on
2026-08-10 and proved able to veto a known-bad delivery and ship a known-good one. It is now the sole
reason 5 correct deliveries were refused. Alive is not the same as calibrated.
