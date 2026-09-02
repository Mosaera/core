# ADR-0062: Proctor faithfulness — deterministic over-strictness detection, not auto-rewrite

- Status: accepted
- Date: 2026-07-19
- Owners: Mosaera core
- Related issue: `#57` (the correctness-oracle arc, ADR-0061 gate 2); successor to `#56` (honest-stop)
- Trust boundary: the auto-loosen variant (MR-C) touched the oracle's *inputs* → red-team REQUIRED;
  it was reverted (below). The shipped detector is DETECTION-ONLY and changes no trust boundary.

## Context — the instrumented finding

`#56` measured `thrash_park` as the dominant non-clean bucket. To find the root cause, **three MCB cases were instrumented** through the real autonomous posture (captured the run's own `test_output`, the hidden
grader verdict, the Proctor-authored tests, and the coder diff):

- **MCB-01** (todo CLI) delivered, grader 8/8 — but the Proctor authored `assert lines[0] == "1 [ ]
  Buy milk"` (**exact whitespace** the spec left open).
- **MCB-21** (journal tag CLI) delivered, grader 8/8 — Proctor authored `stdout.count("#important")
  == 1` (**pins the `#` rendering**).
- **MCB-14** (extract-validation refactor) parked `honest_park`, grader 0/11 — Proctor authored two
  **mutually contradictory** structural tests (`"_validate_user" in source` AND `pytest.raises(
  AttributeError): accounts._validate_user`) → *no implementation can pass both*; the weak coder then
  hallucinated a fake "cannot create files" blocker and gave up.

**Confirmed mechanism (code-level, 3/3):** the Proctor over-specifies **incidental detail the spec
leaves open** — exact whitespace, a rendering literal, a private symbol name — and can even author an
**unsatisfiable** contract. This violates the Proctor persona's own #1 rule ("do not pin an exact
whitespace/format the task left open … a FALSE NEGATIVE that fails a correct implementation"): the
weak local model does not obey its persona. Because coder and Proctor are the *same* model they often
coincide on the incidental choice (→ deliver), so the trap is a **latent, stochastic fragility**.
(Proven deterministically: a correct double-space `"1  [ ] Buy milk"` passes the format-loose hidden
grader but fails the Proctor's `== "1 [ ] Buy milk"`.)

The earlier aggregate "76% of thrashes are false-negatives" figure was **overstated** (inferred from
grader scores, not ground truth) and is corrected here: the over-strictness is real and pervasive in
the *authored tests*; its firing rate vs. genuine capability misses is what the re-baseline measures.

## Decision

> **Amended by [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md)** (2026-08-20): two further checks — `source_formatting_pin` and `vacuous_test` — were admitted under
> ADR-0085 §1 and live in `bar_integrity.py`. Detection-only, below, is unchanged by that amendment.

Treat Proctor over-strictness as a first-class, **deterministically measured** signal, and act on it
with **judgment, never a mechanical rewrite of the oracle**.

1. **Detect + measure (shipped).** A new leaf module `mosaera_core/faithfulness.py` —
   `authored_suite_overstrict_findings` — is a deterministic AST detector, one-sided / deny-by-default
   in the `oraclecheck.py` mould. It flags exact-output equality, exit-code pins, rendering-count
   pins, source/private-name pins, and unsatisfiable **contradictions**, with lightweight
   intra-function dataflow so it sees through `lines = result.stdout…` / `src = inspect.getsource(…)`
   indirection. It only ever flags strictness it can PROVE is incidental (a literal the spec does not
   quote; an exit code the spec left as "non-zero" and did not pin); when unsure it is SILENT.
   The bench measures it two ways in the scorecard meta: `overstrict_static` (detector count) and
   `overstrict_vs_ref` — the run's *own* authored tests run against the case's `reference/` solution,
   so any failure is *provably* over-strict (the reference is correct by construction).

2. **Name it to the Proctor (shipped).** Behind the `proctor_faithfulness_guard` knob (posture ON),
   `author_tests_node` feeds the NAMED findings into the Proctor's existing coder-blind validate/repair
   turn, so a weak model repairs the exact flagged assertion (far more reliable than the general rule
   alone). The engine only NAMES targets — it never edits a test here — so no false-ship channel is
   opened; the red-phase + assertion-floor still gate the result.

3. **Deterministic auto-loosen (MR-C) — BUILT, RED-TEAMED, REVERTED.** An AST transformer was built to
   rewrite the "provably-safe" subset (exact rendered-output equality → whitespace-normalized;
   `== N` → `!= 0`). The required red-team (two independent adversarial passes, run against the real
   code) **CONFIRMED it reopened false-ship**:
   - *whitespace:* bare `.split()` erases **semantic** whitespace — it eats newlines (a "one name per
     line" task ships a one-line impl), collapses column alignment, and drops empty fields — and a
     wrong impl PASSES the loosened assertion. The downstream red-phase/assertion-floor do NOT catch
     it: a loosened assert is a *widened acceptance class*, not a tautology.
   - *exit-code:* `== N → != 0` masked a pinned-code contract (`_spec_says_nonzero` was a whole-spec
     substring), and `.status`/`.rc` in the exit-attr set gutted behavioural `response.status == 200`
     to `!= 0`.

   Distinguishing incidental from semantic whitespace is **not deterministically decidable**, so the
   defect class is inherent to a mechanical rewrite (STOP rule tripped: don't patch normalization
   variant after variant). **Disposition: REVERT the auto-loosen wholesale** — mirroring the 0.6.0
   oracle-demotion that was likewise red-teamed and reverted (ADR-0060). It also directly violates the
   owner's standing mandate (*a higher score from relaxed evaluation criteria does not count*). Kept
   from the red-team: detector precision hardening — `_EXIT_ATTRS` narrowed to `{returncode, exit_code,
   exitcode}` (dropped ambiguous `status`/`rc`), and the exit-code finding now also requires
   `str(code) not in spec`. The exit-code finding is advisory only (the Proctor adjudicates) → residual
   **ACCEPT** (fails safe).

4. **Stronger tester model (MR-D) — configuration, not hardwired.**
   > **AMENDMENT 1 (2026-08-11): MR-D MEASURED and REFUTED as a general lever.** 30 runs, enriched
   > over the 6 cases where over-strictness recurs, tester routed to `qwen3.6:35b` against a coder
   > (and previously tester) of `qwen3-coder:30b`.
   > **Pooled `overstrict_vs_ref` moved +4%** — inside the +21% measured noise floor, against a
   > pre-registered ≥50% reduction. Delivery fell 55%→40% and capability 91.0→88.8 (~1.7 SE, so
   > suggestive rather than conclusive); false ships stayed at 0.
   > **The heterogeneity is the finding:** four cases improved 52–65%, one was already at the
   > floor, and MCB-22 got **three times worse** (5.60 → 17.00, probe runs `[21,8,17,26,13]`) with
   > its deliveries falling 5/10 → 1/5. A stronger model is a better Proctor on most cases and
   > badly worse on at least one; the average cancels. Full record:
   > [`tester-model-probe-2026-08-11.md`](../engineering-history/tester-model-probe-2026-08-11.md).
   > **Confound stated, not resolved:** `overstrict_vs_ref` is a count, not a rate, and no card
   > records the authored suite size — so "wrote more tests" cannot be separated from "wrote worse
   > tests". Record that count before the next Proctor experiment.
   > The default stays `qwen3-coder:30b`. The mechanism this ADR documents is untouched: over-strict
   > authored tests remain the dominant over-park cause, and swapping the authoring model does not
   > fix it.

   The persona is already excellent;
   the bottleneck is a weak model not obeying it. Rather than hardwire a "stronger" tag (violates the
   model-agnostic DNA), the recommended production config routes the TESTER role — and its escalation
   ladder — to a stronger model via the existing seams (`MOSAERA_MODEL_TESTER`, a `tester` entry in
   `MOSAERA_ROLE_ESCALATION`). No engine change; the escalation seam already carries a tester ladder.

## The successor for the reverted class

Loosening an over-strict test needs **judgment about the spec's intent**, which a deterministic pass
cannot supply. The successor is the Proctor's spec-reading repair (item 2, shipped) plus the
**held-out different-model critic** named in ADR-0061 (a *different* model than the coder, downgrade-only)
— it can weigh "is this whitespace incidental or semantic?" the way the deterministic rewriter could not.

## Consequences

- Over-strictness is now a measured lever on the scoreboard (`overstrict_static` / `overstrict_vs_ref`),
  so its movement is tracked, not asserted.
- The arc ships **detection + judgment-based repair**, not an oracle rewrite — the safe direction.
- **Measured effect (`#57` A/B smoke, escalation OFF, repeat=1).** The **guard-OFF baseline arm
  completed (24 runs): clean-conclusion 66.7%** (12 clean_deliver · 4 honest_park · 8 thrash_park ·
  **0 false_ship · 0 crash**), and — the load-bearing result — **`overstrict_vs_ref` = 6 of 20
  measurable cases (≈30%) authored a suite that FAILS the case's correct `reference/` solution** (30
  over-strict tests total). This **confirms the mechanism at scale**: ~30% of runs author an oracle
  that would reject a correct implementation. The guard-ON arm was cut short (direction pivot to
  ADR-0063), so the naming intervention's clean-conclusion delta is **not measured** — but by design it
  was expected to be small and within repeat=1 noise (MR-B only *names* targets to the same weak
  Proctor, and only for the subset the conservative static detector flags). The real levers the
  baseline points to are the **stronger tester + held-out critic** (ADR-0061) and the **workbench**
  (ADR-0063), not the naming nudge. Baseline scoreboard finding stands as the arc's measured evidence.

## Rejected

- **Deterministic auto-loosen of the oracle** — red-team-confirmed false-ship; reverted (above). The
  class is undecidable deterministically.
- **Rewriting the Proctor persona** — it is already correct; the defect is model obedience, addressed
  by naming targets (item 2) + a stronger tester (item 4), not more prose.
- **Changing the reliability classifier** — FROZEN for metric integrity (ADR-0053); this arc reduces
  over-strictness *before* the thrash signals fire, never relabels thrash.
- **Hardwiring a stronger tester model** — violates model-agnostic DNA; the seam already exists.
