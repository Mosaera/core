# ADR-0015: The tester tests the contract's exact strictness — no over-specification

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0013](ADR-0013-adding-an-agent.md) (the tester/Proctor), [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the escalate hand-raise + supervisor re-scope this reuses), [ADR-0007](ADR-0007-capability-benchmark-suite.md) (the MCB benchmark that caught this)

## Context

The test-first tester (Proctor, ADR-0013) authors the acceptance tests the coder must pass. An
MCB benchmark sweep (2026-07-12) measured the tester OFF vs ON. With a **weak local** tester
(`qwen3-coder:30b`) the tester was net-**negative** (MCB-03 96→84, MCB-04 96→78): it wrote
false-negative tests that failed correct code, and the coder thrashed to the iteration cap
(18× cost) before parking. Swapping in a **strong cloud** tester (`claude-sonnet-4-6`) fixed
the *wrong-code* failure mode — Implementation hit 100/100 on all three cases — but 2/3 runs
still **parked** (MCB-04 82, MCB-06 79): the delivered code passed the hidden acceptance suite,
yet the run refused to ship because Proctor's own suite failed.

Root cause (traced in the workspaces): Proctor wrote genuinely good tests but **over-specified
beyond the stated contract** — e.g. the brief says a missing argument "exits non-zero" and
Proctor asserted the exit code is *exactly 2*. When the (stochastic, local) coder satisfied the
real contract but not the stricter assertion, validation failed and the run honestly parked.
The delivered code was correct; the *test* was wrong-by-being-too-strict. The disagreement is
between the tester's suite and the real acceptance contract, and there was no fast resolution —
the coder (which cannot edit protected tests) simply thrashed then parked.

## Decision

**1. Match-the-contract's-strictness rule (persona).** `personas/tester.md` now makes it the
single most important rule: assert *exactly* what the task states, no more. A loosely-worded
requirement ("exits non-zero", "prints an error", "in id order") is asserted at that looseness
(`!= 0`, `stderr != ""`, relative order) — never tightened into a specific value the task never
named (exact exit code, exact error string, an unstated format/ordering). A stricter-than-stated
assertion is a **false negative** that fails correct code. When the task pins an exact value,
assert the exact value; otherwise assert only the property named. When in doubt, assert weaker.

**2. Over-specification escalation valve (graph).** The coder's self-heal prompt for a failing
validation suite (`graph.fix_instruction`, extracted from `fix_node` so it is unit-testable)
now offers a bounded escape: *if and only if* a failing test demands more than the task's stated
contract — so no correct change could satisfy it without contradicting the task — the coder
replies `SUMMARY: escalate — <test> over-specifies beyond the contract: <detail>` instead of
thrashing. This reuses the **existing** hand-raise plumbing (ADR-0012): `capture_node` parses
the SUMMARY, `route_after_capture` sends it to the mode-gated supervisor, which re-scopes
(autonomous → Quincy re-scopes and the tester re-authors; guided/HA → human). No new node,
routing edge, or state key — only a richer instruction and a reused valve.

## Consequences

- Re-running the sweep with the fixes flipped the tester net-**positive**: MCB-03 **100**,
  MCB-04 **95**, MCB-06 **100**, all delivered autonomously in one iteration, zero parks. The
  tester now *raises* delivered correctness (MCB-03 beats the tester-OFF baseline of 96).
- The tester remains **opt-in** (`tester_enabled`, default OFF) and this ADR does not change
  that; it makes the tester *worth* enabling with a capable model. Default-on is still gated on
  the model-quality question (a weak local tester is still net-negative — see the escalation
  ladder work that follows).
- No policy/allowlist/threat-surface change: the coder still cannot touch protected tests; the
  valve routes through the same supervisor the coder already reaches.

## Alternatives considered

- **Let the gate deliver when the reviewer approves despite a failing tester suite.** Rejected:
  that quietly demotes the tester's contract ("a run must never pass by weakening the tester")
  and hides a real disagreement. The valve surfaces and resolves it instead.
- **A stricter no-progress breaker on the fix loop.** Already exists and correctly parked — the
  problem was upstream (the test was wrong), so the fix belongs at the tester and the valve.
