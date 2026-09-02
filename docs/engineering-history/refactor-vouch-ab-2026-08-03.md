# #60 vouch A/B + the wall's true anatomy — measured 2026-08-03

**No ADR** (experiment log). Pre-registered in the roadmap before the run.

## A/B result (n=40, claims-ON vs claims-OFF)

| | ON | OFF |
|---|---|---|
| MCB-14 | 10/10 honest_park (grader-passing) | 10/10 honest_park |
| MCB-05 | 5/5 false_ship | 5/5 false_ship |
| MCB-15 | 5/5 false_ship | 5/5 false_ship |

**Prediction "no leak" CONFIRMED** (05/15 byte-identical across arms). **Prediction "the wall
falls" REFUTED** — and the refutation was diagnosed to the exact conjunct within the hour,
because this time the instrumentation existed BEFORE the mystery:

## The diagnosis chain (instrumented, per-run)

1. Offline replay of the full chain on a live delivered workspace: claims SATISFIED, vouch
   ids produced, real gate_node delivers. Every component correct.
2. New self-explaining `vouch` meta field (the ADR-0078 lesson, applied preemptively):
   live runs show `structural_claims:task-c5,task-c14` — **the vouch FIRES in production.**
3. New `mutation_caught` meta field: **False** — a comprehensive-mutation survivor.

**The wall's complete anatomy:** oracle_verified = (tester ∨ standing-suite ∨ test-cmd ∨
NEW structural-vouch) ∧ mutation_ok ∧ structural_ok. #60's earlier diagnosis named the
disjunction legs; the vouch fixes those — and then `mutation_ok=False` ANDs it dead. The
seed suite (2 tests) provably cannot kill every mutant of the refactored `_validate` (e.g.
the bool-age branch no test exercises), and comprehensive mutation (ADR-0071) demands ALL
caught. The refusal is CORRECT under current doctrine ("a green suite is only an oracle if
it can fail").

## The decision this tees up (owner-level, NOT hotfixed)

For a DETECTED pure refactor with (a) a delta-proving structural claim satisfied and (b) the
scaffold's differential golden-master green, does a comprehensive-mutation survivor still
block delivery? Keeping the AND keeps MCB-14 honestly parked (with a fully-named reason
chain, visible in every scorecard now). Scoping mutation for vouched refactors is a gate-
semantics change — its own decision, red-team, and measurement. Queued for the owner.

## Red-team (vouch, oracle domain): DONE — 1 FIX-NOW, applied

R1 paraphrase-arming CLEAN (trusted task only, 1-arg call verified). R2 shape-without-
behavior CLEAN (validation_failed parks regardless). R3 mid-run claim minting CLEAN (no
writer). R4 do-nothing delivery CLEAN (empty diff ⇒ unevaluable). **FIX-NOW (round 2): the
preservation-claim loophole** — layout-style predicates are true BEFORE any work, so a
trivial touched delivery could satisfy one and vouch unfinished work (a NEW ship channel).
Fixed same day: vouching claims must be DELTA-PROVING (predicate false on the pre-change
tree); layout-style rows excluded from vouching (they still park when violated). Round 3
verify: the exclusion test + all guard fixtures green.
