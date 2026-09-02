# ADR-0075: Layer-2 widening — convert the engine-blocked give-up (#76)

- Status: accepted (built behind `disposition_gap_close`, default OFF; **red-team (2 rounds) +
  targeted measurement DONE 2026-07-23**; class-2 stays default OFF, not recommended ahead of class 1
  pending the oracle-successor)
- Date: 2026-07-23
- Owners: Mosaera core + api
- Related issue: #76 (Layer-2 disposition) — the "other convertible classes… after the MVP measures"
  successor ADR-0074 pre-scoped. Built from the 2026-07-22/23 four-lens deep dive.
- Related threat model: TM-0001 (the Layer-2 disposition row — this widens its convertible signal
  and adds supersession).
- Related ADRs: ADR-0074 (the disposition MVP + its red-team), ADR-0070 (the LLM-judge dead-end —
  the invariant this preserves), ADR-0058 (Proctor owns the tests, NOT a new role), ADR-0060 (the
  honest-stop that labels this class).
- Amended by: [ADR-0090](ADR-0090-gate-reason-classification.md), [ADR-0092](ADR-0092-claim-reason-split.md), [ADR-0093](ADR-0093-mutation-operator-sufficiency.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

The deep dive measured, with hidden-grader ground truth, that **44% of accepted-baseline runs end
holding grader-perfect code that does not ship** — and decomposed the 47% honest-park pool: 16/34
parks are `give_up` where **all 16 hold grader-100 code trapped by a failing local test the coder
may not edit**; ≥11 of the 16 give-up reasons explicitly name a wrong/broken ENGINE-authored test
(some **unsatisfiable by any correct implementation** — e.g. an invented `env=` API the authored
test plumbs but never uses). The root cause is structural: the engine authors a protected oracle
pre-impl, freezes it (author-once), refuses the coder on it — and **no component is authorized to
act on "the authored test is wrong"**. Both built *repair* mechanisms measured-failed and were
reverted (ADR-0070: 0 conversions, false_ship up; the MR-C auto-loosen: a red-team-confirmed
false-ship channel). The dial is not the lever (balanced: the same runs thrashed at 3.3× tokens
with zero extra deliveries), and the tester is not removable (false_ship 5/105 without the oracle).

ADR-0074's MVP class (`oracle_unverified`) deliberately excluded every honest-stop channel
(red-team FIX-NOW #1) — correctly, because an *incidental* give-up must never auto-ship. But the
measured convertible population lives exactly there, under a **deliberate, evidence-gated**
sub-signal: the run gave up *because of the engine's own work-product*, not because the code or the
coder failed.

## Decision — a second convertible class + supersession, same deterministic gate

### The class (`is_engine_blocked_give_up`, core `disposition.py`)

Deny-by-default, ALL of:
- `give_up_reason` truthy; every OTHER honest-stop channel (`stalled`, `plan_unworkable_reason`,
  `blocked_reason`, `escalate_reason`) falsy — ADR-0074 FIX-NOW #1 stands for them.
- No tamper (`tests_modified` falsy), no critic veto, and gate reasons ⊆
  ~~`{validation_failed, reviewer_unknown, iteration_limit, oracle_unverified}`~~ — any
  tamper/security/reviewer-objection/critic/validation_unavailable reason disqualifies.
  **SUPERSEDED 2026-08-08 by [ADR-0090](ADR-0090-gate-reason-classification.md)** (noted 2026-08-18,
  `docs/audits/adr-corpus-review-2026-08-18.md`): the literal set is no longer in the code. Membership is DERIVED from `REASON_CLASS` via
  `give_up_allowed_reasons()` (`eligibility.py`) — its own comment records why: the hand-written
  frozenset *"went stale the moment a later feature minted a gate reason it had never heard of"*
  (`unsatisfied_claim`), silently narrowing both arms to nothing. The admission POLICY is unchanged;
  only its hand-written spelling is retired.
- **The failing set is NON-EMPTY and a SUBSET of the engine-owned tests.** The failing set is
  re-derived from the terminal `test_output` via the existing `parse_failing_tests` (node-ids →
  file paths; `failing_tests` does not survive to final state — supervise clears `progress_trip`),
  with an uncapped-ish bound (50) so a coder-owned failure cannot hide behind the display cap.
  Engine-owned = `authored_tests` ∪ `proctor_edits` (both declared final-state keys). An EMPTY
  derivable failing set is NOT convertible (the vacuous-subset hole, closed by construction). One
  coder- or repo-owned failing test ⇒ not convertible (the code may genuinely be wrong — e.g. the
  MCB-11 shape, whose coder-added wrong test correctly fails the subset check).

`convertible_park_class` is the shared umbrella (class 1 `oracle_unverified`, class 2
`engine_blocked_give_up` — disjoint by construction: class 1 requires `give_up_reason` falsy).
One knob (`disposition_gap_close`) gates both — one Layer-2 feature, one switch, still default OFF.

### Supersession (`supersede_engine_tests`) — retract, never repair

Before authoring, the callers DELETE the trapping engine test files from the working tree: the
engine retracts its own wrong work-product; the fresh independently-verified test replaces it as
the shipped oracle evidence. Deterministic, no model; constrained to `tests/` paths within the
trapping set (which is engine-owned by construction — a baselined/coder file is unreachable).
Deletions ride the existing `git add -A` staging into the ship commit; the commit message and the
`disposition.verified-ship` audit name the superseded files (auditable in the MR evidence). This is
deliberately NOT "repair" — post-diff editing of a test the coder saw fail is the reward-hacking
channel ADR-0058/0070 closed; deletion + fresh authorship has no wrong-code-to-fit.

### The gate is unchanged — plus one extra check

`close_oracle_gap` (author → assertion floor → green on the delivered tree → comprehensive
mutation) runs exactly as red-teamed in ADR-0074; supersession happens BEFORE it, so its
pre-existing-tests tamper hash never sees the deletions. **New for this class only:** after a
`verified` verdict, the WHOLE remaining suite must run green (`resolve_plan(None)`/`run_plan`)
before the commit — a deleted engine test that another test imported would break the delivered
tree, and the authored-suite green step alone cannot see that. Not green ⇒ deny + audit, park
stands. A genuinely-wrong-code give-up still parks: the fresh spec-anchored test fails the green
step (measured in the ADR-0074 bench: false-ship 0/7 on wrong code).

The bench hook mirrors the rung (supersede → gap-close → whole-suite check) so the measurement
stays faithful; the JSONL gains `layer2_class` + `superseded`.

## Rejected

- **A new test-steward role** — rejected by the project's own record (roadmap #54: "NOT a new
  role"; ADR-0058 rejected-options) and by the role-economics criteria every existing role met.
- **Repairing the trapping test** (LLM judge or deterministic auto-loosen) — both built, measured,
  reverted (ADR-0070, MR-C). Supersede-and-re-verify is the only sound form.
- **Reverting the dial to balanced** — measured strictly dominated (0 conversions, 3.3× tokens).
- **Converting ALL give-ups** — a give-up whose failing set includes any non-engine test stays
  parked; a hand-raise (`blocked`/`escalate` surviving), a thrash `stalled`, and a plan breaker
  stay non-convertible.

## Consequences

- Addressable pool: the give-up class alone is ~22% of accepted-baseline runs (all grader-100);
  with ADR-0074's class the correct-code park pool is ~40pp of delivery ceiling (47%→~87%).
- Cost: one tester authoring call + the deterministic gate + ONE extra whole-suite sandbox run,
  per qualifying park, only with the knob ON.
- No new knob, no graph/`state.py`/`packages/policies` touch, no migration. The shipped tree for a
  class-2 conversion contains: the delivered diff + the fresh verified test + the deletions of the
  superseded engine tests — fully green end to end.
- **Honest limits — the who-tests-the-test residual is AMPLIFIED, and the mitigations are PARTIAL
  (red-team R1+R2, corrected twice).** The *mechanism* (a weak/acceptance-faithful authored test ships
  wrong code) is the same class as ADR-0074's ACCEPT residual and fires in class 1 too. Class 2 adds a
  false-ship *trajectory class 1 cannot have*: it converts a population *selected for* code-vs-oracle
  disagreement (higher wrong-code prior), and **deletes the one in-tree oracle that flagged the code**
  before re-authoring. Deterministic hardenings (a POSITIVE ALLOWLIST — only supersede a proven-NEW
  authored path, never one in `integrity_baseline`/`proctor_edits`; origin-gating; the uncapped
  failing-set parse) close the *delete-a-human-test* class. But the CORE residual is **not** closed and
  the mitigations against it are weaker than they look:
  - **The held-out tester is near-theater for the DOMINANT case.** The fresh test is authored *from the
    acceptance* (`_author_instruction` forbids reading the code), so it is a function of `(model,
    acceptance)`. When the blind spot is in the acceptance (the shared input — e.g. the deleted engine
    test asserted a contract the acceptance never mentions), a *different* model is NOT independent; the
    held-out swap only helps against *model-idiosyncratic* blind spots, which are not the measured class.
  - **The residual fires on MUTABLE regions, not just non-mutable ones** (R2, correcting an earlier
    claim): an acceptance-faithful-but-incomplete test passes the enumerated mutants; and wrong behaviour
    in a diff-**unchanged-context** line the changed-line-confined mutation gate never probes.
  - **Efficacy caveat:** the default held-out author (`gpt-oss:20b`) is empty-output-flaky, so it often
    fails to `unavailable` → **false-PARK, never a false-ship** (deny-by-default holds) — but realized
    conversions are RARER than the "~22% addressable pool" (which was measured with the coder as tester).
  - **The post-supersession whole-suite check is collection-integrity ONLY — NOT a correctness gate:**
    after deleting the red test the suite is green by omission; the fresh authored test is the sole
    correctness authority for the delivered change.

  The residual core is inherent to "the model authors the oracle from the acceptance and a deterministic
  gate checks it" — it is the **oracle-successor's mandate**, not closeable by more membership/model
  patches (STOP rule, §Red-team). Given the amplification, class 2 (the give-up conversion) should stay
  the more conservative of the two and is not recommended for enable ahead of class 1 pending that
  successor.

## Red-team — ROUND 1 DONE (2026-07-23, 3 refute-agents, post-merge per CLAUDE.md; feature default OFF)

**Target** = the widening (class predicate + supersession + whole-suite check). **Budget: 2 rounds.**
Verdict: the safety claim was BROKEN — one reproduced end-to-end **false-ship**, plus signal defects.
All FIX-NOW items fixed + re-verified in the follow-up (`fix/adr0075-redteam-r1`). STOP rule not
tripped (one ACCEPT class + distinct deterministic defects).

**FIX-NOW (fixed):**
1. **[CRITICAL] `proctor_edits` deletion → real false-ship (probe c).** `trapping_engine_tests`
   built the deletable set as `authored_tests ∪ proctor_edits`, but `proctor_edits` keys are
   pre-existing BASELINED HUMAN tests. A proctor-edited baselined test was therefore deletable —
   reproduced end to end: a baselined test guarding a negative-input contract was deleted, the suite
   went green by omission, and wrong `double()` shipped. **Fix:** `engine_owned = authored_tests`
   ONLY (the tester's own new files); a give-up whose failing set touches a baselined test now fails
   the subset check → parks. Falsifies the ADR's original "unreachable by construction" claim.
2. **[HIGH] give-up origin-blindness (probe 4/F1).** `supervise_node` clears `blocked_reason`/
   `escalate_reason` when it converts a coder hand-raise to a give-up, so those guards were dead. A
   coder BLOCKED/ESCALATE hand-raise (a coder-capability stop the ADR excludes) was convertible.
   **Fix:** exclude on `coder_escalated` (survives) + the engine-controlled give-up prefixes
   (`blocked:`/`escalation unresolved:`/`gate kept denying`) — only the no-progress origin converts.
3. **[MEDIUM] `_FAILING_CAP=50` spoof (probe b).** A coder printing ≥50 forged `FAILED
   tests/<authored>` lines before the real coder-owned failure filled the cap and hid it. **Fix:**
   parse uncapped; one non-authored failure disqualifies (fails safe — the whole-suite check re-runs
   the real suite regardless).
4. **[HIGH mitigation] amplified who-tests-the-test (probe e / end-to-end).** Class 2 deletes the
   correct backstop on a higher-wrong-prior population, and the tester defaults to the coder model —
   shared blind spot. **Fix:** class 2 requires a **held-out tester** (author with the critic model;
   no held-out model ⇒ park). Narrows, does not close, the core residual.
5. **[hardening] supersession path-guard.** `supersede_engine_tests` used a raw `root / rel` +
   `unlink()` (would follow a symlinked dir; not reachable today). **Fix:** routed through
   `workspace.resolve` + a `tests/`-containment + symlink refusal.

**ACCEPT / DEFER-TO-SUCCESSOR:** the core weak-(held-out-)tester residual on a non-mutable region —
the ADR-0074 ACCEPT class + the #74 mutation blind spot, the oracle-successor's mandate. §Consequences
now states the amplification honestly.

**SAFE (refuted):** tamper-guard ordering (before-set snapshot after deletion), partial-ship (next
run's `reset --hard`+`clean` restores deletions), commit/concurrency (whole disposition under the
project mutex), the empty/vacuous set, mutation-source pollution by a test deletion.

### Round 2 (2026-07-23, 2 agents against the fixed branch) — STOP RULE TRIPPED

Round 2 re-attacked the fixed code. R1's fixes for origin-gating, the cap, the held-out gate, and the
path-guard all **held (verified)**. Two results decided the disposition:

- **The delete-a-human-test class RECURRED via a new route → FIX-NOW, class-closing (this MR).** R1
  dropped `proctor_edits` from the deletable set on the invariant "`authored_tests` = the tester's own
  new files only." That invariant is FALSE: the run's tester can EDIT a pre-existing test during its
  first authoring turn (no `protected_paths` set yet), the edit lands in `authored_tests` with no
  not-in-baseline filter, and the repair turn excuses the tamper — so a baselined human test leaks in and
  supersession deletes it (reproduced end to end). Two consecutive rounds on the SAME class ⇒ per the
  STOP rule, stop point-patching membership and land the **positive allowlist**: supersede a path ONLY
  if it is proven NOT pre-existing (`authored_tests` − (`integrity_baseline` ∪ `proctor_edits`)). This
  closes the class at the source (any pristine-clone test is non-deletable however it entered
  `authored_tests`), not just the two observed routes.
- **The who-tests-the-test residual RECURRED and is INHERENT → ACCEPT, escalate to the oracle-successor.**
  A class-2 false-ship still reproduces (a weak or acceptance-faithful-but-incomplete held-out test ships
  wrong code), and it is strictly the ADR-0074 ACCEPT class, amplified. It is NOT a cleanly-fixable
  deterministic gap — the blind spot is in the acceptance (the shared input), so model independence
  cannot close it. Per the STOP rule: **no more patching; the oracle-successor owns it.** §Consequences
  now states the amplification and the mitigations' real (partial) strength honestly.

Also fixed (R2, not safety): a bench-mirror divergence — the bench snapshotted `protected_paths` AFTER
supersession while production snapshots before; reordered so the measurement faithfully mirrors
production. SAFE/confirmed: the `is_symlink` guard is dead behind `resolve` (harmless — containment is
the real guard); same-model-behind-two-providers is a config-misconfiguration case of the accepted
residual.

**Red-team: DONE (2 rounds, STOP rule tripped on both the delete-a-human-test class — closed by the
positive allowlist — and the who-tests-the-test class — accepted, escalated to the oracle-successor).**

## Measurement (DoD, DONE 2026-07-23)

The 4 cases × 3 through the real engine (cautious + #80 + esc OFF + `--layer2`, held-out author
`critic=devstral:24b`; `docs/demos/observed-outcomes.md` → *Class-2 targeted DoD measurement*):
- **FALSE conversions: 0 / 12** — the hard safety invariant holds. MCB-05 parked its wrong code 3/3;
  MCB-11 clean-delivered 3/3 (its trap class is gone — the merged scaffold arming fix, validated live).
- **TRUE conversions: 0** — class-2's target (an engine-blocked give-up) barely formed (MCB-01/04
  mostly clean-delivered; give-ups are non-deterministic and prevention reduces them). The one give-up
  that fired (MCB-04 rep3) returned `unavailable` (a transient `SandboxUnavailable` → deny-by-default
  park), not a conversion. So the in-bench run did NOT demonstrate a positive conversion — but the
  conversion mechanism is proven in the controlled red-team repros (competent independent author +
  working sandbox → correct code verifies, wrong code parks).
- **Verdict, empirically:** the disposition **never false-ships**, and class-2 **either does not fire or
  fails safe to park** — consistent with the red-team's conclusion that the practical give-up recovery
  lever is *prevention* (author the right test) + the oracle-successor, not this converter. Class-2
  stays default OFF and is not recommended for enable ahead of class 1.
