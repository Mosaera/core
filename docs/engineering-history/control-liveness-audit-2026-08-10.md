# Which controls actually constrain delivery? — the scoped liveness audit (2026-08-10)

**Instrument:** `scripts/experiments/audit_control_liveness.py` (report-only, re-runnable).
**Corpus:** 2,483 benchmark scorecards, 45 excluded as escalations whose role never spoke
([why](escalation-no-op-audit-2026-08-10.md)). Recency split at 2026-08-06.

## Why this was run

Five separate mechanisms were found on 2026-08-10 that had been built, documented, believed, and
were silently doing nothing — each having passed its tests, its gates and a red-team round. The
question the audit answers is not "is the code correct" but **"which of these controls has ever
actually refused anything?"**

`check_control_liveness.py` (ADR-0081) is the right instrument for this and already exists — but it
covers **posture knobs only**, not the gate reasons, oracles and preflight checks that decide whether
work advances. This audit covers that class.

## Caveats, stated first

- **The corpus is bench-only.** A control that is live in production and never exercised on the
  bench reads UNKNOWN here. `intake_park` is exactly that (see below). "UNKNOWN on the bench" is not
  "inert" — it is *no evidence either way*, which is the point of the vocabulary.
- The corpus spans many code versions; the 2026-08-06 recency split is arbitrary.
- `ever = 0` means the control never had an *observed* opportunity to fire, not that it is broken.

## The central finding

**24 of 26 controls cannot distinguish "ran and found nothing" from "never ran."**

Only the two security reasons have a companion field (`security_unavailable_reason`). Everything else
records *what fired* and nothing about what was evaluated and came back clean. A zero from those 24
is epistemically empty — which is precisely how five inert mechanisms survived this long.

The `content_destroyed` prohibition (built today on `fix/gutted-file-removal`, not yet merged —
which is why it is named by mechanism rather than by ADR number here) is the counter-example of
what healthy looks like. Its corpus check reads:

```
ran, found nothing : 24/25
could not evaluate :  1/25   (MCB-09, unreadable tree)
found violation    :  0/25
```

Three distinguishable states. Without the execution field all three collapse into
`content_destroyed = 0`, and the ~4% suppression rate — a real hole in a prohibition — would have
presented as a perfect score.

## Gate reasons

| control | ever | recent | status | disposition |
|---|---|---|---|---|
| `security_findings` | **0** | 0 | UNKNOWN | The security gate **has never caught anything** in 2,483 runs. Meanwhile `security_unverified` fired 73 times, and 92% of those refused work the hidden grader confirms was **correct**. The control's entire measured contribution to this corpus is false refusals. |
| `claim_integrity_failed` | **0** | 0 | UNKNOWN | `gate.py` calls it *"provably co-present with `tests_tampered`"*. With 0 firings that implication is **vacuously true and never tested**. Not LIVE. |
| `removal_unproven` | 0 | 0 | UNKNOWN | New (the SUBTRACT oracle merged today). Expected; not a defect. |
| `reviewer_blocked` | 1 | 0 | STALE | One firing, ever. |
| `critic_vetoed` | 54 | **2** | LIVE | **Collapsed.** The best discriminator in the corpus — only 4% of its parks were on correct work — has nearly stopped firing. Worth its own investigation. |
| `clauses` (applied) | 4 | 0 | STALE | Ships default-OFF; consistent. |
| all others | — | — | LIVE | |

## Claim oracle kinds

**Three of six have never failed:** `validation_exit`, `tests_unmodified`, `non_use`.

`tests_unmodified` never failing corroborates `claim_integrity_failed = 0` — the tamper *claim*
oracle and the gate reason that consumes it are both untested in practice, so the "co-presence"
argument rests on nothing observed.

## Preflight / intake — an instrument divergence

`intake_park` (`plan_unworkable_reason`) fired **0 times on the bench** and **does fire on the live
instance** — LedgerCLI items #83 and #85 both parked `under_specified` before spending a token.

This is the F35 lesson recurring: **the instrument cannot see the defect the product has.** A
bench-only audit would have called this control inert. It is not; the corpus simply cannot observe
it. Any control that runs at intake is invisible to a benchmark that supplies its own fixed briefs.

## Meta-controls

Established mechanically by `packages/core/tests/test_guard_liveness.py` rather than by inspection —
*a guard-test must fail if its guard is deleted*.

- **4 of 6 guards have a test, and all 4 genuinely detect deletion.** Neutering the guard to
  `sys.exit(0)` turns each one red.
- **2 of 6 have no guard-test at all** — `check_layer_imports.py`, `check_state_keys.py`. Pinned in a
  shrink-only list, the same ratchet `check_control_liveness.py` uses for its own grandfathered rows.

**Known limitation:** the mutation check is *file*-granular. A single vacuous test inside a file whose
other tests still detect the deletion would pass. That is not hypothetical — `test_doc_claims.py`
used a specific ADR number as its synthetic invalid fixture, and the moment an ADR with that
number was written, reality satisfied the fixture and that test stopped testing the guard. The file's other tests would have
masked it here. Per-test granularity is the obvious upgrade and was not built.

## What this suggests, without prescribing

1. **`security_unverified` is the highest-value single target** — 67 correct runs refused, zero
   caught, and the *why* is never recorded despite a field existing for it.
2. **`critic_vetoed`'s collapse** deserves explanation before anything is built on top of it; it is
   the one control the data says works.
3. **Observability before enforcement.** 24 of 26 controls need a companion field before any claim
   about their liveness means anything. That is a prerequisite for extending ADR-0081's registry to
   this class — and note the ladder's rungs are **knob-shaped** (they A/B a posture knob on vs off);
   a gate reason has no "off" arm, so the registry transfers but the rungs need redefining.
