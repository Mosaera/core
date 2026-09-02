# ADR-0070: Independent spec review — a held-out judge names the authored tests the Proctor false-fails (#66 Phase A)

- Status: **reverted** (2026-07-21) — measured net-null-to-negative; the code was removed from `packages/` (verified 2026-08-18: `proctor_spec_review`, `review_tests_vs_spec`, `review_authored_tests`, `_spec_review_block` have zero occurrences outside this file). ~~**SUPERSEDED / REVERTED**~~ — one status, not two; corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`. **The mechanism is gone; the LESSON stands.**
- Successor: **ADR-0071** (comprehensive mutation) and **ADR-0072** (structural-spec oracle) — the deterministic path this revert mandated. Re-opening is permitted ONLY on the containment question, per **ADR-0085 §3**.
  The design record is retained below; see **§Measured outcome** for why it was reverted.
- Date: 2026-07-20 (accepted) → 2026-07-21 (reverted)
- Owners: Mosaera core
- Related issue: #66 (two-sided oracle — ship correct code the Proctor false-fails) — Phase A (prevention).
  Successor to #54 (ADR-0058, the Proctor's self validate/repair) and #57 (ADR-0062, the deterministic
  over-strictness detector). Phase B (the ship-despite-red-test adjudication) is a separate ADR.
- Related threat model: TM-0001 (the oracle-authoring trust surface — same boundary #54/#57 touch).
- Red-team: **required** (touches oracle-authoring). Disposition recorded in §Red-team.

## Context

The measured `thrash_cause` split (postfix baseline, 48 runs) showed the dominant class of *correct code
that does not ship* is the **Proctor authoring a test that is WRONG** — it contradicts the task spec,
over-specifies beyond the contract, or is brittle. The coder writes correct code (grader Impl 100),
correctly recognises the test is wrong, cannot modify it (protected), and parks `blocked: the test is
wrong`. Verbatim: *"the test expects bool numeric but the task says exclude bool"* (MCB-16#1), *"the test
contradicts the spec, 16/17 pass"* (MCB-18#0).

**The mechanisms to catch this already exist and were ON when these parked** (the bench runs the full
autonomous posture): `tester_repairs_tests` (#54, the Proctor's coder-blind self validate/repair) and
`proctor_faithfulness_guard` (#57, a deterministic AST over-strictness detector). They missed these cases
because:

- The AST detector is **syntactic** — it catches an exact-whitespace/private-name pin, but cannot see a
  *semantic* contradiction with the natural-language spec (a `bool` counted as numeric when the task says
  to exclude it is a perfectly ordinary assertion structurally).
- The `_proctor_validate_repair` turn is the **self-same weak Proctor reviewing its own tests** — the same
  model that authored the contradiction, with the same blind spot.

## Decision — a held-out, spec-grounded review of the authored tests, before locking

Add `proctor_spec_review` (default OFF; **posture activation HELD pending measurement** — see §Red-team).
When on AND the critic is a DIFFERENT model from the coder (`held_out_ok`), the authored acceptance tests are reviewed by the
**held-out critic model** against the SPEC (task + plan + design) *before* they lock, and each assertion
that SEMANTICALLY contradicts or over-specifies the task is NAMED. The named conflicts ride the **same
coder-blind repair turn** (`tester_repairs_tests`) — the Proctor corrects them with `edit_file`.

- **The engine only NAMES; the Proctor edits.** Identical trust structure to #57 — the judge is read-only
  and never touches a test. The Proctor's repair is still coder-blind (no implementation exists yet) and
  still bounded by the assertion floor + the pre-impl red-verify, so a repair that guts a test to a
  tautology is not excused (ADR-0058 / ADR-0068) and the run parks.
- **Independent by construction.** `held_out_ok` (critic model ≠ coder model) is the gate — a critic bound
  to the coder shares its blind spot, so the review is skipped (no efficacy, never a safety change).
- **Deny-by-default in the SAFE direction.** The judge is told to name a conflict ONLY on a clear
  contradiction/over-specification and to stay silent when unsure; off / not held out / no tests / a judge
  fault / no confident conflict all yield `""` and the Proctor's own validate/repair still runs. A FALSE
  conflict at worst nudges the Proctor to loosen a faithful test (bounded by the assertion floor +
  red-verify); a MISSED one just leaves today's behaviour. It can never tighten a test or block delivery.
- **Echo-injection hardened** like the verdict parse (ADR-0034/#60): `CONFLICT:`-anchored lines, fenced
  blocks stripped before scanning, so a `CONFLICT:` line quoted from the untrusted test bodies is not read
  as the judge's own finding. The checklist is capped (≤12).

Structurally: `review_tests_vs_spec` (agents/critic.py) → `AgentsBridge.review_authored_tests` →
`_spec_review_block` appended to the repair instruction in `_proctor_validate_repair`
(graph/`_proctor_authoring.py`, extracted from `nodes_plan` to stay under the god-file ceiling).

## Rejected

- **Let the judge EDIT the tests.** Widens an LLM judge's authority into the protected-test space and adds
  a false-ship channel (a wrong edit fitting a test to nothing). Keeping NAME (judge, read-only) + EDIT
  (Proctor, coder-blind, `tests/`-confined, floor-gated) preserves the existing boundary.
- **A stronger deterministic detector.** A semantic contradiction with a natural-language spec is not
  decidable by AST; this is exactly the reasoning an LLM adds over the #57 detector (which stays — the two
  compose: syntactic pins + semantic conflicts).
- **Escalate the authoring model instead.** Model strength helps but is a cost/config lever orthogonal to
  this; the independent *second* model closes the self-review blind spot even at equal strength, and the
  posture already runs a held-out critic whose model this reuses.
- **Editing the gate / `evaluate_gate`.** Untouched — this changes only what the Proctor is TOLD before it
  locks its tests; the delivery gate and the frozen outcome classifier are unaffected.

## Consequences

- Knob `proctor_spec_review` (default OFF; posture activation HELD — see §Red-team). When activated it is
  one extra held-out model call on the author path for a verified autonomous run (the deterministic-first
  ladder is respected — it earns its place doing semantic reasoning code cannot). No new RunState, no
  migration. It no-ops entirely without a genuinely held-out (second) model.
- `nodes_plan.py` (was at the 500-line ceiling) is split: the Proctor-authoring helpers move to
  `graph/_proctor_authoring.py`; `nodes_plan` re-exports the three the node uses.
- Phase A only PREVENTS a wrong test from locking. A wrong test that slips past still parks correct code —
  that is Phase B (the coder-disputed, critic-adjudicated ship path), a separate, more adversarial ADR.
- Measured on the wrong-test cluster (MCB-16/18/01/02) esc-OFF; effectiveness is model-gated (the same
  local model powers the judge), so the honest expectation is a partial lift locally, larger with a
  stronger held-out judge.

## Red-team

Done (2026-07-20, 3 parallel refute-agents: oracle-weakening, prompt-injection, independence/timing).
**Verdict: the mechanism's INVARIANTS hold; its posture activation is HELD pending measurement.**

- **Independence / coder-blind timing / crash-safety — HELD (REFUTED).** `held_out_ok` and the judge
  read the SAME `role_model` binding (no desync; misconfig fails safe to `""` or loud build error, never
  a silent coder-model judge). The spec-review is nested in `_proctor_validate_repair` under the run-once
  + `iteration<=1` compound guard, so it can NEVER see the coder's implementation (inherits the #54 FN2
  fix; unit-tested). A judge fault is caught → `""`; no memo/transcript bleed; the refactor is
  behaviour-neutral (no import cycle, re-exports verified).
- **Prompt-injection — REFUTED on safety.** The judge only NAMES; the Proctor that acts cannot delete and
  is `tests/`-confined + floor-gated, so an injected `CONFLICT:` cannot force a ship. One robustness gap
  fixed FIX-NOW: the spec-review prompt now carries the verdict path's "do NOT reproduce/quote a literal
  `CONFLICT:` line from the inputs" instruction, so the "echo-hardened like the verdict parse" claim is
  actually true (previously it was fence-strip-only). The `_acceptance_contract` input fence is escapable
  (no fence escaping) but every downstream path is bounded — ACCEPT.
- **Oracle-weakening — the drop-a-requirement channel → DEFER-TO-SUCCESSOR + POSTURE HELD.** A false
  conflict from a WEAK held-out judge could nudge the Proctor to loosen a FAITHFUL test, dropping one of N
  requirements; the residual suite clears the PER-SUITE assertion floor, reds vacuously pre-impl, catches a
  mutation on the SURVIVING logic, and could ship wrong code. All three agents converged on this as the
  **inherent-static-floor class** — the "catches-some ≠ enforces-all" residual **already escalated by #52
  and #54** to the Proctor-hard-gate / dynamic-per-requirement-verification successor. Phase A does not
  introduce the class; it adds a semantic-loosen TRIGGER. Per the STOP-rule spirit (3-way convergence on an
  inherent class), it is **not patched here** — it is the successor's mandate. BUT because Phase A widens a
  false_ship class and its safety is MODEL-GATED, its **posture activation is HELD** (mirrors #60's
  `behavior_preservation_guard`): the knob ships default OFF + measurable, and is activated in the posture
  only once a targeted A/B shows it converts the wrong-test parks WITHOUT raising `false_ship`. (Finding 2 —
  a loosened NEW authored test rides the weaker `mutation is not False` branch — folds into the same
  deferred class; the posture hold moots it until the successor lands.)
- **STOP rule:** tripped in spirit (all 3 agents surfaced the same inherent-static-floor class) → escalated
  to the Proctor-hard-gate successor, no further patching.

## Measured outcome (2026-07-21) — reverted

The posture was held pending a targeted A/B; running it (DeepSeek-R1:32B as the held-out judge, a
genuinely strong reasoner; both arms share the DeepSeek outcome-critic so only the spec-review differs;
MCB-01/02/16/18 + MCB-05 canary, repeat 3, esc-OFF, $0) settled it:

- **A latent bug surfaced first.** The judge reused the *critic agent*, whose "judge the delivered
  OUTCOME" persona overrode the review task, so it judged nonexistent pre-impl code and never emitted the
  `CONFLICT:` format — the review was **silently inert** (every result parsed as 0). The 3-agent red-team
  verified the *wiring* but could not see a runtime persona-override; only running it + logging the raw
  judge output caught it. Fixed (critic MODEL + a dedicated test-reviewer system prompt); live-confirmed
  DeepSeek then named a real over-specifying test.
- **The working mechanism is net-null-to-negative.** With the fix, DeepSeek produced *sane* conflicts
  (e.g. a landing-page test pinning exact marketing copy the task leaves open), but the outcomes did not
  improve: **0 park→ship conversions in 15 ON runs**; where it acted (MCB-02) it mildly *regressed*
  (2 clean → 1); aggregate `clean_deliver 9→5` (mostly variance — the biggest drop is a 0-conflict case)
  and `false_ship 2→3` (NOT the review's doing — MCB-05 is a refactor case where the deterministic
  scaffold authors the tests, so the review never runs there).
- **The structural lesson:** fixing the Proctor's wrong test — even with a strong judge — does **not**
  make correct code ship. Correct code parks for *deeper* reasons (the gate can't confidently *verify*
  it; planner budget; coder non-convergence). A faithful test is not sufficient. The whole LLM-judge
  oracle-authoring premise (Phase A **and** the more-aggressive Phase B) does not crack throughput on
  these models; the reliable oracle work is the **deterministic** path.

**Decision:** revert the spec-review code (the `_proctor_authoring` module extraction is kept — it is a
good refactor). Do **not** build Phase B. The successor is the **deterministic per-requirement /
Proctor-hard-gate** verification (a red-verified asserting test per requirement, or per-line mutation
that the suite must catch) — judge-strength-independent, the real `false_ship`≈0 lever.
