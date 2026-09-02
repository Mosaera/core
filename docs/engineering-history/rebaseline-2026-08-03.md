# Full-suite rebaseline — 2026-08-03 (24 cases × 3, pre-registered)

**What this is.** The like-for-like reliability baseline that retires the stale
`rebaseline_80on_x3` headline (94.4% clean-conclusion / `false_ship` 0). That figure was not a
control: it recorded `false_ship` 0 while MCB-05's own record was ~53–68% false-ship, and 21 of
24 cases had not run since 2026-07-23 — pre-critic-activation, pre-Wave-2/3, pre-#60/#62. The
five predictions below were **pre-registered in `docs/roadmap.md` before the sweep launched**
(2026-08-03 18:21) and are scored verbatim.

**Measurement isolation.** 72 runs (24 cases × 3 passes) from a detached worktree pinned at
`405ded5` (`~/.mosaera-bench-wt`, its own venv) so branch switches in the main checkout could not
change the code under measurement mid-sweep; escalation OFF, cloud egress OFF. The sweep survived
one host-shell crash at 19/72 and one relaunch (resumable-by-design done-log); scorecards land in
`.mosaera/benchmarks/MCB-*/`, stamps `20260803-1821…20260804-*`.

## Headline

| Metric | Value |
|---|---|
| Runs | 72 (24 × 3), 0 crashes |
| **Clean-conclusion** (clean_deliver + honest_park) | **63/72 = 87.5%** |
| clean_deliver | 36 (50.0%) |
| honest_park | 27 (37.5%) |
| thrash_park | 4 (5.6%) — MCB-01, -21, -23, -26, one each |
| **false_ship** | **5 (6.9%)** — MCB-05 ×2, MCB-15 ×3, nowhere else |
| Worst-bucket per case | 4 clean · 14 honest_park · 4 thrash · 2 false_ship |
| 3/3 clean-deliver cases | MCB-08, MCB-13, **MCB-14**, MCB-17 |
| Median run | 84 s · 274k tokens · $0 (local models) |

## The five pre-registered predictions, scored

1. **Clean-conclusion 88–92%** → **87.5% — NARROW MISS** (0.5 pt below the band). The direction
   was the prediction's substance — materially lower than the museum 94.4% because false-shipping
   is now honestly counted and attributable — and that held. The shortfall is exactly the four
   thrash_parks (5.6%), all in the four historical thrash cases (prior thrash counts across their
   records: MCB-01 ×34, MCB-21 ×17, MCB-23 ×7, MCB-26 ×19).
2. **false_ship confined to MCB-05 + MCB-15 (~7–8% of runs)** → **CONFIRMED.** 5/72 = 6.9%,
   exactly those two cases, zero leakage elsewhere. These are the two-rulers cases awaiting the
   owner's grader-alignment call. Suite-level Wilson 95% interval for false_ship: ≈ 3.0%–15.2%.
3. **MCB-14 delivers** → **CONFIRMED.** 3/3 `clean_deliver`, grader-passing — the case that
   refused correct work 20/20 in every sweep before #62 (the mutation-guided-inputs fix).
4. **Delivery rate up materially vs the July baseline** → **CONFIRMED.** clean_deliver 50.0% vs
   34.7% / 41.7% on the last like-for-like full sweeps (2026-07-18, both n=72) — +8 to +15
   points; clean-conclusion on those same July sweeps was 50.0%, vs 87.5% now.
5. **No case regresses into thrash** → **CONFIRMED.** All four thrash runs occurred in cases with
   long pre-existing thrash histories; no case newly entered the class, and each of the four also
   produced clean conclusions within this same window (none is degenerate).

**Verdict: 4 confirmed, 1 narrow miss (87.5% vs a 88–92% band).** The predictions' combined
story — the wall down, false-shipping named and confined, honesty over headline — held.

## Rule-of-three bounds (per pre-registration)

For the 22 cases with **zero false_ship in n=3**, the rule-of-three 95% upper bound is 3/n ≈
**≤63% per case** — honest but weak at n=3; per-case false-ship claims stronger than that require
more repeats. The informative statement is suite-level: observed 6.9%, entirely attributable.

## Recorded observations (not claims)

- **MCB-05 keeps drifting toward parking**: 2 false_ship + 1 honest_park here (prior record
  ≈53–68% false-ship, parking rare). Consistent with the unpredicted n=5 drift noted in the #62
  record; still unpowered, still not claimed. The case remains gated on grader alignment.
- **MCB-15 is unchanged** (3/3 false_ship) — same class, same pending owner call.
- MCB-01 delivered 2/3 (prior record: predominantly thrash/park) — a real capability gain
  worth watching for stability, not yet claimed.

## Deltas vs the retired headline

`rebaseline_80on_x3` (94.4% / fs 0) is retired as the reliability headline. The standing figures
are now: **clean-conclusion 87.5% · false_ship 6.9% (two named cases) · delivery 50.0%**, at
commit `405ded5`, honestly attributable per case. The path back above 90% runs through the four
historical thrash cases and the two grader-alignment calls — both named, neither hidden.
