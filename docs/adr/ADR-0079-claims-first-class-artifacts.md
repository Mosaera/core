# ADR-0079: Acceptance claims as first-class artifacts — the claim contract

- Status: accepted. Status note (2026-08-03, #63): the `run_claims` ledger has its first
  reader — it rides `run_detail` (no new endpoint) and renders as the per-claim verdict
  table in the ReceiptCard (live gate, evidence tab, durable commit page).
- Date: 2026-08-02
- Owners: @Ashura
- Related issue: the Gate 2 pivot (to be tracked; roadmap "claim contract" arc)
- Related: [ADR-0072](ADR-0072-structural-spec-oracle.md) (the oracle whose activation was
  withdrawn — the null A/B this ADR answers), [ADR-0026](ADR-0026-tamper-to-escalation.md)
  (DECLARED RunState keys), [ADR-0057](ADR-0057-autonomous-oracle-posture.md) (posture),
  [ADR-0063](ADR-0063-capability-through-auditability.md) (traceability),
  [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes),
  `coding-standards.md` §15 (versioned artifact schemas — first implementation)
- Amended by: [ADR-0090](ADR-0090-gate-reason-classification.md), [ADR-0092](ADR-0092-claim-reason-split.md), [ADR-0095](ADR-0095-non-use-oracle-subtract.md), [ADR-0097](ADR-0097-consumer-impact-modify.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.
- Extended by: [ADR-0089](ADR-0089-intake-reachability.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

Gate 2 (`false_ship` ≈ 0) has consumed five oracle attempts: Proctor separation (real, doesn't
catch shape defects), mutation (moved MCB-05 0/3 — wrong defect class), the held-out critic
(abstains exactly on the subtle cases), the structural-spec oracle (n=25/arm A/B null — activation
withdrawn same day, see `engineering-history/structural-oracle-ab-2026-08-02.md`), and the
differential probe (suspicion signal, cannot certify). External research (2026-08-02) closes the
search: **no deterministic technique reconstructs absent intent from a vague brief and certifies
it.** Every oracle needs the claim *stated*.

Mosaera already half-states it. Quincy authors an `acceptance` field per backlog item
(`pm/_backlog.py`), it persists (`BacklogItem.acceptance`), the UI edits it, `spec_lint` lints it
deterministically. Then `_launch.py` **flattens it into the task string** and it dissolves:
`RunState` has no acceptance key, the Proctor/reviewer/coder see one blob, and `evaluate_gate`
takes ~12 scalars — **none per-criterion**, despite Evidence-Gated Advancement reading "tool-backed
evidence per acceptance criterion". The checkability analysis
(`engineering-history/brief-checkability-2026-08-02.md`) adds the sharpest fact: MCB-05/15's
structural claim **was bound to an oracle and still false-shipped 84–100%**, because the AST check
and the hidden grader interpret the same sentence differently. Coverage without a *single shared
binding* is not enforcement.

## Decision

Make the acceptance claim the unit of contract, evidence, and gating.

1. **Claim artifact** (versioned schema, `schema_version: 1` — the first implementation of
   coding-standards §15):
   `{id, item_id, text, predicate, provenance, oracle_kind, oracle_ref, material: bool}` where
   - `provenance ∈ {ENTAILED, REPOSITORY_INVARIANT, INFERRED}` — ENTAILED traces to exact brief/
     operator language; REPOSITORY_INVARIANT to a checked-in rule (the tamper guard is the
     existence proof); INFERRED is a model's belief about intent.
   - `predicate` is the **one binding**: a machine-evaluable statement (test node id, AST
     contract + parameters, parse rule). The gate and any grader consume the *predicate*, never
     re-interpret the *text*. A model may author text and propose a predicate; it never evaluates
     one.
   - `oracle_kind` from the measured vocabulary: `acceptance_test`, `validation_exit`,
     `tests_unmodified`, `ast_transformation_contract`, `wellformedness_parse` — or `none`
     (explicitly unbound).
2. **Only ENTAILED and REPOSITORY_INVARIANT claims may gate.** INFERRED claims may raise
   assurance, trigger clarification (ADR-0080), or park when material — they never silently join
   the acceptance contract. (Deterministic Final Authority, applied to specification.)
3. **Checkability verdict** — `spec_lint` extends to classify each item:
   `CHECKABLE` (every material claim has a bound predicate) · `PARTIALLY_CHECKABLE` (uncovered
   material claims → those claims park delivery, covered ones proceed) · `UNDER_SPECIFIED`
   (→ ADR-0080 clarification, or honest park headlessly). Deny-by-default: an unbindable material
   claim is a parked claim, not a dropped one.
4. **Per-claim gate evidence.** Core assembles `claims_satisfied: list[{claim_id, verdict,
   evidence_ref}]` in RunState (a DECLARED key, ADR-0026) and passes it INTO `evaluate_gate` as
   data; a new `unsatisfied_claim` GateReason names the specific claim in the park. The gate
   stays a pure function — it never reads storage (the ADR-0047 layer rule: policies may not
   import the store facade). This deliberately ends the convention of compressing new evidence
   into existing scalars to avoid touching `packages/policies`.
5. **Ledger persistence** — claims + per-run dispositions in `packages/memory` (Alembic `0018`),
   following the `ProjectMapObservation.provenance` NOT-NULL precedent and the persist ordering
   invariant (evidence rows before run status). DB-less runs keep the in-memory twin in the
   durable shape (the `RunEvent` pattern). This is the **first artifact-registry use case** the
   north-star's Not-Yet clause was waiting on — a claim ledger, not a generalized platform.
6. **Task string keeps working.** Headless/CLI runs without structured claims behave exactly as
   today (claims list empty → gate input absent → current behavior byte-for-byte). Structured
   claims ride alongside the task text, they do not replace it.

### Model-agnosticism consequence (the product dial)

Same gate, same claims, same audit trail on every model tier: a weak model satisfies fewer claims
→ more parks naming exactly which claim lacked evidence; a strong model satisfies more → more
delivery. Capability moves the park/deliver dial, never the safety contract — measurable by
running the identical suite per tier.

## North Star implementation test

- **Artifact:** the claim (versioned schema) + its per-run disposition rows.
- **Authority:** operator/Quincy author ENTAILED text at intake; repo rules own
  REPOSITORY_INVARIANT; predicates are bound deterministically; a model may only propose.
- **Independence:** the producer (Forge) never evaluates a predicate; oracles + gate do.
- **Evidence:** per-claim `evidence_ref` (test result, AST verdict, parse result).
- **Failure:** unbound or unsatisfied material claim ⇒ park naming the claim; fails closed.
- **Audit:** the ledger is the audit artifact — claim, provenance, predicate, evidence,
  disposition, reconstructable per run.
- **Model substitution:** claims/predicates are model-free data; any tier drives the same gate.
- **Scope:** needed now — it is the answer to the measured failure of oracle-per-defect-class.

## Consequences

- `evaluate_gate` signature change (trust boundary, CODEOWNERS) + `unsatisfied_claim` reason;
  17 test call sites in `test_gate.py` extend.
- Replay analysis (§15): existing 1,233 scorecards and stored runs have no claims — they replay
  with an empty claims list, i.e. current semantics; no reinterpretation of stored data.
- The bench gains an intake-contract variant later; the MCB suite measures the headless path and
  cannot demonstrate clarification value (all 24 briefs are materially checkable — see the
  analysis). ~~A new under-specified case class is future work under ADR-0080.~~ **DELIVERED 2026-08-05 as the governance benchmark, not under ADR-0080** (ADR-0083; corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`): the under-specified cases are `G-01`…`G-05` in `packages/core/mosaera_core/govbench/cases/`. Both arms are built; the effectiveness claim is NOT yet earned — `asking_paid: false` at n=3 per arm.
- Risk: predicate vocabulary too narrow at first — mitigated by `oracle_kind: none` + park rather
  than silent drop, and by the measured vocabulary covering all 8 structural claims in the suite.
