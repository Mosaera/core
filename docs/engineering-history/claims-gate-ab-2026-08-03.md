# Claims-gate A/B — the first fingerprint-validated experiment (Wave 2, ADR-0079/0081)

**Date:** 2026-08-03 · **No ADR** (experiment log). Pre-registered in `docs/roadmap.md` before
the run; executed overnight on merged `main` (!315), local `qwen3-coder:30b`, cloud egress off.

## Design (fixed before the run)

Arms: claims ON (default) vs OFF (`MOSAERA_BENCH_CLAIMS_OFF=1`), interleaved per repetition.
n=10/arm × {MCB-13, 14, 21, 22 (new catch surface), MCB-05, 15 (predicted null)};
n=5/arm × {MCB-03, 06} (behavioral controls). 140 runs total (137 completed; 3 MCB-22 reps
lost to timeouts, logged).

## Step 1 — validation BEFORE effectiveness (ADR-0081, first use in anger)

`liveness.experiment_verdict` over per-run fingerprints:

| case | verdict | divergent pairs |
|---|---|---|
| MCB-13 | VALID | 43/100 |
| **MCB-14** | **INVALID_EXPERIMENT_IDENTICAL_EXECUTION** | **0/100** |
| MCB-21 | VALID | 82/100 |
| MCB-22 | VALID | 54/56 |
| MCB-05 | VALID | 26/100 |
| MCB-15 | VALID | 20/100 |
| MCB-03 | VALID | 5/25 |
| MCB-06 | VALID | 18/25 |

**The ladder worked on first use:** MCB-14's arms ran identical paths — every run in both arms
parks at the same pre-existing `oracle_unverified` wall (below), so the case carries NO signal
about claims and its A/B is refused a score instead of contributing convincing noise. This is
the exact failure mode (instance #4) that drove ADR-0081, caught automatically this time.

## Step 2 — the three pre-registered predictions

**P1 — "wrong shapes park; zero claims-caused false parks": SAFETY CONFIRMED, EFFECTIVENESS
NOT EXERCISED.** Claims-caused false parks: **0 of 140** — every `unsatisfied_claim` co-fired
with `validation_failed` (per-park attribution); the new gate input never blocked shippable
work. But the catch half is **vacuous on this sample**: MCB-13/21/22 produced **zero
wrong-shape deliveries in EITHER arm** (false_ship 0/55 across all six arms) — the model
either delivers the correct shape or fails validation outright, so there was nothing for the
new predicates to catch. The catch surface exists (unit-proven, seed-fails/ref-passes) but the
live conversion claim remains unmeasured until a wrong-shape ship actually occurs.

**P2 — "MCB-05/15 still null": CONFIRMED.** MCB-05 ON 9/10 vs OFF 8/10 false_ship (Fisher
p=1.0); MCB-15 ON 8/10 vs OFF 10/10 (p=0.474). The two-rulers diagnosis stands: the graders
assert absolute constants (≤6/≤7) the predicate deliberately doesn't. Single-binding (grader
alignment or Wave-3 authored predicates) is the named lever; owner decision pending.

**P3 — "behavioral controls unchanged": CONFIRMED** (MCB-03 5/5 clean ON vs 4/5 OFF; MCB-06
differences are critic-driven, present in the OFF arm — not claims).

## The finding that outranks the experiment: the critic is a net false-park machine

Across the sweep window: **12 vetoes of grader-PASSING work vs 5 true catches** — precision
~29%. The held-out critic (ADR-0065) is currently the single largest *avoidable* source of
false parks (it hit MCB-03/06/13/21/22 and 15 alike), invisible until ADR-0078 made vetoes
observable and this sweep gave them ground truth. Prior measurement ("no over-veto", n=6 on
two cases) was under-powered. **Recommendation: a tracked issue for critic calibration** —
the REFUTED/SUPPORTED/INSUFFICIENT_EVIDENCE protocol (external research 2026-08-02) with the
veto threshold calibrated on this new labeled corpus.

## The second discovered defect: MCB-14's vouching wall

**20/20 runs, both arms: grader-correct work refused, `oracle_unverified` every time.** The
independence conjunction (`tester_vouched OR standing-suite OR test_cmd`) never vouches on
this case, so correct deliveries can never ship. Pre-existing, unrelated to Wave 2, now fully
attributed. **Recommendation: a tracked issue** (why does no vouching path fire on MCB-14's
shape of work?).

## The honest overall picture this suite now shows

False-shipping is **confined to the two-rulers cases** (05/15) — every other false_ship count
in the sweep is zero. The dominant defect class on the local tier is now **over-parking of
correct work** (MCB-14's wall, the critic's over-vetoes) — Gate 1 territory, not Gate 2. The
instrumentation arc (0078 → 0081 → per-claim attribution) is what made this visible: every
park in 140 runs explains itself.

## Dispositions

- Wave-2 claims gate: **stays active** — measured harmless (0 claims-caused false parks/140),
  catch surface armed but unexercised; C5 proven (unsatisfied-claim ids observed live in
  scorecard meta on MCB-21/22 runs).
- MCB-14 vouching wall → new tracked issue. Critic calibration → new tracked issue.
- Grader alignment (05/15) → owner decision, data banked.
- 3 lost MCB-22 reps: timeouts under memory pressure (a 13GB VM shared the box); disclosed,
  arms remain balanced (7 vs 8).
