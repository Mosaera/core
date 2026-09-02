# ADR-0083: The governance benchmark — grade the system that produces the brief

- Status: accepted
- Date: 2026-08-05
- Owners: @Ashura
- Related issue: #68 (the governance instrument; Wave 3)
- Related: [ADR-0007](ADR-0007-capability-benchmark-suite.md) (MCB — the suite this one deliberately
  does not touch), [ADR-0080](ADR-0080-intake-clarification.md) (the ask this measures),
  [ADR-0081](ADR-0081-control-liveness-ladder.md) (a control nobody runs is a control that rots),
  [ADR-0082](ADR-0082-gate-decisions-and-standards.md) (the clause tier whose promise `compounded`
  checks), [ADR-0061](ADR-0061-v1-measured-definition-of-done.md) (Gate 2)

## Context

MCB hands the loop a **good brief** and grades what the coder does with it. Every case was written
by someone who already knew the answer, so the suite has no under-specified brief in it — measured,
not assumed ([brief-checkability-2026-08-02](../engineering-history/brief-checkability-2026-08-02.md)).
That makes MCB an excellent capability instrument and a blind one about the half of the product
that turns a human's request into a brief.

Two consequences arrived in the same week and are the reason this exists:

1. **A standing decision was inert for its whole life.** The clause overlay was seeded into the
   graph and never DECLARED in `RunState`, so LangGraph dropped it. Every unit test was green
   throughout. Nothing could have caught it, because nothing graded intake end to end.
2. **The one false ship in the 2026-08-05 re-baseline (n=72) was a no-op** — MCB-18, a one-line
   diff certified by a pre-existing suite, because `standing_suite_is_independent_oracle` is a
   *relevance heuristic* being used as a *sufficiency oracle*. A suite written before the task
   existed cannot fail for behaviour the task introduces.

Measurement, not capability, is the meta-blocker (ADR-0081). This is the instrument for the part
of the system that had none.

## Decision

**1. A second, separate suite: `packages/core/mosaera_core/govbench/`, cases `G-NN`.**

Separate rather than more MCB cases. MCB's `overall` is a tracked number with per-case baselines,
and a floor you keep editing is not a floor. Governance dimensions carry `bucket="governance"`;
`overall` averages the `capability` bucket alone, so it is byte-identical with them present.
Asserted structurally (`_CAPABILITY_WEIGHTS` never names a governance dimension) and by case count
(~~`available_cases() == 24`~~ — **`== 26` since 2026-08-09**; corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`. MCB-27 (subtract, ADR-0095) and MCB-28 (modify, ADR-0097) each moved the count with a reviewed diff. The count is the coarse half of the tripwire; the half that actually guards leakage is the `G-` prefix exclusion, which has never changed.)

**2. The case IS the pre-registration.** A case declares — before it is ever run — the verdict the
detectors must produce and whether an operator question is the right response. A case whose verdict
disagrees with its declaration is a **broken case, not a finding**: `score_governance` raises rather
than reporting a low score, because reporting one would launder a fixture bug into a claim about the
system. This caught two broken cases of mine on the suite's first run.

Unlike MCB's loader, an unknown `case.toml` key **raises**. In a suite whose entire subject is
expectations, a typo'd expectation that silently does nothing is worse than a crash.

**3. Two arms, and the cheap one is a standing gate.**

- **Deterministic** (`make test`, no model, no Docker, seconds): runs the REAL loop —
  `run_intake_pass`, the real detectors, the real diversion, the real resolve-through-`enhance` —
  against an in-memory store with only the PM's *proposal* stubbed. It measures ROUTING, not
  Quincy's judgement, and the scorecard says so.
- **Expensive** (`python -m mosaera_core.govbench.live`, opt-in): real coder runs, graded by the
  hidden suite.

The cheap arm runs in `make test` deliberately. An opt-in control is how the last one rotted.

**4. Three cheap dimensions.** `Detected` (declared verdicts reproduced) · `Asked` — **precision AND
recall, never a count**, because an instrument that counts asks scores a system that asks about
everything as perfect, which is exactly the fatigue hazard ADR-0080 names and the same trap as MCB
scoring "parked for a human" 30/100 · `Compounded` (a ratified decision stops the question
recurring — the clause tier's whole promise, unchecked end to end until now).

`G-03`, whose correct behaviour is **silence**, is what makes over-asking observable at all.

**5. The expensive arm classifies a park as `unevaluable`, never as a failure.** A park claims
nothing, so nothing it claimed can be wrong. It also grades parked runs, because a park whose
grader PASSES is the over-park defect — 4 of 5 `thrash_park`s in the 2026-08-05 sweep were correct
work destroyed by our own gates, invisible in every headline.

**6. `G-01`'s grader is derived from the operator's answer and nothing else.** That is what turns
"it should have asked" from a procedural claim into a measured one: the `raw` and `resolved` arms
differ by exactly the operator's reply, so if the unasked arm scores the same, asking bought
nothing and this ADR is wrong on its central point.

**7. The arms are compared on grader SCORE, and a difference is claimed only when the arms
SEPARATE.** Added 2026-08-05 after the first live sweeps
([record](../engineering-history/govbench-first-sweeps-2026-08-05.md)), which falsified two
assumptions in the original text:

- *A verdict comparison suffices.* It does not. The first version required
  `raw == false_ship and resolved == matched`; on a run where the unasked arm scored 5/17 and the
  asked arm 16/17 it reported "asking bought nothing", because neither reached a clean pass. A
  comparison that cannot see its own largest effect is not a comparison.
- *One run per arm reads a direction.* It does not. At n=3 per arm the same case gave raw
  {0.31, 0.38, 0.75} and resolved {1.00, 1.00, 0.00} — overlapping ranges, mean delta +0.19, **not
  separable from run-to-run variance**. The n=1 result had been a draw from a wide distribution.

So `asking_paid` now requires n≥2 per arm **and** every asked run to beat every unasked one. Crude,
but it is the only bar that means anything at these sample sizes, and it is declared before the
numbers rather than chosen after them. `--repeat` exists to earn it.

**A brief that fixes no answer produces an UNSTABLE one, not merely a wrong one.** G-01 spans
0.00–1.00 across six runs while G-05 (decidable) is 1.00 three times. That is a stronger claim than
the ask mechanism was originally justified by, and it is the cheaper one to test next.

## Consequences

- `make test` gains a gate that can fail the build. Accepted — the alternative is the posture that
  let a dead control survive.
- **The cases are authored by me.** `G-01`/`G-04`/`G-05` derive from measured failures, `G-02`'s
  convention is one this repo actually enforces, `G-03` is a control. That is the best footing
  available and still weaker than a hidden grader, and it is to be said whenever the numbers are
  quoted. **Measured base rate: on day one, three of this project's own assertions graded requirements the
  operator never fixed** (output verbosity, boolean amounts, empty input), and two of them scored
  correct work as `false_ship`. The author's failure mode here is over-strictness, which points the
  same way as the over-park defect. A reference proves a grader is *winnable* and says nothing about
  whether it *discriminates* — hence `wrong/`, an adversarial overlay the grader must reject.
- `G-02` and `G-05` have **decidable** acceptance by design; their failure modes are downstream
  (not reading the repo, not verifying the work) and only the expensive arm can see them. A green
  cheap arm must not be read as covering them.
- The cheap arm cannot measure whether the PM would have proposed anything sensible. It measures
  whether a detected ambiguity reaches the operator and whether a decision silences it.
- MCB is untouched: no case added, no baseline moved, no weight changed.

## Alternatives rejected

- **Add governance cases to MCB.** Rejected: it moves a tracked headline and makes the frozen suite
  non-comparable across the very sweeps it exists to compare.
- **Score `Asked` as a count of asks raised.** Rejected: it rewards asking about everything, which
  is the failure mode, not the goal.
- **Keep the whole suite opt-in.** Rejected: that is precisely how the clause control stayed dead
  for its entire life with green tests.
- **Grade `G-01`'s output format.** Rejected: the operator fixed the score, not a layout. Grading a
  format nobody specified would be this suite committing the sin it measures.
