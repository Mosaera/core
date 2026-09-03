# #62 — the differential reaches the branch; the MCB-14 wall falls

**Date:** 2026-08-03 · **No ADR** (experiment log; the governing decision is the ADR-0071
amendment: *the AND stands, the evidence rises*).

## The root cause (my hypothesis was wrong; exploration corrected it pre-implementation)

Predicted: the survivor was the `isinstance(age, bool)` guard. **False, and impossible** —
`isinstance`, `not`, `and`/`or` and constants have NO mutator (the set is `return`→None,
first-`Compare`-op flip, bare-call→`pass`). The real survivor is a **noop mutant deleting the
shared `_validate(...)` call from `create_user`**. It survived because every input the suite
AND the differential generated was VALID: the module's limits are `0` and `150`, while
`_NUM_BOUNDARIES` had no negatives and topped out at `100`, with no string or type variants.
Delete the validation and nothing observable changes.

## The fix

Numeric literals mined from the module under refactor → off-by-one **triples** (`L-1, L, L+1`;
MCB-14 yields `-1, 149, 150, 151`), plus one **type-confusion** per arg per family (bool-in-int,
empty string, stringified number, `None`). Both ordered BEFORE the generic boundary flood so
the case cap cannot evict them; `_MAX_CASES` 24→48. Independent corroboration: the generated
killers are the same inputs the HIDDEN grader uses — two authors, same boundaries.

## Result (pre-registered; n=30, generator ON vs claims-OFF control)

| prediction | verdict |
|---|---|
| 1. `mutation_caught` flips False→True | **CONFIRMED — 20/20 True** (was False on 20/20 before) |
| 2. The wall falls; grader-passing work delivers | **CONFIRMED — MCB-14 20/20 `clean_deliver`** |
| 3. Zero new false ships | **CONFIRMED** (MCB-15 5/5 unchanged; MCB-05 moved toward parking) |
| 4. No new false parks | **CONFIRMED** |

Offline red/green pinned as a test: the golden oracle stays green on a correct refactor and
KILLS the deleted-validation mutant.

## Observations (recorded, not claimed)

- **MCB-05 moved in the SAFE direction**: 2 of 5 runs converted `false_ship` → `honest_park`.
  n=5, unpredicted, plausible mechanism (a richer input matrix catches behaviour changes the
  old one missed). Worth a powered re-measure; NOT counted as a result here.
- **The OFF arm also delivers** (`vouch: no_vouch:no_satisfied_structural_claim`): with the
  golden oracle strong enough, the standing-suite leg vouches on its own. The #60 structural
  vouch is the named voucher in the ON arm, but the *deeper* fix was the evidence, not the
  vouching rule — exactly the ADR-0071-amendment thesis.
- **Stage B (survivor-feedback re-author) is provably unnecessary** and is dropped. Author-time
  literal mining reached the branch without any feedback loop, mid-run re-authoring, or the
  three hazards it carried (re-freezing, tamper re-hashing, loop bounds).
- Half of a typical validation function remains unmutatable (no operator for `isinstance`,
  `not`, `and`/`or`, constants) — the survivor list is a PARTIAL map of the proof's holes, as
  ADR-0071's amendment already states.

## Disposition

`#62` CLOSED. `#60`'s wall is down with **no policy change**: the mutation AND stands
unmodified; a stricter differential made a strict gate satisfiable.
