# ADR-0006: Durable run transcript and honest run outcomes

- Status: accepted
- Date: 2026-07-11
- Owners: Alejandro Rengifo
- Related issue: run transcript UI/reasoning (MRs !135–!137), honest outcomes + durable transcript (MR !138)
- Related threat model: docs/threat-models/TM-0002

## Context

Two related honesty gaps sat between what a run actually did and what Mosaera
recorded about it.

- **Dishonest terminal status.** The run graph *always* ends via `deliver_node`
  (deliver is the graph's single terminus, whether the gate approved or the run
  simply exhausted its options), so the runner unconditionally wrote `completed`
  when the stream ran out. A run that reached the end because it hit the iteration
  cap, tripped the no-progress breaker, or never satisfied the reviewer was
  recorded identically to a real, approved delivery — dressing a give-up as
  success.
- **Ephemeral transcript.** The fine-grained progress a run produces — tool
  activities, agent reasoning-per-turn, node completions, the gate — lived only
  in the in-memory SSE fan-out (`RunSession._history`). It was lost on an API
  restart or session eviction, so a rehydrated run showed a blank timeline, and
  there was no off-platform, machine-readable record for debugging or a benchmark
  harness. The reasoning stream (MRs !135–!137) made the live view rich but left
  nothing durable behind it.

## Decision

### Honest terminal status — classify from final state

`RunSession._run` now inspects the final graph state instead of assuming success.
An approved delivery (`final["approved"]`) → `completed`; anything else → a **new
terminal status `incomplete`** plus a short **`termination_reason`**.
`_termination_reason` derives an ≤80-char reason, preferring the no-progress
breaker's own `stall_reason`, else mapping the gate's evidence reasons
(`iteration_limit`, `validation_failed`, reviewer-prefixed, `security_findings`,
`validation_unavailable`) to a plain-language phrase. It persists via
`MemoryStore.mark_run_incomplete`, which is **guarded so it never overwrites a
settled CANCELLED row** (a user cancel is authoritative). `runs.termination_reason`
(new nullable column, Alembic 0006) and the status flow into `snapshot()` and the
history detail, surfaced in the UI as an amber "Incomplete" badge + reason.

### Durable transcript — append-only `run_events`

A new append-only `run_events` table (Alembic 0006) captures the durable event
types (`activity`, `thought`, `update`, `interrupt` — `_DURABLE_EVENT_TYPES`;
lifecycle/control events like `_end`/`done`/`error` are excluded). It is written
through in `_emit`:

- **Outside the fan-out lock.** The DB append happens after the in-memory
  broadcast and outside `_events_lock`, best-effort via `_safe`, so a slow or
  failing DB write never stalls the live SSE stream or breaks a run.
- **Listed in true insert order (by `id`), not `seq`.** `list_run_events` orders
  by the autoincrement `id`. A rehydrated run restarts its per-session `seq`
  counter, so ordering by `seq` would interleave a resumed run's events wrongly;
  the monotonic `id` preserves chronological order across a restart.
- **Server-stamped epoch-ms `ts`.** `_emit` stamps each event's `ts`, so a replay
  (or a durable read) shows real times instead of clustering every event at the
  read moment.

### Transcript export API

`GET /api/runs/{id}/transcript` returns the durable record: JSON by default (full
event payloads — the benchmark/debug artifact) or `?format=md` (human-readable via
`_transcript_markdown`). It reads durable `run_events` first and falls back to the
live session's `transcript_events()` when nothing was persisted (in-memory store,
or a run still live in-process).

### Reasoning-per-turn stream

A `ReasoningCallback` (`apps/api/mosaera_api/reasoning.py`) rides the existing
LangChain callback propagation as a **sibling to the cost `UsageCallback`**,
attributing each model turn to its owning node and emitting one reasoning block
per turn (message-granularity, best-effort) — no change to the delicate graph
stream loop. Gated by `MOSAERA_STREAM_REASONING` (default on).

## Options considered

- **Always-`completed` vs classified terminal status.** Keeping the single
  success status was rejected — it is the dishonesty this ADR removes. A distinct
  `incomplete` status (not just a flag on `completed`) makes the give-up
  first-class in history and the UI.
- **Live-only vs durable transcript.** Leaving the transcript in the SSE fan-out
  loses it on restart/eviction and offers no off-platform record; a durable table
  is the point.
- **In-lock vs out-of-lock persistence.** Writing `run_events` inside the fan-out
  lock would let a slow DB stall every live subscriber. Best-effort, outside the
  lock, keeps the interactive path unblocked (deterministic-first / perceived
  latency).
- **`seq`-order vs insert-order listing.** Ordering by the per-session `seq`
  breaks after a rehydrate that resets the counter; ordering by the autoincrement
  `id` is chronologically correct by construction.
- **Token-firehose vs message-granular reasoning.** Streaming raw tokens is noisy
  and costly to persist; one block per model turn is legible and bounded.

## Security implications

The transcript now **persists agent reasoning/CoT and tool paths**, and
`GET /api/runs/{id}/transcript` is a **new read surface** reachable with the
service token — a new place run internals can be read. The event payloads are
derived from untrusted repo content and model output and must stay data, never
instruction. The load-bearing risk is **secret leakage into `run_events`**: model
narration or tool detail must not carry credentials into a durable, exportable
store. Cross-reference TM-0002 for the transcript read-surface and
reasoning/tool-path exposure. The `?token=` query-param auth already applies to
this route via the API middleware.

## Operational implications

- One Alembic migration (0006): the `run_events` table + `runs.termination_reason`
  column — schema changes go through Alembic, never `create_all`. Downgrade drops
  both.
- Persistence is best-effort (`_safe`): a DB failure never breaks a run, and the
  transcript API falls back to the live in-memory events, so a DB-less deployment
  still serves a transcript for an in-process run.
- No restart concerns — the durable rows survive an API restart and rehydrate; the
  `id`-ordered read stays correct across the `seq` reset.
- `run_events` grows per run; it inherits the run's `CASCADE` delete, so deleting a
  run prunes its transcript.

## Consequences

- Good: history and the UI tell the truth about how a run ended; every run leaves
  a durable, chronological, timestamped record that survives restart and exports as
  JSON/markdown for debugging and benchmarking; reasoning-per-turn is captured
  without touching the graph stream loop or the policies trust boundary.
- Cost: a new write on the run hot path (mitigated: out-of-lock, best-effort) and
  a new read surface that persists reasoning/CoT — see the security note on secret
  hygiene.
- Follow-up: ~~land TM-0002 for the transcript read surface;~~ **Corrected 2026-08-18**
  (`docs/audits/adr-corpus-review-2026-08-18.md`) — delivered since:
  `docs/threat-models/TM-0002-mosaera-api-web-server.md`. **Still open, and this ADR names it the
  load-bearing risk:** redaction/PII scrubbing on `run_events` payloads. No scrubber exists on that
  path — `packages/connectors/mosaera_connectors/redact.py` only strips credentials from git remote
  URLs — while the transcript is durable and exportable via `GET /api/runs/{id}/transcript`. A
  retention/GC policy is also still open if transcripts grow large.
