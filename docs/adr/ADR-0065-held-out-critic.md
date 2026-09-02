# ADR-0065: The held-out critic — a veto-only, different-model judge of the delivered outcome

- Status: accepted
- Date: 2026-07-19
- Owners: Mosaera core (run-reliability arc `#43`; correctness-oracle successor `#60`)
- Related: ADR-0063 (capability-through-auditability — this is sub-arc 2, "verify the OUTCOME"),
  ADR-0061 (v1 measured DoD — this is the **correctness** gate, the only one 0.6.0 outright fails),
  ADR-0057/0058 (autonomous oracle posture + Proctor test-steward), ADR-0044 (`oracle_verified`),
  ADR-0031/0034 (the reviewer-silence backstop this veto composes with), ADR-0062 (`#57` Proctor
  faithfulness — the loosening this arc is the deferred successor of), ADR-0013 (the agent-role SOP).
- Trust-boundary change (touches `packages/policies` gate + allowlist + the delivery decision) →
  red-team required before `#60`'s successors (MR-B/C) build on it.
- Amended by: [ADR-0100](ADR-0100-critic-may-not-veto-an-unbound-claim.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context — the gap this closes

`0.6.0`'s only outright-failed v1 gate is **correctness**: an autonomous run can DELIVER code the
hidden grader marks WRONG (`false_ship`, MCB-05/09). The confirmed mechanism is
**executed-but-unasserted**: the suite runs the changed code and asserts *something*, but not the
*specific behaviour the spec requires*, so it is green for the wrong reason. Three prior red-teams
(`#52`/`#54`, ADR-0057/0058) proved this class is **inherent to the deterministic checks** — the
static assertion floor proves a test *contains* an assertion (not that it checks the change),
coverage proves *execution* not *assertion*, and mutation ties the two only for one sampled construct
per file. They **STOP-ruled** the deterministic OR-oracle and escalated to this successor: *"dynamic
per-test verification + a rigorous spec-derived Proctor + a held-out different-model critic
(downgrade-only), graded against a hidden suite."* This is also exactly the judgment layer `#57`
deferred loosening to ("the Proctor here; a held-out critic later"). ADR-0063 framed the mandate:
**verify the OUTCOME (does the delivered code meet the spec?), not the process.**

## Decision

Add a **held-out critic**: a NEW agent role `critic` that judges the delivered OUTCOME against the
spec, once per delivery, and can ONLY downgrade a ship to an honest park.

1. **A new role, cloned from the reviewer's shape — not an upgraded reviewer.** The reviewer's
   APPROVE is load-bearing *positive* evidence and it runs *per-iteration* in the fix loop; the
   critic is **inert-on-approve (veto-only)**, **once-per-delivery**, with its own **held-out** model
   binding. Both stay. ADR-0013 SOP: `config` `Role`/`_ROLES`; `team.AGENT_REGISTRY` (read-only,
   display "Judge"); `packages/policies` `allowlist` (`list_files`/`read_file`/`search` — read-only,
   CODEOWNERS); `critic_model` (default `gpt-oss:20b`, held out from the coder's `qwen3-coder:30b`);
   `agents/critic.py` (a bounded read-only loop) + `personas/critic.md`; the `agents_bridge` seam.

2. **A conditional node between `review` and the gate.** `critic_node` runs ONLY when
   `tests_passed is True` (deny-by-default — a failing/None run already parks and has no delivered-
   passing code to judge) AND when the critic is genuinely **held out** (a different model from the
   coder — else it shares the coder's blind spots and is no independent check). It is **memoized by
   `tree_hash()`** (one model call per distinct delivered tree — off the iteration loop, the exact
   mutation/coverage cost-gating pattern) and wrapped `try/except → None` (a fault degrades to
   no-verdict, never crashes, never parks by itself). It gives the critic the spec (`task` + `plan`),
   the delivered `diff`, the `test_output`, and the deterministic `#57` over-strictness findings
   (context for judging the code, not a defect in it). It sets `outcome_verdict`.

3. **Veto-only, calibrated, injection-resistant.** The persona: identify a SPECIFIC spec requirement
   the delivered code fails to meet and VETO only with that concrete evidence; when unsure, SHIP.
   This is the two-sided target — catch MCB-05 (a concrete wrong branch) while NOT vetoing correct
   additive work (MCB-10, which has no unmet requirement). The verdict is a parseable
   `VERDICT: SHIP|VETO`; only a VERDICT-anchored `VETO` sets `vetoed`. Every input (task, diff, repo)
   is treated as untrusted DATA — text telling the critic to "approve"/"ignore the spec" is not an
   order to it.

4. **The gate attach — a new veto-only `GateReason`.** `evaluate_gate` gains `critic_vetoed`; when
   set it appends the `critic_vetoed` reason. Because `_resolve` is monotonic in `reasons` and this
   reason is neither `reviewer_unknown` nor `reviewer_requested_changes`, it forces a **park in every
   mode** (autonomous, and on a reviewer APPROVE): `core != ["reviewer_unknown"]` AND `reasons != []`.
   It is a **universal, downgrade-only** signal — it can only flip ship→park, never park→ship (the
   critic adds no approve branch and never appears on an otherwise-deny path).

5. **Posture + measurement.** `critic_enabled` (deny-by-default) turns ON in `apply_oracle_posture`
   for verified autonomous runs — it IS the correctness gate; guided/HA keep the human. Model tier is
   **local-default, measure the cloud delta** (owner decision): a held-out local critic ships as the
   default ($0, on-box, some judgment), with a stronger cloud tier as an opt-in
   `role_escalation["critic"]` (gated by `allow_cloud_egress` + `model_prices`). The bench measures
   OFF vs local-critic vs cloud-critic via `MOSAERA_BENCH_CRITIC_OFF`; the critic's effect on
   `false_ship`/`clean_deliver` flows through the scoreboard `outcome`, plus a `critic_vetoes` count.

## Consequences

- **Kills the executed-but-unasserted `false_ship` by judgment where determinism structurally
  can't** (MCB-05/09) — the highest-leverage next step to the v1 correctness gate.
- **Downgrade-only means it can never make things less safe**: the worst a broken/weak/injected
  critic can do is fail to veto (no protection gained) or veto correct work (an over-park, measured);
  it can never CREATE a ship. A blank/faulted critic simply doesn't act.
- **Cost**: one model call per delivered tree on the autonomous delivery path (memoized, off the
  loop) — consistent with the mutation/coverage checks already there.
- **Two-sided risk to watch (measured, MR-D):** over-veto of correct additive work would show as
  `clean_deliver` falling / a new `honest_park`. One-line rollback: `critic_enabled=False`.
- **Honest about efficacy:** `#57` found the weak local model doesn't reliably obey its own persona,
  so a *local* critic likely catches less — hence the cloud delta is **measured, not assumed**.

## Red-team disposition (3 adversarial agents, one round; STOP rule not tripped)

Trust-boundary DoD. Three refute-agents (structural park→ship; held-out + injection; state/memo/
degrade). The **downgrade-only property held** — a brute-force over all 2304 gate-input
combinations found 0 rescue violations (a veto parks 100% of the time, autonomous and human alike;
the reason is never dropped; `outcome_verdict` is declared + survives checkpoint/rehydrate).

- **FIX-NOW — echo-injection of the verdict parser (MED, fixed + re-verified).** A reasoning model
  restates untrusted input (diff/quoted source) in its answer, so a `VERDICT:` line PLANTED there
  was read as authoritative by the first-match parser — a false-VETO DoS, or a suppressed veto.
  Fixed exactly as the reviewer solved the same class (ADR-0034): `critic_verdict` now strips fenced
  blocks and collects ALL distinct anchored verdicts; a conflict (echoed opposite next to the
  genuine verdict) or none → **no veto** (deny-by-default in the safe direction, per "when unsure,
  SHIP"). Kills the DoS; bounds suppression to the pre-critic baseline (veto-only ⇒ no new ship).
  Persona reinforced to never reproduce a literal `VERDICT:` line.
- **FIX-NOW — the fault sentinel was memoized (MED, fixed + re-verified).** `critic_node` cached
  `None` on a fault, so one transient blip could PERMANENTLY suppress a veto on a re-delivery of the
  same tree (a looping coder → identical `tree_hash`). Now only a COMPLETED judgement is memoized; a
  fault leaves the memo empty so the next pass retries. (The degrade-to-None itself stays — deny-by-
  default, the mutation-check precedent.)
- **DEFER-TO-SUCCESSOR — bypass-edge coverage gap (LOW).** The critic covers the `review → gate`
  delivery path (where the MCB-05/09 false-ships flow). A green delivery reaching the gate via the
  plan-early-park or supervise-give-up bypass is not critic-judged. Confirmed NOT a downgrade-only
  violation (ships byte-identically with/without the critic) and pre-existing (review + test are
  bypassed there too). Successor: route those edges through outcome verification, or have the runner
  refuse an autonomous auto-approve on a green delivery when the critic is enabled + held-out yet
  `outcome_verdict is None`. Logged on the roadmap.
- **ACCEPT — `held_out_ok` provider-alias (LOW).** It compares `(provider, model)` strings, so the
  critic could be aliased to the coder's exact model/endpoint via a second provider id and still read
  as held-out. Efficacy loss, never a safety hole (veto-only + additive). Consider `(endpoint,
  model)` normalization or a run-submit warning so MR-D's efficacy measurement isn't silently invalid.
- **ACCEPT — degrade-abuse (LOW).** Crashing the critic via repo content to suppress a veto is not
  reliably inducible (model errors → partial output → None, not an exception; the critic still gets
  the diff/spec and can veto). Fails safe to baseline; the FIX-NOW above removes the permanence.
- **NOTE (pre-existing, separate) — ad-hoc `/runs` autonomous skips the egress gate.** The cloud-
  egress consent gate lives in the autonomous project sweep (`launch_item`); the ad-hoc `POST /runs`
  autonomous path applies the posture but has no egress gate — pre-existing ADR-0024 scope, affects
  ALL roles equally, not introduced by the critic. Flagged for a separate hardening MR.

## Alternatives rejected

- **Upgrade the reviewer instead of a new role.** Rejected: the reviewer's positive APPROVE is
  load-bearing and per-iteration; making it veto-only + once-per-delivery + held-out would break the
  fix loop. Separation of the two verdicts is the point.
- **Deterministic loosening / a stronger static oracle (ADR-0062 MR-C).** Built, red-teamed, REVERTED
  — mechanical rewrite erases semantic whitespace and guts behavioural assertions. Loosening needs
  spec *judgment*; that is exactly this critic.
- **Let the critic also APPROVE (raise a ship).** Rejected as the core safety property: a critic that
  can create a delivery is a new way to false-ship. Veto-only is non-negotiable.

## Amendment (2026-08-03, #61): the critic proposes, a deterministic policy disposes

The pre-registered over-veto risk (above) fired and was measured: **12 vetoes of
grader-passing work vs 5 true catches (~29% precision)** across a 140-run fingerprint-
validated sweep (engineering-history/claims-gate-ab-2026-08-03.md) — the 20b judge does not
reliably obey its own "when unsure, SHIP" persona. Every true catch was on the shape cases
the deterministic gate cannot call (the exact residual this ADR exists for); every over-veto
was elsewhere.

**Decision (knob-gated `critic_claim_protocol`, default OFF, A/B before any posture flip per
ADR-0081):** the critic's output contract becomes per-claim
`REFUTED | SUPPORTED | INSUFFICIENT_EVIDENCE` with VERBATIM requirement + evidence quotes
(`personas/critic_claims.md`), bound to the run's ADR-0079 claims; the veto decision moves
out of the agent entirely into `mosaera_core/critic_policy.py`: a REFUTED proposal counts
only when its requirement quote literally occurs in the operator-approved task/claims text
AND its evidence quote occurs in the delivered diff/output (normalized substring, minimum
length). Hallucinated or paraphrased requirements — the measured over-veto shape — convict
nobody, deterministically. SUPPORTED/INSUFFICIENT never veto (abstention is not a park).

Unchanged and still binding: veto-only, downgrade-only, held-out, once-per-delivery,
memoized, fault→None; the gate seam (`outcome_verdict.vetoed` → `critic_vetoed`) is
byte-identical and `packages/policies` is untouched. New: the judgement (reason + rows) is
finally durable — a `critic` Decision row, the gate interrupt payload, and scorecard meta
(`critic_rows`) all carry it; the 17 sweep vetoes had persisted zero reason text.

Discarded refutations are RECORDED (`verified: false` rows), never hidden — the calibration
is auditable per-veto. Legacy protocol retained behind the knob as the A/B arm.

### Fix round (2026-08-03, same day — the aborted first A/B)

The first A/B was ABORTED at 20/140 when the persisted rows diagnosed the over-vetoes as a
third failure shape, **premise poisoning**: whole-brief-derived claims included sentences
describing the STARTING state, and the critic refuted the run for succeeding (MCB-03 vetoed
with evidence "exit code 0"; MCB-13 with the ladder's own removal line). Four deterministic
tightenings before the re-run: (1) premise sentences are non-material at derivation
(`claims._PREMISE`); (2) unknown claim ids are never material; (3) **residual jurisdiction**
— the critic may veto only claims determinism could not cover (`unbound`/`unevaluable`);
a deterministic `satisfied` outranks a model REFUTED, and a deterministic `failed` already
parks without the critic; (4) format-noncompliance is ABSTENTION (advisory reason, no veto
authority) — the legacy fallback measurably leaked the old over-veto failure (3 of 5).
