# Decidability at intake — the axis the checkability verdict could not see (2026-08-04)

Status: **Historical record.** Measurement + detector validation. Not an effectiveness claim —
see *What this does not establish*.

## Why

Three demo runs on 2026-08-04 produced the evidence.

| run | brief states | outcome |
|---|---|---|
| **brownfield** | a **rule**: "raise `ValueError` if removing more than in stock; keep existing behaviour unchanged" | correct code, **0 fix iterations**, 2 file writes, gate clean |
| **greenfield** (run 1) | an **output shape**: "prints a strength score 0–4 plus reasons" | thrash park, `no convergence: 5→5→5` |
| **greenfield** (run 2, oracle posture on) | same brief | **passed the gate with 48 green tests** over a model where a 40-character single-class password scores the same 4 as a properly mixed one |

Two runs of one brief produced **two different invented scoring models**. The loop was not junior —
the input was. And the intake gate could not tell the two briefs apart:

```
greenfield  -> PARTIALLY_CHECKABLE   (5 material claims, 1 bound)
brownfield  -> PARTIALLY_CHECKABLE   (4 material claims, 2 bound)
```

`spec_lint.checkability` measures **bindability** — *can a checker be attached to this sentence* —
through `classify_sentence`'s verb lexicon. A sentence binds because it contains "prints". Nothing
asked whether the claim's **value is computable from the text**.

## The 2×2, and the cell that ships

|  | **decidable** | **undecidable** |
|---|---|---|
| **bound** | the target — brownfield | **the dangerous cell** — greenfield |
| **unbound** | unverifiable but honest | vague; already caught as `UNDER_SPECIFIED` |

Bound-and-undecidable is worse than unbound, because **binding grants confidence**. Greenfield's
"prints a score 0–4" bound to an `acceptance_test`, 48 tests passed, and the gate saw a fully
evidenced run. The tests proved an invented model had been implemented consistently with itself.

This failure was already known and thrice-observed. MCB-05/15 carry one sentence whose graders
disagree (`<=6` and `<=7` — *"no reader, human or machine, could derive 6 for one and 7 for the
other"*), and they are **100% of the suite's `false_ship`**. The
[2026-08-02 checkability analysis](brief-checkability-2026-08-02.md) *discovered* the property —
*"two readers of the same claim text disagree about what it means"* — and answered it with a
**mechanism** (ADR-0079's single binding) rather than a **metric**. The North Star already names
the missing property: *"Forge receives a near-deterministic brief."* Nothing measured it.

## Pre-registered prediction

Written as an **executable test before the detector existed**, so it could not be tuned to pass:

1. MUST flag MCB-05 and MCB-15.
2. MUST flag `demos/greenfield/BRIEF.md`; MUST NOT flag `demos/brownfield/BRIEF.md`.
3. MUST NOT flag MCB-13 (`score >= 90 -> 'A'`, an explicit mapping) or MCB-21 (enumerated modules).
4. **At most one further MCB case.** More than that ⇒ the detector is too broad and gets narrowed
   *before* landing, never the prediction relaxed.

## Scored

```
cases: 24
FLAG MCB-05 | 'a handful' states a magnitude that does not resolve to a count
FLAG MCB-15 | 'a handful' states a magnitude that does not resolve to a count
greenfield  PARTIALLY_CHECKABLE  UNDECIDABLE
            names the range 'strength score 0–4' as an output but states no
            rule for how the value is composed
brownfield  PARTIALLY_CHECKABLE  DECIDABLE
```

**2 of 24**, exactly the two cases that are all of the suite's false ships, and the two demo briefs
separated — from brief text alone, with **zero runs**.

Prediction 4 did the work it was pre-registered to do. Two rounds of narrowing were forced:

- **Bare adjectives cost 5 false positives.** "small"/"short" across this corpus describe the
  *project* ("build a small, self-contained todo manager"), not a countable requirement. Dropped;
  a **scale noun** is now required.
- **A bare `N - M` range matched arithmetic inside an example** (`"1 + 2 - 3"`). Same fix.
- **The suppressor had to become clause-scoped.** MCB-05 reads *"a short orchestrator **(a handful
  of statements)** that delegates to **at least three** helper functions"* — one sentence carrying
  an undecidable clause and a decidable one. Sentence-wide scoping let "at least three" silently
  excuse "a handful", which is the very phrase its two graders disagree over.

**Independent corroboration, from a fixture that predates the check.** `test_decompose_spec_lint_
silent_when_clean` used *"strength(password) returns a score 0-4 and a non-empty list of reasons"*
as its example of a **clean** item. The detector flagged it: CHECKABLE **and** UNDECIDABLE — the
dangerous cell, and the greenfield shape verbatim, written months earlier by someone with no
knowledge of this axis. The sample moved; the assertion did not.

## What shipped

Report-only. Nothing blocks, nothing new asks.

- `spec_lint.decidability()` / `decidability_findings()` — a **sibling** verdict, not a widened one.
  The axes are orthogonal, and two correct existing tests pin the current shape (`test_checkable_
  item` asserts the whole dict; `test_under_specified_item_fires_the_finding` asserts `len == 1`).
- The backlog GET carries `decidability` beside `checkability` (additive fields only).
- **Quincy's context marks it.** Previously only `UNDER_SPECIFIED` was tagged, so a bound-and-
  undecidable item read to him as indistinguishable from a good one — the exact blind spot.
- `_lint_and_recurate` joins the findings into the existing one-pass re-curate.

**Deliberately untouched:** the launch gate, the clarify fence (`== "UNDER_SPECIFIED"`), and
`nodes_plan.py`'s plan-entry park. ADR-0080 names clarification fatigue as the stated hazard and
calls the ask-rate *"a measured dial, not a promise"* — so this cut measures before it asks.

## What this does not establish

**This validates the detector, not effectiveness.** ADR-0080 binds us: *no effectiveness claim
without proven arm divergence on a new case class.* Today's greenfield two-models observation **is**
that missing case class, and `#59` MCB-D is the instrument that would let us claim the check
improves outcomes rather than merely identifies inputs. A lexical detector is also crude by
construction: it covers patterns with three observed failures behind them and grows only when a new
failure class appears.

**Open:** the MCB-05/15 grader alignment decision (see
[grader-alignment-brief-2026-08-04.md](grader-alignment-brief-2026-08-04.md)) — if those graders are
aligned, the corpus loses its two false ships and this detector loses its two positives, which is
the correct outcome for both.

## The backfill — the same mechanism pointed backwards

`checkability` and `decidability` judge `todo` items only (`spec_lint.py`: `if
str(item.get("status", "todo")) != "todo": continue`, four times). That is right for the run path —
settled work isn't re-judged mid-run — and it is exactly why **work authored before these checks
existed has never been looked at by them**. Everything already delivered is invisible to both.

`diagnose_item` / `diagnose_backlog` are the status-blind entry point. Deliberately a **separate
primitive rather than a widened filter**: widening would silently change what every existing caller
sees, including the clarification gate and the re-curate pass. Pinned by a test asserting the
run-path verdicts still return `{}` for a settled item after the diagnosis has read it.

An item is **non-compliant** in the two states the engine actually treats as broken:
`UNDER_SPECIFIED` (nothing binds — parks a run today) or `UNDECIDABLE` (the text does not fix its
answer — ships invented evidence). `reasons` names each failure rather than stopping at the first.
`PARTIALLY_CHECKABLE` is deliberately not one of them — see defect 2 below, which is how that rule
got calibrated.

Two decisions worth keeping:

- **Derived at read, never stored.** A `compliant` column would freeze today's detectors into the
  schema and go stale the moment they improve — and today's detectors are two weeks old and already
  narrowed twice. Recomputing keeps the answer honest, needs no migration, and makes the pass
  repeatable. *If the verdict ever becomes stored, that crosses the schema/artifact-contract bar
  and needs an ADR + migration + replay analysis.* Read-only and derived, this sits with
  `GET /projects/{id}/metrics`, which has none.
- **A flag is not an accusation.** For settled work, non-compliant says *the acceptance text could
  not have gated this*, **not** *the delivered code is wrong*. That sentence rides in the API
  payload's `note`, the card's hover, and the docstrings, because the over-claim is the obvious
  failure mode of a backfill and it is the one the anti-gaming rules forbid most directly. The
  board chip is deliberately quiet ("Pre-standard", neutral tone), and it is suppressed on `todo`
  items, which already carry their own live chips.

Surfaces: `compliant` + `compliance_reasons` on every backlog row (all statuses), a read-only
`GET /projects/{project_id}/compliance` summary (totals, `by_status`, per-item rows with
`created_at`), and the card marker.

## Driving it as operator — two defects the tests could not have found

Both were found by *using* the check against the live API, not by reading it. Neither would have
been caught by any test I would have thought to write, because both were errors in my model of
what the check should say.

**1 · A rule one sentence later still fixes the value.** Repairing the greenfield brief exactly as
the finding instructed — *"state the rule that fixes the value"* — produced a brief that **still
scored UNDECIDABLE**, because the rule landed in the next sentence and the suppressor's scope was
the claim. That is a false flag on a correctly-repaired brief: report-only it costs one sentence in
a curate instruction, but the moment the check gates anything it blocks good work, which is the
fastest way to teach an operator to ignore it.

The two patterns now take **different suppressor scopes**, because they fail for different reasons:
vague magnitude stays clause-scoped (a countable elsewhere does not fix "a handful" — the MCB-05
shape), while a named output scale is block-scoped (bullet/paragraph). Block, not document: the
original greenfield brief has `->` in its *second* bullet and must still flag. Corpus prediction
re-scored and unchanged — 2/24, MCB-05 and MCB-15.

**2 · A partially-checkable brief is not a failure.** The first compliance rule was `CHECKABLE ∧
DECIDABLE`. Under it:

```
brownfield (the GOOD brief)  PARTIALLY_CHECKABLE  DECIDABLE    compliant=False
greenfield (the BAD brief)   PARTIALLY_CHECKABLE  UNDECIDABLE  compliant=False
```

The same verdict for both — **the exact failure this arc exists to fix, reintroduced one layer up
in my own compliance rule.** `PARTIALLY_CHECKABLE` is the modal state of a real brief and blocks
nothing in the engine today. Non-compliance is now the two states the engine actually treats as
broken: `UNDER_SPECIFIED` (nothing binds — parks a run today) or `UNDECIDABLE` (ships invented
evidence).

**Verified live** through the running API against the real project: the item flags, the operator
states the rule via `PATCH`, the flag clears, the rule is removed, it flags again. Quincy's real
context line carries `[decidability=UNDECIDABLE]` and **no** checkability marker — the blind spot,
visible. The scratch item was deleted afterwards; the project is as it was found.

The general lesson, which is the same one #58 taught about our own CI: **an instrument nobody has
driven is an untested instrument**, however green its unit tests are.
