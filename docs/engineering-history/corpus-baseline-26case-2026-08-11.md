# The 26-case baseline — 130 runs, post ADR-0100 (2026-08-11)

**The new reference point.** Not a comparison: the corpus gained a case (MCB-28) and the critic's
veto jurisdiction changed on the same day, so corpus-wide rates here are **not** directly comparable
to the [125-run 25-case baseline](corpus-baseline-2026-08-11.md). Where a comparison IS valid — the
same 25 cases, like for like — it is given below and it is **null**.

| | |
|---|---|
| commit | post-ADR-0100, slice 4 merged |
| coverage | **130 = 26 cases × 5** |
| elapsed | 319 min |
| config | tester = coder = `qwen3-coder:30b`; mutation veto ON (default); escalation ladder empty |

## The result

| metric | value |
|---|---|
| **critic vetoes** | **0** |
| **false ships** | **0** |
| delivered | 68/130 (52.3%) |
| over-park | 47/130 (36.2%) |
| clean-conclusion | 89.2% |
| capability | 90.1 |
| outcomes | 68 clean_deliver · 48 honest_park · 14 thrash_park |

## The critic fix: confirmed, and it is NOT inert

Zero vetoes is ambiguous on its own — it reads the same for *"the fix works"* and *"the control is
dead"*, which is the exact failure mode the liveness work exists to catch. The cards settle it
without needing a model probe:

```
critic_rows present on          90/130 runs   -> it RAN
REFUTED rows proposed              25         -> it JUDGED, and objected
discarded_refutations              22         -> quote-verification denied most
vetoes                              0         -> jurisdiction denied the rest
```

The critic is actively judging and proposing refutations; **none survive to a veto**. Three
refutations passed verification and were denied by the ADR-0100 jurisdiction rule alone — direct
evidence the narrowing fired, rather than an absence of firing.

**Statistically:** the prior rate was 7 vetoes in 250 runs, so ~3.6 were expected here. Zero has a
~2.7% chance under "nothing changed". Combined with the mechanism check above, the fix is confirmed.

## Like-for-like: over-park did NOT move

Restricting to the same 25 cases the old baseline used:

| | before | after |
|---|---|---|
| over-park | 31.2% (39/125) | **33.6% (42/125)** |
| clean-conclusion | 94.4% | 92.8% |

**+2.4pp against a standard error of 5.9pp — 0.41 SE. Not resolvable**, exactly as pre-registered
before the sweep ran. The critic fix was never expected to move this: its effect was ~5–9 runs
against a noise floor of ~15.

**The 26-case figure reads higher for an arithmetic reason, not a regression.** MCB-28 contributes
**5 over-parks in 5 runs** — it is a hard MODIFY case whose bottleneck is Proctor compliance, not the
gate. It also accounts for 5 of the 14 `thrash_park` runs.

**A prediction I got slightly wrong, recorded:** I forecast ~32–33% for the 26-case figure; it came
in at 36.2%. The direction and the mechanism were right, the point estimate was low.

## What this establishes

- **The critic no longer refuses correct work**, and is still live and judging.
- **Zero false ships in 130 runs** — the narrowing did not open a hole this corpus can detect.
- **Over-park is unchanged at ~33%.** The dominant cause is untouched and remains
  [over-strict authored tests](over-park-attribution-2026-08-11.md): `validation_failed` (25) and
  `claim_behavioral_failed` (22) still lead the over-park reason counts, with `oracle_unverified`
  down at 10.

## Over-park reason counts (n=47)

```
25  validation_failed          22  claim_behavioral_failed
17  reviewer_unknown           17  security_unverified
10  oracle_unverified           7  tests_tampered
 7  claim_structural_failed     6  reviewer_requested_changes
```

Archived: `~/mosaera-backups/corpus-26case-baseline-2026-08-11.tar.gz` (130 cards).
**This is the reference point for future sweeps.** Do not compare it to the 25-case figures.

> **⚠ SECOND DISCONTINUITY (2026-08-12, `research/over-park-reduction`):** the bench now runs
> under the ratified `structural.body_statements=5` clause by default (owner ratification;
> ledger P1). This corpus ran with NO clause — refactor-case rates (MCB-05/13/14/15) are not
> comparable across that boundary. The no-clause arm remains expressible via
> `MOSAERA_BENCH_CLAUSES=none`.
