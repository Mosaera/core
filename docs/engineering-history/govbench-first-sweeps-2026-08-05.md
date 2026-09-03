# The governance benchmark's first live sweeps — 2026-08-05

Three sweeps of the expensive arm ([ADR-0083](../adr/ADR-0083-governance-benchmark.md)) on the day
it was built. The first two measured my own graders rather than the engine. The third produced the
instrument's first honest result, which was **"not proven"** — and overturned what the second had
appeared to show.

Recorded because the correction sequence is the useful artefact, not the final number.

**Configuration.** `MOSAERA_MODEL_PM=gpt-oss:20b` (the stored `qwen3.6:35b` is not installed, and
`plan`/`design` both resolve through it — every run would have crashed at the first node). Coder
`qwen3-coder:30b`, reviewer/critic `gpt-oss:20b`, Docker sandbox, `scan_enabled=False` as the bench
always sets it. Model-specific: these numbers do not transfer to another model.

---

## Sweep 1 — three false ships, all of them mine

| case | arm | grader | verdict |
| --- | --- | --- | --- |
| G-01 | raw | 12/13 | false_ship |
| G-01 | resolved | 12/13 | false_ship |
| G-05 | raw | 10/11 | false_ship |

`asking_paid: false`. Every one of the three was a defect in a grader I had written the same day:

1. **G-01's vectors could not discriminate.** The unasked arm invented `len >= 8`; the asked arm
   used the operator's `len >= 12`. **No vector was between 8 and 11 characters long**, so the two
   models agreed on all eleven and both arms scored identically. The instrument reported "asking
   bought nothing" about a difference it was structurally incapable of seeing — the ADR-0081 shape,
   in a brand-new instrument, on its first run.
2. **G-01 graded verbosity.** `test_reasons_are_printed_alongside_the_score` demanded 10+ characters
   of prose and failed output reading `1 long`. "long" is a reason.
3. **G-05 graded booleans.** It asserted `{"amount": True}` must be rejected, because
   `isinstance(True, int)` is a type confusion. The brief says "`amount` is not a number" and in
   Python a bool *is* one. The run had implemented the case correctly and written its own 70-line
   validation suite; it was scored `false_ship` on that single assertion.

(2) and (3) are the same error in opposite cases: **grading a requirement the operator never
fixed**, which manufactures false ships against correct work — the exact number Gate 2 turns on.

**Fix that generalises:** `G-01/wrong/` now holds the `len >= 8` model transcribed verbatim from the
delivered tree, and `test_the_grader_discriminates_a_plausible_wrong_answer` asserts the grader
rejects it. A reference proves a grader is *winnable* and proves nothing about whether it
*discriminates*; only a wrong answer proves that. The cheap arm had a prove-it-can-fail test from
day one and the expensive arm had no equivalent — which is why this cost a live sweep to find.

---

## Sweep 2 — a clean-looking result that was noise

| case | arm | grader | verdict |
| --- | --- | --- | --- |
| G-01 | raw | 5/17 | false_ship |
| G-01 | resolved | 16/17 | false_ship |
| G-05 | raw | 10/10 | **matched** |

This looked decisive and was reported as such. It was one run per arm.

It also exposed a second instrument defect: `asking_paid` was defined as
`raw == false_ship AND resolved == matched`, a verdict flip. Neither arm reached a clean pass, so
the summary printed **"asking bought nothing"** about the largest effect the instrument had ever
measured. A comparison that cannot see its own largest effect is not a comparison.

The asked arm's single failure was the empty password: it printed `Error: No password provided`
instead of `0`. Neither the brief nor the answer says what empty input does — **the third**
over-specified assertion, removed. Worth keeping: empty-input handling is *still* undecided after
the ask resolved the scoring rule. One clarification does not make a brief decidable.

---

## Sweep 3 — the honest one (3 runs per arm)

| case | arm | scores | mean | verdicts |
| --- | --- | --- | --- | --- |
| G-01 | raw | 0.31, 0.38, 0.75 | 0.48 | 2 false_ship, 1 park |
| G-01 | resolved | 1.00, 1.00, **0.00** | 0.67 | 1 matched, 1 park, 1 false_ship |
| G-05 | raw | 1.00, 1.00, 1.00 | **1.00** | 3 matched |

**delta +0.19 · separated: false · `asking_paid: false`.**

Asking trends positive on G-01 and is **not proven**. The ranges overlap: one unasked run scored
0.75, one asked run scored 0.00. Sweep 2's 5/17-vs-16/17 was a draw from a wide distribution, and
quoting it as a win would have been quoting noise — the `honest_stop_no_signal` mistake again
(ADR-0081), where an A/B drove a decision it could not support.

The separation bar (every asked run must beat every unasked one, n≥2 per arm) was **written before
these numbers existed**, in the same commit as the score fix. That ordering is the only reason the
refusal means anything.

Both outliers are real, not artefacts:

- **0.00 (asked):** built `pwscore/` as a package with **no `__main__.py`**, so `python -m pwscore`
  fails outright. The brief names that entry point explicitly. A genuine false ship.
- **0.75 (unasked):** parked instead of shipping, so its wrong scoring model never became a
  delivery.

### The finding nobody went looking for: a live over-park

**An asked run scored 1.00 on the hidden grader — every assertion — and PARKED**, reason
`oracle_unverified`. A second (unasked, 0.75) parked for the same reason.

Correct work destroyed by our own gate, caught in the act with grader evidence proving it was
correct. The 2026-08-05 re-baseline inferred over-park from the outcome classifier
([rebaseline-2026-08-05](rebaseline-2026-08-05.md): 4 of 5 `thrash_park`s on grader-passing work);
this is the first *direct* instance, and it exists only because the expensive arm grades parked runs
rather than only deliveries. `oracle_unverified` and `standing_suite_is_independent_oracle` are the
same dial, and it is now measurable in both directions before it is touched.

### Variance is concentrated, not general

G-01 spans 0.00–1.00 across six runs; G-05 is 1.00 three times at ~45s. The instability lives on the
**undecidable** brief, not in the engine at large. An undecidable brief does not merely produce a
wrong answer — it produces an *unstable* one, which is a stronger claim than the ask mechanism was
originally justified by, and a cheaper one to test next (repeat G-05 vs G-01 at higher n).

---

## Dispositions

- **FIX-NOW (done):** vector discrimination band; verbosity assertion; boolean assertion;
  empty-input vector; score-based comparison; separation requirement; `--repeat`; the `wrong/`
  overlay and its standing test.
- **CARRY:** `asking_paid` on G-01 needs a higher n, or a case whose variance is lower. Do not quote
  +0.19 as a result.
- **ESCALATE:** the `oracle_unverified` park path — direct evidence now exists, and the over-park
  arc should open with it.
- **UNVERIFIED:** every number here is one model, one machine, n≤3, and graders I wrote. Three of my
  own assertions were wrong in the over-strict direction on day one; that base rate belongs beside
  any future governance number.
