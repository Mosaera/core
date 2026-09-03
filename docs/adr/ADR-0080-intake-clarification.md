# ADR-0080: Intake clarification — ask when asking is cheap

- Status: accepted
- Date: 2026-08-02
- Owners: @Ashura
- Related issue: the Gate 2 pivot (claim-contract arc)
- Related: [ADR-0079](ADR-0079-claims-first-class-artifacts.md) (the claims this clarifies),
  [ADR-0012](ADR-0012-cohesive-team-supervision.md) (the existing late pause),
  [ADR-0004](ADR-0004-auth-and-session-model.md) (who may answer),
  [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (park semantics)
- Amended by: [ADR-0091](ADR-0091-clarification-proposal-kind.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.
- Extended by: [ADR-0089](ADR-0089-intake-reachability.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

Mosaera has exactly two human pause points, both **late**: the delivery gate (at the door,
`policies/approval.py`) and the supervise escalation (mid-thrash, `nodes_plan.py`). There is no
pause at the one moment a question costs almost nothing: intake. The research conclusion behind
ADR-0079 is that absent intent cannot be reconstructed after the fact — but in the product's
actual workflow (operator ↔ Quincy → validated backlog) intent is *negotiable at intake*. The
missing control is the mechanism that notices under-specification early and asks the one
authority who has the answer.

Wiring facts (explored 2026-08-02): a third graph interrupt would touch `_loop.py` dispatch,
`_lifecycle.py` park/resume, `ApproveBody` (**the resume channel is boolean+free-text only**),
`client.ts` payload types, `RunWorkbench.tsx` branch, transcript labels, `_rehydrate.py`. But the
budget park (`runner/_budget.py`) proves a park need not originate in the graph — and intake
happens at *backlog* time, where Quincy's chat + the backlog UI already exist.

## Decision

Two paths, one rule — **a material claim without a binding is asked about or parked, never
guessed**:

1. **Primary — backlog-time (no run, no interrupt).** When ADR-0079's checkability verdict on a
   generated/edited item is `UNDER_SPECIFIED` (or a material claim is INFERRED), Quincy raises a
   **clarification request on the item itself**: the specific claim, why it is unbindable, and
   2–3 proposed bindings the operator can accept, edit, or reject in the existing backlog UI/PM
   chat. An accepted proposal becomes ENTAILED (operator words are the provenance); the item's
   verdict recomputes. Items with open material clarifications are **not runnable** —
   deny-by-default at launch, same mechanism as `locked`.
2. **Fallback — run-time intake park (headless).** A run launched with `UNDER_SPECIFIED`
   material claims (CLI, API without backlog, or a stale item) parks **before implementation** —
   at `plan`, before tokens are burned — as `honest_park(under_specified: <claim>)` (ADR-0006
   vocabulary; a new termination reason, not a new outcome). In guided mode this surfaces through
   the existing interrupt machinery as a new `action: "clarify"` payload
   `{claims: [...], proposals: [...]}`; the resume shape extends `ApproveBody` with an optional
   `answers: {claim_id: text}` — the one API shape change, additive and optional.
3. **The answer is data, not instruction.** An operator's answer updates claim text/predicate via
   the same validated path as backlog edits (coerce + lint + recompute verdict) — it is never
   spliced raw into a prompt. Repo content stays untrusted; the *operator's* decision is the one
   trusted input, attributed in the ledger (who answered, when, what changed).

## North Star implementation test

- **Artifact:** the clarification request + answer, recorded on the claim (ledger rows).
- **Authority:** the operator owns intent; Quincy may only propose bindings.
- **Independence:** clarification changes the *contract*; evaluation stays with oracles + gate.
- **Evidence:** the recomputed checkability verdict; the answered claim's new provenance.
- **Failure:** unanswered material clarification ⇒ not runnable / parks pre-implementation.
- **Audit:** ask → proposals → answer → recomputed verdict, all reconstructable.
- **Model substitution:** proposals are model-authored but non-binding; any model tier.
- **Scope:** the intake half of ADR-0079; no new agent, no conversational A2A messaging.

## Consequences

- Cheap where it matters: the primary path reuses PM chat + backlog UI; the run-time park fires
  pre-implementation, so a weak model's under-specified run costs a question, not a thrash loop.
- MCB cannot measure this (all 24 briefs are materially checkable — see
  `engineering-history/brief-checkability-2026-08-02.md`); a new **under-specified case class**
  is required before any effectiveness claim. Per ADR-0081, no such claim may be made without
  proven arm divergence.
- Risk: clarification fatigue (asking too often). Mitigated by asking only on **material**
  claims, batching per item, and always attaching accept-in-one-click proposals. The ask-rate is
  a measured dial, not a promise.

## Status note (2026-08-03, Wave 3 built)

§1 (backlog-time, primary) BUILT: the fenced `clarify` block → stored on the item (Alembic 0019) →
resolved through the validated `enhance` path; open material ask ⇒ not-runnable at the single
launch choke point (override = the operator's escape hatch); clarify card + Question-open
badge in the UI. §2 (run-time fallback) BUILT-MINIMAL: an UNDER_SPECIFIED run parks at
plan-entry with zero model calls via the plan-unworkable seam (honest_park by construction;
diagnostic `under_specified` cause). **`ApproveBody.answers` DEFERRED, deliberately**: the
runner dispatch auto-approves unknown interrupt actions, so a new `clarify` action is a
footgun until that dispatch is hardened; answers belong at backlog time per §1, and a
run-time answer rides the existing deny+feedback replan meanwhile. Deterministic auto-ask at
decompose time (Quincy proposing without being chatted with) ~~is follow-up scope~~ **SHIPPED** — `run_intake_pass` (`packages/core/mosaera_core/intake_ask.py`) runs the bounded pass behind `ask_enabled`, and the standing-backlog sweep landed 2026-08-05 (`backlog_audit.py`). Corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`. **`ApproveBody.answers` is still deferred and still absent**, but its stated blocker is gone: ADR-0082 §5 landed `ApproveBody.option_id` with an unknown id rejected (400), never auto-approved.

Status note (2026-08-03, #63 Ledger): resolving no longer DELETES the exchange — the record
is retained (`status: resolved|dismissed` + `resolution` + `resolved_at`) and rides a new
`clarification_record` field; the open-only `clarification` field and the launch gate are
unchanged. The retained ask→answer renders as a ledger row on the run pages.
