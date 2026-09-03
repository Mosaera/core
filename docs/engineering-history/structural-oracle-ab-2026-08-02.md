# Structural-spec oracle A/B — the false-park widening that became a replication failure

**Date:** 2026-08-02 · **No ADR** (experiment log). Relates to
[ADR-0072](../adr/ADR-0072-structural-spec-oracle.md) and its relative-measure successor.

## What was asked

The successor's recorded open item: *widen the false-park measurement before tightening the 2/3
ratio*. The activation record rested on n=3/arm.

## Design (fixed before the run)

- **Arms:** the existing `MOSAERA_BENCH_STRUCTURAL_SPEC_OFF` lever — ON = the shipped posture
  (oracle active), OFF = oracle disabled. Nothing else varies; the heuristic was frozen for the
  whole sweep.
- **Cases:** MCB-05 and MCB-15 — proven statically to be the oracle's **entire** engagement
  surface (a zero-model-call sweep of all 24 briefs through `extract_structural_constraints`
  found exactly these two; pinned by `test_structural_spec_blast_radius_is_bounded`).
- **n = 25 per case per arm** (100 runs), arms **interleaved per repetition** so machine load,
  model warmth, and drift hit both arms equally.
- **Model:** local `qwen3-coder:30b`; cloud escalation force-disabled
  (`MOSAERA_MODEL_ESCALATION=false MOSAERA_ALLOW_CLOUD_EGRESS=false`).
- **Metrics:** per-run frozen `outcome` × hidden-grader ground truth (`MOSAERA_LAYER2_LOG`
  JSONL). A **false park** = a park outcome with `grader_passed=true`.

## Results

| arm | n | false_ship | 95% CI | false_park | other |
|---|---|---|---|---|---|
| MCB-05 ON  | 25 | 21 (84%)  | 0.65–0.94 | 0 | 4 honest_park |
| MCB-05 OFF | 25 | 23 (92%)  | 0.75–0.98 | 0 | 2 honest_park |
| MCB-15 ON  | 25 | 25 (100%) | 0.87–1.00 | 0 | — |
| MCB-15 OFF | 25 | 24 (96%)  | 0.80–0.99 | 0 | 1 clean_deliver |

Fisher exact (two-sided): MCB-05 **p = 0.667** · MCB-15 **p = 1.0** · pooled **p = 1.0**.

## Findings

1. **The conversion did not replicate.** The activation's n=3 result (MCB-05 3/3 false_ship →
   3/3 honest_park) is contradicted at n=25: the ON arm false-ships 84% of the time. The n=3
   effect was sampling noise. **The posture activation is withdrawn** (same-day) — the knob,
   the pure check, and the bench lever remain for re-test.
2. **The safety half held.** 0 false parks in 100 runs, both arms — the oracle never rejected
   grader-passing work. 95% upper bound ≈ 3% (rule of three). This supersedes the earlier
   "0 false-parks across 20 references" static bound with a measured dynamic one.
3. **Ambient false-ship is much worse than the historical figure.** MCB-15 false-ships 96–100%
   in *both* arms (MCB-05: 84–92%) vs the 52.7% (48/91) historical MCB-05 record. These two
   refactor cases appear to be essentially beyond `qwen3-coder:30b` regardless of gating —
   a model-capacity observation, not an oracle one. Relevant to the model-tier product story;
   a paid strong-model arm was considered and deferred (measure the real product once claims
   are first-class).

## Companion finding (same day): the `honest_stop_no_signal` measurement was void

The ADR-0077 decision-6 hold ("no conversion, Reliability 67 vs 83, +22% tokens" on MCB-26) is
**not a measurement**. The knob's only behavioural read is in `_no_signal_path`
(`graph/convergence.py`), reachable only when the validator yields no countable result — and #81
made SQL countable, so post-#81 MCB-26 always takes the counted path. The ON-arm's distinctive
reason string (`"no convergence (no countable result)"`) appears in **0 of 1,233 scorecards,
ever**. ON and OFF ran byte-identical code; the numbers were run-to-run noise. The hold stands,
but for the corrected reason: **not measurable on the current suite** (MCB-02, the obvious
uncountable case, stalls in 1 of 76 runs — on a different path). Measuring it needs a case
engineered to fail identically-and-repeatedly against an uncountable validator.

This is the fourth instance of the *control-that-cannot-fire* pattern (after `reviewer_advisory`,
the never-run ADR-0071/0072 measurement, and the empty-by-construction `gate_reasons`) — the
motivating evidence for a control-liveness ladder (ADR proposal pending).

## Disposition

- Activation **WITHDRAWN** (`config/_posture.py`); tripwire test updated (`test_oracle_posture.py`).
- Roadmap corrected: the activation entry, the ADR-0077 hold rationale, and the stale
  staleness-audit line.
- The oracle code is retained untouched. Re-measure after the claim-contract arc gives the check
  a stated contract to score against, and/or on a stronger model tier.
