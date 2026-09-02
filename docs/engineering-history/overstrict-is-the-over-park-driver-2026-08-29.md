# Over-strict authoring is the over-park driver, and the production detector is blind to it

**Measured 2026-08-29 over every surviving scorecard. Slice 3 of the efficiency/over-park arc
(#129).** No new runs — the corpus
already contained the answer.

## The effect

`overstrict_vs_ref` is the bench-only measure of how much stricter the authored acceptance suite is
than the **reference solution**. Of 163 runs that record it:

| | n | over-park | delivered |
|---|---|---|---|
| over-strict **> 0** | 57 | **44%** | 47% |
| over-strict **= 0** | 106 | **10%** | 84% |

**A 4.4× difference in over-park rate**, on the largest single split anything in this corpus has
produced. Over-strict authoring is not *a* cause of over-park; on this evidence it is *the* cause.

## The gap

`overstrict_static` is the detector production actually runs (ADR-0062's surviving half — the
reverted MR was the auto-loosen; detection shipped). Cross-tabulated against the reference measure:

| | ref > 0 | ref = 0 |
|---|---|---|
| **static > 0** | 4 | 3 |
| **static = 0** | **53** | 103 |

**The production detector catches 4 of 57 — 7% sensitivity.** It misses 53. (Three false positives,
so the precision problem is minor; the recall problem is total.)

The bench sees over-strictness because it can diff against a reference solution. Production has no
reference. That is the whole asymmetry, and it means every downstream mechanism fed by the detector
— the Proctor's named repair targets, the faithfulness block in the repair instruction — is
operating on 7% of the signal.

## Recorded prediction, written BEFORE the measurement it refers to

A run of `MCB-01` with `tester_repairs_tests=1` (the coder-blind proactive repair pass, built,
default OFF, in the liveness sentinel backlog) is in flight as this is written.

**Prediction: it will move little.** The repair loop is fed by named targets, and the detector that
names them sees 7% of the problem. A repair pass with nothing to repair cannot fix authoring it
cannot see. If the arm moves substantially, this prediction is wrong and the bottleneck is the
repair rather than the detection — which would be worth knowing and is why it is written down first.

Baseline for comparison, MCB-01 x3: Fidelity 33, Autonomy 53, Governance 67, 97 calls, 1.57M tokens.

## What this implies for slice 3

The target is **detector recall**, not the repair loop. And unusually for this repo, the work has a
real labelled dataset already sitting in the corpus: **57 positives and 106 negatives**, labelled by
a measure that does not depend on the thing being built. A stronger static detector can be scored
against it directly, with no GPU and no new runs.

**Non-widening by construction.** A better detector NAMES more targets for coder-blind repair before
the coder exists. It never relaxes a bar after a failure — the ADR-0062 line — and it can only cause
the Proctor to be asked about more assertions, never cause more to ship.


## PREDICTION FALSIFIED — 2026-08-29

The arm landed and **the prediction above was wrong.** Recorded here rather than quietly amended,
which is the only reason writing it down first was worth anything.

| | n | over-park | delivered | calls | tokens |
|---|---|---|---|---|---|
| baseline | 3 | 2/3 | 1/3 | 97 | 1.57M |
| **`tester_repairs_tests=1`** | 2 | **0/2** | **2/2** | 86 | 1.07M |

The repair arm delivered both runs with **no gate reasons at all**, on the single hardest case in
the class (MCB-01 contributes 8 of the 31).

**Why the reasoning failed.** I assumed the repair loop was fed only by the detector, so a 7%-blind
detector meant nothing to repair. It is not: `_repair_instruction` asks the Proctor to validate and
repair its own suite **against the spec** — *"REPAIR a test that is UNFAITHFUL to the spec
(over-strict beyond what the task states, or simply wrong)"* — and the detector's named targets are
an ADDITIONAL block layered on when `proctor_faithfulness_guard` is on. The Proctor can find its own
over-strictness without being told where to look. The detector improves the repair; it does not
gate it.

**n=2 vs n=3 is far too thin to conclude.** Fisher exact on 2/2 vs 1/3 is p ~ 0.4 — this is a
direction, not a result, and the third repair run was killed by the harness rather than completing.

**What it changes.** The repair loop moves from control to leading candidate, and the detector work
becomes the thing that makes it better rather than the thing that makes it possible. Both are still
worth building; the ordering was wrong.


## SLICE 3 IS BLOCKED ON DATA — both routes, and the blocker is instrumentation

Recorded 2026-08-29 after establishing the diagnosis. Neither remedy can be *concluded* with what
the corpus retains, and saying so is cheaper than a plausible-looking answer built on n=2.

### Route 1 — the repair loop: needs 7–20 GPU-hours

The direction is encouraging on the hardest case and absent on the next one:

| | MCB-01 | MCB-02 |
|---|---|---|
| baseline | 1/3 delivered, 2/3 over-park | 1/2 delivered |
| `tester_repairs_tests=1` | **2/2 delivered, 0/2 over-park** | **1/2 delivered — identical** |

Cost fell on both (MCB-01 97→86 calls, 1.57M→1.07M; MCB-02 46→42 calls, 431k→356k), but outcome
moved on one case and not the other.

**Noise floor, computed rather than guessed.** Baseline delivery across the four dominant cases
(MCB-01/02/09/26, n=40) is **35%**. For a binary outcome at α=.05, power .80:

| effect | n per arm | GPU-hours (both arms, 3.5 min/run) |
|---|---|---|
| +15% delivery | 171 | ~20 h |
| +20% | 98 | ~11 h |
| +25% | 63 | ~7 h |

n=2 vs n=3 is not a tenth of the way there. **This is a decision for the owner, not something to
burn unasked.**

### Route 2 — the detector: the corpus does not retain what it needs

The plan was to score a stronger `overstrict_static` against the 57 positives / 106 negatives
labelled by `overstrict_vs_ref`. That requires the **authored test text** the labels refer to.

It is not there. Of the labelled runs whose patch survives, only **6 positives and 2 negatives**
contain the authored test files. The scorecard retains exactly three fields touching authoring —
`layer2_authored`, `overstrict_static`, `overstrict_vs_ref` — all scalars. **The assertions
themselves are never recorded.**

So the corpus can say a run *was* over-strict, and never *which assertion* made it so. A detector
cannot be developed or validated against that.

### The cheap enabler, and the real recommendation

**Record the assertion profile of the authored suite on the scorecard.** `assertion_profile` already
exists (`oraclecheck.py`) and is already computed during authoring for the assertion floor — it is
being thrown away. Persisting it costs one field and turns 57 labelled positives from a number into
a dataset.

That is the honest ordering: **instrument first, then build the detector, then spend the GPU-hours
on the repair loop with a properly powered design.** Every prior over-park attempt in this repo
measured null, and the pattern in the record is remedies designed before the cause could be seen.

This is the same defect class the arc is about, one level up: the engine cannot fix what it does not
record, and neither can we.


## THE ENABLER WORKED — a corpus pass, a real dataset, and two checks scored against it

### The corpus pass

29 cases, one run each, ~55 minutes, into a home outside the live tree. Every card carries both the
digest and its label: **10 positives, 12 negatives, 0 labelled-but-missing-digest.**

**The production detector fired on 0 of the 10 positives.** That is an independent confirmation of
the 7% figure on fresh data — and on this sample it is 0%.

### What the positives actually assert

The data the corpus could never show before:

```
MCB-06  assert "not found" in str(exc_info.value)
        assert "Invalid JSON" in str(exc_info.value)
MCB-17  assert "Row 2" in error_message
MCB-18  assert "OperationError" in str(type(e))
        assert "unknown action 'foo'" in str(e)
```

The dominant shape is **pinning the WORDING of an error message**. The spec says an error is
raised; the test pins its prose, so rephrasing a message fails a correct implementation.

### Candidates scored BEFORE implementing

| rule | recall | precision |
|---|---|---|
| R1 exception-message pin | 3/10 (30%) | 75% |
| R2 type-name-as-string | 2/10 (20%) | **100%** |
| R3 whole-dict equality | 3/10 (30%) | 75% |
| R4 `assert False` sentinel | 2/10 (20%) | 50% |

**R1 ∪ R2 → recall 30%, precision 75%.** Adding R3 reaches 40% at 67%.

**R1 and R2 shipped; R3 and R4 did not.** R4's precision is a coin flip. R3 buys 10 points of
recall for a third of the precision, and precision is what makes the existing detector trustworthy —
its findings feed the Proctor's coder-blind repair turn, so a wrong name spends a repair
consideration on a faithful assertion.

The implemented AST checks score **identically to the regex prototypes** (3/10, 75%), which is the
check that the implementation matches what was measured.

### Why this is not ADR-0062

Both checks are **detection only**, and both carry `auto_loosenable=False`. Rewriting either needs
information the assertion does not carry — what the message *should* say, or which type is meant.
That is judgment, and judgment belongs to the Proctor's coder-blind turn, which is precisely the
half of ADR-0062 that survived. The reverted half was the mechanical rewriter.

Both inherit the module's faithfulness guard: **a literal the spec quotes verbatim is the contract
and is never flagged.** Pinned by a test.

### Honest limits

- **n=10 positives.** 3/10 has enormous error bars; this is "0 → some" not "30% exactly".
- **70% still missed.** The remaining seven positives (MCB-09/12/13/19/20/21/22) are exact-value
  and collection-equality shapes that need either R3's precision problem solved or a different
  approach.
- **The digest cannot be backfilled.** It only helps runs from now on; the 57 historical positives
  stay unusable.
- **Not measured end-to-end.** Better detection *should* mean better repair and less over-park, but
  that chain is unproven — and the repair sweep that would prove it is the 11-GPU-hour experiment
  still outstanding.


## THE CAUSATION SWEEP — ran 2026-08-29/30. The intervention is NOT supported, and the mechanism is CONTRADICTED.

Full corpus, **30 paired cases, both arms, blocked by case** (each arm ran the same cases, so the
between-case variance that dominates this corpus cancels). ~3 hours of GPU.

### The delivery signal: favourable, and not significant

| | baseline | repair ON |
|---|---|---|
| over-park | 10/30 (33%) | 7/30 (23%) |
| delivered | 18/30 (60%) | 21/30 (70%) |

Paired flips: **6 fixed by repair, 3 caused by it.** McNemar exact two-sided **p = 0.51**.

Making 33% → 23% significant needs **n = 319 per arm — about 21 GPU-hours.**

### The mechanism: contradicted

The hypothesis was *repair reduces over-strictness, which reduces over-park*. The first half is
false.

Over-strictness as a **rate** (`overstrict_vs_ref / overstrict_total`, normalised because the raw
count is confounded by suite size — repair authors more tests, so more can fail):

| | base | repair |
|---|---|---|
| mean over-strict rate | **6.8%** | **10.2%** |
| cases | improved 3 · worsened 8 · unchanged 15 |

**The repair pass makes suites MORE over-strict on average, not less.** Whatever produced the
delivery direction, it was not the mechanism this arc proposed.

A plausible alternative, untested: `_repair_instruction` asks the Proctor both to loosen unfaithful
assertions *and* to **strengthen weak ones**. The strengthening half may dominate, and a stronger
suite can help delivery for reasons unrelated to over-strictness.

### Disposition: STOP. Do not buy the 21 hours.

Spending 21 GPU-hours to resolve a delivery signal whose proposed mechanism has been refuted is the
bad bet this arc's own discipline section warns about — *"remedies designed before the cause could
be seen"*. The honest position is that **the intervention is unproven and the causal story is
wrong**, and the next move is re-diagnosis, not more n.

### What survives the null, and it is not nothing

1. **The observational finding stands.** Over-strict runs over-park at 44% against 10% (n=163).
   Correlation intact; this sweep shows only that *this particular intervention* does not exploit it.
2. **The instrumentation works**, verified end-to-end and now shipping on every run: which
   assertions were flagged, the suite before and after repair, and the outcome — the chain is
   readable from one scorecard. That is what made this null legible instead of mysterious.
3. **A real production defect was found and fixed** on the way here: the detector was reading the
   PM's paraphrase as the contract, so a planner restating an error message silenced it
   (MCB-06: bench 9 findings, production 0). Independent of this result.
4. **The detector gained recall** 0% → 30% on labelled data, at 75% precision.

### The corrected picture for the arc

Over-park is 33% on this corpus. Over-strictness predicts it strongly. But the one available
intervention against over-strictness does not reduce over-park, and does not even reduce
over-strictness. **Slice 3's remedy is back to open** — with far better instruments than it started
with, which is the difference between a null that teaches and a null that repeats.

## CHASED DOWN — 2026-08-30. The contradiction resolves, and the founding number was inflated.

The null above was a stopping point, not an answer. Pushing on it produced three findings, all from
data already collected.

### 1. The repair pass does two opposite things, and they were measured separately

From the pre/post digests, 30 repair-arm runs, no GPU:

| | before repair | after |
|---|---|---|
| assertions the detector flags | **15** | **2** |
| total assertions | **521** | **644 (+24%)** |

**The loosening half works** — flagged assertions fell on 2 cases and rose on 0. **The strengthening
half grows suites 24%**, and the new assertions carry new over-strictness that swamps the fix. That
is the whole contradiction: `_repair_instruction` asks for both *"REPAIR a test that is UNFAITHFUL"*
and *"STRENGTHEN one too weak"*, and they pull opposite ways.

### 2. Two attractive explanations were tested and REJECTED

- *"Suite growth causes over-park."* Within the repair arm, grown suites over-parked 33% against
  13% — but across all 60 runs suite size does not predict over-park at all (over-parked mean 21.4
  assertions, delivered 23.1; tertiles 20% / 35% / 30%, no trend). **Noise.**
- *"The historical corpus is confounded by engine version."* The effect holds *within* each batch
  (3.5× and 11.4×). **Not a version confound.**

### 3. The founding 4.4× is inflated by REPEATED SAMPLING

| | ratio |
|---|---|
| historical, all runs (7.8 runs/case, 21 cases) | **4.2×** |
| historical, one run per case (200 resamples) | **3.0×** (IQR 2.0–4.9) |
| fresh sweep, one run per case | **1.7×** |

The historical corpus sampled a few pathological cases many times, and those cases are both
over-strict-prone and over-park-prone. Weighting each case once roughly halves the effect.

**This is the same between-case confound the noise floor identified for the A/B design** — it was
applied to the experiment and not to the observation that motivated it. The real headroom is
1.7–3×, not 4.4×, which is why an intervention that fixes one half and worsens the other nets to a
wash.

### 4. Loosen-only: built, and mechanically verified

`repair_loosen_only` drops the STRENGTHEN half. On the six cases where the detector fires:

| | over-park | delivered | suites grown |
|---|---|---|---|
| base | 2/6 | 4/6 | 1/6 |
| full repair | 1/6 | 5/6 | 1/6 |
| **loosen-only** | **1/6** | **5/6** | **0/6** |

It keeps the fix and never grows a suite (MCB-06 19→4, MCB-17 15→7, MCB-18 31→24, MCB-01 52→48).

**The mechanism is fixed; the outcome is not proven.** At n=6 it is indistinguishable from full
repair on delivery, and the earlier power calculation stands: separating them needs ~319 runs/arm.

### Where this leaves slice 3

Honest end state: the *mechanism* is now understood and the harmful half is isolated and switchable.
The *outcome* claim — that any of this reduces over-park — remains unproven at achievable n, and the
headroom is half what the arc assumed. Any future attempt should weight cases equally rather than
runs, or it will re-inflate the same number.

## SLICE 4 — round trips. Prefetch measured NEGATIVE, and the pattern across three levers is the finding.

`coder_prefetch` hands the coder the plan-named file contents the DESIGNER already gets
(`build_grounding`, memoized, deterministic). Precedent: ADR-0059 hands it the authored test bodies
for the same reason. Measured on 4 cases:

| | base | prefetch |
|---|---|---|
| total calls | 187 | **201** (+7%) |
| coder calls | 62 | 60 |
| total tokens | 1,238,133 | **1,347,618** (+9%) |
| over-park | 1/4 | 2/4 |

**Worse on every axis**, and for the reason recorded on the knob *before* the run: the opening
message is re-sent every turn, so prefetched content is paid on **every** round trip while saving
only the first few reads. The coder did not read less (62 → 60); it just carried more.

### Three levers, one conclusion

| lever | shape | result |
|---|---|---|
| `coder_batch_reads` | ask the model to batch | **null** (1/30 vs 0/30) |
| `coder_prefetch` | give it the files up front | **negative** (+7% calls, +9% tokens) |
| a `read_files(paths)` tool | offer a batching tool | not built — see below |

Round-trip COUNT is a model behaviour: the engine cannot force the model to stop calling tools, it
can only make each call cheaper or offer alternatives the model may decline. Two of the three
available levers have now been measured and neither worked; the third (`read_files`) has the same
failure mode as the first — the model must choose to use it, and the batch-reads probe showed this
model declines batching at 3% even when explicitly permitted.

**Slice 4 is closed as a dead end for this model.** This is not a statement about the idea; it is a
statement about `qwen3-coder:30b`, and it is consistent with the standing vLLM / model-upgrade
direction. Both knobs stay default OFF and re-runnable against a future model, which is the
`oracle_structural_spec` precedent.

### What that leaves

The one lever measured to WORK this whole arc is deterministic replacement of a model judgement:
ADR-0124's engine-authored oracle, delivery 33% -> 100% on the shape it targets. Efficiency work
should follow that pattern, not the round-trip one.

## SLICE 2 — the coverage defect, FIXED but NOT demonstrated end-to-end

`change_is_covered` counted a changed line as untested unless it ran under a `test_function`
context. A module-scope statement — `__version__`, `__all__`, a dataclass field default, a decorator,
an import, a class body — executes at IMPORT time, so it can never carry a context and was
structurally uncoverable. The gate credited a **comment** (not executable, so the check passed
trivially) and refused a **version bump** the standing suite genuinely verified.

**The fix.** `import_time_lines` (AST) identifies statements outside every function body; those are
excluded from the must-cover set. When *every* changed line is import-time, the verdict is `None` —
the module's existing "coverage is moot" contract — which hands the decision to the caller's import
heuristic, and that still requires baselined tests asserting something real AND referencing the
changed module.

**Not a widening.** The exclusion never credits a line; it removes an unanswerable question and
defers to a check that can answer it. Pinned by tests: an uncovered *function-body* line still
denies, a mixed change is still judged on its coverable lines, an unmeasured file still denies, and
absent import-time info falls back to judging every line. Two tests were confirmed to fail with the
exclusion removed.

### The honest part: its practical reach is now smaller than when it was found

The defect was found on `MCB-32` under Approach **A**, where the reduced lane skipped the Proctor so
`standing_suite` was the deciding leg — it read False and the run parked with `oracle_unverified`,
3/3, grader passing.

Approach **B** shipped instead (ADR-0124), and B keeps `author_tests` and manufactures an oracle. So
`tester_vouched` is now True on those runs and `standing_suite` is `not_evaluated` — the leg the
defect lives in is short-circuited before it is reached. **Re-running MCB-32 with the fix therefore
does not demonstrate the fix**; it demonstrates B. Claiming the before/after as evidence would be
comparing two different configurations.

**What the fix is still worth:** the defect is real, structural, and affects every run where
`standing_suite` IS the deciding leg — a repo whose Proctor authors nothing, a `tester_vouched`
failure, or any future path that leans on the standing suite. It is correct by construction and
unit-tested. It is simply not the over-park win the arc hoped for, because B got there first by a
different route.

Also observed while checking: MCB-32 still over-parks ~2/3 under B, now on `validation_failed` +
`iteration_limit` rather than `oracle_unverified`. A different defect, not this one, and unexamined.
