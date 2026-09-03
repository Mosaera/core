# Decision brief — MCB-05 / MCB-15 grader alignment (Gate 2)

**For:** the owner. **Status:** decision pending; this brief assembles evidence already banked across
four records and recommends, it does not decide. **Why now:** these two cases are the *entire*
remaining `false_ship`, so this call — not any engineering task — is what moves Gate 2.

## The situation in one paragraph

The standing baseline is **clean-conclusion 87.5% · `false_ship` 6.9% · delivery 50.0%** (72 runs,
24 cases × 3, commit `405ded5`). All five false ships are **MCB-05 ×2 and MCB-15 ×3, with zero
leakage anywhere else**. Both are "two-rulers" cases: the hidden grader and the engine measure the
same property with different instruments, so the engine can prove everything it holds and still be
scored wrong. Gate 2 (`false_ship ≈ 0`) is the only v1.0 release gate 0.6.0 outright fails.

## What the grader asserts

`packages/core/mosaera_core/bench/cases/MCB-05/grader/test_acceptance.py`:

```python
assert len(fn.body) <= 6   # checkout_total
assert len(called) >= 3    # delegates to at least three helpers
```

`packages/core/mosaera_core/bench/cases/MCB-15/grader/test_acceptance.py`:

```python
assert len(fn.body) <= 7   # parse_log_line
assert len(called) >= 3
```

`len(fn.body)` counts **top-level statements only** and **includes the docstring**. Both graders also
carry behavioural tests, which pass on any behaviour-preserving refactor — so on a correct run the
**only** thing separating pass from fail is that absolute constant.

## What the engine proves instead

`packages/core/mosaera_core/structural_spec.py:250-281`, reached from `claim_oracles._eval_transformation`:

```python
elif now * _SHRINK_DEN > was * _SHRINK_NUM:   # 2/3
    reasons.append(f"`{fn.name}` is {now} statements where it was {was} — …")
elif _has_loop(before) and _has_loop(fn):
    reasons.append(f"`{fn.name}` still iterates — …")
```

A **relative** 2/3 shrink, counted **recursively** (`_total_stmts`, the R1 nesting-dodge fix),
**excluding** the docstring, plus a loop-extraction rule. The absolute constant was removed
deliberately — `structural_spec.py:31-52` records why: *"MCB-05 and MCB-15 use near-identical brief
wording, both extracted 6, yet their graders score `<=6` and `<=7` — no fixed integer satisfies both."*

## The mismatch, on four independent axes

| | grader | engine |
|---|---|---|
| measure | absolute (`<=6` / `<=7`) | relative (`now <= 2/3 · was`) |
| counting | top-level statements | every statement, recursively |
| docstring | counted | excluded |
| loops | silent | must be extracted |

Measured divergence on the same seed: **MCB-05 is 9 statements by the grader's ruler and 20 by the
engine's.** So the engine can satisfy every predicate it holds — behaviour preserved, ≥3 helpers,
body under two-thirds, loop extracted — and still land a **7–8 statement orchestrator** that trips
`<= 6`. ADR-0072 measured exactly that on MCB-05, 15/15 runs. The gate has no evidence it is wrong,
so it ships; the grader says fail; the verdict is `false_ship`.

> **AMENDED 2026-08-05 — the premise below was wrong, and it was load-bearing.** This brief
> originally read: *"Note the asymmetry: `structural_spec` is downgrade-only and **cannot manufacture
> a false ship** — the gap comes entirely from the ruler."* It could, and it did.
> `check_structural_compliance` returned *met* after executing **zero predicates**, which minted a
> structural vouch, cleared `oracle_unverified`, and let the gate approve. Archaeology on the five
> banked false ships (MCB-05 ×2, MCB-15 ×3) confirms every one of them delivered by that route:
> `vouch: structural_claims:…`, `gate_reasons: []`. The defect was fixed 2026-08-04 and the cases
> have not delivered since — 24/24 `honest_park` across two independent matrices.
>
> **This changes the decision, not just a sentence.** The gap did *not* come entirely from the
> ruler; the ruler was one of two causes and the other was ours. Option A's stated cost — *"the
> credibility of the 6.9% figure rests precisely on the grader being untouched and hidden"* — no
> longer holds, because the 6.9% is already unreproducible for a reason that has nothing to do with
> the grader. The two-rulers divergence is still real and still unmeasured; what changed is that we
> can no longer observe it, since nothing ships. Re-measure at HEAD before choosing an option.

## The banked numbers

- **Rebaseline** (n=72): 5 false ships = 6.9%, exactly MCB-05 ×2 + MCB-15 ×3; suite-level Wilson 95%
  interval **3.0%–15.2%**.
- **Claims-gate A/B** (n=140, both arms fingerprint-VALID): MCB-05 ON 9/10 vs OFF 8/10, **p=1.0**;
  MCB-15 ON 8/10 vs OFF 10/10, **p=0.474**. Pre-registered as P2 and **CONFIRMED** — the predicate
  change moved nothing, which is what a two-rulers gap predicts.
- **Structural-oracle A/B** (n=25/arm): MCB-05 84% vs 92% false ship, MCB-15 100% vs 96%, pooled
  **p=1.0**. Ambient false-shipping on these two cases is far worse than the historical 52.7% record.
- **Critic calibration** (n=140): MCB-15 self-voided (neither arm's critic fired); MCB-05 supplied
  **the only true catches in the entire corpus** (2 new-arm / 1 old-arm) and they survived the filter.
- **Unclaimed observation:** MCB-05 is drifting toward parking (2 false ship + 1 park at n=3;
  2/5 at n=5). Unpowered, explicitly not claimed, worth a powered re-measure.

## The thing I would lead with

**Neither brief states a number.** Both say only "a short orchestrator (a handful of statements)" and
"delegates to at least three helper functions". Near-identical prose is then graded `<=6` in one case
and `<=7` in the other. That is a **self-inconsistency in the benchmark**, not a defect in the engine:
no reader — human or machine — could derive 6 for one and 7 for the other from those words. The
engine's relative rule is arguably the *more* defensible reading of the prose; it just isn't the
ruler it is scored against.

That reframes the question. It is not "whose measurement is right", it is **"the contract was never
written down, and two parties guessed differently."**

## Options

**A · Align the graders to the engine's ruler** (make them relative, or at minimum count recursively
and exclude the docstring). Removes the gap at the source. **Cost:** it changes ground truth mid-arc,
so every historical `false_ship` number for these two cases stops being comparable — and the
credibility of the 6.9% figure rests precisely on the grader being untouched and hidden. Also: MCB-05
is the only source of true critic catches in the calibration corpus, so weakening its grader may
silently remove the only case where that control is exercised.

**B · Change the predicate to match the graders.** Requires reintroducing an absolute constant, which
is **provably impossible** from these two briefs — one prose form cannot yield both 6 and 7. ADR-0072
already retired that constant as unsound. Not recommended; it is the deterministic cousin of the
ADR-0070 LLM-judge dead end.

**C · Fix the briefs, not the rulers** (ADR-0080 / Wave-3 authored predicates). State the contract in
the brief — an operator-approved predicate saying exactly what "short orchestrator" means for this
case — so grader and engine read the same sentence. This is already the named successor to the
ADR-0072 red-team ACCEPT. **Cost:** it is real work, and it does not move the number this week.

**D · Accept as a named, attributed class.** Keep both rulers, record the 6.9% as two known cases with
a stated cause, and restate Gate 2 (see below). Fully supported by the data: attributed per case, zero
leakage, CI 3.0%–15.2%.

## Recommendation

**C as the fix, D as the interim posture — and do not take A.**

The gap is a missing contract, not a wrong measurement, so the repair belongs in the brief where the
ambiguity lives. Editing our own hidden grader to agree with our own engine is the one move that
would quietly damage the thing that makes these numbers worth having; the grader's independence is
the evidence. Meanwhile D costs nothing and is honest: 6.9%, two named cases, cause stated.

**Pair this with the Gate 2 restatement that is already due.** ADR-0079/0080/0081 are accepted, so the
pending change from a bare `false_ship ≈ 0` to *"no unestablished material claim ships"*, with the rate
stated as a bound on a named distribution (rule of three, ~3/n at 95%), is unactioned and the gate
table still carries the old wording. Under the restated gate these two cases are describable rather
than merely counted — which may well dissolve the question.

## Before touching either ruler

1. **MCB-05 is the only case producing true critic catches** in the calibration corpus. Changing its
   grader may remove the only live exercise of that control.
2. `test_the_unsound_body_check_is_still_the_load_bearing_one` was written to start **failing** as the
   retirement signal for the old constant. Check its current state first — it is a tripwire, and it is
   telling you something either way.

## Sources

`docs/engineering-history/rebaseline-2026-08-03.md` · `claims-gate-ab-2026-08-03.md` ·
`critic-calibration-ab-2026-08-03.md` · `structural-oracle-ab-2026-08-02.md` ·
`docs/adr/ADR-0072-structural-spec-oracle.md` (Amendment 2) ·
`packages/core/mosaera_core/structural_spec.py` · `packages/core/mosaera_core/bench/cases/MCB-{05,15}/`
