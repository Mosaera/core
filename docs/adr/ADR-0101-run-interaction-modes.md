# ADR-0101 — Run interaction modes: gates ask for direction, not permission to build

- **Status:** accepted (owner-approved 2026-08-13, in-session)
- **Scope:** core + api + web · threat model TM-0001 updated
- **Amends:** the guided/autonomous run vocabulary (ADR-0012 interrupt sites unchanged);
  **supersedes [ADR-0086](ADR-0086-approval-posture-ladder.md)** (the approval posture ladder —
  its `risk-gated` middle rung was never implemented; `accept` replaces it, and §2's risky-write
  list is carried forward unbuilt; back-link recorded 2026-08-18,
  `docs/audits/adr-corpus-review-2026-08-18.md`);
  relates ADR-0063 (capability through auditability), ADR-0087 (escalation gate),
  ADR-0036/0013 (test protection — unchanged and load-bearing here)

## Decision

A run has one **interaction mode**, operator-switchable while it lives:

| Mode | Write approvals | Direction checkpoint | Escalation / stuck / delivery gates |
|---|---|---|---|
| **ask** | every write interrupts (today's guided) | — (the writes are the conversation) | always |
| **accept** | auto-approved, each recorded as a decision | ONE pause after design: plan + design digest + files-to-touch → approve direction / adjust (notes → replan) | always |
| **auto** | auto-approved, recorded | none | always |

- **Gates are for direction, escalation, convergence, and delivery — never build
  supervision.** Per-file write approval is not a gate *category*; it is `ask` mode's
  behavior. The deterministic layer carries the safety the write gates appeared to:
  the policy allowlist (deny-by-default), the ADR-0036 tamper guard on delivered tests,
  the network-off sandbox, and the deterministic delivery gate, which **no mode can skip**.
  This is ADR-0063 applied to the operator surface: containment + verification at the
  door, not process-restriction.
- **Mode is run-scoped and mutable** (`PATCH /api/runs/{id}/mode`), effective at the next
  write/checkpoint decision, recorded as a `mode_change` decision row (from → to, when).
  Every auto-approved write records its own decision row (`auto-accepted (mode: …)`) —
  the same audit shape the ask-mode batching opt-in already writes. Nothing is silent.
- **Legacy mapping:** guided → ask, autonomous → auto. The stored/run-submit vocabulary
  keeps the legacy keys for compatibility; the snapshot exposes `interaction_mode`.
- **Posture hook (DIRECTION, not built):** RBAC/posture will later pin a floor per
  environment (e.g. regulated ⇒ ask only, no mid-run switching). The switch endpoint is
  where that floor will be enforced.
- **Counsel channel (DIRECTION, deferred by owner):** an out-of-band PM conversation
  about a live run is a NEW feature, not part of this redesign.

## Why now

Measured this week on live runs: a docs-only task produced five consecutive write gates
before the coder started; the operator experience is click-fatigue that reviews scaffolding
("gating a web designer mid-implementation"), while the finished product is what the
delivery gate exists to judge. The batching opt-in (2026-08-13) was the stopgap; this is
the decision it pointed at.

## Consequences

- The web run page gains a mode switcher and a docked gate arrival (no reflow); the gate
  panel composition is unchanged for escalation/stuck/delivery.
- TM-0001 gains a row: auto-accepted writes shift the guided-mode human checkpoint from
  per-write to direction+delivery; residual = a malicious write INSIDE policy scope lands
  in the workspace without a human glance until review/delivery — bounded by the sandbox,
  the allowlist, the tamper guard, review, and the delivery gate; identical to today's
  autonomous posture, now explicit for accept.
- The direction checkpoint reuses the existing interrupt/park machinery
  (`action: "direction"`); a park at it survives restart like any other (ADR-0012).
