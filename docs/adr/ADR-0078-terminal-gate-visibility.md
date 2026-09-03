# ADR-0078: Terminal gate visibility — the benchmark must see why a run parked

- Status: accepted
- Date: 2026-08-02
- Owners: @Ashura
- Related issue: measurement defect found while mining the scorecard corpus (1,233 runs)
- Related: [ADR-0053](ADR-0053-reliability-scoreboard.md) (the scoreboard this feeds),
  [ADR-0065](ADR-0065-held-out-critic.md) (whose arc metric was structurally zero),
  [ADR-0069](ADR-0069-gate-loop-honest-stop.md) (the FROZEN classifier this must not disturb),
  [ADR-0060](ADR-0060-honest-stop-lean-engine.md) (the `rode_to_cap` compensation)

## Context

Mining every benchmark scorecard on disk (**1,233 runs**, 2026-07-10 → 2026-08-02) surfaced two
figures that cannot both be true of a working system:

- `meta["gate_reasons"]` is `[]` on **all 526 instrumented runs**.
- `meta["critic_vetoed"]` is `False` on **643/643 runs**.

The second follows from the first: `bench/cli.py` derives it as `"critic_vetoed" in gate_reasons`.
So ADR-0065's arc metric — the held-out critic's fire rate, which `compare.py` aggregates as
`critic_vetoes` — has been **structurally zero since it shipped**. A veto is a downgrade that
*parks*, and a park is precisely the case whose evidence was discarded.

### Root cause

`gate_node` puts its decision in the **interrupt payload** and only returns `gate_decision` into
state *after* the interrupt resumes. `bench/harness.py::_resolve` parks by returning without
resuming, so the terminating visit never commits. The result is worse than "empty": on a
deny→replan run, `final["gate_decision"]` holds a **stale earlier-visit** decision that *was*
resumed.

**This exact bug was already found in production and fixed there.** `apps/api/.../runner/_loop.py`
stashes the decision off the interrupt payload, with the comment: *"The break happens AT the gate
interrupt, before the gate node returns `gate_decision` into the state… Without this, escalation
silently no-ops on every gate-blocked item (found live)."* The bench never received the same fix.

It is the third instance of one pattern — a control or metric that looks live but cannot fire.
The other two, both found the same week: `reviewer_advisory` (zero engine reads behind a live UI
toggle over gate policy), and ADR-0071/0072 held "pending measurement" whose measurement was never
run. **Decisions were being deferred on measurements that could not produce a signal.**

## Decision

Capture the gate decision from the interrupt payload in `bench/harness.py::_resolve`, on a new
`RunOutcome.terminal_gate_decision` field, and read it through a `terminal_reasons` property that
falls back to the committed decision. `bench/cli.py` sources `gate_reasons` from that property;
`critic_vetoed` and the layer-2 JSONL reuse the same local and need no edit.

**Last-wins is correct by construction:** `_resolve` returns immediately on a park, so the final
assignment is the visit that actually terminated the drive. Earlier assignments were denials the
run moved on from.

Scope: only `action == "deliver"` carries a gate decision (`policies/approval.py` is its sole
producer). Escalation interrupts carry `kind`/`reason`; write gates are disabled headlessly.

### The constraint that shaped this — never merge into `final`

The live runner merges its captured decision back into `final`. **Copying that here would be a
bug**, because `reliability.classify_outcome` reads `final["gate_decision"]["reasons"]` and buckets
`iteration_limit` as thrash. Making those reasons visible to the classifier would flip runs
`honest_park → thrash_park` and **silently move the clean-conclusion headline** — a metric the
owner accepted at 94.4%.

That classifier is FROZEN (ADR-0069), and ADR-0060 gave it a `rode_to_cap` check that reads
`final["iteration"]` *precisely to compensate* for this missing data. The compensation is already
there; re-adding the raw signal would double-count it.

So: **measurement is allowed to see more than the classifier does.** That asymmetry is the design,
not an oversight. Whether the classifier should eventually consume the captured reasons is a
separate, deliberate, measured decision.

## Consequences

- Park causes become legible for the first time — including the 312 recent over-conservative parks
  whose reasons were previously unrecoverable.
- `compare.average` gains `park_reasons` (a plain `Counter`, sorted). Without it the **averaged**
  card — the one `--compare` / `--update-baseline` actually write, since repeat defaults to 3 —
  would drop the newly-captured evidence one layer above where it was captured.
- **Historical comparisons across this boundary are invalid.** Every pre-ADR-0078
  `critic_vetoed: False` means **unmeasured**, not "no veto". Any before/after chart of
  `critic_vetoes` spanning this change is a fiction.
- Backward compatible: `compare()` reads only `overall`/`dimensions`/`cost`; `suite.py` reads only
  outcome/taxonomy keys; `scorecard.meta` is free-form JSON. Old cards stay loadable and inert.

## Deliberately NOT done

- **`build_inputs`' `reviewer_verdict`** has the same blind spot, but it is a *scored* input —
  sourcing it from the capture would move dimension scores and every committed baseline.
- **`diagnose_bottleneck`** is blind the same way, so on a parked run the escalation ladder loses
  its most specific signal. Fixing it would change *which runs re-run with which model* — a
  behavioural change, not a measurement one.
- **`apps/api`'s residual** — a parked run that is cancelled or orphan-finalized still never
  commits, so `persist.py` records no gate-decision row. Terminal-only and narrow.

Each is a real defect; each needs its own evidence, and none may ride in on a measurement fix.

### A FOURTH residual, missed here and found 2026-08-08 — now closed

This list should have had four entries. **Layer 2's eligibility predicate reads
`final["gate_decision"]` too** (`convertible_park_class` / `convertible_decline_reason`, called from
`bench/cli.py`), and Layer 2 (ADR-0074/0075) predated this ADR by ten days — so it was there to be
enumerated and was not. It is also the residual that mattered most: the other three degrade a
*measurement*, this one gates the mechanism that can **ship code unattended**.

Measured cost, found by driving the mechanism rather than reading it: **2,049 stored scorecards,
544 honest parks, Layer 2 eligible ZERO times.** Its own decline recorded *"no blocking gate reason:
not a park this disposition is for"* — the plausible-sounding wrong answer `convertible_decline_reason`'s
docstring warns about — while the scorecard beside it read `gate_reasons=['claim_structural_failed']`
from the capture this ADR built. Two sources, one blank.

**Closed under this ADR's own reasoning, not a new decision.** `_resolve` now also captures
`claim_dispositions` and `claims` (same payload, same seam — their absence is why ADR-0090's
`unsatisfied_claim_kinds` read `{}` on a parked card), and `RunOutcome.terminal_state` composes them
over `final` for readers that judge the park. **The writer-side fix was rejected precisely because of
the constraint above** — putting the decision into state would show the frozen classifier the
captured reasons and move the clean-conclusion headline. `terminal_state` gives that asymmetry a name
so it stops being a convention each call site has to remember. Verified: `reliability.py` shows 0
changed lines and both guards still pass.

Post-fix measurement (20260808-16, n=10): the decline now reads *"class1: core reasons beyond
oracle_unverified: ['claim_structural_failed']"* — the true blocker — and `unsatisfied_claim_kinds`
carries `{'ast_transformation_contract': 3}`. Still 0 conversions: those parks were structural, which
ADR-0092 classifies `objection` and deliberately does not rescue. Whether the mechanism can convert
correctly is measured separately, on cases that produce class-1 parks.

## Verification

- `reliability.py` shows **0 changed lines** — part of the evidence, checked in the diff.
- `test_capture_never_mutates_the_frozen_classifier_input` builds the captured reasons as
  `["iteration_limit"]` — the one reason whose leakage would move the metric — and asserts
  `classify_outcome` still returns `HONEST_PARK`. Invariance here is **structural, not empirical**:
  bench runs are stochastic, so re-running the corpus could never prove it. That test *is* the
  evidence.
- `test_critic_veto_is_visible_on_a_parked_run` pins the 643/643 defect.
- A source-level ratchet in `test_bench_reliability.py` asserts `cli.py` still passes `run.final`
  to both classifier calls, catching the "tidy up that asymmetry" refactor at the call site.

## What this unblocked — answered same day

The question the corpus could not answer: **does the held-out critic ever actually veto?**

**It does — but not on MCB-05, and that is correct behaviour.** Wiring verified sound end-to-end
(`outcome_verdict` DECLARED, node spliced on `review→gate`, `critic_enabled` posture-ON,
`held_out_ok()` True). Through the real `judge_outcome` path, a **blatant** MCB-05-shaped defect
(0 helpers) draws a **VETO** with correct reasoning quoting the spec — so model, prompt, parse and
calibration all work. The **subtle** shape (3 helpers, long orchestrator body — MCB-05's *actual*
failing criterion per ADR-0072) yields **no confident verdict**, i.e. no veto. Live: MCB-05 ×3 → 0
vetoes, MCB-10 ×3 → 0 vetoes (no over-veto either).

So `critic_vetoed: False` on 643/643 was **two things compounded**: this ADR's blind spot, *and*
the critic correctly declining a judgement it cannot make confidently ("when unsure, SHIP" — the
safe direction, by design). ADR-0065 is not inert. *Not established:* whether that abstention is
genuine uncertainty or an empty/unparseable reply — the raw-capture harness used was flawed and its
output is discarded rather than reported.

The consequence for Gate 2 is recorded in [`docs/roadmap.md`](../roadmap.md): MCB-05's defect is a
fuzzy shape judgement, an LLM judge abstains from it, and a deterministic rule can only call it via
an arbitrary constant — which is why ADR-0072's relative-measure successor is the next arc.

Either answer was worth more than the measurement was costing; this one redirected an arc.
