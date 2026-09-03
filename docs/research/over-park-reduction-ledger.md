# Research ledger — reducing the over-park rate

**Mission.** Reduce the historical over-park rate (correct work refused) from ~30–36% to ≤10%,
ideally ≤5%, **without** weakening safety, evidence standards or any named invariant. Correct work
must succeed because Mosaera can *prove* it correct, never because Mosaera became willing to ship
unproven work.

**Branch** `research/over-park-reduction` · **from** `3cabffe` (main, `0.6.2` beta) ·
**backup** `~/mosaera-backups/full-repo-2026-08-12/mosaera-full-2026-08-12.tar.gz`
(473 MB, 52,487 entries, verified to contain `.git`, `.mosaera/benchmarks`, `packages/policies`).

## Baseline

**Gates at `3cabffe`: all four green** — `fmt-check`, `lint` (six guards), `typecheck`,
`test` (2,464 passed / 120 skipped).

**Benchmark baseline: the 130-run 26-case sweep of 2026-08-11**
(`docs/engineering-history/corpus-baseline-26case-2026-08-11.md`), run on this exact code, archived
at `~/mosaera-backups/corpus-26case-baseline-2026-08-11.tar.gz`. It already carries every diagnostic
field added on 08-11, so the first analyses need no GPU time.

| metric | baseline |
|---|---|
| over-park | **47/130 = 36.2%** |
| false ships | 0 |
| delivered | 68/130 (52.3%) |
| clean-conclusion | 89.2% |
| capability | 90.1 |

## Over-park taxonomy (n=47) — measured, not assumed

Exact gate-reason **sets**, which is the run's real story (a frequency count of individual reasons
conflates co-occurring ones):

| population | count | share |
|---|---|---|
| `validation_failed` cluster (own tests failed) | 25 | 53% |
| sole-cause `oracle_unverified` | 9 | 19% |
| sole-cause `claim_structural_failed` | 6 | 13% |
| `tests_tampered` + `validation_failed` | 7 | 15% |
| reviewer-only (`conflict` / `requested_changes`) | 3 | 6% |

Sub-split of the `validation_failed` cluster: **13 of 25** authored ≥1 test the case's own
*reference solution* fails (the over-strict story); **5 of 25** authored **zero** such tests and
still failed validation — a different mechanism; 7 unmeasurable.

`oracle_unverified` sole-cause, via the `oracle_legs.blocked_by` field added 08-11:
**5 blocked by `mutation` alone** (independence satisfied via `tester_vouched`), **3 by
`independence` alone** (all four routes False), 1 by both.

## E0 — Is the structural checker wrong? (falsification, no GPU)

**Hypothesis.** The 6 sole-cause `claim_structural_failed` over-parks (5 of them MCB-15, same three
claims, 5/5 runs, deterministic) come from a checker that rejects correct refactors.

**Experiment.** Run `check_structural_compliance` against the case's **own reference solution**,
with the seed as the pre-refactor baseline — correct by construction, so a `False` would prove the
checker broken.

**Result.** `verdict=True` — *"`parse_log_line` meets the requested structure"*. **Hypothesis
refuted.** The checker accepts a known-good refactor.

**But the comparison surfaced something sharper.** MCB-15's hidden grader *also* checks structure
(`body <= 7 statements`, `>= 3 module-level helpers`), and an over-park means the grader **passed**.
So two structural checkers disagreed on the same delivered code. The engine's checker carries **two
predicates the acceptance criteria do not**:

1. a **shrink ratio** — the orchestrator must be ≤ 2/3 of the original's statement count;
2. **"still iterates"** — `_has_loop` fails the orchestrator if it retains any `For`, `While`
   **or comprehension**, whenever the original had one.

A short, 3-helper orchestrator containing a single comprehension passes the case's acceptance and is
refused by the engine. That is a *deterministic* false-park generator, and it is the opposite of the
model-side over-strictness diagnosed on 08-11.

**Interpretation.** Not yet proven to be what fired on the 5 runs — the per-claim reason reached no
stored record. Observability first.

**Keep/Revert:** no behavioural change made. Hypothesis recorded as refuted-but-productive.

## I1 — Instrumentation: per-claim failure reasons

`unsatisfied_claims` names ids, `unsatisfied_claim_kinds` names classes; neither distinguishes
*"the code missed the requested shape"* from *"the checker asked for more than the acceptance
criteria did"*. Added `claim_failure_reasons` (`claim_id -> oracle_ref`, failed rows only) to the
scorecard.

## E1 — MCB-15: the engine grades its own scaffolding · **ROOT-CAUSED AND FIXED**

**Hypothesis.** The 5 MCB-15 parks come from the structural checker enforcing predicates the case's
acceptance criteria never stated (a shrink ratio and a no-loop rule).

**Experiment.** Re-run MCB-15 ×5 with `claim_failure_reasons` recording, then reproduce offline
against the persisted workspace.

**Actual result — the hypothesis was wrong and the truth is sharper.** The recorded reason reads:

> `parse_log_line` is 13 statements where it was 13 … delegates to 0 module helper(s) (wanted >= 3)

That is the shape of the code **before** the refactor. The delivered `logparse.py` is a textbook
refactor (4 statements, three module-level helpers) and the checker **passes** it. The failure came
from a **second file**: the refactor scaffold (ADR-0066) writes a golden-master snapshot to
`tests/_frozen_logparse.py` holding the pre-refactor function verbatim. That basename does not match
the pytest pattern, so `is_test_file` returned False and it entered *delivered sources*. The
red-team R2 rule — judge EVERY changed file defining the target, so a decoy cannot shadow a bloated
real one — then made the frozen copy's inevitable failure authoritative.

**A frozen copy of the original can never satisfy "refactor this", by construction.** The engine was
grading its own scaffolding as the agent's work product, deterministically, on exactly the cases the
scaffold exists to help.

Reproduced byte-for-byte from the persisted workspace:

| judged sources | verdict |
|---|---|
| `logparse.py` (delivered) | **True** — meets the requested structure |
| + `tests/_frozen_logparse.py` | **False** — the exact recorded string |

**Change.** `_delivered_sources` additionally skips anything under a `test/` or `tests/` directory.
`is_test_file` is shared with the ADR-0036 tamper guard and is **not** widened; the location check
lives beside `_delivered_sources`, its only caller. One-sided — it can only judge fewer files.

**Keep.** Commit `e7b0d42`, with a regression test carrying a positive control (ordinary source is
still judged), because a filter that excluded everything would "fix" the park by disabling the check.

**Pre-fix measurement (n=5, instrumented):** 4 over-parks, 0 delivered, all five blocked *solely* by
`claim_structural_failed`. One run had `grader=False` — genuinely wrong work that this bug caught by
accident. **Post-fix that accidental save disappears, so the false-ship count is the number to
watch.**

### E1 measured result

| MCB-15, n=5 each | delivered | over-park | false ships | true refusals |
|---|---|---|---|---|
| pre-fix | 0/5 | **4/5** | 0 | 1 |
| post-fix | **5/5** | **0/5** | **0** | 0 |

All five post-fix runs: `clean_deliver`, grader passed, **zero gate reasons**.

**Stated honestly:** the pre-fix set contained one genuinely-wrong run (grader=False) that this bug
refused *by accident*. All five post-fix runs happened to be behaviourally correct, so the fix's
behaviour on wrong work is **not exercised by this sample** — the false-ship risk is untested at
n=5, not disproven. The structural check itself is unchanged and still refuses a genuinely
non-compliant refactor; only the engine's own frozen snapshot stopped being judged.

### Realistic ceiling after E1

`claim_structural_failed` appears in **7** of the 47 baseline over-parks. Best case this takes
over-park to **40/130 = 30.8%**. The ≤10% target is ≤13 over-parks, so **27 more must go**.

Remaining populations: 18 `validation_failed` · 10 `oracle_unverified` · 7 `tests_tampered` ·
5 reviewer-only.

## E1 — **REVERTED**: correct in isolation, unsafe alone

**What the measurement sweep found at 36/130.** Three runs delivered work the grader failed. One
(MCB-01) is a `crash`, not a false ship — my ad-hoc filter (`delivered AND grader failed`) does not
match the reliability classifier, and that filter was wrong. **The other two are genuine false ships
on MCB-05**, which delivered **0/5** in the baseline.

**Cause, traced.** MCB-05 is a refactor, so the scaffold authors `tests/_frozen_checkout.py` — present
in both baseline and post-fix workspaces. Pre-fix, judging it guaranteed a `False`, so the structural
claim never satisfied and MCB-05 never delivered. Post-fix, the claim satisfies, and a satisfied
`ast_transformation_contract` claim **mints a structural independence vouch** that clears
`oracle_unverified` — so the run ships. The grader's own
`test_checkout_total_is_a_short_orchestrator` (`len(fn.body) <= 6`) fails it.

**So the frozen-file bug was accidentally masking a second defect:** the engine's structural
predicate is more permissive than the case's acceptance test, *and* satisfying it grants
independence. That is the same class as the 2026-08-04 defect where
`check_structural_compliance` minted a vouch after executing zero predicates.

**Disposition: REVERT the behavioural change; keep the diagnosis, the predicate and its tests.**
False ships must remain 0, and this change moved them off 0. `_in_test_tree` is defined, documented
and tested but **not applied**, so the next attempt starts from evidence.

**The exclusion may only land together with a fix for the vouch leniency.** That is now the concrete
next experiment, not a guess.

**A note on evidence preservation.** The delivered code for these runs is **unrecoverable**:
`checkout.py` was never staged (index = HEAD = original) and `overstrict_vs_reference` overlays the
reference onto the working tree afterwards. The poison sentinel marks the tree, but the agent's work
product is simply gone. MCB-15 was diagnosable only because its file happened to be staged. This is
a real gap in the audit trail for exactly the runs most worth diagnosing.

## Corrections to earlier readings

- The 08-11 attribution ("26 of 38 over-parks are over-strict authored tests") **does not reproduce**
  on this baseline. With the denominator now recorded, over-parks author *fewer* tests than other
  runs (12.6 vs 16.0) at a barely higher over-strict **rate** (9.9% vs 7.1%). The raw-count reading
  was a volume artefact.
- Over-park is a **portfolio of distinct mechanisms**, not one cause. Three cases park 5/5 for three
  *different* already-identified reasons (MCB-15 scaffolding, MCB-26 no independence route,
  MCB-28 Proctor compliance) = 32% of all over-parks.
- Non-Python cases over-park at 53% vs 34% for Python — elevated, but only 8 of 47.

## Open questions

- Are the 5 `mutation`-blocked over-parks the same class the 08-11 A/B measured as null?
- MCB-26 (SQL) has **no independence route at all** — all four are Python-shaped. 5/5 over-park.
- MCB-22 (4/5) and the long tail: unexamined.


## E4/E5 — the clause experiments (MEASURED)

The four refactor cases, 20 runs per arm, same code except the env-supplied clause:

| arm | delivered | over-park | false ships |
|---|---|---|---|
| baseline (no E1, no clause) | 7/20 | 8 | 0 |
| E4: E1 + `structural.body_statements=6` | 16/20 | 4 | **2** |
| **E5: E1 + `structural.body_statements=5`** | **18/20** | **2** | **0** |

**E4's false ships are a unit mismatch, found from the preserved patches:** `_body_stmts` excludes a
leading docstring (documented rationale) while the graders count `len(fn.body)` raw — so 7 grader
statements measure 6 engine statements, and a clause of 6 admits what a `<= 6` grader refuses.

**E5 works for the reason ADR-0082 predicted, not by tightening a checker:** `weave_criteria` puts
the clause INTO the brief, so the agent aims at 5 and lands with a statement of grader headroom.
Telling the model the number fixed both directions at once — over-park 8→2 AND false ships stay 0.
This is the third time "give the model the missing contract" has outperformed "check harder"
(clauses A/B 0/6→5/6; ADR-0098 naming targets; now E5).

**Prior art honoured:** `grader-alignment-brief-2026-08-04.md` already framed MCB-05/15 as
"two-rulers" cases pending an owner decision. E5 is the measured resolution that brief was waiting
for. The remaining MCB-13 2/5 parks are `oracle_unverified` (mutation), not structural — a
different population.

## THE PLAN — population → intervention, sequenced

Baseline 47/130 over-parks. Measured or projected effect per population:

| # | population | n | intervention | status |
|---|---|---|---|---|
| P1 | refactor structural (MCB-05/13/14/15) | 8 | E1 + ratified clause=5 | **MEASURED 8→2** |
| P2 | validation_failed cluster (8 cases) | 17 | extend the E5 lesson: mine the brief's own quoted examples into the Proctor's assertions (deterministic, ENTAILED — the claims extractor already parses them); plus #62 mutation-guided inputs at authoring for all capabilities | designed |
| P3 | MCB-26 SQL — zero independence routes exist | 5 | credit a LanguagePack validation plan with real assertion queries as the independence oracle (needs ADR — it widens what counts as independent evidence) | designed |
| P4 | oracle_unverified, mutation-blocked non-refactor | 7 | extend #62's input generator beyond the refactor scaffold (proven pattern: "the AND stands, the evidence rises") | designed |
| P5 | MCB-28 Proctor compliance | 5 | model-tier decision — instruction measured 0/5 complied on default model; OWNER call | blocked on owner |
| P6 | reviewer-only (unknown/conflict) | 5 | verdict-recovery already exists (ADR-0028); diagnose why it misses these | not examined |

**Honest ceiling:** P1 (−6) is measured. P2–P4 are designed with strong priors but unmeasured;
if each lands at E5-like effectiveness the projection is ~15–20/130 (11–15%). **≤10% likely
requires P5, which is a model-tier question the mission cannot decide.** Every intervention raises
evidence; none lowers a bar.

**External grounding:** the P2 mechanism is the documented failure mode of LLM test generation —
oracles capture actual/invented behaviour rather than the specification, with numeric-literal
assertions the dominant false-positive source (TOGLL: 25% FP on assertion oracles). The corrective
that matches Mosaera's invariants is differential/metamorphic validation plus specification-anchored
assertions — exactly what mining the brief's quoted examples does deterministically.


## P1 — LANDED (2026-08-12)

**Change.** `_in_test_tree` applied in `_delivered_sources` (E1), plus the ratified
`structural.body_statements=5` as the bench DEFAULT clause (`bench/harness._RATIFIED_DEFAULT`,
env-overridable; sentinel `MOSAERA_BENCH_CLAUSES=none` expresses the no-clause arm). Owner
ratified both the value (5) and default-on this session.

**Why 5 and not 6.** The instruments disagree by one: `_body_stmts` excludes a leading docstring,
the graders count `len(fn.body)` raw. Clause=6 was measured to false-ship twice through that gap
(E4); the counter is not changed because counting docstrings penalises documentation — the
docstring-exclusion's own rationale. Documented at `_body_stmts`.

**⚠ Measurement-methodology change.** Sweeps from this commit run under the ratified clause;
the 130-run 26-case baseline ran with NO clause (the relative fallback). Refactor-case rates are
not comparable across that boundary. Old posture: no clause, relative shrink check. New posture:
`structural.body_statements=5` woven into every brief. Recorded here and on the baseline doc.

**Expected corpus effect** (from E5, n=20): over-park −6 (47→~41), delivery +11 on the four
refactor cases; false ships stay 0. Verified end-to-end below, full-corpus confirmation deferred
to the post-P2/P3 sweep so one sweep measures the stack.

### P1 end-to-end verification (6 runs, NO env set, archived `p1-verification-2026-08-12.tar.gz`)

| case | result | what it proves |
|---|---|---|
| MCB-15 ×2 | `clean_deliver`, grader ✓, `clauses_applied=['structural.body_statements=5']` | **the default fires end-to-end** — no silent vacancy |
| MCB-13 ×2 | `clean_deliver`, grader ✓, `clauses=[]` | delivers; the clause correctly does not claim credit (its structural claim binds via the single-if verb, untouched by this parameter) |
| MCB-01 ×2 | `thrash_park`, baseline-shaped reasons | nearby-unaffected control: greenfield, no structural claim, behaviour unchanged — its over-park is P2's population |

**False ships: 0.** One plan wording corrected: MCB-13's baseline mutation parks were labelled
"must stay parked" — they were over-parks (grader-passing), so delivery is the desired direction;
the mutation veto's code is untouched. **P1 CLOSED: Keep.**


## P2 Stage B offline replay — the token discriminator is REFUTED before GPU

**Hypothesis.** Seed-failing authored tests that mention no new-behaviour token (from material
claims' code-spans) are the over-strict ones; naming them to the Proctor's repair turn would fix
the validation_failed cluster.

**Experiment.** Replay against 8 real baseline2 workspaces (MCB-21/22): reconstruct seed + staged
authored tests, run against the seed for `seed_failures`, against the reference for ground truth,
compare the discriminator's flags.

**Actual result.**

| run | seed-fail | ref-fail (ground truth) | flagged | precision |
|---|---|---|---|---|
| MCB-21 ×3 | 15 / 10 / 11 | 13 / 6 / 10 | **0 / 0 / 0** | — |
| MCB-22 ×5 | 11 / 8 / 11 / 4 / 16 | 7 / 0 / 1 / 1 / 9 | **5** / 0 / 0 / 0 / 0 | 4/5 |

**Precision is fine when it fires (4/5); recall is ~0 on the primary target.** Cause: MCB-21's
brief restates EXISTING behaviour as material-looking bullets (*"`python -m journal add "<text>"`
— add an entry"*), so `add`/`list`-adjacent tokens enter the new-behaviour vocabulary and every
over-pinned format test mentions them (they add entries before asserting). The claims vocabulary
does not separate new from old on exactly the briefs where over-strictness lives.

**The plan's measure gate said proceed only if the flag fires on ≥ half the over-parking runs.
Offline says it will not. Stage C is NOT built.** Kept: per-test seed failures (Stage A — valuable
regardless), the discriminator as a recorded diagnostic with its measured precision/recall, and an
ANSI-stripping fix the replay itself surfaced (a colourised pytest made the parser honestly return
None — the vacancy pin did its job before the fix existed).

**P2 status: the intervention is refuted as designed; the population remains open.** The honest
options now on the table, all unbuilt: failure-mode analysis (AttributeError-vs-AssertionError as
the new/old split — noisy on subcommand CLIs), example-mining (dead on MCB-21: the brief quotes no
exact outputs), or accepting P2 as blocked pending a better idea and moving to P3/P4.


## P4′ — revive Layer 2: the evidence-of-last-resort channel (Stage 1 LANDED, Stage 2 running)

**Origin.** The owner asked: why not one least-trusted LLM gate that can ship solely on its
judgment when every deterministic gate vouches — a proxy for the user when the change is
irrefutably correct? The literal version is barred (*Deterministic Final Authority*; "LLM judgment
as release evidence" is a hard prohibition; the critic's veto record is 9-for-9 wrong). The
faithful version **already exists**: `close_oracle_gap` — the model AUTHORS the missing evidence,
deterministic machinery decides (assertion floor + green on delivered tree + comprehensive
mutation catch). Witness, not judge.

**Why it converted nothing (2026-08-09 deferral: 13 eligible, 0 converted):** its freeform
authored test could not form a mutation-catching question. #62 proved the cure on the same wall —
mined boundary triples took `mutation_caught` 0/20 → 20/20 — but the generator lived only in
`refactor_scaffold`.

**Stage 1 (commit `4aebc8c`).** `mined_boundaries` → shared `input_mining.py`; the disposition's
authoring instruction now carries the changed modules' mined values + a wrong-typed-input
requirement. Empty mine ⇒ byte-identical instruction, pinned. One near-miss recorded: ruff sorted
the new import into the `if False: # TYPE_CHECKING` block — present for mypy, absent at runtime,
NameError swallowed by the deny-by-default except ⇒ a control born dead. Caught by the positive-
case test before any measurement consumed it.

**Stage 2 (running).** 24 runs, the 8 convertible-park cases, `disposition_gap_close=ON`.
**Pre-registered:** success = conversions > 0 AND false conversions = 0 (grader ground truth via
the four-cell `layer2_report`); 0 conversions again = the wall stands, record and stop. Stage 3
(engine-side channel) is conditional on Stage 2 AND an owner autonomy decision + ADR + red team.


### P4′ Stage 2 — MEASURED: the mutation wall fell, and the independence wall behind it stood

24 runs, 8 convertible-park cases, `disposition_gap_close=ON`, archived
`stage2-corpus-2026-08-13.tar.gz`.

| eligible park | layer2 verdict | mutation caught | hidden grader | |
|---|---|---|---|---|
| MCB-06 | verified | True | **True** | a TRUE conversion — the first in Layer 2's existence |
| MCB-18 | verified | True | **False** | a **FALSE conversion** — disqualifying |

**The pre-registered rule (false conversions = 0) fired. Stage 3 does not proceed.**

**Two-layer reading, both halves real:**

1. **Stage 1 worked at what it targeted.** The 2026-08-09 wall was "the authored test cannot form
   a mutation-catching question" — 0 of 13 eligible ever verified. With mined inputs: **2 of 2**
   authored tests were green AND mutation-catching. The evidence-raiser raised the evidence.
2. **Which exposed the deeper wall: correlated wrongness.** On MCB-18 (malformed-op robustness),
   the disposition's independently-authored test encoded the SAME wrong reading of the spec the
   delivered code implements — green on wrong code, strong enough to catch mutants, wrong about
   the requirement. A confidently wrong oracle. This is the North Star's sentence made
   operational: *separate models add diversity, not independence, unless evidence ownership AND
   decision authority are separated* — here both test and code descend from the same brief read
   by the same model family, and no deterministic check can see a shared misreading.

**Consequences.** `disposition_gap_close` stays default OFF; Stage 1's mined-inputs block is kept
(instruction-only, and it is what made the channel capable of converting at all); the engine-side
channel (Stage 3) is dead under the rule as registered. At n=2 the false-conversion rate is
unbounded in any useful sense — but the mechanism is structural, not statistical, and the honest
projection is that scaling eligibility scales both columns.

**What would change the verdict:** an evidence source that cannot share the producer's misreading
— a second model FAMILY for disposition authoring (diversity ≠ independence, but different-family
diversity is measurably better than same-family), or grounding the authored test in artifacts the
producer never emitted (the brief's own quoted examples, reference I/O pairs). Both are future
experiments, neither is scheduled.


## Mission disposition — DEFERRED by the owner (2026-08-13)

P1 landed and verified; P2's discriminator refuted offline; P4′ Stage 2 disqualified by its own
pre-registered rule (the correlated-wrongness wall). The remaining over-park (~30% like-for-like)
affects **autonomous delivery only** — guided runs put a human at every gate, where an over-park
is a five-second approval rather than lost work. The owner is prioritising UI polish and a public
demo; this mission resumes later from this ledger. The two recorded paths through the wall, for
whoever picks it up: a different model FAMILY as the disposition witness, or authored tests
grounded in artifacts the producer never emitted (the brief's own quoted I/O pairs).
