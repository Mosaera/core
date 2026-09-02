# Changelog

Engine version history (see [ADR-0055](docs/adr/ADR-0055-engine-versioning.md)). Versions are `0.x`,
**maturity-anchored**; post-`0.6.0`, completed arcs bump **PATCH** (`0.6.0 → 0.6.1 → …`) — MINOR/MAJOR are
rationed toward a production-proven-at-scale **`1.0` = the SWE team is production-stable** (~99%
clean-conclusion + Python stable; see the ADR-0055 amendment). Each release carries its **benchmark
snapshot** so progress is measured, not vibes. `mosaera --version`, the API `/config`, every run report, and the scoreboard trend
(`_suite/history.jsonl`) all stamp the version, so any outcome is attributable to the engine that produced it.

A **separate** maturity channel — `alpha` / `beta` / `rc` / `stable`, currently **`beta`** — answers
"how much may I trust this?" alongside the number's "how far along?"
([ADR-0088](docs/adr/ADR-0088-engine-maturity-channel.md)). The operational procedure for a release is
[`docs/runbooks/versioning.md`](docs/runbooks/versioning.md).

## 0.6.3 — 2026-08-31 — the over-park anatomy, and two fixes that hold up

**Benchmark snapshot — MCB ×5 = 150 runs (30 cases), 2026-08-31, engine at `5d6794fc`.**
Posture: autonomous verified (`apply_oracle_posture`) — Proctor authoring + repair on, change
coverage on, mutation check on, faithfulness guard on, held-out critic on; `MOSAERA_ORACLE_RECORD_ALL_LEGS=1`; escalate-arm OFF (default); `reduced_lane` / `inert_oracle_scaffold` /
`static_testkit` OFF (default). Local models: coder+tester `qwen3-coder:30b`, PM/reviewer/critic
`gpt-oss:20b`.

| metric | 0.6.3 (n=150, 30 cases) | 0.6.2 (n=130, 26 cases) |
|---|---|---|
| clean-conclusion | **91.3%** | 89.2% |
| `false_ship` | **0/150** | 0/130 |
| over-park | **26.0%** (39/150) | 36.2% (47/130) |
| thrash_park | 8.7% (13/150) | — |
| crashes | **0** | 0 |
| mean capability | **92.5** | 90.1 |
| delivery | **68.7%** (103/150) | 52.3% (68/130) |

**`false_ship` bound.** 0 observed in 150 runs on the MCB corpus under the posture above; by the
rule of three the residual is **< 2.0% at 95%** *for that distribution*. It is not a claim about
repos outside the corpus. Across this release's two full sweeps the observed count is 0/300.

**The comparison is NOT like-for-like and the gain is only 40% attributable.** The corpus gained
four cases since `0.6.2`. On the 30 cases shared with the immediately preceding sweep, delivery
moved 58.7% → 68.7% and over-park 36.7% → 26.0% — but a paired per-case sign test gives **p = 0.36**
(12 cases better, 7 worse, 11 unchanged), and of the +15 delivered runs only **+6 have a named
mechanism** (the decomposition-bar fix on MCB-30/32). +7 come from two cases whose improvement was
investigated and traced to *authoring luck* — MCB-19 and MCB-02 delivered at iteration 1 where they
previously thrashed, with every candidate mechanism ruled out. The remaining 26 cases net +2.
There is no same-code replicate, so sweep-to-sweep variance of this size cannot be excluded.

### What is actually proven

- **A task that preserves behaviour is not thereby a decomposition.** `scaffold_if_refactor` armed
  on `is_behavior_preserving` alone and then planted a red phase asserting *decomposition happened*.
  A comment fix and a version bump promise "No behaviour changes" and decompose nothing, so both got
  `assert 2 > 2` against trees the hidden grader passed 100%. Now requires `requests_restructuring`
  as well. Targeted measurement: **2/10 → 9/10 delivered, Fisher p = 0.005**, control unaffected.
- **An empty tamper baseline is a result, not an absence.** `plan_node` guarded its ADR-0036
  capture with `if not state.get("integrity_baseline")`, and a repo with no tests baselines to `{}`
  — falsy. Every gate-deny re-plan therefore re-baselined a tree the Proctor and coder had already
  written to, recording the authored suite as PRISTINE: the absorption that guard's own comment
  forbids, on greenfield repos where the coder can write anything. **Greenfield runs reporting a
  pre-existing suite on an empty repository: 6/20 → 0/20.**
- **The gate now says when two bars disagree.** When an authored assertion refuses a tree the
  repository's own standing suite passes, the operator is told so, with the failing assertion named.
  Computed after the verdict, changes nothing about it (ADR-0062 intact — nothing advances on it),
  red-teamed across 7 attack classes. **8 firings, 8/8 the tree was genuinely correct, 0 false
  alarms on delivering runs.**

### What was measured and did NOT work — recorded so it is not rebuilt

- **`case_impossible`** detects an assertion no implementation can satisfy (`"<!DOCTYPE html>" in
  content.lower()`). Exact, unit-proven, wired — and **null**: the shape appeared once in eight runs
  and moved nothing. Kept because it is free and correct.
- **The static-site testkit** (`statickit`, 44 tests) hands the Proctor correct helpers so it need
  not write a parser. Adoption was **4/4**; delivery went **4/5 → 0/4**, because the model called
  the helpers without importing them — reproducing the exact `NameError` class that motivated it.
  Ships default OFF. Fourth prompt-level lever this arc, and the first to make things worse.
- **`coder_prefetch`** (+7% calls, +9% tokens) and the **repair-loop causation sweep** (McNemar
  p = 0.51, mechanism contradicted) were both null earlier in the arc.

### The anatomy that did not exist before

`docs/engineering-history/over-park-anatomy-2026-08-30.md`. Every over-park is a tree the hidden
grader passed 100%, and they split into two OPPOSITE mechanisms needing opposite fixes: **59% the
authored bar refused correct code**, **36% no oracle could vouch at all**. Of the bar-refusals,
~91% are a wrong or over-strict expected value — not broken code — which is the wall this release
does not clear: the engine cannot compute the right value without running code it must not see.

Three instrument corrections are recorded there too, because each one invalidated a number this
arc had already reported: a detector measured at 30% recall on a self-labelled corpus fires on
**4.2%** of the real cases; a gate-reason set counted 6 tamper runs as over-strictness; and the
"24/26 standing-suite" figure was contaminated by the baseline defect above (19/19 on brownfield).


## 0.6.2 — 2026-08-11 — a behaviour change can finally ship, and a safety control that refused correct work 9 times out of 9

**Benchmark snapshot — MCB ×5 = 130 runs (26 cases), 2026-08-11, engine `0.6.1` (the run precedes
the bump, per the runbook's *benchmark first* rule).**

| metric | 0.6.2 (2026-08-11, n=130) |
|---|---|
| clean-conclusion | **89.2%** |
| `false_ship` | **0/130** |
| over-park | 36.2% (47/130) |
| crashes | 0 |
| mean capability | 90.1 |
| delivery | 68/130 runs (52.3%) |

Outcomes: 68 `clean_deliver` · 48 `honest_park` · 14 `thrash_park` · 0 `false_ship` · 0 `crash`.

**`false_ship` bound (ADR-0061 gate 2 wording).** 0 observed over the named distribution — MCB 26
cases × 5 under the posture below — gives **≤ 2.3% at 95%** by the rule of three. The zero is **not
vacuous**: 68 runs delivered, so a delivery channel existed and none produced an unestablished claim.

> **NOT COMPARABLE TO 0.6.1.** Two independent reasons, either of which alone breaks the comparison:
> the corpus grew from 24 to **26 cases** (MCB-28 added by verb-arc slice 4, and `available_cases()`
> globs the directory), and the posture is **different in kind** — 0.6.1's snapshot ran the
> deterministic baseline (`tester_enabled=False`, `critic_enabled=False`,
> `oracle_mutation_check=False`, `scan_enabled=False`), where this ran the **autonomous verified
> posture** with all four ON. Reading 89.2% against 0.6.1's 90.3% would be wrong in both directions
> at once. Per-case comparisons remain valid; corpus-wide rates do not.

**Posture configuration.** `autonomous_verified=True` → `tester_enabled=True`,
`tester_repairs_tests=True`, `critic_enabled=True`, `oracle_coverage=True`,
`oracle_mutation_check=True`, `oracle_mutation_vetoes=True`, `proctor_faithfulness_guard=True`,
`reason_on_stall_enabled=True`; `escalate_arm=False`, `amendment_gate=False`,
`disposition_gap_close=False`, `oracle_structural_spec=False`, `stall_detection_enabled=True`,
`reliability_sensitivity=balanced`, `scan_enabled=True`. Escalation ladder **empty** (the configured
model is not installed) — every run concludes at tier 0. Models: pm `qwen3.6:35b`, coder + tester
`qwen3-coder:30b`, reviewer + critic `gpt-oss:20b`.

### The headline

**A MODIFY item delivered autonomously for the first time** — `clean_deliver`, zero gate reasons,
hidden grader passed. Verb-arc slice 4 gives a behaviour change an oracle
([ADR-0097](docs/adr/ADR-0097-consumer-impact-modify.md)) and tells the Proctor which pre-existing
test asserts the behaviour being changed ([ADR-0098](docs/adr/ADR-0098-modify-amendment-targeting.md)).
Six mechanisms had to hold at once; this is the first run where they did.

**The held-out critic was refusing correct work every time it fired** — 9 vetoes across 260 runs, 9
wrong, 8 of them quoting a *premise* sentence ("crashes on the first malformed op") that a correct
fix necessarily falsifies. Root cause was structural, not a missing pattern: an unmatched sentence
mints `oracle_kind: none` → disposition `unbound` → **the gate discards it**, yet `unbound` sat
inside the critic's veto jurisdiction, so a model could park a run on evidence the deterministic
layer had refused to gate on. Fixed by construction in
[ADR-0100](docs/adr/ADR-0100-critic-may-not-veto-an-unbound-claim.md); **0 vetoes in the 130 runs**,
and the critic is demonstrably still live (ran on 90/130, proposed 25 refutations, all correctly
denied).

### Also in this release

- **[ADR-0099](docs/adr/ADR-0099-undeclared-destruction.md)** — a pre-existing file *emptied* rather
  than deleted is now a standing prohibition in the tamper family (`content_destroyed`).
- **Verb-arc slices 1 and 2.1** — SUBTRACT gets a non-use oracle; the exec ceiling gets a
  denominator.
- **The evidence store was destroyed on 2026-08-10 and the cause is now known, reproduced and
  closed** — a committed `.mosaera` symlink plus the WSL-era `core.symlinks=false`, under which git
  writes a symlink as a regular file containing its target path, silently overwriting the store on
  any checkout or merge. Closed at four layers with a guard test
  ([record](docs/engineering-history/evidence-store-loss-2026-08-10.md)).
- **Diagnostics that make refusals attributable** — `oracle_legs` (which term of the oracle AND
  refused), `amendment_refusals`, `overstrict_total`, `modify_amendment_targets`,
  `security_unavailable_cause`.
- **Measurement records, including the null results** — the mutation-veto A/B (null, and
  underpowered by design), the ADR-0062 MR-D tester-model probe (refuted), and the over-park
  attribution.

### What this release does NOT claim

**Over-park is unmoved.** Like-for-like on the same 25 cases: **31.2% → 33.6%**, a 0.41-standard-error
difference that this sample cannot resolve. Roughly a third of runs still refuse work the hidden
grader confirms was correct, and the dominant cause — the system authoring acceptance tests its own
correct code fails — is **untouched**
([attribution](docs/engineering-history/over-park-attribution-2026-08-11.md)). Two candidate fixes
were tested and both failed. No ADR-0061 v1.0 gate went green.

## 0.6.1 — 2026-08-08 — the controls got controls: invisible refusals, inert state, and a re-baseline that says where we actually are

**Benchmark snapshot — MCB ×3 = 72 runs (24 cases), 2026-08-08, engine `0.6.0` (the run precedes
the bump, per the runbook's *benchmark first* rule).**

| | 0.6.0 baseline (2026-08-05, n=72 @ `c83d0be`) | **0.6.1 (2026-08-08, n=72)** |
|---|---|---|
| clean-conclusion | 91.7% | **90.3%** |
| `false_ship` | 1.4% (1/72) | **0/72** |
| over-park | 30% (18/60) | **36.1%** (26/72) |
| crashes | 0 | **0** |
| mean capability | 89.5 | **91** |
| delivery | — | 13/24 cases |

Outcomes: 39 `clean_deliver` · 26 `honest_park` · 7 `thrash_park` · 0 `false_ship` · 0 `crash`.
Cost 11.97M tokens / $1.71 / 1,220 calls. By capability: greenfield 78 · bug-fix 87 · feature 97 ·
refactor 93 · robustness 94.

**Posture configuration** (code defaults; `.mosaera/settings.json` overrides none of these):
`reliability_sensitivity=balanced`, `max_iterations=8` (per-case `case.toml` caps govern),
`tester_enabled=False`, `critic_enabled=False`, `escalate_arm=False`, `amendment_gate=False`,
`disposition_gap_close=False`, `reason_on_stall_enabled=False`, `intake_ask_unreachable=False`,
`oracle_mutation_check=False`, `stall_detection_enabled=True`, `ollama_num_ctx=32768`,
`pm_step_limit=20`, `coder_step_limit=25`. The harness additionally forces `approve_writes=False`
(headless — no write gates, no operator turns) and `scan_enabled=False`, and resolves gates through
the real `autonomous_resolution` policy.

**Read it honestly, because the numbers do not flatter the release.**

- **`false_ship` 0/72 is the good news, and it is bounded, not zero.** By the rule of three the 95%
  upper bound on that distribution — *autonomous MCB runs under the posture above* — is **~4.2%**.
  Gate 2 is **not** passed. Per the ADR-0061 gate-2 amendment, a rate is only a result when the
  distribution it bounds is named; this is that naming.
- **Clean-conclusion is flat within noise** (−1.4pt). There is **no seed and no determinism control
  anywhere in the bench**, and temperature is 0.1–0.2 per role, so a single ×3 sweep is a sample.
- **Over-park moved the wrong way** (+6.1pt) and is now the worst number in the system.
- **Roughly fifteen changes shipped since the prior baseline and bought no measured reliability.**
  That was pre-registered before the sweep ran, and for a stated reason: this cycle's work was
  workflow-shaped — operator surfaces, refusal reasons, gate presentation, the amendment path — and
  MCB exercises no operator, no write gate and no amendment. The instrument is blind to the work by
  construction, which is an argument about the instrument, not evidence the work was worthless.
- **The posture differs from the prior baseline** (`balanced` here; `cautious` was recorded for the
  2026-07-22 `#43` figure). The two are **not posture-matched**, so treat the row-by-row deltas as
  indicative rather than controlled.
- **Greenfield 78 is the worst capability**, below refactor (93) and robustness (94). Every
  capability scoring well is brownfield-shaped — an oracle already exists to lean on. Greenfield is
  the one phase where the apparatus must be created before anything can be verified, and it is the
  phase a non-technical operator starts in.

Maturity channel: **`beta`** (ADR-0088) — unchanged. Three of ADR-0061's four gates remain open.

**Headline work in this release**

- **The invisible-control class, found four times in one day and then closed as a class**
  (`#75`/F70, `#76`/F71, `#79`/F73). A control that offers or declines *invisibly* — F61's button,
  F65's vanished offer, F69's placeholder, F71's silent refusal. Every refusal now records its reason
  and shows it, via one classifier whose predicate is its `.paths` and whose reason is its `.reason`,
  so the two cannot drift. Writing the per-branch tests found a further defect: the amendment offer
  was computed without checking `tester_enabled` while consumption requires it.
- **The amendment path completes end to end** ([ADR-0087](docs/adr/ADR-0087-test-contracts-and-renegotiation.md)
  §5/§6, `#65`/F63). A delivered test was a permanent, unamendable assertion, so any item that
  *changes* behaviour deadlocked. The operator may now authorize amending specific blocking tests;
  the **Proctor** — never the coder — rewrites them once. Confirmed live (item #87 delivered, clean
  gate). **And the more important live result was a refusal:** offered two blocking tests, the
  operator amended only the legitimate one and declined the other, because it correctly encoded the
  acceptance criterion and failed for want of a capability. Authorizing it would have used a human
  signature to weaken a bar to fit a capability gap.
- **Intake asks whether an item is REACHABLE** ([ADR-0089](docs/adr/ADR-0089-intake-reachability.md),
  `#78`/F76). A third deterministic axis beside checkability and decidability. The capability boundary
  had lived as **prose inside a prompt**; it is now data the PM prompt renders from and the check
  matches against. Default OFF pending a precision measurement.
- **A codebase audit, and a sixth lint guard.** `check_state_keys.py` fails any production
  `state.get("X")` naming a key `RunState` does not declare — LangGraph drops those silently
  (ADR-0026). Run red it flagged exactly three reads and **zero false positives** across 374 files.
  Three HIGH fixes none of which a run had found: the gate reported security `"clean"` on two branches
  that never enter `scan_node` (F77 — this **tightens** a gate), `run_diagnosis` recorded an empty
  vouch on *every* live run (F78), and `operator_edits` never reached the raw-bytes tamper guard
  (F79). Leanness result was good: no dead code, no orphaned modules across 496 files, all 72 knobs
  genuinely read.
- **The god-file ratchet made to ratchet** (`#81`/F75). `GRANDFATHERED` had names but no sizes, so a
  listed file could grow forever and the guard only fired when you *fixed* one. It caught its own
  author within minutes.
- **The governance benchmark persists its results** ([ADR-0083](docs/adr/ADR-0083-governance-benchmark.md)).
  Five deterministic cases, sub-second and free, already in `make test` — but with no scorecard, no
  history and no engine stamp, so nothing accumulated. `mosaera-govbench` now writes a stamped
  scorecard beside MCB's, and **refuses to score over a broken fixture** rather than reporting fixture
  drift as a finding about the system.
- **The gate stops misstating what your answer will do** ([ADR-0082](docs/adr/ADR-0082-gate-decisions-and-standards.md)
  §1/§5, F61). A denial at the iteration cap *terminated* the run while the button said "send back to
  revise" — ~1.1M tokens of correct work, HTTP 200, nothing anywhere saying so. An option that cannot
  function is no longer offered.
- **First project driven end to end.** LedgerCLI, all three slices delivered (one guided, two
  autonomous). *Completion is not correctness* — F57 shipped through every green control.
- **The verb arc named** (`#82`, [`docs/design/verb-arc.md`](docs/design/verb-arc.md)) — the engine
  can only ADD, and no wave had modelled it. PROPOSED; nothing built.

**Also in this release**

- **Versioning SOP — the maturity channel, drift closure, and a bump tool**
  ([ADR-0088](docs/adr/ADR-0088-engine-maturity-channel.md), extending ADR-0055). `0.6.0` had sat
  still for three weeks with nothing in the product saying how much it may be trusted, and ADR-0055's
  promised `bump_version.py` had never been written — so the bump stayed a ten-file hand-edit that
  had already drifted twice. Now: a separate `__maturity__` constant on a closed, ADR-0061
  gate-anchored ladder (`beta` today), shown as `mosaera 0.6.0 (beta)`, in `/config`, and as a header
  badge; `scripts/bump_version.py` (bump · `--check` · `--verify-record`) moving all 9 version
  strings together and inserting a CHANGELOG stub whose benchmark snapshot is an explicit TODO; a CI
  `version-record` job that verifies but never bumps or tags; and three drifted strings closed —
  `apps/web/package.json` and the FastAPI `version=` argument had each sat at `0.1.0` through two
  releases, and the unread `mosaera_agents.__version__` was deleted rather than synced. The version
  itself is unchanged and deliberately stays a plain PEP 440 release: maturity is a second axis, not
  a suffix, because `0.6.1-beta.1` is invalid PEP 440 that `uv` would silently normalize.
- Reliability arc `#43` baseline **accepted by owner (2026-07-22): 94.4% clean-conclusion, `false_ship` 0,
  crash 0** — run `rebaseline_80on_x3` (MCB ×3 = 72 runs, `#80` structural-spec oracle ON + `cautious`
  sensitivity, escalation OFF; delivery ~47%). Structural-spec oracle (`#80`, ADR-0072) + comprehensive
  mutation (`#74`, ADR-0071). *(Scoreboard artifacts live under the gitignored `.mosaera/`, so this figure
  is recorded here as the durable source.)*
- Quincy Layer-2 disposition `#76` (ADR-0074/0075) — arc closed; default OFF.
- Independent security gate `#83` (ADR-0076) — a scan that can't verify parks; merged + red-teamed.
- Project onboarding `#42` (ADR-0047) — map/charter store + recon + onboarding flow (MR1–MR4).
- Documentation overhaul — blueprint North Star, execution-contract CLAUDE.md, normative coding-standards, durable project brief, lean roadmap + engineering-history split.
- **On-box endpoints are not cloud** ([ADR-0024](docs/adr/ADR-0024-cloud-egress-and-price-gate.md)
  amendment) — a local OpenAI-compatible inference server (vLLM/llama.cpp/TGI) reached through the
  `openai` provider with a loopback `base_url` was classified as CLOUD, so an autonomous run demanded
  off-box egress consent for traffic that never leaves the box. A binding is now on-box when the
  provider is inherently local OR **both** its `base_url` host is loopback **and** the operator
  explicitly declared it (`ProviderConfig.on_box`, admin-gated, default OFF). Deny-by-default: loopback
  alone does not exempt, because a forwarding proxy also binds to loopback. Defaults keep existing
  configs byte-for-byte identical.

## 0.6.0 — 2026-07-19 — the honest-stop: the engine concludes, not just bounds

**Benchmark snapshot (MCB ×3 = 72 runs, autonomous oracle posture, escalation OFF, frozen classifier):
clean-conclusion 50.0% → 65.3%** (+15.3pp). Buckets vs the 0.5.x #54 baseline: clean_deliver 25→**32**,
honest_park 11→**15**, thrash_park 35→**24**, false_ship 0→**1** (isolated to MCB-05, the known weak-oracle
case — the oracle-successor's target, honestly counted against the rate), crash 1→**0**. The gain is real
thrash→{deliver, honest} conversion under *equivalent* conditions — same hidden grader, classifier
untouched, oracle at full strength (no relaxation channel).

**The honest-stop + lean engine (#56, ADR-0060) — the #43 arc's missing mechanism:**
- **The honest-stop** — a deterministic best-so-far progress breaker (`bump_progress`; catches
  oscillation the prior two-value window missed; K = the existing `stall_limit`, so the #51 sensitivity
  dial scales it — no new knob) that routes a non-converging run to `supervise` for a *decision*
  (re-scope once vs give up) and parks EARLY with an accurate `give_up_reason` — classifying `honest_park`
  by construction, never by relabeling (the classifier is frozen). The engine had seven mechanisms that
  BOUND a loop and none that CONCLUDE one; this is that one. A give-up park still diagnoses the coder, so
  the ADR-0016 model-escalation re-run fires on exactly these honest parks.
- **Lean engine** — deleted `gap_fill` (a posture-excluded confirmation oracle) and `react_on_bad_test`
  (an LLM call that only reworded a park note); the honest-stop's deterministic diagnosis (failing-test
  names + count trend) replaces the latter on every park. Two knobs removed; RunState net −1.
- **Oracle demotion — considered, red-teamed, REVERTED.** A cost-saving demotion (coverage out of the
  posture; mutation proctor-scoped) was built and dropped: the red-team reproduced end-to-end that it
  reopens the executed-but-unasserted park→ship channel. Correctness-first — the oracle keeps full
  strength; the demotion rides with the dynamic-verification successor. **So this arc makes no
  trust-boundary change.**
- **Three robustness fixes the re-baseline exposed** — (1) prune build-artifact dirs during the workspace
  walk so a venv can't crash `tree_hash`; (2) create the sandbox venv with `--copies` (root-cause fix for
  a dangling-symlink `WinError 1920` crash on Windows); (3) head+tail truncation of validation output so
  pytest's summary survives — without which the honest-stop's count signal was starved and the whole
  mechanism silently didn't fire. Running the benchmark before merging caught the last one.

## 0.5.0 — 2026-07-17 — reliability arc; the first *measured* release

The version series begins here: the first release we can **measure** — the reliability scoreboard is live.
(0.5.0 is maturity-anchored: it acknowledges the substantial un-versioned pre-history below.)

**Run-reliability arc (#43) — deliver, or park honestly, without looping/thrashing:**
- **Reliability scoreboard** (ADR-0053, #43): the MCB suite classifies each run's terminal outcome
  (`clean_deliver` / `honest_park` / `thrash_park` / `false_ship` / `crash`) and reports a
  **clean-conclusion rate** — the arc's definition-of-done instrument.
- **Already-satisfied → honest conclude** (ADR-0052, #44): a task already met before any code concludes
  *early and honestly* (surfaces "appears already satisfied — confirm") instead of thrashing to a
  mislabeled give-up. It does **not** auto-deliver. Red-team-redesigned pre-merge.
- **Whole-suite validation** (ADR-0054, #45): validation now runs pytest's own config-driven discovery
  (`--import-mode=importlib`) — a test outside `tests/` is no longer silently skipped, closing the top
  `false_ship` class. Red-team-redesigned pre-merge.

**Benchmark snapshot** (local models, `repeat=1`):
- **Clean-conclusion: 91.7%** (target ~99%) — up from **83.3%** at the arc's start.
- Suite capability: **88 / 100**.
- Outcomes (24 runs): clean_deliver 13 · honest_park 9 · thrash_park 1 · false_ship 1 · crash 0.

**Known next levers** (scoreboard-attributed): the oracle gap (a missing-new-behavior false-ship needs the
Proctor/coverage, not validation scope), the thrash bucket (the #44-successor: degenerate-plan breaker +
Proctor red-hunt bound), and a `repeat=3` denoise for a stable trend point.

---

**Un-versioned pre-history behind 0.5.0** (recorded in `docs/adr/` + `docs/roadmap.md`): the trust/oracle
stack (ADR-0020/0031/0034/0035/0036/0044), the coverage-based oracle arc (#29, ADR-0049), the mutation
check (#39), project onboarding — durable map + recon (#40/#41, ADR-0047), the cost architecture (#19),
autonomous orchestration (ADR-0019–0024), the PM/Quincy + backlog-ownership foundation (ADR-0008–0013),
multi-user auth + config-in-UI (ADR-0004/0005), and the LanguagePack seam (ADR-0032).
