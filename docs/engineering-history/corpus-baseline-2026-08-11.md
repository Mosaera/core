# The rebuilt corpus baseline — 125 runs, one commit, five repeats (2026-08-11)

**Why this exists.** The previous corpus (~2,500 scorecards) was destroyed on 2026-08-10
([record](evidence-store-loss-2026-08-10.md)). Every figure derived from it became a written
assertion rather than something anyone could re-query. This is its replacement, and it is
**methodologically better**: the old corpus pooled runs across many code versions — a caveat that
sat on every number taken from it — where this is five runs of every case on a single commit.

> **⚠ CORPUS DISCONTINUITY — every figure below is 25-CASE.** Verb-arc slice 4 merged MCB-28 on
> 2026-08-11, and `available_cases()` globs the cases directory, so `--all` became **26 cases /
> 130 runs** from that commit onward. Corpus-wide rates (over-park %, clean-conclusion %,
> capability) computed after it are **not directly comparable** to anything here — the denominator
> and the case mix both changed. Per-case comparisons (`compare_arms.py --by-case`) are unaffected
> and remain the right instrument across the boundary.

## Method

| | |
|---|---|
| commit | `8522a3f` (staging, after slices 1 + 2.1, the escalation fix and ADR-0099) |
| command | `scripts/experiments/rebuild_corpus.py --repeat 5` |
| coverage | **125 cards = 25 cases x 5 runs**, none short |
| elapsed | 318 min + a 6 min resume for MCB-23 |
| escalation | **none** — `role_escalation` empty, so every run concludes at tier 0 |
| models | pm `qwen3.6:35b` · coder `qwen3-coder:30b` · reviewer/critic `gpt-oss:20b` |
| store | passed explicitly via `MOSAERA_HOME`, never inherited from cwd |

**Escalation was deliberately off.** The configured ladder pointed at a model that is not installed,
which is precisely the no-op condition the 2026-08-10 escalation fix exists to catch. Tier-0 is also
the honest measurement: on 2026-08-10 every wrong conclusion drawn that day was corrected by
re-running at tier 0.

## The baseline

| metric | value | prior corpus (recorded, unverifiable) |
|---|---|---|
| **over-park** (correct work refused) | **31%** — 39/125 | 34% |
| clean-conclusion | 94.4% | 91.7% |
| **false ships** | **0** | 1.4% |
| grader passed | 110/125 (88%) | — |
| avg capability | 90/100 | — |
| outcomes | 71 clean_deliver · 47 honest_park · 7 thrash_park | — |

**Sole-cause over-parks — 14 of 39.** Removing one reason would have shipped correct work:

```
oracle_unverified        9
claim_structural_failed  5
```

**Mutation verdict on the 39 over-parks:** `None` 25 · `False` 7 · `True` 7.

## What reproduces, and what does not

**The over-park finding reproduces** (31% vs 34%) and `oracle_unverified` remains the dominant sole
cause. Both survive the loss of the corpus that first produced them.

**Zero false ships in 125 runs** is the strongest result and the cleanest possible floor for the
mutation A/B below: against zero, any increase is unambiguous.

**Interim figures during the sweep were misleading and are recorded as a caution.** At n=32 the
clean-conclusion read 100% and at n=98 it read 98.0%; the final figure is **94.4%**, because cases
run in ID order and the harder ones are later. Roughly two-thirds of the apparent improvement over
the 91.7% baseline evaporated as the sweep completed. Capability drifted 93 -> 90 the same way.
**Nothing should be concluded from a partial sweep of an ordered corpus.**

## The trace this baseline enabled

`oracle_verified` is an OR over four independence routes, then ANDed with `mutation_ok` and
`structural_ok` (`graph/nodes_review.py`). One over-park is decisive: a run whose independence WAS
satisfied (a structural vouch) still parked, because `mutation_caught` was False. That isolates the
mutation check as a veto rather than the independence legs failing.

**But it is sized smaller than the trace suggests.** Only **7 of 39** over-parks carry a `False`
mutation verdict; **25 carry none at all**, meaning something else in the AND refused them and
nothing currently records which. See the sequence in [`../roadmap.md`](../roadmap.md).

### The attribution, and a hypothesis that died on contact with it

A first reading proposed that the 25 `mutation=None` over-parks were the prize: under
`sanctioned_test_edit` the mutation floor tightens to "vouch only on a proven catch", so `None`
parks the run — and the posture turns on `tester_repairs_tests`, making sanctioned edits common.
The code path is real. **The claim about which runs travel it was false**, and querying the corpus
before writing any code settled it:

| | |
|---|---|
| mutation=`None` over-parks | 25 |
| …of which carry `oracle_unverified` at all | **2** |
| …dominant reason set instead | `validation_failed` + `claim_behavioral_failed` (14 of 25) |

On those runs `None` is a **symptom of never reaching green** — no delivered code, nothing to
mutate — not a cause of refusal.

**What the data says instead.** The original trace was right. Of the 9 sole-cause
`oracle_unverified` over-parks, **6 carry mutation=`False`**. Corpus-wide the proven-`False` veto
fired **7 times: 7 parked, 7 grader-passed, 0 delivered, 0 true positives.** Every firing refused
correct work.

**The caveat that must travel with that number.** This corpus has **0 false ships**, so no veto
*could* have shown a true positive — there was nothing bad to catch. The veto's **cost** is
measured; its **benefit is unmeasured, not disproven**. That is the critic's 0/408 problem again,
and the reason this is an A/B rather than a deletion.

Note also what `mutation=False` means: the *code is correct* (the grader passed) and the *suite is
weak* (it failed to catch a mutation). Refusing to ship correct code behind an unconvincing suite is
a defensible policy, not a defect — the question the A/B answers is whether it is worth 18% of the
over-park rate.

**Recorded prediction, made before the sweep:** 6 of the 7 are sole-cause and would deliver; the
7th also carries `reviewer_conflict` and would still park. Over-park **39 → 33 (31% → 26%)**,
false_ship stays **0**. A sweep is still required, because a gate deny routes back to `plan` and
changes trajectories rather than being purely additive.

**The methodological point.** The cause had to be *inferred* from a co-recorded field, because
nothing recorded which term of the AND refused. That is why `oracle_legs` now exists
(`graph/_oracle_legs.py`): the verdict and the record of how it was reached come from one
evaluation, so the record cannot drift from the decision it describes.

**A caution about the `vouch` field.** `no_vouch:not_behavior_preserving` appears on 8 of the 9
sole-cause `oracle_unverified` runs and reads like a refusal reason. It is not — it explains only why
the *refactor-specific extra* vouch disjunct did not apply, which for a feature or robustness task is
correct. It says nothing about why the main path failed. That misreading cost an hour on 2026-08-10
and is exactly what the "which leg failed" recording in the roadmap sequence is for.

## Durability

The cards live in the (gitignored) evidence store, so this record is the durable form of the
numbers. A snapshot of the raw cards is archived at `~/mosaera-backups/corpus-2026-08-11.tar.gz`
(77 KB, 125 cards + settings). Re-derive any figure with
`scripts/experiments/audit_control_liveness.py` or the queries above.
