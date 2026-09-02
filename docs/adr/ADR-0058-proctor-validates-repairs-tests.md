# ADR-0058: The Proctor validates/repairs tests up front + a locked-down reactive test-review park (#54, arc #43)

- Status: accepted
- Date: 2026-07-18
- Owners: Mosaera core
- Related issue: #54 (test-steward / thrash lever) — arc #43; child of #51 (thrash reducer, ADR-0056) / #49
- Related threat model: TM-0001 (updated — a sanctioned actor may repair a baselined test)
- Red-team: **DONE** (2026-07-18, 2 rounds, 7 refute-agents; 3 FIX-NOW fixed + re-verified; STOP-rule tripped
  on the gut-a-pre-existing-test class → the residual escalates to the Proctor-hard-gate successor; see §Red-team)

## Context

The repeat=3 re-baseline of the real autonomous posture (ADR-0057) is **thrash-dominated** — ~46% of runs
grind to the breaker because the local coder cannot satisfy an acceptance test. Two sub-causes:

- **(a) a BAD / over-strict / wrong test** — the Proctor mis-authored it (pinned an exact value the task
  left open), or a *pre-existing* test over-constrains the change. No correct implementation can pass it, so
  the coder thrashes against an unwinnable bar.
- **(b) a VALID test the weak local coder simply can't pass** — the test is faithful; the coder is limited.

The owner's framing: **treat the tests as a system, not just an agent output.** The Proctor (the Tester
role, which already *authors* the tests) should *own* them — able to validate and repair a bad test **before
the coder runs**, so the team isn't stuck thrashing on a test nobody is allowed to fix. But this must never
become a channel to help the coder pass: an agent that edits a test *after seeing the coder's failing code*
is reward-hacking (a documented failure mode — RL/agentic coders "overwrite unit tests, delete assertions,
write to protected paths" to fake a pass).

## Decision

Two mechanisms, both anchored to the invariant that the **coder** can never author, edit, weaken, or delete
its bar (unchanged: `factory.py` protected-path refusal + the ADR-0036 tamper guard).

### 1. Proactive: the Proctor validates/repairs tests up front, coder-blind (fixes (a))

- **The Tester role gains `edit_file`** (`packages/policies/…/allowlist.py`, CODEOWNERS) — it can now MODIFY
  a test, not only author one. Still `write_prefix="tests/"` (never source), still **no `delete_file`**
  (deletion drops a requirement wholesale and can't be quality-checked).
- **After authoring and BEFORE `implement`** (`author_tests_node` → `_proctor_validate_repair`), when
  `tester_repairs_tests` is on, the Proctor reviews the authored suite + the pre-existing tests against the
  **spec** (Task/Plan/Design/foresight — trusted; repo test content is untrusted data, AGENTS.md) and
  REPAIRS an unfaithful test (over-strict beyond the brief, or wrong) / STRENGTHENS a weak one. It matches
  the contract's strictness exactly and does **not** loosen a faithful test (persona rules in `tester.md`).
- **Why coder-blind is the whole game:** acting before the coder, the Proctor is *structurally blind to the
  coder's diff* — no implementation exists yet — so it **cannot** relax a test to fit the coder's wrong
  code. That is a stronger guarantee than any bolt-on gate, and it is why this is the Proctor (the existing
  owner) gaining a capability, **not a new mid-loop role**. Trade-off (accepted): no *reactive* mid-loop
  repair — a test that only proves bad while the coder fails it isn't auto-fixed; case (b) parks honestly
  via the #51 sensitivity self-stop, and the reactive path (below) hands it to a human.
- **Mutation feedback is post-impl, so it is NOT in the proactive pass.** Mutation feedback (the literature's
  53%→89.5% test-quality technique) needs *code to mutate*; coder-blind there is none. So the proactive pass
  primarily RELAXES over-strict tests + enforces the assertion floor; the mutation check stays a post-impl
  *gate* (below). Mutation-feedback *strengthening* (feeding survivors back to add assertions) is a Phase-2
  follow-up at a post-impl hook — a different insertion point.

### 2. Freeze + the quality-gated, actor-scoped tamper excuse (trust-safe)

The Proctor's up-front edits to **pre-existing (baselined)** tests must be excused from the ADR-0036 tamper
guard — but nothing else may be, and the pristine baseline stays immutable:

- **`proctor_edits: dict[path, integrity_hash]`** (declared RunState) records the Proctor's post-edit content
  in the **guard's integrity hash space** (`testintegrity.integrity_hash`, newline-normalized) — fixing the
  gap_fill CRLF wrong-hash-space bug. `tampered_integrity(..., proctor_edits=…)` excuses a baselined path
  ONLY when its on-disk content hashes to EITHER the pristine baseline OR the Proctor's recorded hash. Any
  other content — a later coder re-weakening, a deletion (content → `""`), an out-of-space hash — still trips
  deny-by-default. The excuse is content-pinned to the Proctor's exact edit, never a blanket "may change".
  `integrity_baseline` is never re-baselined in place.
- **Quality gate (honest-error protection, since gaming is already structurally closed):** `gate_node` requires
  `tests_mutation_caught **is True**` for a `proctor_edits` run (not merely `is not False`), so an
  unmeasured (`None`) mutation can't vouch a repaired run — a weakening the Proctor made by *honest error*
  can't launder through. (Implies `oracle_mutation_check` for the repair posture.) The Proctor's edits ride
  `diff_all()` → **reviewable** at `review_node`/`gate_node`.

### 3. Reactive: a locked-down human-in-the-loop test-review park (NOT an autonomous editor) (helps (b))

> **DELETED 2026-07-19 by [ADR-0060](ADR-0060-honest-stop-lean-engine.md) §Decision 3 — this section
> is HISTORY, not current authority** (recorded 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`).
> Neither symbol below exists in the tree: the `react_on_bad_test` knob and
> `agents.diagnose_test_review` were removed, along with the `test_review_needed` state key — ADR-0060
> judged it "an LLM call with zero write authority and zero routing effect that only reworded a park
> message". The honest-stop's deterministic diagnosis (failing-test names + count trend, on every park,
> at zero model cost) replaces it. §1 and §2 above — the coder-blind repair and the `proctor_edits`
> excuse — are unaffected and live.

On mid-loop thrash — the coder failing the SAME test to a genuine PARK (`stalled`, after any reason-before-
park pass, and never on a tamper park) — the engine must NOT autonomously edit the test. When
`react_on_bad_test` is on, `test_node` runs a **tool-less, read-only** judgment
(`agents.diagnose_test_review`, the reviewer role model with NO tools bound) of whether the trapping test is
**suspected-bad** (over-strict / missed case / buggy) vs the **coder is limited** (the test is faithful). It
writes only a structured `test_review_needed` NOTE and parks; `_termination_reason` surfaces a suspected-bad
test distinctly. **Zero write authority:** no tools ⇒ it structurally cannot edit a test or feed the coder,
and the verdict goes to a HUMAN at the park, never back into the loop. The ONLY autonomous test-editing
anywhere is the coder-blind, up-front, mutation-gated proactive pass (§1) — so the reactive path can never
game or help the coder pass. Opt-in; once per run.

### 4. Confound fix (bench-only)

The live escalation path gates cloud egress (`cloud_tier_allowed`, ADR-0024); the benchmark caller did not, so
it bound an unpriced/unreachable cloud tier that no-op'd and overwrote tier-0 outcomes with thrash. `bench/cli.py`
now applies the same gate — the scoreboard stops mis-attributing an escalation confound as thrash.

## Options considered

- **Proctor gains repair authority, coder-blind (chosen).** Matches the owner's "the oracle owns the tests"
  model, drops ~12 sites of new-role scaffolding, and is ungameable by construction (blind to the coder's
  diff). Trade-off: no reactive auto-repair — handled by the human-park + #51 self-stop.
- **A separate mid-loop test-steward role** (the first cut). Rejected by the owner: redundant owner, and a
  mid-loop editor that *can* see the coder's failure is exactly the reward-hacking channel to close.
- **Autonomous reactive repair** (edit the bad test to unblock the coder). Rejected — "would I be okay if the
  agent did this without asking?" is NO; it is the reward-hacking channel. → diagnose-and-park for a human.
- **Mutation-feedback in the proactive pass.** Not possible (no code pre-impl); deferred to a Phase-2 post-impl
  strengthen hook. The mutation *gate* stays post-impl.
- **Allow `delete_file` for the Proctor.** Rejected in Phase 1 — deletion drops a requirement and can't be
  quality-checked; repair/strengthen only.

## Security implications

Deny-by-default is preserved. The coder's trust boundary is untouched. The one new positive-trust affordance —
the Proctor editing a *baselined* test — is (i) confined to `tests/` (never source), (ii) never a deletion,
(iii) coder-blind by timing (structurally can't fit wrong code), (iv) content-pinned in the correct hash space
(a later re-weakening still trips), (v) gated on a PROVEN mutation-catch, and (vi) reviewable in the diff. The
reactive path adds **zero** write authority (diagnose-only; the human decides). Residual (the red-team target):
an *honest* weakening of a faithful test the changed-lines-only mutation check can't see (a dropped *unrelated*
requirement) — one-sided (fails toward a park a human reviews), not a new gaming hole. → TM-0001.

## Red-team (DONE — 2026-07-18, definition-of-done gate, pre-merge)

**Scope card:** target = this MR (the Proctor's up-front test-edit authority + the `proctor_edits` excuse + the
gate tightening + the reactive park). Durable, load-bearing trust-boundary change → **~3 rounds**. **Round 1**:
5 refute-agents, distinct lenses (weakening / excuse-integrity / reactive-lockdown / coder-blind-timing /
orchestration-resume). **Round 2**: 2 refute-agents adversarially verifying the Round-1 fixes.

**3 FIX-NOW (fixed + re-verified; the fixes ship in this MR):**
- **FN1 — gut/empty/weaken a pre-existing test → SHIP (HIGH; R1, 3 agents converged, one end-to-end ship
  repro).** `_proctor_validate_repair` recorded a `proctor_edit` for *any* changed baselined path with no
  quality check; an emptied test's integrity content hashes to `hash("")`, self-excusing the drop (and a later
  deletion, and a `conftest` collection-control edit). The mutation-True gate was no backstop — a *sibling*
  test catches the single whole-suite mutation while the gutted test's requirement is dropped. **Fixed** two
  ways (defense-in-depth): (builder) a repaired baselined test is excused ONLY if it still clears the
  **assertion floor**; (consumer) `tampered_integrity` treats EMPTY on-disk content as always-tampering, so a
  sanctioned `hash("")` can never launder an emptied/deleted test.
- **FN2 — post-impl repair laundered on the gate-deny re-plan (HIGH; R1, timing agent).** `author_tests_node`
  has no run-once guard and the workspace is never reverted, so on a gate-deny → `plan → design → author_tests`
  the "coder-blind" repair ran again *with the coder's code on disk* — collapsing the whole coder-blind
  guarantee. **Fixed:** run the repair (and record `proctor_edits`) ONLY on the coder-blind first pass
  (`iteration <= 1`; `plan_node` increments `iteration`, so any re-plan is `>= 2`). A later tester edit of a
  pre-existing test then gets no excuse → deny-by-default tamper park. (R2 verified this is structurally sound:
  `author_tests` has one inbound edge always preceded by `plan`; `iteration` is monotonic from seed 0; resume
  replays to the *gate* interrupt, never re-entering `author_tests`.)
- **FN3 — the assertion floor was REACHABILITY-BLIND, re-opening FN1 (HIGH; R2, floor-attack agent).** The
  FN1 builder fix leaned on `_asserts_something_real`, which `ast.walk`'d the whole subtree and credited an
  assertion *anywhere* — so four gut constructs cleared the floor while asserting nothing at runtime: an
  assert in a **nested uncalled function**, under a **statically-false `if False:`**, an **`assert <lambda>`**
  (a lambda object is always truthy), and an **empty `@parametrize([])`** (zero cases → skipped). **Fixed**
  with a single principled rule: the floor now counts only *reachable, non-trivial* asserts — `_reachable`
  skips nested-function/lambda scopes and statically-false branches, `assert <lambda>` is trivial, and empty
  `parametrize` is treated as a skip. Errs safe (an assert only in a called nested helper conservatively
  parks). The shared floor gates `tester_vouched` for all runs; the full oracle/integration suite confirmed
  no delivery regression.

**STOP-rule TRIPPED — the gut-a-pre-existing-test class recurred across Rounds 1 and 2, so it escalates; no
Round 3 on floor constructs.** DEFER-TO-SUCCESSOR:
- **Partial weakening that still asserts (executed-but-unasserted).** A repaired pre-existing test that keeps
  *some* real reachable assertion but drops one of several requirements, where a *sibling* test catches the
  single whole-suite mutation, can still ship. This is the same class #52's red-team STOP-ruled to the
  **Proctor-hard-gate / per-requirement mutation** successor. The static assertion floor is inherently
  incomplete (a runtime-opaque non-executing assert — obfuscated, review-visible code — can pass any static
  check); the durable fix is a **dynamic** per-repaired-test verification (run it under coverage / require a
  red-verified asserting suite to ship). Logged on the roadmap. Do NOT patch the floor further.

**ACCEPT (documented deny-by-default residuals):**
- **Prompt-injection loosening a faithful test** (PLAUSIBLE, model-dependent) — no structural guard beyond the
  spec-anchored persona + AGENTS.md "repo content is untrusted"; but the edit is coder-blind, reviewable in the
  diff, and post-FN1/FN3 an injection-driven *gut* parks — only a still-asserting partial weakening survives
  (the deferred class).
- **Ephemeral `protected_tests` on resume** — the coder's tool-refusal set is rebuilt empty on rehydrate, but
  the durable `proctor_edits` tamper guard is the real boundary and survives resume (R1 orchestration agent:
  NO-BREAK), so a coder re-weakening still parks; the tool-refusal is defense-in-depth.
- **Unwrapped proactive `validate_and_repair_tests` model call** — a model fault crashes to `status="error"`,
  but that is the same pre-existing crash class as `author_tests` and runs *before* `implement`, so no
  deliverable diff is discarded.

**Verified NO-BREAK:** the reactive path has zero test-write authority (structurally tool-less; the verdict
reaches only a human at the gate, never the coder loop); resume preserves `proctor_edits` + the strict gate;
the `Settings.from_env`/coverage-ledger splits are byte-identical; the bench confound fix mirrors the live
egress gate; knob/posture wiring is complete.

**Verdict:** 3 FIX-NOW fixed + re-verified (both HIGH reproductions now park instead of ship; the floor
rejects all four R2 constructs); the executed-but-unasserted class STOP-ruled → escalated to the
Proctor-hard-gate successor (no Round 3); the rest ACCEPT. Deny-by-default held throughout — every residual
fails toward a human-reviewed park, never an unattended ship.

## Consequences

- **Good:** the dominant thrash sub-cause (a bad/over-strict test nobody could fix) gets an owner that repairs
  it before the coder — without opening a reward-hacking channel; a coder-limited thrash parks with a rich,
  honest, human-actionable handoff instead of a generic give-up.
- **Follow-up:** the red-team disposition (record here + roadmap); re-baseline `mosaera-bench --all`
  (`tester_repairs_tests` on, `MOSAERA_MODEL_ESCALATION=0`) → thrash → (clean | honest_park); the Phase-2
  post-impl mutation-feedback *strengthen* hook; a provider-aware sensitivity default (local → `cautious`).
- **Ops:** ~~two knobs (`tester_repairs_tests`, `react_on_bad_test`), default OFF, both ON in the autonomous
  posture (`apply_oracle_posture` → 6 knobs).~~ **Corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — **one** knob (`tester_repairs_tests`), default OFF, ON in the autonomous posture; `react_on_bad_test` was DELETED by ADR-0060 (see §3). The posture has since grown past six flags (`proctor_faithfulness_guard` ADR-0062; `critic_enabled` ADR-0065). No migration.
