# Full-suite re-baseline — 2026-08-05 (24 × 3, at `c83d0be`)

**Why this one exists.** The standing baseline (87.5% clean-conclusion / `false_ship` 6.9% /
delivery 50%, `405ded5`) was taken **before** the vacuous-vouch fix and never retaken. Archaeology
on 2026-08-05 established that the 6.9% was produced by a defect of ours —
`check_structural_compliance` returned *met* after executing zero predicates, minting a structural
vouch that cleared `oracle_unverified` and let five runs ship (MCB-05 ×2, MCB-15 ×3, every one
carrying `vouch: structural_claims:…` and `gate_reasons: []`). Fixing it removed the only delivery
channel those cases had, so the old number could be neither reproduced nor trusted.

**Measurement isolation.** 72 runs (24 cases × 3 passes) from a detached worktree pinned at
`c83d0be` (`~/.mosaera-bench-wt`, its own venv) so branch work in the main checkout could not change
the code under measurement mid-sweep. Knobs at their **defaults** — this measures the posture we
ship. Escalation OFF, cloud egress OFF (both already default; pinned explicitly so the record states
the configuration rather than assuming it). One deviation from the shipped config, recorded because
it is real: `MOSAERA_MODEL_PM=gpt-oss:20b`, because the stored `role_models.pm.model`
(`qwen3.6:35b`) is **not installed on this box** — a live misconfiguration that breaks Quincy for
all project work, unrelated to this sweep. Resumable done-log; scorecards in
`.mosaera/benchmarks/MCB-*/`, stamps `20260804-23…20260805-…`.

## Headline

| Metric | This sweep | Prior (`405ded5`) | Δ |
|---|---|---|---|
| Runs | 72 (24 × 3), **0 crashes** | 72 | — |
| **Clean-conclusion** | **66/72 = 91.7%** | 87.5% | **+4.2pp** |
| clean_deliver | 41 (56.9%) | 50.0% | +6.9pp |
| honest_park | 25 (34.7%) | 37.5% | −2.8pp |
| thrash_park | 5 (6.9%) | 5.6% | +1.3pp |
| **false_ship** | **1 (1.4%)** | 6.9% | **−5.5pp** |
| Mean capability | 89.5/100 | — | — |

`false_ship` 1/72 = 1.4%, **95% Wilson upper bound ≈ 7.5%**.

## Gate 2 does not pass — and the restated wording is why that is visible

Under the old bare wording ("`false_ship` ≈ 0 on held-out inputs", naming no suite, no n, no
configuration) 1.4% would have been arguable as green. Under the restatement adopted the same day
(*no unestablished material claim ships*, rate as a bound on a **named** distribution) it fails on
both counts: the bound is nowhere near zero at this n, and **there is a real one**.

## MCB-05/15: the historical false-ship pair is now silent

6/6 `honest_park`, `delivered=False` every time. The channel that carried the entire historical
figure is closed. This is the confirmation that **the 6.9% was ours**, not a capability gap — and
note what it does *not* mean: the two-rulers grader divergence is still there, unmeasured, because
nothing ships on those cases any more.

## The one false ship is a different animal — and worse

**MCB-18**, `delivered=True`, `gate_reasons: ['reviewer_unknown']`, grader `0/1`.

The grader could not collect because `from ops import OperationError` failed — **a missing symbol,
not a broken module.** The coder's own transcript describes implementing the full `OperationError`
contract; **a one-line diff reached disk** (`result.get(op["key"], 0)`). The seed's pre-existing
suite asserts the *old* contract and stayed green.

Every control abstained:

- `standing_suite_is_independent_oracle` credited the pre-existing suite → `oracle_verified=True`
- the Proctor authored **no** test files (`delivered_test_files == 0`)
- the held-out critic returned `INSUFFICIENT_EVIDENCE`
- claims bound to no oracle (`unsatisfied_claims: []`, clauses `[ENTAILED → none]`)
- validation passed **correctly** — the run's own suite is green, and exit codes are interpreted
  soundly (collection error → `passed=False` is unreachable here because nothing failed)

**`reviewer_unknown` was a passenger, not the cause.** Had the reviewer emitted `APPROVE` — as it
does on 33 of 35 deliveries in this sweep — reasons would have been `[]` and the identical no-op
ships through the empty-reasons path. Only **2** runs in the whole sweep rode the ADR-0031 silence
backstop at all; the other 33 deliveries got a real approval.

**The defect named:** a pre-existing suite is a **relevance** heuristic ("does this test touch the
changed module?") being used as a **sufficiency** oracle ("does this verify the task?"). For any
task asking for *new* behaviour, a pre-existing suite is structurally incapable of failing.

## The bigger number is over-park, and it is on CORRECT work

**5 thrash parks (6.9%) — larger than the false-ship rate — and four of the five had a passing
grader:**

| case | grader | cause |
|---|---|---|
| MCB-21 | **8/8** | `stalled:plan` → `iteration_limit` |
| MCB-26 ×3 | **5/5** each | `stalled:plan` every time |
| MCB-23 | 2/8 | `give_up` |

**MCB-26 threw away correct work three times out of three** — not variance, a case the engine
cannot conclude on. All five carry `validation_failed` + `unsatisfied_claim` and rode to the cap.

Four runs (5.6%) produced grader-passing work that was destroyed by our own gates. That is now the
largest measured defect in the suite, and it is invisible in every headline we quote.

## Per-case (mean capability, 3 passes)

```
MCB-01 72.3 park×3     MCB-09  91.7          MCB-17  99.0
MCB-02 84.0            MCB-10 100.0          MCB-18  79.7  false_ship×1
MCB-03 98.7            MCB-11  86.7          MCB-19  83.3
MCB-04 80.7            MCB-12  97.3          MCB-20 100.0
MCB-05 94.0 park×3     MCB-13  97.0          MCB-21  88.7  thrash×1
MCB-06 99.3            MCB-14  97.0          MCB-22  95.0
MCB-07 97.3            MCB-15  89.7 park×3   MCB-23  55.0  thrash×1
MCB-08 100.0           MCB-16  86.3          MCB-26  75.0  thrash×3
```

## What this retires and what it leaves stale

- **Retires** the prose standing baseline (87.5% / 6.9% / 50%, `405ded5`).
- **Still stale, and deliberately left so:** the per-case `bench/baselines/*.json` were last written
  2026-07-14 and record `delivered: true` for MCB-05/15, which is now false 6/6, so
  `make bench-compare --all` will read false regressions. They are **not** regenerated here for two
  reasons, both from `baselines/README.md`: a baseline is *"a deliberate record of the capability we
  expect — never auto-commit it"*, and baselines are **model-specific**, while this sweep ran with
  `MOSAERA_MODEL_PM=gpt-oss:20b` rather than the canonical (missing) `qwen3.6:35b`. Regenerating
  from these cards would bake a non-canonical model into the committed expectation. **Owner action:
  fix the PM model, then `--update-baseline` and review before committing.**

## Two diagnostic defects found, neither causal

1. `bench/grade.py::_FAILED_ID` captures pytest's `ERROR collecting <path>` as the literal token
   `collecting`, so `grader_failed_tests` read `['collecting']` on the one run that mattered. My own
   regex, added the day before.
2. The scorecard records `Action: require_human` on a run the runner delivered — the ADR-0034
   defect-#5 asymmetry resurfacing in what a human auditing the card reads first.

---

## CORRECTION (2026-08-05, later the same day): over-park is 18/60, not 4/72

**The numbers above are not restated — they were correct for what they counted. The over-park
count was too NARROW, by 4.5×.**

This record said "5 thrash parks, four with a passing grader — 5.6%, the largest measured defect".
It counted only `thrash_park`s. Re-reading all 60 stored scorecards with the full rule — *any
non-crash run that did not deliver, whose hidden grader passes* — gives:

**18 of 25 parks (72%) had a PASSING hidden grader. That is 18 of 60 runs — 30% of the sweep.**

The 14 that were missed stopped **promptly**, so they classified as `honest_park` and never entered
the over-park tally. They are honest about *stopping* and wrong about the *work*: the code was
correct and did not ship. `classify_outcome` is right and stays frozen (ADR-0069) — the two
questions are simply different, and only one of them was being asked.

| n | cause | core gate reasons (benign removed) | convertible by Layer 2 as built? |
|---|---|---|---|
| 7 | `give_up` | validation_failed + unsatisfied_claim | maybe — class 2, only if the failing tests are engine-authored |
| 3 | `parked` | oracle_unverified | **yes** — class 1, exactly what it is for |
| 4 | `stalled:plan` | validation_failed + unsatisfied_claim (+reviewer) | **no — excluded by construction** |
| 2 | `give_up` | validation_unavailable | no |
| 2 | `parked` | unsatisfied_claim | no |

**Why it stayed hidden:** `parked` and `grader_passed` were BOTH already recorded on every card.
Nothing crossed them. The instrument had the data and never asked the question — the same shape as
every liveness incident in ADR-0081, and the reason the `Fidelity` dimension now computes this on
every run instead of leaving it to archaeology.

**The 4 stall parks are excluded by construction, not by evidence.** `is_oracle_unverified_park`
rejects any run with `stalled` set, and `is_engine_blocked_give_up` requires `give_up_reason`
truthy — which the stall breaker never sets. Their evidence reads
`no convergence: failing count 4 → 4 → 4 over 3 non-improving attempts` while the hidden grader
passes 5/5: the engine's own failing tests are wrong and trap the run, which is precisely the
situation class 2 exists for, arriving through a door the predicate does not cover.

**Caveat, carried wherever this number is quoted:** "the grader passed on a parked run" measures the
work in the uncommitted tree, and a thin grader over-credits — MCB-18 proved this suite can be
fooled by a no-op. And some of the 18 are correct *process* decisions that still lost correct work
(`validation_unavailable`: the engine could not verify anything). The dimension measures outcome
fidelity, not gate error; both readings can be true of one run.
