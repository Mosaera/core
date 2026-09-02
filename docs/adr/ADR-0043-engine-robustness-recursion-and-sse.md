# ADR-0043: Engine robustness — the recursion limit covers the escalation budget, and SSE streams without pinning a worker

- Status: accepted
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Related: [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the supervisor escalation loop this bounds), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (park honestly at a cap, never crash)

## Context

Two engine durability gaps the re-audit reproduced.

**1. The supervisor loop still crashed on a high `max_escalations`.** LangGraph's
`recursion_limit` caps node executions per invoke. An earlier fix (`recursion_limit_for`) sized
it off `max_iterations_ceiling` so raising the iteration ceiling parked honestly instead of
crashing. But it ignored the *other* loop: the supervisor re-scope. `plan_node` increments
`iteration` every time it runs, and the supervisor routes back to `plan` up to `max_escalations`
times **without re-checking the iteration cap** (that check lives on the test/review path, not
the supervise path). So the worst-case step count is `(max_iter + max_escalations) ×
NODES_PER_ITER`, while the limit was sized off the ceiling alone — a `max_escalations` of, say,
20 blew past it with a `GraphRecursionError` instead of parking. `max_escalations` itself is only
floored at 0 (no upper bound).

**2. Each SSE viewer pinned an anyio threadpool worker.** `GET /runs/{id}/events` streamed a
**sync** generator (`session.events()`, a `queue.get(timeout=1.0)` poll loop) via
`iterate_in_threadpool`. That runs the generator in anyio's threadpool, and the generator blocks
in `queue.get` for the life of the connection — so every open stream, even idle, holds one
worker. anyio's pool defaults to **40** tokens, so ~40 idle viewers exhausted it and starved
*every* sync route (FastAPI runs sync handlers in the same pool).

## Decision

**1. Size the recursion limit off both budgets.** `recursion_limit_for` now returns
`(max_iterations_ceiling + max(0, max_escalations)) × NODES_PER_ITER + RECURSION_HEADROOM`. A
high escalation budget now raises the limit with it, converting the crash into an honest,
bounded park (ADR-0006) — the run still terminates via the `escalations > max_escalations`
give-up, just without a `GraphRecursionError`. The default (ceiling 12, `max_escalations` 1) is
160; it was 150, a 10-step increase that only ever adds headroom.

**2. Stream SSE from an async generator.** Add `session.aevents()` — the async counterpart of
`events()`, same replay-then-live fan-out semantics, but it polls the thread-safe subscriber
queue **non-blockingly** (`get_nowait`) and `await asyncio.sleep(0.25)`s between polls. The
endpoint is now `async def` and yields from it directly (no `iterate_in_threadpool`), so the
generator runs on the event loop and holds **no** threadpool worker while idle. `events()` stays
for the tests that drain the backlog synchronously; both share factored `_subscribe`/
`_unsubscribe`/`_stream_ended` helpers.

## Consequences

- A run with any `max_escalations` parks honestly at its caps instead of crashing; raising the
  knob raises the recursion budget proportionally, mirroring the ceiling fix.
- SSE now scales to many concurrent viewers without degrading the rest of the API; a burst of
  streams can no longer starve sync endpoints. Event-delivery latency improves slightly (0.25s
  poll vs the old 1.0s `queue.get` timeout).
- `recursion_limit_for`'s default rises 150 → 160 (headroom only). Integration tests that pin a
  small fixed `recursion_limit` for fast failure are unaffected (they don't call it).
- Follow-up (not taken here): `max_escalations` is still unbounded above — a truly absurd value
  yields a huge-but-valid limit and a long, bounded run, not a crash. A dedicated
  `max_escalations_ceiling` knob could clamp it if operators ever set pathological values.
