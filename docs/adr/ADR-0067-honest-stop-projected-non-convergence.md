# ADR-0067: The honest-stop projected-non-convergence breaker — conclude the slow crawl (#65, arc #43)

- Status: accepted
- Date: 2026-07-20
- Owners: Mosaera core
- Related issue: #65 (honest-stop projected non-convergence) — arc #43; direct successor to #56
  (ADR-0060, the honest-stop / best-so-far breaker)
- Related threat model: TM-0001 (no trust-surface change — graph routing + an honest state field
  around `evaluate_gate`, exactly as ADR-0060)
- Red-team: **not required** — not a trust-boundary change. `wont_converge` is a pure deterministic
  projection; the `projected` flag only routes a trip toward the existing honest give-up (it can flip
  a would-be re-scope to a park; it can never flip a park to a ship). Unit- and integration-tested.

## Context

ADR-0060's honest-stop uses a **best-so-far** failing-count breaker: an attempt counts as progress
only when it beats the lowest failing count seen this episode. That catches stagnation (12→12→12) and
oscillation (5→6→5) — but it has a blind spot the local-baseline measurement surfaced as the #1 owner
annoyance (thrash): **the slow crawl.** A weak coder that inches the failing count down every attempt
— 12 → 11 → 10 → 9 … — *always* beats its best, so the streak never increments and the breaker never
trips. The run then spends its entire iteration budget crawling toward a bar it cannot clear in time
and **rides to the cap**, where the frozen classifier (correctly) scores it `thrash_park`. It is the
exact failure the honest-stop was meant to end — a run that will not converge — wearing the one
disguise the best-so-far signal can't see (monotonic-but-too-slow improvement).

The owner's standing directive from ADR-0060 applies unchanged: *"if it can't do something it should
be honest and flag it right away."* A run whose own trend says it won't reach zero by the cap should
conclude **now**, honestly, strictly below the cap — not grind out the remaining budget.

## Decision 1 — the projection (`progress.wont_converge`)

A pure, deterministic, **conservative** projection added alongside `bump_progress` and consumed in
`test_node`:

```
wont_converge(history, remaining, min_history=3) -> bool
```

- **Optimistic average-rate estimate.** From the episode's failing-count `history`, take the net
  improvement `first - current` over the attempts so far and the average per-attempt rate. If
  `current / avg_rate > remaining`, the run cannot reach zero within the remaining iteration budget
  even at its *average* pace → it won't converge.
- **Conservative by construction — never trips a run that would actually converge:**
  - `min_history=3`: needs a real trend before it estimates (no 1- or 2-point extrapolation).
  - Requires **net progress** (`first - current > 0`): a flat/oscillating episode is the best-so-far
    streak breaker's job, not this one — the two never fight over the same episode.
  - `current <= 0` (already green) → never trips; `remaining <= 0` (budget already spent) → never
    trips (that's the iteration cap's job, and a give-up at the cap would be thrash).
  - The average rate flatters the run (early-fast/late-slow crawls look *better* than they are), so a
    trip means "won't make it even on the optimistic read."

This is the missing third convergence question — stagnation (streak), oscillation (best-so-far), and
now **too-slow** (projection) — answered deterministically at zero model cost.

## Decision 2 — a projected trip FORCES give-up, never a re-scope (the routing)

A streak/oscillation trip (ADR-0060) climbs the budget-aware ladder and may earn **one autonomous
re-scope** — a re-plan can plausibly break a stuck approach. A **projected** trip must not: the run is
already improving, just too slowly, so a re-scope would only restart the same crawl and ride to the
cap. So a projected trip:

1. **Skips the reason-pass rung** (`not projected` guard in `test_node`) — a "different approach"
   retry re-thrashes for the same reason a re-scope would.
2. **Carries a `projected: True` flag** on the `progress_trip` payload into `supervise`.
3. **Forces `give_up`** in `supervise_node` (`projected_trip` added to the give-up condition) — so the
   autonomous resolver's "re-scope" is **overridden** and the run concludes `give_up_reason` /
   `stalled=False` → `classify_outcome` buckets it `honest_park`, strictly below the cap, by
   construction (same mechanism as every ADR-0060 give-up).

The reason string distinguishes the cause honestly: *"improving too slowly to pass in the remaining N
attempt(s)"* (projection) vs *"over N non-improving attempts"* (streak). The two trip kinds are
**mutually exclusive** (`projected = not tripped and …`), so the ladder is unambiguous.

## Decision 3 — a knob (default ON), gated like the rest

`honest_stop_projection` (`config/_settings.py`, `_knobs.py` `MOSAERA_HONEST_STOP_PROJECTION`,
`settings_store._ALLOWED_KEYS`) — default **True** (the crawl is the dominant thrash cause; off is the
pre-#65 behavior). A `MOSAERA_BENCH_HONEST_STOP_PROJECTION_OFF` A/B lever (`bench/cli.py`) measures it
ON/OFF against the reliability scoreboard, the same pattern as `MOSAERA_BENCH_CRITIC_OFF`. No posture
change is needed — it composes with the honest-stop already active for every run.

## Rejected

- **A new projection-threshold / lookahead-window knob.** The projection reads the *existing*
  `stall_limit`-scaled history and the *actual* remaining budget; a tunable margin is a second dial to
  mis-set. Conservatism is baked into the optimistic average-rate + `min_history`.
- **Letting a projected trip re-scope once (like a streak trip).** The whole point is that a crawl's
  re-scope re-thrashes; the measurement (thrash is the #1 annoyance) says conclude, don't retry.
- **Median/last-step rate instead of the average.** The average is deliberately optimistic (forgives a
  late slow-down); a last-step rate would trip *more* runs, contradicting "never trip a converger."
- **Editing `evaluate_gate` / `classify_outcome`.** Frozen. `give_up_reason` flows around the gate
  exactly like ADR-0060; honesty is by stopping earlier with an accurate reason, never by relabeling.

## Consequences

- Knobs: added `honest_stop_projection` (default ON). RunState: `progress_trip` gains an optional
  `projected` key (no new top-level field). No migration.
- `progress.wont_converge` + 3 unit tests (`test_progress.py`); 2 integration tests
  (`test_graph_integration.py`): a projected trip forces give-up over a resolver "re-scope"
  (`escalations == 1`, `honest_park`); projection OFF lets the same crawl keep fixing.
- The re-measurement (repeat=5 local baseline, qwen3 + scaffold + honest-stop, esc-OFF) lands the
  before/after thrash delta in CHANGELOG (ADR-0055).
