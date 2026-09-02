# ADR-0063: Capability through auditability — the agent workbench

- Status: accepted (owner-ratified 2026-07-19). Status note (2026-08-03, #63): the
  traceability leg gained the durable delivery receipt — gate verdict, priced residual,
  vouch diagnosis, and claim verdicts persist as a `receipt` decision row — now rendered
  as the LEDGER view (owner-directed redesign, same day): a chronological timeline of the
  item's life on both run pages, sealed with `finished_at`/`engine_version`/`receipt_id`
  (migration 0020; a deterministic sha256 anyone can re-derive from the durable record).
- Date: 2026-07-19
- Owners: Mosaera core (owner-directed 2026-07-19)
- Related: ADR-0002 (deterministic-first + model-agnostic — this is a third DNA principle),
  ADR-0046 (posture governance), ADR-0061 (v1 measured DoD), the `#43` reliability arc, `#55`
  (coder toolkit), `#57` (Proctor faithfulness). North star: `docs/architecture/north-star.md`.
- This ADR states a **principle + direction**. It authorizes no capability change by itself; each
  capability-opening below ships as its own MR and, where it touches a trust boundary, its own
  red-team. What it changes is the *default reasoning* used to decide those MRs.

## Context — what the reliability work taught us

Two arcs converged on the same root cause. `#55` (the coder toolkit) found the coder thrashing on a
*trivial* task because it had no sanctioned way to run a snippet or keep a scratch file — so it
smuggled debug scripts into `tests/`. `#57` found the dominant thrash cause was an oracle that
**dictated the implementation** (exact whitespace, a private symbol name) instead of **verifying the
outcome**. Different symptoms, one disease: **the harness restricts the agent's *process* in the name
of safety, which produces thrash without buying safety** — because the safety was already provided by
something else (the sandbox), and the restriction only takes away the tools that make coding tractable.

The tell is introspective. A capable agent (the kind we consume through `get_chat_model`, and the kind
a human senior engineer is) codes by *experimenting*: run a probe, keep a scratch file, get the full
failure, run one test fast, self-check against reality, run the gates before handing off, ask a helper.
Take those away and even a strong model flails. Our harness took most of them away.

## The principle (decision)

**Safety is three orthogonal mechanisms — containment, traceability, verification — and only one of
them is a boundary. Restricting the agent's process is not a fourth safety mechanism; it is a tax on
capability. Default to: free inside the sandbox, logged throughout, proven at the door.**

1. **Containment** is the hard boundary: the throwaway, network-off, `/work`-confined sandbox. It caps
   the *blast radius* regardless of what the agent does inside. This already exists and is correct.
2. **Traceability** is the trust primitive: every action is recorded, attributed, reasoned, and
   reproducible in a tamper-evident, exportable log. This is what *licenses* broad capability — you can
   grant power you can always reconstruct and review.
3. **Verification** happens at the delivery boundary: the *output* is proven correct (the correctness
   oracle) and ships as a reviewable, revertable MR carrying its evidence. The gate judges the *result*,
   not the *process*.

Corollary — the load-bearing reframe: **because the sandbox already contains the blast radius,
restricting what the agent does *inside* it buys almost no safety while directly causing thrash.** Move
enforcement to the boundary (verification) and the log (audit); free the agent inside. Process
restrictions survive only as *cheap defense-in-depth*, never as the primary mechanism, and never at the
cost of the agent's ability to do the work.

This is a third DNA principle beside ADR-0002's deterministic-first and model-agnostic. It is also the
concrete form of the owner's standing thesis that **MR-based versioning (rollback) + RBAC + an audit
trail let us relax capability gating** — auditability, not pre-restriction, is the safety net.

## What each pillar requires (honestly)

### Containment (have it — keep it as the boundary)
The sandbox is the wall: `--network none` on the test phase, read-only rootfs, `--cap-drop ALL`,
ephemeral, single writable `/work`. Nothing inside it can reach the host, the network, or the source
repo. *This* is why in-sandbox freedom is safe. The dangerous, irreversible, outward-facing actions —
delete repo, push/merge, outward network, secret access — live **outside** the sandbox and stay
human/RBAC-gated (the `packages/policies` trust boundary). The allowlist should therefore be *generous
inside the wall and strict at the wall*, not strict everywhere.

### Traceability (partial — promote it to the trust primitive)
The audit log is the "camera on the workbench," and it is what makes the workbench safe to hand over.
It must carry, per run:
- **Provenance on every action** — command / diff / tool call, the *actor* (role + model + version),
  timestamp, inputs, outputs/exit, cost.
- **The reasoning trail** — hypotheses (`HYPOTHESIS:`), the plan, decisions — *why*, linked to the *what*.
- **Reproducibility** — the run replays from the log + checkpointer.
- **Tamper-evidence + export** — append-only, hash-chained or signed, exportable (ADR-0046's audit log).
- **A verification-evidence bundle with every delivery** — not just the diff, but the *proof*: which
  oracle vouched, which tests/coverage/critic, the gate decision. "Verifiably excellent" means the
  evidence is *attached and checkable*, not asserted.
- **A capability manifest per run** — the tools the agent had, used, and was denied, so an auditor knows
  the power surface (the `CODER_TOOL_CAPABILITIES` drift map is the seed).

Today we have seeds — `run_events`, the durable checkpointer, the transcript, per-role attribution — but
they are not yet a single tamper-evident, exportable, evidence-bearing log. Promoting them is what
*unlocks* the capability relaxations below.

### Verification (the critical-path arc — verify outcome, not process)
The gate must prove the *result* meets the spec without dictating *how*. This is exactly the
correctness-oracle arc (ADR-0061 gate 2): a spec-derived Proctor that asserts *behaviour/intent*, a
held-out different-model critic, graded against a hidden suite. An oracle that pins incidental format
(the `#57` finding) is verification *doing restriction's job* — it must be calibrated to the spec's
actual strictness. Verification integrity (e.g. the delivered acceptance tests are the *authored* ones,
not coder-weakened) is legitimate and stays — but it is enforced as *evidence at the boundary* (a hash
match at delivery), with per-write blocking kept only as defense-in-depth.

## The workbench (the direction — each opens with audit, not with a safety tradeoff)

| Capability | Today | Direction (all inside the sandbox, all logged) |
|---|---|---|
| **Scratch space** | none → smuggles into `tests/` | a first-class `/scratch` mount: write/run anything, **excluded from the deliverable diff**, every file + command logged. Cheapest, highest-impact item. |
| **In-sandbox execution** | read-only probe (`#55`), can't persist | full write+exec inside the wall; each command → the audit log. The wall, not the probe, is the boundary. |
| **Fast, rich feedback** | whole-suite `-q` | run one test / snippet; full traceback + expected-vs-actual (the head+tail cap + `verbosity_assertions=2` shipped in `#55/#56` are the start). |
| **Self-verification** | relies on the downstream gate | the agent runs the gates (lint/type/test) itself and iterates to green before handoff. |
| **Helpers on demand** | fixed spine | scoped sub-agents for parallel explore/verify, each with its own logged transcript (the orchestrator direction). |

None of these is a safety trade — each is *more capability and more audit trail at once*.

## Posture is the tuning knob, never the off-switch for containment or audit

How much in-sandbox freedom before delivery is a **posture** decision (ADR-0046), not a global default:
Free/Business run the open workbench; Regulated may narrow the boundary (tighter delivery review,
dual-control, a smaller in-sandbox allowlist) — but **containment and the audit log are invariant across
all postures**. Posture can only *tighten* (ADR-0046), and it tightens the *boundary and the ceremony*,
never the containment or the traceability. This is the one genuine policy call to make deliberately per
tier, and it is now written down to be chosen rather than defaulted.

## How the recent work clicks with this direction (the evaluation)

- **`#57` (Proctor faithfulness) — dead-on.** The over-strict Proctor is *verification doing
  restriction's job*: it dictated format/structure instead of verifying the outcome. The arc's **revert
  of the deterministic auto-loosen** is this principle in action — a mechanical rewrite of the oracle
  reopened false-ship (verification must stay sound), so we kept **detection + naming to a
  judgment-based repairer** and deferred true loosening to the spec-reading critic. Correct: *don't
  weaken verification; stop letting verification restrict the process.* The detector's `overstrict_vs_ref`
  measure is itself a small audit artifact (it proves, against the reference, that a test over-restricts).
- **`#55` (coder toolkit) — right direction, one flinch.** Giving the coder a probe, richer failure
  output, and the acceptance-test bodies is exactly the workbench. The **read-only** probe is the
  restriction reflex re-appearing: the sandbox already contains it, so the honest version is
  write+exec-inside + logged. Its live-Docker red-team (32 attacks, all blocked at the kernel mount
  boundary) is the *evidence* that containment — not the read-only limit — is what makes it safe.
- **The sandbox — the model citizen.** It is containment done right, and it is *why* the rest can open up.
- **The tamper guard / protected paths / write-gates — reframe, don't delete.** Protecting the oracle's
  integrity is a *verification* concern (delivered tests must equal authored tests) → enforce it as
  evidence at the boundary, keep per-write blocking as defense-in-depth. Per-file write approval is a
  *posture* knob (HA/guided), not an autonomous default.
- **`run_events` + checkpointer + MR delivery — the seeds** of traceability and boundary-verification,
  not yet the tamper-evident evidence-bearing log this principle needs.
- **Honest counter-check:** this principle does **not** say "remove the guards." It says *classify* each
  guard as containment (keep — the wall), verification (keep — but verify outcome, not process), audit
  (invest — the enabler), or process-restriction (relax to defense-in-depth). `#57`'s refusal to weaken
  the oracle is the proof that "capability through auditability" is **not** "capability through
  relaxation" — verification stays sound; only the *process* opens up.

## The sequenced arc this implies

1. **Scratch mount** — small, immediate; kills the `tests/`-abuse *and* unblocks experimentation. The
   cheapest capability with the clearest audit story (excluded-from-diff, fully logged).
2. **Verify-outcome oracle** — the correctness-oracle arc (ADR-0061 gate 2): the gate proves the result
   without dictating the path. Already the critical-path arc; this ADR says *why* it is load-bearing here.
3. **Audit log as enabler** — promote `run_events`/checkpointer/transcript into the tamper-evident,
   exportable, evidence-bearing log (ADR-0046), *then* progressively open the in-sandbox workbench
   (write+exec probe → self-gate → sub-agents), each opening riding on the audit trail + its own red-team.

## Consequences

- The design question shifts from *"is this capability safe to allow?"* to *"is this action contained,
  logged, and its output verified?"* — a question we can answer mechanically.
- Reliability and safety stop trading off: the workbench reduces thrash (capability) while the audit log
  + boundary verification preserve safety. `#57`'s revert shows the guard rail — verification is never
  the thing we relax.
- It gives the governance/audit-log arc a *reason* beyond compliance: it is the primitive that unlocks
  capability, so it moves up the priority order.

## Rejected

- **Process restriction as a safety mechanism.** It is a capability tax the sandbox already makes
  redundant; it is the direct cause of the `#55`/`#57` thrash.
- **"Capability through relaxation."** Not this. Verification (does the output meet the spec?) and
  containment (the wall) are *never* relaxed — only the agent's in-sandbox process opens up, under audit.
- **A blanket capability grant now.** Each opening ships as its own reviewed, red-teamed MR; this ADR
  sets the default reasoning, not a free pass.
