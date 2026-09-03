# Demo-repo observed outcomes (#53)

Live-drive results for the three demo shapes (`demos/`), driven through the engine
on the **webUI autonomous** path (the faithful gate). The `Expected` column is set
by each shape's `EXPECTED.md`; the `Observed` columns are filled from a real drive.

Cross-reference: the reliability scoreboard buckets (`bench/reliability.py`) —
`clean_deliver` / `honest_park` / `thrash_park` / `false_ship` / `crash`.

| Shape | Brief (1-line) | Expected bucket | Expected reason | Observed bucket | Observed reason | Cost (tok / calls) | Notes |
|---|---|---|---|---|---|---|---|
| greenfield | build a password-strength CLI | `clean_deliver` (else `honest_park`) | oracle vouches, else `oracle_unverified` | **`thrash_park` (safe)** | tamper guard: the weak local coder edited the Proctor's protected tests → refused to ship, parked (iter 2, 248s) | ~248s, local qwen3-coder | ✅ matches "thrash on weak models"; the safety boundary held (no false-ship) |
| brownfield | add `remove_item` (no negative) | `clean_deliver` (correct) / `validation_failed → honest_park` (naive) | whole-suite runs the root `test_invariants.py` (#45) | **`clean_deliver`** | correct fix delivered (iter 1, 107s); whole-suite validation ran the root invariant → fix respected it | ~107s, local qwen3-coder | ✅ matches "correct fix"; genuine delivery, not a false-ship |
| spaghetti | add a median to the report | `honest_park` (silent reviewer) / syntax-only `clean_deliver` | `shallow` strength — nothing behavioural to validate | **`thrash_park` (safe)** | tamper guard: coder edited protected tests → refused to ship, parked (iter 2, 82s) | ~82s, local qwen3-coder | tamper-park (a genuinely honest safety park the frozen classifier scores thrash); no false-ship/crash |

## 0.6.0 live-drive verdict (2026-07-19, engine 0.6.0, autonomous posture, escalation OFF, local qwen3-coder)

The reliability property **holds outside the benchmark**: every shape either **delivered correct code**
(brownfield) or **safely refused to ship** (greenfield + spaghetti — the ADR-0036 tamper guard catching
the weak local coder editing its own tests). **Zero false-ship, zero crash across all three.** The two
tamper-parks fired *before* the honest-stop could engage (correct safety precedence: tamper > progress);
on a stronger/escalated coder they'd likely deliver, consistent with matrix A's finding that the local
coder is the binding constraint. Follow-up (classifier fidelity, not a regression): a tamper/safety park
is honest — consider distinguishing it from `thrash_park` in `classify_outcome`.

## Full backlog-sweep drive (2026-07-21, engine 0.6.0 @ `bf8b36c`, greenfield, operator-in-the-loop)

Beyond the single-task drives above: the greenfield shape driven through the **entire project flow**
as a real operator would — `POST /projects` (local path source, autonomous) → Quincy intake chat →
approve → decomposed 3-item backlog (module → CLI → tests) → autonomous sweep → operator remediation →
re-run. PM/reviewer `gpt-oss:20b`, coder `qwen3-coder:30b`, all local, $0.

| Item | Run | Outcome | What happened |
|---|---|---|---|
| #1 module (1st) | 47a582 | `thrash_park` (safe) | Quincy's decompose invented **over-exact acceptance** (exact reason tuples, `12345678` as an "only digits" fixture); the Proctor pinned tests to it; the coder's blocklist behaviour was *more correct than the test*; tamper guard held; iteration cap → honest park. 35 min, 1.3M tok, 108 calls. |
| #1 module (re-run) | fcff64 | **`clean_deliver`** | Operator PATCHed the acceptance to behavioural spec → delivered in ~6 min / 73 calls. 13/13 tests green; blocklist precedence correct (verified by hand). |
| #2 CLI | a2fe3a | `honest_park` (oracle misfire) | Coder built a **working `cli.py`**, but the acceptance phrase "produces the **same output** as the command line" (input-path consistency) tripped `is_behavior_preserving`'s `(same)\s+(output)` pattern → refactor shape misclassified → `test_decomposition_happened` (#80 structural scaffold) demanded decomposition on a feature task → impossible bar → supervisor re-scoped once, then honest give-up. |
| #3 tests | a892d3 | `honest_park` (already satisfied) | ADR-0052 honest-conclude: item #1's delivery already shipped the test suite — the decomposed backlog item was redundant. Correct behaviour; the backlog itself was the flaw (Quincy decomposed "tests" into a separate item its own item-#1 acceptance already covered). |

**Held:** zero false-ship, zero crash; stacking worked (items #2/#3 branched from item-1's tip);
honest-stop reasons were specific enough for the operator to act on; the acceptance fix converted a
35-min thrash into a 6-min delivery — the operator loop *works* when the park reason names the gap.

**Found (levers, in priority order):**
1. **`is_behavior_preserving` false positive** (`behavior_preservation.py` pattern
   `(same|identical)\s+(observable\s+)?(behaviou?r|output|result)s?`): "same output as <other input
   path>" is a *consistency* clause, not a preservation-across-versions promise — and Quincy's
   natural acceptance language emits it readily. Composes into an impossible structural oracle on
   feature tasks (#80 red-team-grade finding; failure direction is over-park, fail-safe).
2. **Quincy's decompose over-specifies acceptance** (exact return tuples/strings) and creates
   redundant items — the #1-thrash and the #3-park were both *backlog* defects, not engine defects.
   The #54 test-stewardship functions (Proctor-owned repair per ADR-0058 — NOT a new role) / a
   decompose-time acceptance lint are the successors.
3. **Parked work is unrecoverable**: run a2fe3a's correct `cli.py` was discarded on park
   (`/runs/{id}/patch` → 404 for incomplete runs); the next item's checkout wiped the tree. An
   operator who fixes the park cause must pay the full item again.
4. **Local-path projects can't complete the loop**: `/merge` is GitLab-MR-only, so `in_review`
   items can never reach `done` and item#N `branch` is never recorded (stacking works via the
   clone anyway; the *record* doesn't). The demo runbook's local-path flow ends at the diff.
5. Configured **coder cloud-escalation never fired** during the 12-iteration thrash (usd stayed 0) —
   the one lever that likely converts the thrash into a first-pass delivery.

## Spec-lint validation drive (2026-07-22, engine @ `feat/backlog-spec-lint`, greenfield, Phase-0 rungs armed)

Same protocol as the 07-21 backlog-sweep drive (isolated instance + DB, materialized greenfield),
now with ADR-0073's `backlog_spec_lint` ON, the comparative-"as" classifier fix merged, and the
Phase-0 rungs armed (`resilient_recuration` on, escalation priced+laddered).

**Lint proof (the #53 defect classes, live):**
- Decompose produced a 5-item backlog with visibly behavioural acceptance — item #4's reasons
  "include *substrings*" (the doctrine sentence landing), **zero exact-value tuples** (07-21's
  thrash cause), and the one "same output as `cli.main`" phrase is now inert (the classifier fix)
  — R2 correctly stays quiet on it.
- **`spec-lint: 1 finding(s), 0 remaining after re-curation`** — the detect → one-bounded-curate →
  deny-by-default-apply loop fired end-to-end in production.
- **Item #4 (the substantive module item): `clean_deliver` in ~3 min / 46 calls, first pass** —
  vs the 07-21 equivalent's 35-min/1.3M-token `thrash_park` that needed operator acceptance
  surgery before a 6-min re-run delivered.
- Recuration (Phase 0) fired live and sensibly: stuck item #3 → Quincy authored a scoped
  successor item.

**New findings (pre-existing, logged not fixed):**
1. **PM empty-output flakiness** — decompose fell back to the single "Implement the brief" item
   twice; A/B-reproduced offline with BOTH the old and new prompt: `gpt-oss:20b` intermittently
   returns a fully EMPTY response on the second consecutive long call (decompose always follows
   `synthesize_understanding`). `robust_invoke` retries exceptions, not empty responses —
   retry-on-empty is a cheap candidate fix (agents `retry.py`).
2. **Trivial scaffolding items can't satisfy the independent oracle** — "create a package
   marker" has no testable behaviour, so under the autonomous posture it can only park
   ("no independent oracle vouched"), and even a sensible recuration just spawns another
   untestable item ("add a test that the import works" — still the coder's own test). Successor:
   decompose-granularity doctrine ("no items without observable behaviour") or an R4 lint rule,
   feeding the #54 steward design.

## Composed-tip drive (2026-07-22, engine @ `ff9cb31` — all July-22 merges active, escalation OFF by choice)

One full backlog drive on the merged tip (greenfield, isolated instance, `MOSAERA_MODEL_ESCALATION=0`
per owner — the escalation lever deliberately NOT exercised).

**The operator-layer pieces all validated, composed:**
- **Zero decompose fallbacks** (retry-on-empty holding — first generation produced 3 items).
- **`spec-lint: 1 finding(s), 0 remaining`** fired again in production.
- **Zero scaffolding-only items** (R4 + doctrine — no package-marker item this time), and acceptance
  came out substring-based/behavioural throughout.
- The "same output as" phrase class stayed inert (Phase-0 classifier fix).

**Delivery: 0/3 — item #1 (greenfield module) refused honestly 3×, blocking #2/#3:**
1. **Tamper-park** — NEW defect class for the #54 steward file: the decomposed acceptance contained a
   **factually wrong example** (`'Abcdefgh12!'` is 11 chars, claimed "score 4 / length ≥12"); the
   Proctor faithfully encoded the contradiction; the coder correctly diagnosed it, then EDITED the
   protected test to "fix the typo" → tamper guard refused (separation of duties held). The lint
   can't catch semantic/factual contradictions — shape-rules only; steward-mandate evidence #2.
2. After an operator acceptance fix: **thrash-park** (validation_failed at cap, empty diff), then the
   gate-deny → re-plan loop ended honestly ("no grounded plan").
3. Fresh attempt: parked with real work + a **concrete critic catch** (≥12-chars/low-variety branch
   returned the 8–11 band); the operator's targeted deny-feedback WAS implemented in the next loop
   (the fix appears in the diff) — but the loop re-tripped `tests_tampered` + `iteration_limit` →
   deny-by-default held → operator STOP (3-attempt cap, no rabbit-hole).

**Verdict:** the July-22 work fixed what it aimed at — the spec/backlog layer is clean, honest stops
are specific and actionable, the feedback loop demonstrably transfers operator intent into code.
End-to-end greenfield delivery with a weak LOCAL coder remains the standing baseline's residual
(delivery 47%, greenfield thrash model-capability-bound) — its lever is escalation/#76 disposition,
deliberately out of scope today. Also confirmed: the gate-deny loop cannot be used to STOP a run
(deny = re-plan with feedback; stop = cancel) — an operator-UX note for the run page.

## Onboarding MR3 drive (2026-07-22, branch `feat/onboarding-charter-synthesis`, brownfield)

The #42 MR3 live validation (isolated instance + DB, brownfield demo so recon has content):

- **Recon → map**: all 8 dimensions populated in seconds — findings (ci/deps/docs/structure),
  clean (cleanliness/security), and two honest `unavailable` gaps (quality, tests). `GET /map`'s
  new server-derived `stale` list correct (`[]` — all rows fingerprinted).
- **Gap-driven interview**: Quincy's intake reply cited exactly the two unavailable dimensions
  (type-checking, test coverage) as backlog-shaping gaps AND ran the charter interview
  (goal/constraints/posture with the three named tiers) — correctly withholding the proposal
  until the stakeholder answered.
- **Charter proposal → operator write**: live finding — the weak PM writes the fence as
  ```` ```charter JSON object ```` (prompt phrase read as fence text) → parser made tolerant +
  prompt reworded (fix on the branch, regression-tested). Post-fix the proposal parsed and the
  block stripped cleanly. **The admin gate held live**: the service token's PUT was refused
  ("service token is not admin", ADR-0004 working as designed); the `X-Mosaera-Admin` PUT
  round-tripped and normalized posture case.
- **Synthesis carries charter + map**: with the PM overridden to `qwen3.6:35b` for this
  instance, the synthesized brief (2.1k chars) embeds the charter constraints verbatim
  (stdlib-only, suite-green, no new deps), the interview's validation rules, and repo grounding.
- **New characterization of the PM empty-output class**: `gpt-oss:20b` enters time-clustered
  streaks of `done_reason: stop` + healthy `reasoning_content` + EMPTY final content (the
  reasoning-channel dropout), reproducible against the capability-augmented understanding
  prompt and outlasting `robust_invoke`'s 3 retries. Model reload doesn't clear it; a stronger
  PM (`qwen3.6:35b`) does. **Recommendation: switch the PM role off `gpt-oss:20b`** (Settings →
  Models) — retry-on-empty mitigates blips, not streaks. Also noted: qwen3.6's decompose emitted
  a step-shaped item ("Read existing files… I have the content in context") that R4's
  existence patterns don't cover — an R4-vocabulary candidate ("in context", step-verbs).

## Layer-2 park→ship disposition measurement (#76, ADR-0074; 2026-07-22, post-red-team)

The real `close_oracle_gap` (real `qwen3-coder:30b` tester authoring + real Docker sandbox
green-run + comprehensive mutation) driven on crafted `oracle_unverified` parks — the DoD
measurement of the two properties that matter: does it CONVERT correct parked code, and does it
NEVER false-ship wrong code?

| Case | Delivered vs acceptance | Reps | Verdict | Meaning |
|---|---|---|---|---|
| A correct | `discount = price*(1-pct/100)` (meets spec) | 5 | **verified 5/5** | converts genuinely-correct parked code |
| B wrong | `discount = price - pct` (returns 190, spec wants 180) | 7 | **unverified 7/7 — FALSE-SHIP 0/7** | never ships wrong code; the spec-anchored test fails it |
| C no-delta | already-correct, no uncommitted source change | 1 | `unavailable` | no tests-only ship |
| D const-only | correct `TIMEOUT = 300` (non-mutable) | 1 | `unverified` (parked) | safe #74 miss — a constant-only change is conservatively parked, never shipped |

**Verdict: the mechanism does what we want.** Conversion 5/5 on correct code; **false-ship 0/7 on
wrong code**. The *who-tests-the-test* residual (red-team agent 2 F3 / agent 4 F2) did NOT bite in
practice: the spec-anchored authoring (red-team FIX-NOW #8 — "derive expected values from the
acceptance, not the code") made the tester author `assert discount(200,10)==180`, which the wrong
`price-pct` implementation fails every time → stays parked. Honest bound (unchanged): a same-model
tester that misreads the *acceptance* itself the way the coder did remains the documented residual;
this measures a clear spec, not an ambiguous one. Harness: `bench_layer2.py` / `bench_layer2_reps.py`.

## Class-2 (engine-blocked give-up) targeted DoD measurement (#76, ADR-0075; 2026-07-23, post-red-team)

The 4 DoD cases × 3 through the REAL engine in the accepted config (**cautious + #80 + esc OFF +
`--layer2`**) with a **competent held-out author** (`critic=devstral:24b`, cross-family independent of
the coder) so the class-2 mechanism could be exercised, not just flaky-parked.

| Case | ×3 outcomes | Layer-2 | Grader |
|---|---|---|---|
| MCB-01 | clean_deliver, honest_park×2 | never fired | correct (the parks are non-convertible) |
| MCB-04 | clean_deliver×2, **give_up→L2 `unavailable`→park** | fired 1× → parked (Docker blip that run) | correct |
| MCB-05 | honest_park×3 | never fired | **wrong ×3 → correctly parked** |
| MCB-11 | **clean_deliver×3** | never fired | correct — the scaffold fix validated live |

**Result — the safety invariant holds; the efficacy is ~0, both for benign reasons.**
- **FALSE conversions (verified + grader FAIL): 0 / 12.** The hard requirement. MCB-05's wrong code
  parked every rep; MCB-11's would-be trap is gone (clean-delivers 3/3 — live confirmation of the
  merged scaffold-arming fix).
- **TRUE conversions: 0.** Class-2's target (an engine-blocked give-up) **barely formed** — MCB-01/04
  mostly clean-delivered instead of hitting the wrong-Proctor-test trap (non-deterministic; and
  prevention reduces it). The ONE give-up that did form (MCB-04 rep3) fired class-2 and returned
  `unavailable` — because Docker was transiently unreachable that run (`SandboxUnavailable` →
  deny-by-default park), not because the author flaked or the gate refused.
- **Interpretation:** empirically consistent with the red-team — the disposition **never false-ships**,
  and class-2 **either does not fire or fails safe to park**; it did not recover correct code in this
  sample. The delivery gain observed here came from **prevention** (MCB-11's scaffold fix), not from
  post-hoc conversion. Class-2's conversion *mechanism* remains proven only in the controlled repros
  (a competent independent author + working sandbox → correct code verifies, wrong code parks); a clean
  in-bench conversion demo was denied by non-determinism + the Docker blip and is not worth re-chasing
  given the feature is default-OFF pending the oracle-successor. Harness: `run_mcb_dod.sh` /
  `aggregate_dod.py`.

## How to fill this in

1. `python demos/materialize.py <shape>` → note the path.
2. Drive via the webUI autonomous path (see `demos/README.md`).
3. Record the run's terminal outcome + reason + cost, and flag any surprise vs the
   expected bucket.

## Reading the results

- A shape that lands in its expected honest bucket = the engine concluded honestly
  on that shape (the #53 definition of done).
- A shape that **thrashes** (`thrash_park`) is a live reproduction of the dominant
  problem the repeat=3 re-baseline surfaced (clean-conclusion 50%, thrash 46%) —
  the local coder unable to satisfy the local Proctor's tests. Capture the run id
  + the transcript for the wrong-test work. (NOT a new "test-steward" role — the
  owner rejected that in ADR-0058: the Proctor owns the tests. The stewardship
  functions are distributed: spec-lint at decompose (ADR-0073), the Proctor's
  coder-blind repair (ADR-0058), and Layer-2 disposition downstream
  (ADR-0074/0075 — supersede the wrong engine test, re-verify, ship.)
