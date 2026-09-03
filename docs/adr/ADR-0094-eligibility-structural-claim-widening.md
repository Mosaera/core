# ADR-0094 — Layer-2 eligibility admits a structural-claim-only park, to measure what the gate cannot currently be scored on

- **Status:** accepted
- **Date:** 2026-08-09
- **Amends:** [ADR-0074](ADR-0074-layer2-park-to-ship-disposition.md) (class-1 eligibility), [ADR-0092](ADR-0092-claim-reason-split.md) (whose classification is deliberately NOT changed)
- **Scope:** `packages/core/mosaera_core/eligibility.py` (new), `config/_knobs.py`, `config/_settings.py`, `bench/cli.py`
- **Invariants:** *Evidence-Gated Advancement*, *Deterministic Final Authority*, *Control Points not Headcount*, *Capability through Auditability*
- **Amended by:** [ADR-0095](ADR-0095-non-use-oracle-subtract.md), [ADR-0097](ADR-0097-consumer-impact-modify.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context — the empty column

The 193-run sweep (2026-08-09, all 24 cases ×8) measured Layer 2 end to end:
**74 honest parks → 13 eligible → 13 attempted → 1 converted, 0 false ships.**

The headline is not the conversion count. It is that **all 13 eligible parks were on work the hidden
grader PASSED**. Zero were on wrong work. The gate has therefore **never once been handed a wrong
delivery to refuse**, so its 12 refusals cannot be scored as correct — there was nothing there to
catch. **Measured discrimination is UNDEFINED, not good.** On this record Layer 2 is indistinguishable
from a mechanism that says no to everything, and 12 of 13 times that "no" discarded correct work.

One conversion also bounds nothing: the rule of three puts the 95% upper bound on the false-ship rate
at 300%.

Of the 61 parks turned away, 41 were correct work. Their blockers:

| Blocker | n | grader RIGHT | grader WRONG |
|---|---|---|---|
| `claim_structural_failed` **alone** | 17 | 10 | 7 |
| behavioral claim + security + `validation_failed` | 25 | 21 | 4 |
| reviewer objection + `validation_unavailable` | 8 | 0 | **8** |
| security + `validation_not_attempted` | 7 | 7 | 0 |
| `critic_vetoed` | 2 | 2 | 0 |

## Decision

**Admit a park whose only blocking reason is `claim_structural_failed`**, behind the knob
`layer2_admit_structural_claim`, **default OFF**, and read **only by the bench**.

Every other bucket is degenerate and stays refused, on evidence rather than principle:

- **`security_unverified` is never alone in a reason set** — it always rides with failed or
  unattempted validation, so for **class 1** relaxing it unlocks nothing.
  **CORRECTION (2026-08-09, F84):** this ADR originally generalised that to "relaxing Sentinel's
  veto would unlock exactly zero runs — dead on data." **That is false for class 2.** Class 2
  admits `validation_failed` as a `shortfall` (its entire premise), so there
  `security_unverified` **is** the sole blocker — on **25 parks, 21 of them correct work**. The
  decision below is unaffected (the structural bucket was chosen for being the only *mixed* one),
  but the reasoning was wrong and is corrected here rather than quietly left standing.
  **The right response is still not to relax the veto:** `security_unverified` means a scan was
  EXPECTED and produced NO verdict — absence of evidence, not a finding (`security_findings` was
  raised **zero** times in 193 runs). It fires on **17%** of runs. That is a scanner-availability
  defect, tracked as **F84**, and fixing availability removes the blocker without touching the
  control.
- **Reviewer objections were 8-for-8 on wrong work** — perfect discrimination. Untouchable.
- **Failed / unattempted validation** cannot ship on principle, whatever the grader later says.
- **A held-out critic veto** is an independent control finding a real defect.

The structural bucket is the **only MIXED one**, and therefore the only one that can put genuinely
wrong deliveries in front of the gate. That is its entire purpose: it makes the empty column
populable with 7 known-wrong deliveries.

**`REASON_CLASS` is deliberately not edited.** `claim_structural_failed` remains an `objection`
(ADR-0092). Reclassifying it would have been the one-line version of this change and would have
widened *every* consumer of that table at once — including class 2's derived admission policy —
silently. A narrow named exception in one predicate is what makes this measurable and reversible.

`eligibility.py` is split out of `disposition.py` (which sat at exactly 500/500). The boundary is
real and worth naming: **this module decides who is checked; `disposition.py` performs the check.**

## This is not a gate weakening — and here is the line

`close_oracle_gap`'s green + comprehensive-mutation steps are **untouched**. A park still stands
unless they independently vouch for it. What widens is who is *attempted*.

That distinction is load-bearing, so state the counter-argument too: eligibility is **not inert**. It
is what keeps a security-objected or critic-vetoed park away from an automated ship, which makes it
partly a control. Hence the widening touches exactly one reason, is default OFF, is bench-only, and
is pinned reason-by-reason by `test_eligibility_widening.py`.

The anti-gaming rule forbids weakening a gate to improve a benchmark number. This is the opposite
motion: it admits **7 deliveries known to be wrong** in order to find out whether the gate catches
them. The expected outcome is *more* refusals, and a result that could well condemn the mechanism.

## Red team (1 pass — knob-gated stopgap with a planned successor)

- **R1 — benign-reason smuggling.** No finding. `iteration_limit` / `reviewer_unknown` cannot carry a
  real blocker past the subset test. The subset test also required an explicit non-empty check:
  `set() <= anything` is True, so without it a park with no blocking reason would have become
  convertible. Pinned.
- **R2 — the knob is a no-op in production.** Confirmed and **ACCEPTED as containment**: the API rung
  never threads the flag, so the widening cannot reach a live ship. But a knob nothing reads is this
  repo's most-repeated defect (F74), so the no-op is *pinned by a test* — threading it into
  production means deleting that test, a deliberate reviewed act rather than a silent widening.
- **R3 — a conversion here ships an unsatisfied structural claim. ACCEPTED, documented.** The gate
  proves *behaviour* (green + mutation); it does not check AST shape. So a park admitted under this
  knob can convert while its declared structural claim is **known to have failed**. This is the
  sharpest residual and the reason the knob is bench-first: the 7 known-wrong deliveries are exactly
  the population that tests whether behavioural proof is sufficient without structural proof. It
  relates to ADR-0090's R2 residual (an *unevaluable* structural claim emits no reason at all).

## Consequences

Expected: eligible attempts roughly double (13 → ~30) and the WRONG column becomes non-empty for the
first time. **Predicted from stored cards: all 17 admitted, 10 right / 7 wrong** — a prediction the
re-run either confirms or falsifies.

**Pre-registered:** if any of the 7 known-wrong deliveries CONVERTS, that is a false ship, and it
condemns the mechanism rather than the knob — `disposition_gap_close` would stay off permanently
pending a redesign. If they are all refused, that is the first evidence Layer 2 discriminates at all.
Either way the knob stays default OFF and out of production until the number exists.
