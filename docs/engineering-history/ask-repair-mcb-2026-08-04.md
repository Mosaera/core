# Repairing the ask: MCB-05/15 (2026-08-04)

Status: **Historical record.** A signal check at n=3 per cell on two cases — not a suite-level
effectiveness claim. See *What this does not establish*.

## Question

MCB-05 and MCB-15 both say the orchestrator should be "a handful of statements"; their hidden
graders assert `len(fn.body) <= 6` and `<= 7`. If stating the rule in the brief clears both, the
**ask** was the defect for these cases and no new machinery is needed for them.

## Design, and the contamination it had to survive

**The graders were read before the repair was written.** Knowing the answers is exactly how you
manufacture a pass, so the design had to be robust to it:

- **One rule, identical in both briefs, matching neither grader number.** Both repaired briefs state
  *"its body is at most 5 statements"*. Verified mechanically: neither `6` nor `7` appears anywhere
  in either repaired brief.
- **5 is derived from the brief's own text.** It already demands delegation to *at least three*
  helpers, so a compliant body is three calls plus a return, with one local to spare.
- **5 is stricter than both graders**, so obeying the stated rule clears both by construction — it
  does not aim at either. A run delivering 6 statements *fails* the stated rule while *passing*
  MCB-05's grader; the arms are not aligned to the oracle.
- **Graders and seeds byte-identical between arms** (hash-verified). Only the brief text differs.
- **Gate before running:** the decidability check must score control `UNDECIDABLE` and treatment
  `DECIDABLE`, else the repair does not address the finding and the experiment does not start. It
  did.

Arms: `MCB-05`/`MCB-15` (control) vs temporary `MCB-05D`/`MCB-15D` (treatment), n=3 each, 12 runs.
The experimental case directories were deleted afterwards; the shipped corpus is unmodified.

## Result

```
                 grader          statements   failing assertion
MCB-05  control  7/8, 7/8, 7/8   8, 8, 8      short_orchestrator x3   (limit 6)
MCB-05D treated  8/8, 7/8, 8/8   -, 8, -      short_orchestrator x1
MCB-15  control  6/7, 6/7, 6/7   9, 9, 8      short_orchestrator x3   (limit 7)
MCB-15D treated  7/7, 7/7, 7/7   -            none
```

**Control 0/6 grader-clean; treatment 5/6.** Fisher exact, two-tailed: **p = 0.015**.

The mechanism is visible, not inferred: the control runs do not miss by one. They deliver **8 and 9
statement** orchestrators against limits of 6 and 7 — "a handful" was being read as roughly twice
what the grader meant. The disagreement is not 6-vs-7 at the margin; it is a brief that fixes no
value at all being read generously.

## The false-ship framing was wrong

**All 24 runs across both matrices ended `honest_park`, `delivered=False`, gate reason
`unsatisfied_claim`. Zero ships, zero false ships, in either arm.** In this configuration these
cases do not lie — they refuse.

So what a vague brief costs here is not a bad ship. It is a **guaranteed park**: work that cannot
satisfy a rule nobody stated, burning a full run to discover it. The
`false_ship 6.9% (MCB-05/15 only)` attribution belongs to a different configuration and should not
be repeated without re-deriving it.

## The correction worth keeping

The first matrix could not be interpreted at all: re-grading the finished workspaces gave full
passes that the run-time grade had not reported, and I raised that as a possible integrity problem
in the capability scoreboard. **That was wrong.** `overstrict_vs_reference` deliberately overlays
the case's *reference solution* onto the workspace after grading — its docstring says so
(*"it destroys the delivered code; that is fine because grading is complete"*) — via `shutil.copy2`,
which preserves the reference's mtime. A post-mortem bench workspace therefore holds the reference
implementation wearing the seed's timestamp, **not the delivery**. The scoreboard was correct; the
post-hoc method was not. Recorded because the next person to inspect a bench workspace will reach
the same wrong conclusion.

What made the second matrix readable was persisting what the grader saw (`grader_failed_tests` +
`grader_output_tail`, and `--tb=line -rf` so the assertion text survives). The counts alone —
"7/8" — cannot be reconciled against anything. First round after the fix named the failing
assertion and quoted the statement count, in one line, with no guessing.

## What this does not establish

n=3 per cell, two cases, one operator. It is a signal check, not a suite-level claim, and it says
nothing about whether the decidability *detector* improves outcomes generally — that needs paired
variants across many cases (the MCB-D instrument, `#59`).

**And the repair was authored by a human, not derived by the system.** Two briefs were fixed by
hand; nothing recorded that "short orchestrator" means ≤5 statements, so the third case asks again,
and so does every refactor item after it. That gap is the standing-standards tier of
[ADR-0082](../adr/ADR-0082-gate-decisions-and-standards.md) — decide once, inherit everywhere — and
it is what would turn this result into leverage rather than a demonstration.
