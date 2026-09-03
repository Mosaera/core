# ADR-0022: Live model escalation — recover a too-weak autonomous run by bumping the bottleneck role

- Status: accepted
- Date: 2026-07-12
- Owners: Alejandro Rengifo
- Related: [ADR-0016](ADR-0016-deterministic-model-escalation.md) (the pure diagnose/escalate funcs this graduates to the live path), [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (the verify overlay this composes with), [ADR-0017](ADR-0017-reason-before-park.md)/[ADR-0018](ADR-0018-reasoning-escalation-ladder.md) (in-run reasoning recovery — the precursor), [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (the honest `incomplete` this triggers on)

## Context

ADR-0016 built the machinery for model escalation — `diagnose_bottleneck` (attribute a failed run to exactly
ONE role from the terminal signals, no model call) and `escalate_role` (bump only that role one tier up its
`role_escalation` ladder) — but wired it into the **benchmark only**. On the live autonomous path, a run whose
coder (or, with ADR-0020, tester) is simply **too weak** for an item ends honestly `incomplete` and **parks** —
even when a stronger model is configured and available. Reason-on-stall (ADR-0017/0018) recovers a *stuck* run
by rethinking with the same model; it does not change the *model*. So the one recovery lever that addresses
"this model can't do it" was sitting idle in `bench/`.

## Decision

**On an autonomous item run that ends `incomplete`, diagnose the bottleneck role and, if it has a next tier,
re-run the same item with the stronger model — before parking.** The loop lives in `AppContext`, the graph
owner (a `RunSession` only holds a compiled graph), and reuses ADR-0016's pure funcs verbatim.

1. **The outer loop is event-driven, in `launch_item._after`.** `_after` already branches on terminal status
   (clean delivery → advance; cancelled → clear; else → pause). A new branch sits **before the pause**: when
   `session.status == "incomplete"`, `_try_model_escalation` runs; if it launches a re-run, `_after` returns
   (no pause note). This mirrors the existing `advance_project` chain — the re-run is a fresh `launch_item` on
   the worker thread after the prior session is terminal and the project reservation released, then re-reserved
   by the re-launch (no deadlock, single-writer per project; a raced manual launch → `ProjectBusy` → falls
   through to the pause, exactly as the chain already handles).
2. **Settings are injected through the factory, drift-free.** A shared pure `resolve_run_settings(req,
   escalation_settings)` is the single place run Settings are computed: `None` → `from_env` + the sandbox /
   cost-mode / verify (ADR-0020) overlays; an escalated `Settings` (from `escalate_role`) is returned verbatim.
   Both `default_graph_factory` (new optional `settings=` param) and `launch_item` (which needs the run's exact
   Settings to diagnose from) call it, so the graph is built with byte-identically what the diagnosis reads.
   The factory return stays a 4-tuple — no unpack-site churn.
3. **Bounded, gated, autonomous-only.** Fires **iff**: `status == "incomplete"` (an honest not-approved run —
   never a crash/`error` or a human `cancel`), `mode == "autonomous"`, `model_escalation_enabled` (a **separate
   opt-in**, default OFF — NOT auto-enabled by `autonomous_verified`, because a re-run is expensive), a
   configured `role_escalation` ladder for the diagnosed role (empty → `escalate_role` returns None → park),
   and `escalation_attempt < max_model_escalations`. The re-run resets the item's branch to the predecessor tip
   (ADR-0021) and starts clean; the escalation path is audited (`escalation.<role>`) and best-effort (a build
   failure records a note, never leaves the item silently `todo`).

## Consequences

- **Recovers a genuinely-too-weak run** (the coder that couldn't pass validation, or — with ADR-0020's tester
  on — the tester that over-specified: `diagnose_bottleneck` attributes each) by escalating exactly the one
  culprit role, not the whole team (cost discipline preserved). Would let MCB-05's stuck 8th case get a stronger
  coder instead of parking.
- **Composes with the correctness gate (ADR-0020).** Verify catches ship-wrong; escalation recovers can't-do.
  Together an autonomous run either delivers *correct* or escalates then parks — it doesn't ship wrong and
  doesn't give up while a stronger tier remains.
- **No live grader → an honest diagnosis limit.** `acceptance_failed=False` always (there's no hidden oracle
  live), so the diagnosis rests on the graph's terminal signals (gate reasons, reviewer verdict, stall kinds).
  It cannot catch a false-positive *ship* — that stays benchmark-scoped, as ADR-0016 already states.
- **Local tiers now; resumed runs don't escalate.** In practice `role_escalation` holds local tiers today; a
  cloud tier would egress on an auto re-run — doubly gated (operator configures the ladder AND flips the knob),
  the same class as ADR-0018's deferred cloud egress. A run that parked and was *rehydrated* after restart does
  not itself escalate (the attempt counter isn't persisted); the items it subsequently chains do. Both are
  acceptable v1 boundaries.

## Threat surface
No new class. Local escalation is host-only. A **cloud** tier placed on a `role_escalation` ladder would egress
repo content on an unattended re-run — already owned by **TM-0001** (BYOM key/context egress), doubly gated
(configured ladder + `model_escalation_enabled`). The formal egress + hosted-tier-price gate is **deferred to
the cloud-enablers step** (same deferral ADR-0018 records for `reason_escalation`). No TM edit now.

## Alternatives considered
- **Auto-enable escalation for every autonomous run** (bundle into `autonomous_verified`). Rejected: a full-item
  re-run is expensive and only helps when a stronger tier is configured — it earns its own opt-in.
- **Escalate inside the graph** (a node). Rejected: rebuilding the graph with different model bindings is a
  build-time concern the factory owns; the graph shouldn't re-instantiate itself. `AppContext` is the seam.
- **A stronger single reviewer/verifier instead.** Doesn't address a too-weak *producer*; orthogonal to ADR-0020.
