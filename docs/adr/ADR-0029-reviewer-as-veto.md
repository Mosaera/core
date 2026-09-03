# ADR-0029: The reviewer is a veto, not a required sign-off — deliver on an independent oracle

- Status: superseded
- Superseded by: [ADR-0031](ADR-0031-deliver-on-silence-with-deterministic-validation.md) (dropped the tester-oracle requirement) then [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) — **the current delivery condition is ADR-0034**. Read this record for history only.
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0028](ADR-0028-reviewer-verdict-recovery.md) (the reviewer-channel fix this builds on), [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (the tester = the independent oracle this leans on), [ADR-0025](ADR-0025-behaviour-smoke-gate.md) (behaviour-smoke, folded into `tests_passed`), the delivery gate (`packages/policies/gate.py`, CODEOWNERS)

## Context

Even after the ADR-0028 reasoning-channel fix, MCB-21 8-run measurement leaves a residual ~1–2/8 parks. Part is
legitimate (a genuine validation miss should park), but part is the same trust gap one notch smaller: the local
reviewer (`gpt-oss:20b`) still occasionally emits **no usable verdict at all**, and the gate treats that silence
(`reviewer_unknown`) as a blocker — so **correct, oracle-validated work false-parks on reviewer flakiness.** The
pre-fix rate was ~75%; the point stands that a flaky local reviewer must not be a single point of delivery
failure.

The gate's stated invariant was "an UNKNOWN verdict is never approval." That conflates two very different things:
a reviewer *objection* (BLOCK / REQUEST_CHANGES — a real signal to stop) and reviewer *silence* (no verdict — the
absence of a signal). Blocking delivery on silence, when independent evidence already says the work is correct, is
a false negative, not caution.

## Decision

**Make the reviewer a veto, not a required sign-off.** In `autonomous_resolution` (which *only* the autonomous
runner and the benchmark harness call — so this is autonomous-only by construction), when the **sole** blocking
reason is `reviewer_unknown` and an **independent oracle is green**, resolve to `approve` instead of `park`:

- `oracle_verified` — the tester's spec-derived acceptance suite ran and passed (ADR-0020). Passed to
  `evaluate_gate` by the graph as `settings.reviewer_advisory and bool(tests_baseline)` (a non-empty
  `tests_baseline` ⇒ Proctor authored protected acceptance tests), and **sanitized to `False` unless
  `tests_passed is True`** so it can never claim verification the run didn't earn. `tests_passed` already folds in
  the behaviour-smoke floor (ADR-0025), so "oracle green" means *the spec tests passed AND the entrypoint runs*.
- No security findings (a clean scan) and no other blocking reason. `iteration_limit` is ignored when isolating
  the sole blocker (it rides along on any non-empty reasons).

A real objection (`reviewer_blocked` / `reviewer_requested_changes`) still resolves normally (park / bounded
revise). `evaluate_gate`'s **reasons list is unchanged** — the human-gated path is untouched, so a person still
parks on reviewer silence and decides. Gated by a new `reviewer_advisory` knob (**default ON**); OFF restores the
pre-ADR-0029 behaviour (silence parks).

## Consequences

- **Delivery confidence rests on positive evidence, not the absence of an LLM objection.** An autonomous run ships
  only when the tester's spec-derived tests pass, the entrypoint runs, and the scan is clean — the reviewer's
  flaky silence can no longer false-park that. This is the "99% confident delivery *within the reachable class*"
  posture: the confidence equals the oracle's strength.
- **The reviewer keeps its real power (veto) and loses only its accidental one (silence-blocks).** BLOCK /
  REQUEST_CHANGES still stop delivery; genuine validation failures still park (`oracle_verified` is `False` when
  tests didn't pass); a run without the tester (no `tests_baseline`) still parks on silence — no strong oracle, no
  backstop.
- **Human-gated and non-autonomous paths are byte-for-byte unchanged** — the change lives entirely in
  `autonomous_resolution` + one additive `GateDecision.oracle_verified` field.
- **Honest residual.** The oracle is the tester's *LLM-authored* acceptance suite (ADR-0020's standing residual):
  strong for spec-clear, offline-testable Python, but not a truly independent production oracle (only the
  benchmark's hidden grader is). So this closes the reviewer-flake parks and holds delivery confidence high for
  the reachable class; it does not make delivery trustworthy for fuzzy/undertested specs. Raising the bar further
  = stronger tester acceptance coverage + documented-command verification (future work).

## Threat surface

Relaxes the delivery gate's "UNKNOWN never approves" for **autonomous** runs → recorded in
`docs/threat-models/TM-0001` (the run loop's trust decisions). The mitigation is the strict, deny-by-default
conjunction above (objection-free, oracle-passed, clean-scan, tester-in-loop) plus the `reviewer_advisory`
off-switch; the human-gated boundary is unchanged.

## Alternatives considered
- **A heavier / more adversarial reviewer** (as an external review of the pyledger run suggested). Rejected —
  contradicted by the measurement: the local reviewer is *so* unreliable it can't emit even a simple verdict ~75%
  of the time; a longer, more demanding prompt makes the reliability worse, not better. The fix is to stop gating
  delivery on it, not to lean harder on it.
- **Default `reviewer_unknown` → APPROVE unconditionally.** Rejected — ships on the *absence* of evidence; the
  backstop requires *positive* independent evidence (the passed acceptance oracle).
- **Do it in `evaluate_gate`'s reasons (drop `reviewer_unknown`).** Rejected — that would also change the
  human-gated path (a human should still see the silence and decide). Keeping it in `autonomous_resolution`
  scopes the change to autonomous runs.
- **A structured-output / tool-call verdict from the reviewer.** Still worthwhile to raise reliability further,
  but orthogonal and larger; deferred. This ADR removes the *dependency* on the reviewer for delivery.
