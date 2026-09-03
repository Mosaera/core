# ADR-0069: The gate-loop honest-stop — conclude a stuck delivery gate (#67, arc #43)

- Status: accepted
- Date: 2026-07-20
- Owners: Mosaera core
- Related issue: #67 (gate-loop honest-stop) — arc #43; the honest-stop family's last uncovered loop
  (successor to #56/ADR-0060 and #65/ADR-0067)
- Related threat model: TM-0001 (no trust-surface change — graph routing + an honest field around
  `evaluate_gate`, like ADR-0060)
- Red-team: **not required** — not a trust-boundary change. The gate-loop breaker flows AROUND
  `evaluate_gate` (no `packages/policies` touch, which ADR-0060 "Rejected" protects); it can only turn a
  would-be `thrash_park` into an `honest_park`, never a park into a ship. Classifier FROZEN.

## Context

After the tamper-guard fix (ADR-0068) the esc-OFF benchmark reached ~81% clean-conclusion. The
`thrash_cause` instrumentation split the residual thrash three ways; only ONE is a clean, safe fix:

- **`rode_to_cap` (this arc):** a run whose delivery gate keeps DENYING re-plans to the iteration cap on
  CORRECT code (grader Impl 100). The honest-stop family covers the fix loop (#56) and the slow crawl
  (#65), but the **gate-deny → `plan` loop had NO breaker**: the #51 plan-breaker only trips on a
  fallback/identical plan (a planner emitting fresh, distinct plans resets its streak), so the loop is
  bounded ONLY by `iteration >= max_iter` (`route_after_gate`, `nodes_review.py`) → thrash. (The gate
  visit that would carry `iteration_limit` parks its interrupt and never commits the reason to `final`,
  so this shows up as the empty-reasons `rode_to_cap` the #51 classifier fix was written to catch.)
- **`stalled:plan` — LEFT ALONE.** A `_stalled_kind` mislabel of the fingerprint-stall fallback for
  UNPARSEABLE validation output, which ADR-0060 **deliberately keeps as thrash** ("no count signal → no
  honest diagnosis → relabeling flatters the metric"). Its successor is the ADR's "measured follow-up".
- **tamper-gaming catch — DEFERRED.** A caught-gaming run (rigged `conftest.py`) is honest, but flips a
  security invariant the ADR-0060 red-team relies on and scoring a caught-cheating run as "clean" is an
  owner judgment. Its own trust-boundary arc.

**Framing (owner-corrected): honest_park is the FLOOR, not the win.** If the code is correct, autonomy
means SHIP it — the real fix is #66 (a two-sided oracle that confidently ships correct code it now
denies). #67 only catches the residue the oracle genuinely CAN'T verify (the engine can't ship what it
can't verify) and stops it thrashing.

## Decision — a fingerprint-stall on the gate's blocking reasons

In `gate_node`'s deny path (`packages/core/mosaera_core/graph/nodes_review.py`), fingerprint the gate's
blocking reasons (`gate_decision.reasons`) and count *consecutive same-reason* denials with the existing
`bump_stall` + `fingerprint("gate", …)` (`progress.py`) into the existing `stall_by_kind["gate"]` slot
(no new RunState field). After `gate_stall_limit` consecutive same-reason denials **AND `iteration <
ctx.max_iter`**, set `give_up_reason` naming the recurring blocker (≤80 chars) with `stalled=False`.
`route_after_gate` already finalizes on `give_up_reason` (before the `iteration>=max` check) → `deliver`
→ `classify_outcome` returns `honest_park` **by construction** (below the cap, `stalled` False, no
`iteration_limit`). Mirrors the `plan_unworkable_reason`/#56 give-up pattern exactly.

- **Fingerprint, not a raw deny-count** — a CHANGED deny reason (progress through different blockers)
  RESETS the streak (`bump_stall` resets on a changed fingerprint), so a run still working toward a ship
  is never cut off. This is the guardrail against parking shippable code.
- **The named blocker FEEDS #66** — the recurring reason (`oracle_unverified`, `reviewer_*`, …) is the
  map of *why* correct code isn't shipping, the input to the oracle arc.
- **Knob `gate_stall_limit`** (default 2 — a gate cycle is a full re-plan = several iterations, so it is
  lower than `stall_limit`), scaled by `apply_reliability_sensitivity` (cautious→1, persistent→3, mirror
  `plan_stall_limit`).

## Rejected

- **A new counter field / `_stall_bump`.** `_stall_bump` hardcodes `stall_limit`; the gate loop needs its
  own (lower) budget, and the existing `stall_by_kind["gate"]` slot + `bump_stall` avoid a new RunState
  field entirely.
- **Concluding on a raw deny-count.** Would park a run progressing through *different* blockers — exactly
  the "don't park correct code we should have shipped" failure. The fingerprint reset prevents it.
- **Re-routing `stalled:plan` / the tamper catch** (the other two residual classes) — doctrine-protected
  and trust-boundary respectively; out of scope (see Context).
- **Editing `evaluate_gate` / `classify_outcome`** — frozen; `give_up_reason` flows around the gate like
  `plan_unworkable_reason`.

## Consequences

- Knob: `gate_stall_limit` (default 2, dial-scaled). No new RunState field (reuses `stall_by_kind`). No
  migration.
- Tests: a gate denying the same reason concludes `honest_park` strictly below the cap; the existing
  cap=2 denial-loop test is unchanged (the 2nd deny lands AT the cap so the guard holds it back — it still
  rides to cap/thrash there); the dial scales `gate_stall_limit`.
- `_termination_reason` order already surfaces `give_up_reason` (2nd) — a gate-loop conclusion reads
  accurately with no change there.
- The measured `rode_to_cap` residual converts to `honest_park`. #66 is the follow-on that turns those
  honest parks (and the gate-stuck ones) into `clean_deliver` — the real autonomy lever.
