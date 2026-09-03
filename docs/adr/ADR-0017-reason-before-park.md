# ADR-0017: Reason-and-change-approach on stall — reason before park

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the `SUMMARY: escalate` hand-raise + mode-gated supervisor this reuses when the reason pass yields), [ADR-0015](ADR-0015-tester-contract-scope.md) (the over-specification escalation valve the reason prompt mirrors), [ADR-0016](ADR-0016-deterministic-model-escalation.md) (deterministic model escalation — this is its **precursor**: change the *approach* with the same model before escalating the *model*)

## Context

When a self-heal loop stops converging — the coder produces the SAME failure `stall_limit`
times — the no-progress breaker trips `stalled=True` and the run drains to the gate and **parks**.
It never stops to reason about the *root cause* or try a *different* approach the way a human
engineer (or Claude) does: the breaker only *detects* repetition and *stops*; there is no step
between "stuck" and "park." The live MCB escalation demo made this concrete — MCB-09 produced
**correct** code (8/8 hidden acceptance) yet parked, looping on stray-file cleanup / a test
disagreement instead of reasoning through it.

The DNA escalation ladder (ADR-0002) says: try a different approach before escalating the model.
ADR-0016 escalates the *model*; this escalates the *idea* first — the cheapest rung, and the
precondition for later *surgical* model escalation (escalate the reasoning about the specific stuck
point, then drop back down).

## Decision

**1. A `needs_reason` signal distinct from `stalled`.** A shared closure `_apply_trip` at all three
trip sites (`test_node`/`hygiene_node`/`review_node`) decides, once a bump trips: if
`reason_on_stall_enabled` **and** `reason_attempts < max_reason_attempts` → set `needs_reason`
(carrying the tripped kind + failing text) instead of `stalled`; otherwise set today's `stalled=True`
+ `stall_reason` (noting a reason pass was already spent). The two signals are mutually exclusive.

**2. A `reason_node`** (modeled on `fix_node`). It hands the coder its OWN model
`prompts.reason_instruction(kind, failing_text)` — "STOP, state the ROOT CAUSE in one line, then take
a genuinely DIFFERENT approach", and reply `SUMMARY: escalate — …` if the blocker is truly outside its
control. It **resets the tripped kind's stall streak** (a fresh start so the stale fingerprint doesn't
instantly re-trip), increments `reason_attempts`, clears `needs_reason`, logs to `feedback`, and
increments `iteration` (sharing `max_iter`). It routes to `implement`; a `SUMMARY: escalate` the coder
emits is parsed by `capture_node` and routed to the supervisor with **zero extra wiring** (ADR-0012).

**3. Opt-in and double-bounded.** `reason_on_stall_enabled` defaults **OFF**. Two independent bounds
guarantee it cannot loop: (a) `reason_attempts` is a single run-level counter capped by
`max_reason_attempts` (default 1) — so only the **first** trip across any loop reasons; every later
trip parks; and (b) every coder loop (the reason pass included) increments `iteration`, capped by
`max_iter`, so `route_after_gate` finalizes at the cap regardless.

**4. Coder-model note.** The coder model (e.g. `qwen3-coder`) has no reasoning channel (`models.py`
excludes any `*coder*` name), so "reason" here means a strong text chain-of-thought driven by the
instruction, not a separate channel. Whether that is enough with the coder's own model is exactly what
the benchmark measures — if not, the deferred *surgical* escalation raises the reasoning to a stronger
reasoner.

## Consequences

- On the first stall, an enabled run spends ONE extra bounded coder pass to rethink instead of parking;
  a spent budget parks with an honest "…a reason-and-change-approach pass was already attempted" note.
- **Iteration headroom:** a trip needs `max_iterations ≥ stall_limit`; a *fresh multi-attempt* retry
  after reasoning needs `max_iterations > stall_limit` (the reason pass consumes an iteration). With the
  default `max_iterations=3` the new approach gets a single shot then parks — correct and bounded, but
  under-powered; operators enabling this should raise `max_iterations` (≈ `2·stall_limit`). MCB cases
  (`max_iterations` 4/6/8) have headroom.
- The single run-level `reason_attempts` counter means the first trip (of any kind) reasons and later
  trips park. A per-kind budget (`reason_attempts` as a dict) is a future option if measurement shows a
  need.
- **Threat surface: unchanged.** Same models, opt-in, no new egress, tools, policy, or migration — so
  **no threat-model edit** (recorded here explicitly per the ADR discipline).

## Alternatives considered

- **Reuse the supervisor (Quincy re-scope) on every stall.** That is the coarser path (re-plan) and
  fires an interrupt; the reason step is lighter — the coder self-reasons and stays in the implement
  loop. The supervisor remains reachable via the preserved `SUMMARY: escalate` valve.
- **Overload `stalled` with a "reasoned once" flag.** Rejected: a distinct `needs_reason` keeps the
  trip→reason and budget-spent→park paths explicit and the routing branches trivial to read/test.
