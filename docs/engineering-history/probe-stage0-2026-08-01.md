# Stage 0 — Acceptance Differential Probe: offline hypothesis validation (2026-08-01)

> **Experiment log, not a decision.** Per `CLAUDE.md`, benchmark snapshots and experiment logs need
> no ADR. Nothing here authorizes a production build. The live roadmap is
> [`docs/roadmap.md`](../roadmap.md); decisions are in [`docs/adr/`](../adr/).
>
> **Status: COMPLETE — disposition `INCONCLUSIVE (underpowered, leaning positive)`.** Everything
> in the pre-registration section was written *before* the sweep ran and is unedited.

---

## Why

The measured dominant defect in the correctness oracle is the **dual** of the one mutation testing
attacks. Mutation (ADR-0071) detects suites that are too **weak** — it guards `false_ship`. The
recurring failure is the opposite: the Proctor authors a suite that is too **strict**, or outright
unsatisfiable, so correct code parks.

The measured scale (`roadmap-and-arc-history.md`):

- `overstrict_vs_ref` = **6/20 cases (~30%)** author a suite the *correct* `reference/` fails.
- **~89%** of parked runs are code the hidden grader scores correct (Implementation ≥85/100) that
  the run's own validation false-reds; **0–2** are genuine coder-fails.
- The convertible pool is **44%** of runs; "≥11/16 reasons name a wrong authored test; some
  unsatisfiable by any correct code."

`faithfulness.py` (ADR-0062) attacks this side but is one-sided by construction — it flags only
strictness it can *prove* is incidental from the spec, and stays silent when unsure. Its
deterministic auto-rewriter was built, red-teamed twice, and **reverted** (it reopened
`false_ship`). Distinguishing incidental from semantic strictness is not deterministically
decidable from the spec alone.

## The hypothesis under test

> An independently-authored implementation, given the same acceptance contract the coder receives,
> **fails an over-strict suite — and does not fail a sound one.**

If it holds, an Acceptance Differential Probe run **coder-blind at authoring time** can hand the
Proctor named repair targets inside the one window where test repair is already sanctioned
(`nodes_plan.py:172`, `iteration <= 1`, ADR-0058). If it does not hold, the arc dies here.

## Why this is measurable offline

`bench/faithfulness.py::overstrict_vs_reference` already overlays a case's known-good `reference/`
onto a run workspace and re-runs the authored suite. **Any authored test the correct reference
fails is provably over-strict.** That is a ground-truth label, and **22 of 24** MCB cases ship a
`reference/` (greenfield MCB-01/02 do not). The experiment reuses that overlay for a second arm.

## Method

Harness: `scripts/experiments/probe_stage0.py` (throwaway; `scripts/` is outside the
`check_file_sizes.py` / `check_layer_imports.py` scan roots).

Per case, per repeat:

1. **Truncated authoring run** — drive the real graph `plan → design → author_tests` and stop by
   abandoning the update stream. This is exactly the production probe's vantage point: coder-blind,
   `iteration <= 1`, no implementation on disk.
2. **Arm A (ground truth)** — copy the authored tree, overlay `reference/`, run the authored suite.
   Over-strict iff ≥1 authored test fails. A second copy is scored with the **shipped**
   `overstrict_vs_reference` as a control.
3. **Arm B (probe)** — clone a fresh seed, copy the authored tests in and **protect** them, hand a
   held-out model the same brief + `_acceptance_contract`, let it implement, then run the authored
   suite against its tree.

**Failing pytest node IDs are captured on both arms** (`-rfE`), not just counts — the decisive
question is whether the probe fails *the same assertions* the reference fails, and count-agreement
can be coincidental.

### Symmetry (the load-bearing choice)

The probe gets the **same** affordances as the production coder: authored tests on disk and
protected, the same `_acceptance_contract` (test bodies, ADR-0059), the same repo toolset including
exec/scratch. Independence comes from separate authorship and a distinct role model — never from
information asymmetry. A probe given *less* than the coder would fail for interface reasons (wrong
module path, wrong signature) and manufacture false over-strictness signals, whose downstream
action is loosening a good test. That is the one path to `false_ship`.

### Fail-safe asymmetry

Only the FAIL branch can cause harm downstream. A PASS — even a wrong one, even a probe that games
the suite by special-casing tests — yields no repair target and reverts to today's behaviour.
Hence FAIL-branch precision is the primary metric, and a cheating probe is a benign no-op rather
than an attack.

### Configuration

| | |
|---|---|
| Coder / tester | `ollama:qwen3-coder:30b` |
| Probe (held out) | `ollama:gpt-oss:20b` |
| PM (plan/design) | `ollama:qwen3-coder:30b` — **deviation**, see below |
| Sandbox | `docker`, `mosaera-sandbox:dev` |
| Cloud escalation | **disabled** (`MOSAERA_MODEL_ESCALATION=false`, `MOSAERA_ALLOW_CLOUD_EGRESS=false`) |

**Recorded deviation:** the stored config pins `pm` to `ollama:qwen3.6:35b`, which is not installed
locally. PM was overridden to `qwen3-coder:30b` for this sweep. This means plan/design/coder/tester
all share one model while the probe stays held out from all of them — which preserves what the
experiment measures (probe independence), but the authored suites are not identical to what the
stored production config would produce. Escalation was disabled so the tester could not silently
become a cloud model mid-sweep, which would have changed the suite author.

---

## PRE-REGISTRATION — abandon thresholds

*Written before the sweep. Ground-truth label = `reference_failures > 0`.*

| Metric | Threshold | Consequence |
|---|---|---|
| **FAIL-branch precision** — P(truly over-strict \| probe FAIL) | **< 0.70** | Abandon the broad probe, or narrow to deterministic filters (contradiction findings, exact-format assertions) and re-measure. |
| **Assertion overlap** — mean Jaccard of probe-failing vs reference-failing node IDs on true positives | **≈ 0 while precision is high** | The probe is detecting something else (most likely its own defects). Do **not** proceed to the Proctor-repair wiring. |
| **Probe PASS rate** | **≈ 100%** | Uninformative — the contract includes test bodies, so satisfiability may be near-tautological. Narrow or abandon. |

Supporting measurements (not thresholds): FAIL-branch recall, probe build-failure rate (the
interface/environment confound, counted separately and never as over-strictness evidence), tokens
and wall-clock per probe.

**Scoring rule:** only rows where *both* arms actually executed are scored. A probe that never
built is a confound, not evidence.

**Noise control:** the Proctor is stochastic and the existing audit warns single-pass runs are
sampling-noisy ("a single-pass (repeat=1) snapshot, not the 3×-averaged baseline the discipline
calls for"). Suite authoring is the dominant noise source → **repeat ≥ 3**. Report per-repeat and
pooled; a label that flips between repeats is flagged as an unstable case, never averaged away.

**Harness validity gate:** Arm A must agree with the shipped `overstrict_vs_reference`. Any
disagreement makes the harness suspect and Arm B meaningless.

---

## Results

66 rows (22 cases × 3 repeats). **0 authoring failures.** Runtime ~50 min, all-local.

### Harness defects found *after* the sweep — and their correction

Two defects in the experiment harness inflated the first summary. Both are recorded because the
uncorrected numbers were briefly the headline, and the corrected ones are materially weaker.

1. **Non-pytest cases were scored as failures.** `MCB-23` is `kind=node-cli` and `MCB-26` is
   `kind=sql`, but the harness (like the shipped `overstrict_vs_reference`) hardcodes
   `python -m pytest`. Neither arm can execute `.ts` or `.sql`, so pytest exits non-zero and
   *both* arms registered "failed" for a reason unrelated to over-strictness — manufacturing **6
   false true-positives**. The shipped function returns `None` (unmeasurable) for these; the
   harness now does too. The Arm A validity gate missed this because it only compared counts when
   *both* were non-`None`.
2. **Jaccard scored two empty sets as 1.0**, i.e. "no data from either arm" counted as perfect
   agreement — inflating mean overlap from 0.65 to 0.825.

8 rows total are excluded as unmeasurable (the 6 above plus one row each from MCB-13/MCB-15 where
a failure produced no parseable pytest result).

### Corrected results — python-pytest rows only

| | Uncorrected | **Corrected** |
|---|---|---|
| Scored rows (both arms ran) | 55 | **47** |
| TP / FP / FN / TN | 12 / 0 / 10 / 33 | **5 / 0 / 9 / 33** |
| FAIL-branch precision | 1.00 | **1.00** — Wilson 95% CI **[0.57, 1.00]** |
| FAIL-branch recall | 0.55 | **0.36** — Wilson 95% CI [0.16, 0.61] |
| Mean assertion overlap on TPs | 0.83 | **0.78** (on **5** TPs with real node data) |
| Probe PASS rate | 0.78 | **0.89** |
| Probe build failures | — | **11 / 66 (17%)** |
| Arm A vs shipped `overstrict_vs_reference` | — | **0 disagreements** |

### Against the pre-registered thresholds

| Threshold | Result | Fires? |
|---|---|---|
| Precision < 0.70 → abandon | point estimate **1.00** | **No** |
| Overlap ≈ 0 while precision high → do not wire to the Proctor | **0.78** | **No** |
| PASS rate ≈ 100% → uninformative | **0.89** | **No** |

**No abandon threshold fired.** But see the disposition — not firing an abandon threshold is not
the same as establishing the hypothesis.

### Ground-truth label instability — the most reusable finding

**9 of 22 cases flip their over-strictness label across the 3 repeats** (MCB-04, -05, -06, -12,
-13, -15, -19, -20, -22). The Proctor authors a different suite each time, so *the ground truth
itself is stochastic*. Consequences:

- Any single-pass measurement of over-strictness is noise. This vindicates repeat ≥ 3 and means
  per-case conclusions from `overstrict_vs_ref` should never be drawn from one run.
- Four cases are stable-positive (MCB-09, -18, -21 and, before exclusion, -23/-26) and eight are
  stable-negative — a usable stratification for a follow-up with more statistical power.

### Systematic misses

`MCB-09` and `MCB-18` are stable `ref=TTT` / `probe=FFF` — the probe satisfied, on all three
repeats, suites that the *known-correct reference* cannot. That is the mechanism behind the low
recall: **the probe contorts its implementation to fit the assertions.**

This is a structural tension worth carrying into any ADR:

> The fail-safe property and the recall ceiling are the same mechanism. A probe that *can* contort
> to pass will pass — so it will not flag. High recall and benign-gaming cannot both come out of
> this design.

The feature's ceiling is therefore a **high-precision, low-recall, safe** detector — never a
general solution to over-strictness.

### Cost

| | |
|---|---|
| Authoring (truncated `plan→design→author_tests`) | 5,537,821 tok / 66 runs = **~84k per run** |
| Probe (independent implementation) | 3,374,991 tok / 66 attempts = **~51k per run** |
| Probe overhead on top of authoring | **+61%** |
| Probe mean wall-clock | **21 s** |

Local-model tokens, so this is time not dollars — but the +61% is the real per-eligible-run tax,
and it is why `#57` (post-park in-flight spend) must land before any production cost claim.

## Disposition

**INCONCLUSIVE — underpowered, leaning positive. Not validated, not refuted.**

The honest reading: precision rests on **5 FAIL events**. The point estimate is 1.00 and no
pre-registered abandon threshold fired, but the Wilson 95% lower bound is **0.57 — below the 0.70
threshold**. The pre-registration named the point estimate, so this technically clears the bar;
claiming validation on that basis would be exactly the kind of "measured" result the anti-gaming
rules exist to prevent.

What *is* established:

- **Zero false positives across 47 scored rows.** The harm branch stayed empty. That is a real,
  if underpowered, safety signal.
- **When the probe fires, it names largely the right assertions** (overlap 0.78) — the property
  that would make it a repair-target generator rather than a bare flag.
- **The probe is not tautological** (PASS rate 0.89, not ≈1.0).
- **Arm A is trustworthy** — 0 disagreements with the shipped function on every measurable row.

**Recommended next step — not an ADR yet.** Accumulate FAIL events before deciding: re-run with
more repeats concentrated on the stable-positive and label-flipping strata, targeting ≥20 FAIL
rows so precision has a lower bound clear of 0.70. That is another ~1–2 h of local compute and no
production code. Only then does ADR-0077 become an evidence-backed proposal.

**The consolation asset, banked regardless.** The Arm A failing node IDs are a labeled corpus of
*provably* over-strict assertions — known-correct code fails them. Specimens from this sweep:
`test_has_required_helper_functions`, `test_helper_functions_have_correct_signatures`,
`test_parse_log_line_is_orchestrator`, `test_parse_log_line_is_short_orchestrator`,
`test_original_functionality_preserved`, `test_random_inputs_match_original`. These are the
`source_introspection` and behaviour-preservation shape-pinning classes. They are direct input for
extending `faithfulness.py`'s deterministic detectors — free at runtime, no model, no new agent,
and none of the probe's loosening hazard. That may be the better lever per unit of risk.

### Limitations

- One model pair (`qwen3-coder:30b` coder+tester vs `gpt-oss:20b` probe) on one machine.
  Correlated-fault behaviour is pair-specific.
- `tester` and `coder` are the **same model** in this configuration — the "who-tests-the-test"
  correlation the history records as inherent is live in these numbers.
- PM deviation (see Configuration).
- 17% probe build-failure rate; those rows yield no evidence either way.
- Python-first, refactor/CLI-skewed cases; the two non-Python cases had to be excluded outright.
- Measures **detection only**. It says nothing about whether the Proctor would *repair* correctly,
  and nothing about `false_ship` — Stage 0 has no gate and no delivery.

## Note on sequencing

This experiment serves **delivery rate** (parked-but-correct), not Gate 2 (`false_ship`), which is
the declared v1.0 blocker. The probe's only harm path — the Proctor loosening a good test — pushes
*against* Gate 2. ADR-0066 is the precedent: built and measured, posture activation **held**,
because the ON arm showed a `false_ship` the OFF arm did not. If this proceeds past Stage 0,
`false_ship` must be the **primary** metric of any ON/OFF evaluation, and the re-sequencing should
be recorded in `docs/roadmap.md` as a deliberate choice.
