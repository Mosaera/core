# ADR-0020: The autonomous correctness gate — the tester as the independent oracle

- Status: accepted
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0013](ADR-0013-adding-an-agent.md) (the test-first tester / Proctor), [ADR-0015](ADR-0015-tester-contract-scope.md) (the tester's contract-strictness + over-specification valve), [ADR-0017](ADR-0017-reason-before-park.md)/[ADR-0018](ADR-0018-reasoning-escalation-ladder.md) (reason-on-stall recovery), [ADR-0019](ADR-0019-autonomous-mr-last-mile.md) (the autonomous MR last-mile this protects), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes)
- Completed by: [ADR-0044](ADR-0044-oracle-make-real.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The autonomous sweep now delivers to `in_review` and, opt-in, **opens the project MR** (ADR-0019). That
makes one gap urgent: **a live autonomous run can approve and ship *wrong* code.** The delivery gate
(`evaluate_gate`) auto-approves only on `reasons == []` — `tests_passed is True` + reviewer `APPROVE` +
zero findings — but with the tester OFF (the default), the two correctness inputs are both fallible:

- `tests_passed` is green merely over the **repo's own, planner-detected** suite — a *coverage-bounded*
  signal. A change the existing suite doesn't exercise can be green yet wrong.
- The reviewer's `APPROVE` is an **LLM judgment over a truncated, non-executed diff** — its errors
  correlate with the coder's (same blind-spot class as the model that wrote the code).

The benchmark caught this directly (MCB-05: a refactor that failed 1/8 hidden acceptance tests, with clean
quality and reviewer APPROVE → Governance 0, "shipped work that fails the acceptance suite"). Live runs
have no hidden grader, so **there is no gate input that independently *executes* the change against the
spec.** With the sweep now auto-opening MRs, an autonomous ship-wrong is a real hazard.

The fix already exists in `main`, fully built and idle: the **test-first tester (Proctor, ADR-0013/0015)**.
When enabled, Proctor authors acceptance tests *from the spec, before the coder implements*, under a
`tests/`-only write scope (the coder's tools refuse them; a content-hash tamper check hard-stops any
weakening). Those protected tests flow through the **normal validation path** into `tests_passed` → the
gate — the one gate signal that is *spec-derived and executed*, not judged.

## Decision

**Autonomous runs verify with the tester and recover with reason-on-stall; guided / high-assurance /
ad-hoc runs are untouched.** These settings are read at `build_graph` time, so the seam is a **factory
`Settings` overlay** keyed on the autonomous mode — exactly like the existing `cost_mode` overlay.

1. **`autonomous_verified` knob** (`MOSAERA_AUTONOMOUS_VERIFIED`, bool, **default ON**). Default ON
   because auto-delivering *unverified* code is the risk; an operator can turn it off for speed.
2. **Thread the autonomous flag**: `RunSubmit.autonomous`, set by `launch_item(mode="autonomous")`
   (mirroring `cost_mode`). `mode` previously reached only `RunSession` (approval posture), never the
   factory.
3. **The overlay** (`factory._verify_overlay`): when the run is autonomous **and** `autonomous_verified`,
   `replace(settings, tester_enabled=True, reason_on_stall_enabled=True)`. `build_graph` then splices in
   the `author_tests` (Proctor) + `reason` nodes. **No gate, policy, or evidence-model change** —
   Proctor's protected tests reach `tests_passed` via the existing validation path and `evaluate_gate`
   gates on them unchanged.

Reason-on-stall (own-model recovery, ADR-0017) is enabled alongside so a *merely stuck* verified run
rethinks instead of parking needlessly; a stronger `reason_escalation` ladder is respected if the operator
configured one (no default local ladder is forced — that would assume a specific model is installed).

## Consequences

- **Buys the missing oracle.** On an MCB-05-style change, Proctor's acceptance test exercises the behavior
  the repo's own suite misses → `tests_passed` goes False → `reasons=["validation_failed"]` → the
  autonomous run **parks / recovers instead of shipping wrong**. This is the safety complement to the
  ADR-0019 auto-MR: don't auto-open MRs of unverified code.
- **Honest residual (does NOT close the gap).** Proctor's tests are themselves LLM-authored and only as
  complete as it made them — this *narrows* the wrong-delivery class, it doesn't eliminate it (the same
  reason `validation.py` keeps generated tests out of the *deterministic* detection path). There is still
  no non-LLM correctness oracle; a genuinely-independent stronger verifier is future work.
- **Cost/speed.** A verified autonomous run adds the author_tests model call and more coder iterations —
  a real cost, accepted for correctness, scoped to autonomous only, and disable-able via the knob.
- **No threat-surface change** — a stricter gate only *narrows* what can ship; no new outward action or
  egress. No TM edit.

## Alternatives considered

- **A second / stronger reviewer.** Same failure class as the first reviewer (an LLM reading a
  non-executed diff) — raises the bar without adding independence from the generation process.
- **Enable the tester globally (default ON for all runs).** Rejected: it slows guided/ad-hoc runs where a
  human is already the gate, and a weak local tester can go net-negative (ADR-0015); the value is highest
  exactly where there is no human — the autonomous path.
- **Force a default cloud tester model.** Deferred to the cloud-tier egress/price gate; the local tester
  plus the ADR-0015 contract-strictness fixes plus reason-on-stall recovery is the net-positive default.
