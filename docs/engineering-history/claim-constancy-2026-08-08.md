# Why the failed-claim set never changes — and the second cause nobody was looking for

**Date:** 2026-08-08 · **Issue:** #84 ·
**Method:** re-derivation over the 24 MCB briefs + 2,055 stored scorecards. **No new runs, no model,
no Docker.**

[ADR-0090](../adr/ADR-0090-gate-reason-classification.md) measured that **19 of the 23 MCB cases
emitting `unsatisfied_claim` emit a byte-identical failed-claim id set on every run** and deferred the
cause as *"a separate finding about claim minting."*

There are **two** causes. The first is fully explained and is not a defect. The second was not
anticipated by the issue, is a real defect in a documented contract, and is the reason this writeup
exists.

---

## Cause 1 — the two-boolean collapse (within one engine version)

**Half 1: the id→kind partition is a pure function of the brief.** `bench/harness.py:263-273` mints
claims once at launch from `weave_criteria(case.brief, …)` — the **entire `brief.md`**, since a bench
case has no `acceptance` field and no brief carries an `## Acceptance` heading.
`claims_from_acceptance` is pure, ids are positional (`task-c{n}`), and **no graph node ever writes
`state["claims"]`**. Every run of a case therefore gets identical ids, texts and `oracle_kind`
assignments. This is correct and by design.

**Half 2: every behavioural claim reads ONE shared boolean.** `claim_oracles.py:235-277` —
`acceptance_test`, `validation_exit` and `wellformedness_parse` all resolve to `state["tests_passed"]`
**verbatim**, reading nothing else: not the workspace, not even the claim's own text.
`tests_unmodified` reads `state["tests_modified"]`. `ast_transformation_contract` is the only kind
that inspects the delivered tree.

So a case's failed set is drawn from a tiny fixed lattice: the behavioural ids (all or none) × the
tamper id (all or none) × whatever the structural claims independently decide.

### The corpus, re-derived from the briefs

| | cases |
|---|---|
| **no structural claims ⇒ failed set is driven purely by shared booleans** | **18 of 24** |
| carry `ast_transformation_contract` (the only per-claim oracle) | 6 — MCB-05, 13, 14, 15, 21, 22 |

Per case (`none` claims can never fail — they resolve `unbound`):

| case | claims | none | acceptance_test | wellformedness | tests_unmodified | ast |
|---|---|---|---|---|---|---|
| MCB-01 | 19 | 10 | 6 | 3 | – | – |
| MCB-02 | 19 | 8 | – | 11 | – | – |
| MCB-03 | 9 | 7 | 2 | – | – | – |
| MCB-04 | 9 | 4 | 4 | 1 | – | – |
| MCB-05 | 14 | 10 | 1 | – | – | **3** |
| MCB-06 | 13 | 11 | 2 | – | – | – |
| MCB-07 | 15 | 8 | 7 | – | – | – |
| MCB-08 | 11 | 9 | 2 | – | – | – |
| MCB-09 | 14 | 10 | 3 | – | 1 | – |
| MCB-10 | 10 | 6 | 4 | – | – | – |
| MCB-11 | 14 | 12 | 2 | – | – | – |
| MCB-12 | 18 | 10 | 8 | – | – | – |
| MCB-13 | 16 | 13 | 1 | – | – | **2** |
| MCB-14 | 17 | 10 | 4 | – | – | **3** |
| MCB-15 | 20 | 15 | 2 | – | – | **3** |
| MCB-16 | 10 | 8 | 1 | 1 | – | – |
| MCB-17 | 15 | 10 | 3 | 2 | – | – |
| MCB-18 | 19 | 17 | 2 | – | – | – |
| MCB-19 | 11 | 9 | 2 | – | – | – |
| MCB-20 | 9 | 5 | 4 | – | – | – |
| MCB-21 | 19 | 8 | 7 | 3 | – | **1** |
| MCB-22 | 21 | 5 | 13 | 2 | – | **1** |
| MCB-23 | 23 | 13 | 5 | 5 | – | – |
| MCB-26 | 16 | 15 | 1 | – | – | – |

### The prediction is exact, once stated correctly

A first pass predicted "the observed set == all bound ids" and matched 14 of 21 cases. **That
prediction was too crude, not the mechanism.** Refined — behavioural, integrity and structural claims
are three *independent* channels — every apparent mismatch resolves:

- **MCB-09** — observed `{c3, c8, c14}` = exactly its three `acceptance_test` ids; `c11`
  (`tests_unmodified`) absent because that run modified no tests. Two booleans, not one.
- **MCB-05** — two observed sets: `{c5, c7, c12}` (its three structural ids) and `{c9}` (its one
  behavioural id). Structural claims fail independently of `tests_passed`, exactly as designed.
- **MCB-06, 21, 22** — see Cause 2.

**No run's failed set contains a claim id whose kind could not have produced it.** Within one engine
version the mechanism accounts for every observation.

---

## Cause 2 — the claim id space is NOT stable across engine versions

Three cases cite ids that **cannot exist** under today's briefs:

| case | claims minted today | ids cited by stored cards |
|---|---|---|
| MCB-06 | 13 | `task-c16` |
| MCB-21 | 19 | up to `task-c34` |
| MCB-22 | 21 | up to `task-c37` |

The briefs did not change — MCB-06's `brief.md` has a single commit. **The splitter did.** Commit
`5bcae6e` (2026-08-03), *"sentence splitter survives markdown — the last over-veto class (#61)"*,
rewrote `_sentences`, and its own message records the effect: *"MCB-03: 16 claims → 9."*

The stored cards show it happening, on one afternoon, with no brief edit:

| case | last card before | max id | first card after | max id |
|---|---|---|---|---|
| MCB-21 | `20260803-140838` | `c34` | `20260803-202644` | `c17` |
| MCB-22 | `20260803-100249` | `c37` | `20260803-202955` | `c19` |

**`task-c24` denoted a different sentence before and after that commit.** Nothing on a scorecard, a
trend row or a baseline records which minting version produced its ids, so the drift is silent and
irreversible.

### What this breaks

`models_claims.py` documents `(item_id, claim_id)` as *"the cross-run key."* **It is not.** It is a
key only within one minting version, and the repo has already crossed at least one boundary. Any
longitudinal analysis keyed on claim ids across 2026-08-03 compares different sentences under the
same name.

Nothing consumes that key today — the only reader is `list_run_claims(run_id)`, single-run scope — so
this is a latent defect, not a live one. It becomes live the moment anyone builds the cross-run
analysis the docstring invites.

This is also a **concrete instance** of the missing corpus/version identity on the benchmark: the
suite trend stamps `engine_version` but nothing stamps what the run was *asked*, or how that ask was
parsed.

### Self-check: does this invalidate ADR-0090's measurement?

ADR-0090's 118-card split spans the boundary, so it had to be re-checked rather than assumed. Split
by the `5bcae6e` cutover:

| | n | grader passed |
|---|---|---|
| **pre-`5bcae6e`** · `uc ∧ validation_failed` | 13 | 10 (77%) |
| **pre-`5bcae6e`** · `uc ∧ ¬validation_failed` | 1 | 1 (100%) |
| **post-`5bcae6e`** · `uc ∧ validation_failed` | **50** | **44 (88%)** |
| **post-`5bcae6e`** · `uc ∧ ¬validation_failed` | **54** | **16 (30%)** |

**The conclusion holds and is stronger on single-version data** — 88% vs 30% over n=50/54, with the
pre-boundary cards a 14-of-118 minority whose `¬vf` bucket is n=1. ADR-0090's argument never depended
on id identity in any case (it partitions on gate reasons and grader outcome, not on which ids), but
that had to be demonstrated, not asserted.

---

## What this means for ADR-0090's MR2

`unsatisfied_claim` on a behavioural-only case is **`validation_failed` restated N times**, where N is
now computable per case from the brief alone. ADR-0090 inferred that from an 86% correlation; it is
now a **proof from the mechanism**, which is a strictly stronger basis for the admission matrix.

The uncomfortable corollary, stated plainly: **on 18 of 24 cases the ADR-0079 claims apparatus
contributes zero information to the gate.** Either behavioural claims acquire a genuine per-claim
oracle, or they stop emitting a gate reason when `validation_failed` is already present. MR2 chooses
the latter, and this analysis is why that is currently right. The successor — binding a behavioural
claim to specific grader assertions — is filed separately.

## Residuals, recorded and deliberately not fixed

1. **`_MARKUP` misfires on shell placeholders.** `<[a-z][a-z0-9]*>` matches `<id>`, `<term>`,
   `<args>`: **15 claims across 6 non-markup cases** classify as `wellformedness_parse`, plus
   "well-formed" in ordinary prose (MCB-16/17). **Harmless today** — that kind shares an oracle with
   `acceptance_test`. Tightening the regex now is precisely what [ADR-0085](../adr/ADR-0085-oracle-defect-detection-strategy.md)
   warns against (*"a photograph of a defect we already saw"*) for a defect with no consequence.
   **Recorded as a precondition on ever giving `wellformedness_parse` its own oracle**, which is when
   it would hand a shell command to an HTML parser.
2. **Materiality does not gate.** `failed_claim_ids` does not filter on `material` and
   `evaluate_claims` never reads it. An immaterial claim reaches the gate reason only-by-coincidence:
   every `material=False` return in `classify_sentence` happens to pair with `kind="none"`, enforced
   nowhere. **Measured 0 violations across all 24 briefs** — now pinned by a test.
3. **The bench feeds the whole brief**, title and premise prose included: MCB-01's `task-c1` is its
   title glued to the intro paragraph, and 10 of its 19 claims are `none`. Noisy but not wrong
   (`none` can never fail). Changing the input changes the claim corpus and therefore the measurement,
   with no corpus identity to make that visible — **blocked behind that instrumentation.**
4. **Nothing records the minting version.** Cause 2's root. The fix belongs with corpus identity on
   the scorecard, not here.

## Reproducing

```python
# Cause 1 — kinds per case, from the briefs alone
from mosaera_core.claims import claims_from_acceptance
claims_from_acceptance(None, Path("packages/core/mosaera_core/bench/cases/MCB-01/brief.md").read_text())

# Cause 2 — ids no current brief can mint
#   for each case: max(int(id.rsplit("-c")[1]) for id in card["meta"]["unsatisfied_claims"])
#   vs len(claims_from_acceptance(None, brief))
```

Stored cards: `.mosaera/benchmarks/<CASE>/<stamp>.json` → `meta.unsatisfied_claims`,
`meta.gate_reasons`, `meta.grader_passed`. Since ADR-0090 the cards also carry
`meta.unsatisfied_claim_kinds`, which makes the kind split a direct read instead of the
`validation_failed`-co-presence proxy used above.
