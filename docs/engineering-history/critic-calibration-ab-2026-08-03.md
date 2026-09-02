# Critic-calibration A/B (#61) — abort, fix, re-run, verdict

**Date:** 2026-08-03 · **No ADR** (experiment log; the decision record is the ADR-0065
amendment). Two runs: an aborted first attempt whose 20 runs diagnosed a new failure shape,
and a completed 140-run second attempt on the fixed code.

## Run 1 (ABORTED at 20/140)

The new arm over-vetoed MORE than baseline. The persisted rows diagnosed **premise
poisoning** in minutes: whole-brief claims included starting-state descriptions, and the
critic refuted runs FOR SUCCEEDING (MCB-03's veto evidence: `exit code 0`; MCB-13's: the
ladder's own removal line). Also found: the legacy fallback leaking the old over-veto (3/5)
and unknown-claim-ids defaulting material. Four deterministic fixes (premise filter ·
unknown-id never material · residual jurisdiction · noncompliance = abstention), predictions
re-registered, relaunched.

## Run 2 (completed, n=140, arms interleaved)

**Validation first (ADR-0081):** 6/7 cases VALID (26-95% divergent pairs); **MCB-15
self-voided** (0/100 — neither arm's critic fired there; no signal, no score).

| | new arm | old arm |
|---|---|---|
| true catches | **2** (MCB-05) | 1 (MCB-05) |
| over-vetoes | **1** | 8 (06×4, 22×4) |
| veto precision | 2/3 = 67% | 1/9 = 11% |
| discarded refutations (verifier working) | 7 | — |
| clean deliveries | **38**/70 | 31/70 (Fisher p=0.31, directional) |
| false ships | 18 | 18 (identical — none new) |
| premise-class vetoes | **0** | — |

**Over-veto reduction 8→1: Fisher two-sided p = 0.033** — statistically significant at n=70/arm.

**Predictions:** P1 (premise class = 0) CONFIRMED · P2 (over-vetoes near-0) CONFIRMED with
significance · P3 (no new false ships) CONFIRMED (18=18) · P4 (delivery rises) directional
(38 vs 31, ns) · **Kill-switch: PASSING** — the catches survive (new arm 2 vs old 1 on
MCB-05); precision 67% sits just under the pre-registered 70% target at n=3, which is why the
targeted probe (below) decides activation, not this sweep.

## The residual over-veto, root-caused to the character

The new arm's ONE over-veto (MCB-03) was a **fragment claim**: the sentence splitter broke a
line-wrapped premise sentence at the newline, orphaning a tail ("descriptive-statistics
module and its test suite)") into a material unbound claim — real quotes, residual
jurisdiction, wrong claim to exist. (A second apparent over-veto at 08:14 was an
aborted-run-1 leftover mis-globbed into the window — excluded.) **Fixed same day**: split
only on sentence punctuation + blank lines + bullets; single newlines join; <3-word headings
are non-material. MCB-03: 16 claims → 9, zero fragments.

## Disposition

- The protocol works: harm down 8×-significant, catches up, hallucinations caught-and-logged
  (7), everything auditable per-veto.
- **Activation still gated** on the targeted probe (05 n=15/arm · 15 n=10 · 06 n=8 · 03 n=6,
  running): catch-retention at event-level n + precision above target + fragment-class
  verified dead. The 70% precision bar stands; no rounding up at n=3.
- Merge of !317 is safe independent of activation (knob default OFF = byte-identical).

## Probe (partial, 41/78 — stopped on the owner's activation decision)

Old arm: 1 TRUE CATCH (MCB-05) + 2 more over-vetoes (MCB-06); new arm: 0 vetoes, 0 discards
on its own runs (no catch opportunity presented). Consistent with the sweep; adds nothing that
changes the picture. The owner decided activation with the retention question converted to a
standing production measurement (every veto persists its quoted rows) — recorded in
`_posture.py` with the one-line rollback.
