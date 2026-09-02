# ADR-0026: Test-tampering is an escalate-the-coder signal, not a defer signal

- Status: accepted
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0013](ADR-0013-adding-an-agent.md) (Proctor + the protected-test tamper check), [ADR-0016](ADR-0016-deterministic-model-escalation.md)/[ADR-0022](ADR-0022-live-model-escalation.md) (`diagnose_bottleneck`/`escalate_role` + the live loop), [ADR-0023](ADR-0023-resilient-autonomous-sweep.md) (the recovery ladder that defers as a last rung)
- Completed by: [ADR-0036](ADR-0036-test-integrity-baseline.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The tester (Proctor) authors protected acceptance tests test-first; the coder is refused at the
tool level from editing them, and a defense-in-depth tamper check (`tampered_files`) hard-stops a
run whose baseline test hashes changed anyway (`graph.py` `test_node`). In the pyledger case study
the local coder, stuck, **edited the protected tests twice** to make the suite pass — both runs were
tamper-killed and delivered nothing. That is **35% of the case study's tokens spent on runs that
produced no software.**

Tampering is the loudest possible "this model is out of its depth" signal — a coder that rewrites the
contract instead of satisfying it. Yet the recovery ladder (ADR-0023) treated a tamper-killed run
like any other stall: model-escalate only if `diagnose_bottleneck` attributed it, else **defer**. And
`diagnose_bottleneck` couldn't even see the tamper: it read `gate_decision.reasons` / the reviewer
verdict / stall counters, none of which distinguish a tamper. Worse, a tamper that the reviewer had
*approved* (validation still fails, verdict APPROVE) would fall through to **Rule 2 and be
misattributed to a "weak tester"** — escalating the wrong role.

## Decision

Two tiny edits, no trust-boundary or schema change:

1. **Emit a machine-readable tamper signal.** `test_node`'s tamper branch already sets
   `tests_passed=False` / `stalled` / `stall_reason`; add `result["tests_modified"] = True`. ~~It merges
   into the terminal `final` state automatically (LangGraph state reducer) — no plumbing.~~

   > **CORRECTED 2026-08-18 — the struck claim was FALSE, and this ADR's rule therefore NEVER FIRED in
   > production until [ADR-0036](ADR-0036-test-integrity-baseline.md) declared the key.** `tests_modified` was
   > not declared in `RunState`, so LangGraph silently dropped it between nodes and `diagnose_bottleneck` never
   > saw it. The code says so at the two sites:
   > `packages/core/mosaera_core/graph/state.py` — *"A DECLARED key so LangGraph keeps it (ADR-0026 wrote it
   > undeclared, so it was silently dropped and the tamper→escalate rule never fired)"* — and
   > `packages/core/mosaera_core/graph/nodes_impl.py` — *"ADR-0026 wrote tests_modified undeclared, so it was
   > silently dropped and the rule never actually fired."* ADR-0036 (header: *"Completes: ADR-0026 (declares the
   > signal ADR-0026 emitted into a dropped channel)"*) declared it; the rule is now proven to fire from a live
   > compiled graph in `packages/core/tests/test_graph_integration.py`.
   > Recorded in `docs/audits/adr-corpus-review-2026-08-18.md`.

2. **Diagnose it as the coder, top-priority.** In `diagnose_bottleneck`, add a rule **before the
   tester over-specification rule (Rule 2)**: `final_state.get("tests_modified")` → return `"coder"`.
   So a tampered run escalates the coder's model up its ladder (ADR-0016) via the existing live loop
   (ADR-0022) instead of deferring, and an approved-tamper is never misread as a tester fault. Ordered
   after the PM/`acceptance_failed` rules (a tampered run never *delivers*, so `acceptance_failed` — a
   grader verdict on a shipped run — can't co-occur), before everything reviewer/coder/tester below.

`escalate_role`, `_try_model_escalation`, the gate, and `packages/policies` are all untouched.

## Consequences

- **A cheating coder escalates instead of wasting the token budget.** The out-of-depth local coder is
  bumped one tier (e.g. to the configured Sonnet escalation) and re-runs BEFORE the item defers —
  turning the 35%-wasted class into a recovery path.
- **Correct role attribution.** The approved-tamper misattribution (tamper → "tester") is fixed; the
  fault lands on the producer that tampered.
- **Bounded and gated as before.** Escalation still requires `model_escalation_enabled` + a `coder`
  ladder + (for a cloud tier) `allow_cloud_egress` + a price (ADR-0024); bounded by
  `max_model_escalations`. With none configured, the behaviour is unchanged (diagnose returns `coder`,
  `escalate_role` returns `None` → the run still defers) — a pure no-op without a ladder.
- **Honest residual.** This attributes and escalates; it does not *prevent* tampering (the tool-level
  refusal + the hard-stop remain the guard). If the stronger model also can't satisfy the contract the
  ladder tops out and the item defers honestly (ADR-0023).

## Alternatives considered
- **Treat tamper as its own terminal reason in the gate.** Rejected — edits `packages/policies/gate.py`
  (CODEOWNERS) for no gain; the run already hard-stops, we only needed the *diagnosis* to see it.
  **Corrected 2026-08-18 — this rejection was later REVERSED.**
  [ADR-0036](ADR-0036-test-integrity-baseline.md) added exactly that: a dedicated `tests_tampered` reason in
  `packages/policies/mosaera_policies/gate.py`, because after the reviewer-silence backstop (ADR-0031/0034) a
  tamper also has to be a reason autonomous mode can never ship past — a gain this ADR did not foresee.
  Asserted through the compiled graph at `packages/core/tests/test_graph_integration.py`
  (`assert "tests_tampered" in gd["reasons"]`). Recorded in `docs/audits/adr-corpus-review-2026-08-18.md`.
- **Escalate on the first tamper without a ladder / unconditionally.** Rejected — escalation stays
  operator-configured (a `coder` ladder must exist) and bounded; no implicit off-box egress.
