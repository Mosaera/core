# Roadmap & Arc History (engineering journal — full detail)

> **This is the ENGINEERING HISTORY, not the forward-looking roadmap.** It preserves the full arc
> record — diagnoses, implementation notes, benchmark snapshots, red-team dispositions, lessons, and
> rejected ideas. It is the deep reference; nothing here is lost. The **lean, current roadmap**
> (what/why/status/next) is [`docs/roadmap.md`](../roadmap.md); **decisions** are in `docs/adr/`;
> **direction** is in `docs/architecture/north-star.md`. Read this when you need the *why-and-how* of a
> specific arc; read the roadmap when you need *what's next*.

---

A frozen snapshot of Mosaera's arc-by-arc build history — the north-star arcs, tracked GitLab
issues, near-term needs, and debt as they were reconciled during development. The **live** roadmap
(what to build next, and where each piece stands *now*) is [`docs/roadmap.md`](../roadmap.md); this
file is the deep *why-and-how* reference behind it.

## How this was organized (the classification scheme, for reference)

- **Each item is classified:**
  - **[arc]** — part of a north-star arc; build it when that arc runs.
  - **[prereq]** — an arc can't start without it; build it first even if it looks like "just debt."
  - **[debt]** — genuinely independent; slot opportunistically as friction dictates.
- **Sequence by leverage + dependency, not size.** A small piece that unblocks three others goes first.
- **GitLab issues** (`#N`) were the unit of work; this file was the map over them. The board's
  **Phase A–E** milestones are reconciled below.

## North stars (the epics)

> **The full blueprint is [`docs/architecture/north-star.md`](../architecture/north-star.md)** — Mosaera
> as a **governed decision engine with institutional memory** (a Fortune-500 decision process
> compressed into six control points), whose defining bet is **orchestrate artifacts, not agents**.
> This roadmap is the build-order/status for the arcs it names.

- **NS-1 — Software org / the firm** (`#18`, P1): the six-control-point governed SWE team (Quincy /
  Atlas / Sentinel / Forge / Rook / Human — *control points, not headcount; nobody approves their own
  work*). In the north-star framing this org *is the first TEAM of the firm*.
- **NS-2 — Governed-execution business** (`#19`, P0): cost architecture (largely delivered) +
  enterprise/regulated posture.
- **NS-3 — Capability benchmark (MCB)** (`#20`, P0): the offline capability grader + benchmark-as-product.

## Road to v1.0 — the measured bar (ADR-0061)

**`1.0` = "the SWE team is production-stable"** (ADR-0055) is now a **measured** bar, not a vibe: the engine
drops into *any* repo and either delivers correct, industry-standard code for the project **or** honestly
refuses — all governed and fully auditable. The reframe (ADR-0061): the engine is the **trust +
verification + project-knowledge + governance** layer around a *swappable* frontier model — we don't build
the intelligence, we make it provably trustworthy on the buyer's codebase. **Anti-gimmick clause: every
gate is measured on held-out inputs the coder can't game, or it doesn't count.**

**v1.0 ships only when ALL FOUR gates are green on one held-out benchmark run** (recorded as the release's
snapshot):

| Gate | Threshold | 0.6.0 status |
|---|---|---|
| **1. Reliability** | ~99% clean-conclusion (deliver-correct or park-honestly, no thrash), repeat≥3 | 65.3% (esc OFF); ~90%+ (esc ON, matrix B) — routing lever |
| **2. Correctness** | `false_ship` ≈ 0 vs a **hidden** grader the coder never saw | ✗ **the load-bearing gap** (MCB-05) — the critical-path arc |
| **3. Any-repo** | the bar holds on **brownfield** repos in **≥2 languages** (Python → TS/JS or SQL) | Python-first; brownfield/demo harness exists |
| **4. Governance** | tamper-evident exportable audit log + dual-control ceremonied autonomy + control-mapped posture | foundation only (gate/sandbox/tamper/honest-outcomes) |

**Pillars → existing arcs (sequenced; correctness first — it's the only gate 0.6.0 outright fails):**
- **[arc] Correctness oracle** (the #54 successor) — dynamic per-test
  verification + a rigorous spec-derived Proctor (property/metamorphic) + a held-out different-model
  critic (downgrade-only), all graded against a hidden suite. **Directly kills the MCB-05
  executed-but-unasserted `false_ship` class this arc's predecessor (#56) surfaced.** *The highest-leverage
  next arc — it converts "passes the tests" into "code you'd sell."* Feeds the **coverage arc** (`#29`).
  - **[arc] MR-A — the held-out critic** (`#60`, **ADR-0065**, run-reliability arc `#43`; ADR-0063
    sub-arc 2) — **BUILT + RED-TEAMED (3 agents, 2 FIX-NOW fixed):** a NEW role `critic` (ADR-0013 SOP;
    read-only allowlist, held-out `critic_model` `gpt-oss:20b` ≠ coder `qwen3-coder:30b`) cloned from the
    reviewer's shape but **veto-only, once-per-delivery, held-out**. A conditional `critic_node` between
    `review` and the gate runs ONLY on a green + held-out run, memoized by `tree_hash` (one call/tree, off
    the loop), `try/except→None`. It judges the code against the spec **independent of the tests**, VETOes
    only with a SPECIFIC unmet requirement, SHIPs when unsure (two-sided: catches MCB-05, spares MCB-10). A
    new veto-only `GateReason` `critic_vetoed` → **universal, downgrade-only park** (can only flip
    ship→park). Posture ON for verified autonomous runs; **local-default, cloud delta to be measured**
    (`MOSAERA_BENCH_CRITIC_OFF`; effect flows through the scoreboard `outcome` + a `critic_vetoes` count).
    Proactive: the autonomous cloud-egress consent gate now includes `critic`. **RED-TEAM (downgrade-only
    property held — 0/2304 rescue violations): 2 FIX-NOW fixed** — echo-injection of the verdict parser
    (fence-strip + distinct-verdict conflict→no-veto, mirrors ADR-0034) and a memoized fault sentinel (only
    completed judgements cached). **DEFER-TO-SUCCESSOR:** the critic covers `review→gate`; a green delivery
    via the plan-early-park / supervise-give-up bypass is not critic-judged (pre-existing, NOT a
    downgrade-only violation) — route those edges through outcome verification, or have the runner refuse an
    autonomous auto-approve on a green delivery when critic-enabled + held-out yet `outcome_verdict is
    None`. ACCEPT residuals: `held_out_ok` provider-alias (efficacy); degrade-abuse (fails safe). NOTE
    (pre-existing, separate MR): ad-hoc `POST /runs` autonomous skips the egress gate for ALL roles.
    Follow-on: MR-B dynamic per-test verification, MR-C rigorous spec-derived Proctor, MR-D re-baseline +
    version.
  - **[arc] Behaviour-preservation Proctor** (`#60`, **ADR-0066**, correctness arc) — **BUILT +
    MEASURED → posture activation HELD** (the MCB-05 ON/OFF smoke REFUTED the prompt-led hypothesis:
    a `false_ship` on the ON arm the OFF arm didn't show + no `clean_deliver` win — the weak local
    Proctor authored too loose a suite, reopening the #57 false-ship class; the local critic didn't
    veto). Posture activation withdrawn (the detector + `source_introspection` finding + the
    guidance-behind-the-knob stay live); the follow-up is the **deterministic golden-master scaffold**
    (the engine authors the differential test, not the weak model), measured correctness-neutral
    before any re-enable. **★ SCAFFOLD BUILT** (`refactor_scaffold.py`, `refactor_oracle_scaffold`
    knob, posture ON): for a detected refactor the ENGINE authors a verbatim frozen copy + a
    differential behaviour test (real == frozen across generated inputs) + a name-agnostic
    decomposition check — validated (reds on the seed, greens on a correct decomposition, catches a
    behaviour change), general (import-based target + literal-input mutation, no MCB coupling),
    deny-by-default; the prompt-led guard stays OFF. Next: a single MCB-05 run to confirm
    honest_park→clean_deliver, then the esc-ON repeat=3 baseline. The
    "rigorous Proctor" phase, re-sequenced ahead of dynamic per-test verification by the MR-A smoke,
    which showed MCB-05's *active* bottleneck is the over-strict Proctor honest-parking a correct
    refactor, not a false-ship). Prompt-led + measured: a deterministic `is_behavior_preserving`
    detector (deny-by-default) + the differential-golden-master (freeze the original module, assert
    equal output across generated inputs — no hand-computed goldens) + loose-structural (property, not
    a private name) authoring guidance (persona + injected instruction) + a new `source_introspection`
    over-strictness finding (extends `#57`) + `behavior_preservation_guard` (posture ON) + a
    `MOSAERA_BENCH_BEHAVIOR_PRESERVATION_OFF` A/B lever. NOT a trust-boundary change (guidance + a
    detector, no gate/policy touch); judgment-authored (heeds the reverted-auto-rewriter lesson).
    Verify: 4 gates + unit + a live MCB-05 ON/OFF smoke (`honest_park→clean_deliver`, `overstrict`↓,
    correctness held). Logged follow-up if the weak local model can't execute the pattern: the
    deterministic golden-master *scaffold*. **2026-07-23 arming-seam fix:** `scaffold_if_refactor`
    now arms from the TRUSTED TASK only — the PM plan/design paraphrase armed the scaffold on a
    feature task (bench MCB-11: the brief's symbol-scoped constraint didn't match, the lossy
    paraphrase did → an unmeetable protected decomposition bar double-trapped a grader-correct run;
    ADR-0072 §Live-drive finding records the closure).
  - **[arc] Proctor faithfulness — over-strictness DETECTION** (`#57`, **ADR-0062**, run-reliability arc
    `#43`) — instrumented three MCB cases → the dominant `thrash_park` cause is the Proctor pinning
    **incidental detail the spec leaves open** (exact whitespace, a `#`-rendering, a private helper name)
    or authoring an **unsatisfiable** contract (MCB-14). **BUILT:** a deterministic AST detector
    (`faithfulness.py`) measured on the scoreboard (`overstrict_static` + `overstrict_vs_ref` vs the case
    `reference/`), NAMED into the Proctor's coder-blind repair turn (`proctor_faithfulness_guard`). The
    deterministic **auto-loosen (MR-C) was built, red-teamed, and REVERTED** — 2 adversarial passes
    CONFIRMED false-ship (bare `.split()` erases semantic whitespace; `== N → != 0` guts behavioural
    `.status`). **DEFER-TO-SUCCESSOR:** loosening needs spec judgment → the Proctor + the held-out critic
    above. Stronger-tester = config (model-agnostic), not hardwired. Classifier FROZEN. **MEASURED
    (guard-OFF baseline, 24 runs): clean-conclusion 66.7%, 0 false_ship, and `overstrict_vs_ref` = 6/20
    cases (~30%) author a suite that fails the correct `reference/`** — the mechanism confirmed at scale.
    The guard-ON A/B was cut short (pivot to ADR-0063); the naming nudge's delta was expected within
    noise — real levers = stronger tester + held-out critic + the workbench.
  - **[arc] Oracle-authoring — the Proctor must not false-fail CORRECT code** (`#66`, the `#54`-successor
    MR-B/MR-C made concrete + **EVIDENCE-BACKED**; correctness arc; **RED-TEAM-REQUIRED** — the oracle is a
    trust-boundary domain). **The repeat=5 local baseline (esc-OFF, full posture, qwen3-coder:30b) proved
    the ceiling is the ORACLE, not the coder:** of the parked runs, ~**89% are code the HIDDEN grader scores
    correct (Implementation ≥85/100) that the run's OWN validation false-red** ("Validation 25 — tests
    failed"; the grader labels it *"refused to ship work that actually passes (over-conservative)"*), and
    **0–2 are genuine coder-fails.** The reviewer is SECONDARY (a few `REQUEST_CHANGES`; MCB-15 parked with
    reviewer APPROVE); the PRIMARY defect is the weak local Proctor authoring an acceptance suite the CORRECT
    reference fails — the `overstrict_vs_ref` ≈30% mechanism (`#57`) at scale, now the dominant thrash cause.
    The gate is honest (deny-by-default on a red suite); the SUITE is wrong. **Build (judgment-authored —
    heeds the reverted-auto-rewriter lesson, `#57`/ADR-0062):** **(MR-B) dynamic per-test verification** —
    before an authored test is allowed to FAIL the coder, verify the TEST against the spec (run it against a
    known-correct `reference/` where one exists; a property/metamorphic check — the held-out-model-judge
    variant is DEAD, measured net-null-to-negative and reverted in ADR-0070; only the deterministic forms
    remain live); a test a correct reference fails is provably over-strict →
    drop/loosen with judgment. **(MR-C) take authoring off the weak model where deterministic derivation
    exists** — generalize the `#60`/ADR-0066 scaffold pattern beyond refactors (spec examples → parametrized
    cases; properties/metamorphic relations; golden-master where a reference exists), so correctness never
    rests on the weak model writing assertions; + the held-out critic (`#60`, built) as the ship-correctness
    backstop. **Measure (hidden grader):** `overstrict_vs_ref`→0, false-park thrash→0, `clean_deliver`↑,
    `false_ship`≈0 held. **Domain:** `packages/agents` (personas/tester), `packages/core`
    (`faithfulness`/`oraclecheck` + a new per-test verifier); minimize `graph/build.py`/`policies/gate.py`.
    **blockedBy:** none hard (builds on the merged `#57` detector + `#60` critic + `#60` scaffold). *The
    highest-leverage arc for BOTH the Reliability and Correctness v1 gates — it converts "correct code the
    engine rejected" into "correct code the engine ships." Complementary to `#67` (which makes the residual
    HONEST now); `#66` makes it DELIVER.*
- **[arc] Capability through auditability — the agent workbench** (**ADR-0063**, owner-directed
  2026-07-19; a third DNA principle) — the `#55`/`#57` thrash root cause: the harness restricts the
  agent's *process* for safety, which causes thrash **without** buying safety (the sandbox already
  contains the blast radius). **Principle:** safety = containment (the wall) + traceability (a
  tamper-evident audit log — the trust primitive) + verification (prove the *output* at the boundary,
  verify outcome not process); process-restriction is a capability tax, kept only as defense-in-depth.
  **Free inside the wall, logged throughout, proven at the door.** Sequenced sub-arcs: **(1) scratch
  mount** — a `/scratch` write+exec space excluded from the deliverable diff (cheapest, kills the `#55`
  `tests/`-abuse *and* unblocks experimentation); **(2) verify-outcome oracle** = the correctness-oracle
  arc above (now with a *reason* it's load-bearing); **(3) audit-log-as-enabler** — promote
  `run_events`/checkpointer into the tamper-evident, exportable, evidence-bearing log (folds ADR-0046's
  governance log forward as the primitive that *unlocks* capability), then progressively open the
  workbench. Posture tunes the boundary + ceremony, never containment or audit. Authorizes no capability
  change by itself — each opening is its own red-teamed MR.
  - **[arc] `/scratch` space** (`#59`, **ADR-0064**, sub-arc 1) — **BUILT + RED-TEAMED.** `.mosaera/scratch/`
    = a writable, any-name, never-shipping, logged scratch dir (a workspace dir, not a tmpfs) that closes
    the `#55` `tests/`-abuse. **Red-team (2 passes) caught 2 FIX-NOW pre-merge:** a coder `.gitignore`
    `!.mosaera/` negation outranked `.git/info/exclude` (scratch shipped) → moved containment to the
    DELIVERY SEAM (`workspace._stage_all` reset + fail-closed assertion); and bare-`pytest` collection
    honored the untrusted repo's `norecursedirs`, so a scratch `test_*.py` could poison the oracle →
    `--ignore=.mosaera`. Lesson: enforce at the delivery boundary, positively + fail-closed.
- **[arc] Project-knowledge** — onboarding interview → recon → durable **map** + **charter** (`#42`/`#6`,
  ADR-0047) so runs are gap-analysis against the project's real state + respect its conventions; then
  **language #2** via the LanguagePack seam *after* the Python oracle is green.
- **[continuous] Capability / routing** — frontier coder + local-for-cheap + **escalation routing**
  (ADR-0016/0022); the engine's job is context quality (repo-map, exact diff, spec) + reliability. Matured
  by measurement (matrix B), not a serialized arc.
- **[arc] Governance layer** — posture policy-as-code + dual-control enablement ceremony + tamper-evident
  exportable audit log (`#6`/`#8`/`#11`, ADR-0046; Waves B/C). Largely parallelizable once the core
  delivers — the enterprise wrapper, not a correctness blocker.

The **correctness `false_ship` metric** joins clean-conclusion as a first-class release gate on the
scoreboard.

## Reality vs. the board — where we drifted / left things open

Honest reconciliation as of 2026-07-16:

| Finding | What happened | Action |
|---|---|---|
| **Built *ahead* of the board** | This session hardened the correctness **oracle + trust boundary** (ADR-0034/0036/0044) — a whole foundation the board never tracked as an issue. It's the *prerequisite* for safe autonomous org/enterprise, and it's done + adversarially hardened. | Record it as **Phase 0** (below). The board undercounts what exists. |
| **Rabbit-hole (honest)** | The oracle change-relevance heuristic took **four** adversarial rounds; each found a name-collision variant. We got a solid stopgap and proved **coverage is the durable fix** — but it was a lot of spend on a static heuristic. | Stop polishing the heuristic; the coverage arc (Wave A) is the exit. Logged so we recognize the pattern next time. |
| **Done-but-open** | `#28` (onboard hosted API providers in the GUI) looks substantially delivered by **ADR-0014** (BYOM live model discovery). | **Verify against ADR-0014 / MR !168 and close** if shipped. |
| **Partially done, stale scope** | `#23` (evidence cache + work packets): the **within-run MVP shipped** (ADR-0003); only the *durable cross-run work-packet store* remains. | **Rescope `#23`** to the durable store only. |
| **Not tracked (gaps)** | The **coverage-oracle arc** and **PM session/context management** are core prerequisites with **no issue**. | **Create two issues** (Wave A). |
| **Vocabulary drift** | `#18` says "11-persona team"; the north star says "firm of teams." | Reconciled: the 11-persona org = the SWE *team*; the firm layer sits above it. |

## The plan (waves ← reconciled with the board's phases)

### Phase 0 — Correctness & trust foundation — *mostly DONE* (not previously an issue)
- **[done]** Trust boundary: deny-by-default tools + evidence gate; honest outcomes; tamper baseline; independent-oracle delivery gate (ADR-0020/0031/0034/0035/0036/0044).
- **[prereq]** Remaining: the coverage arc below turns the coarse oracle into a real one.

### Wave A — Foundations (now) — *the high-leverage prerequisites*
- **[arc] Run-conclusion reliability** (`#43`, ★ **owner priority 2026-07-17** — *ahead of resuming
  feature work; onboarding `#42` MR3/MR4 paused until this holds*) — target: **~99% of runs reach a
  clean terminal state** (deliver, or park honestly with an accurate reason) **without looping or
  thrashing** toward the iteration/escalation/recursion caps. Filed from two live `password_generator`
  runs: a false-ship without the proctor, and a thrash-to-park with it.
  - **[arc] Reliability scoreboard** (ADR-0053) — the arc's definition-of-done instrument. **DONE:**
    the MCB suite rollup now classifies each run's terminal outcome (`clean_deliver` / `honest_park` /
    `thrash_park` / `false_ship` / `crash`, `bench/reliability.py`) and reports a **clean-conclusion
    rate** = `(clean_deliver + honest_park) / runs` in the suite MD/JSON, the CLI, and the
    `history.jsonl` trend. Pure aggregation over existing signals (no new run-state, no migration).
    **Next: run `mosaera-bench --all` to record the baseline**, then measure-then-fix the top offenders
    below until the rate holds ≥99%.
  - **[arc] Already-satisfied conclude** (`#44`, ADR-0052, **red-team: done**) — a task already met
    before any code made the Proctor's suite green pre-impl → `oracle_unverified` park → 138 calls /
    1.2M tokens of thrash then a `supervise` give-up mislabeled "beyond what I can complete."
    **DONE (this MR, `fix/autonomous-conclude-not-park`):** when the authored suite is green-pre-impl AND
    a NON-skipped test asserts something real (`already_satisfied`), the run concludes EARLY + HONESTLY —
    `route_after_capture` no longer gives up over a degraded-plan escalate (a genuine coder hand-raise
    still wins via `coder_escalated`), and the reason reads "appears already satisfied — confirm." It
    **does NOT auto-deliver**: it parks on `oracle_unverified` for a human (autonomous → honest
    `incomplete`), landing in the scoreboard's `honest_park` (clean) bucket. **Red-teamed (3 agents):**
    the first cut auto-delivered a guarded tests-only diff but that FALSE-COMPLETED unmet tasks
    (wrong-target/skip-xfail green) + the subset guard leaked (`__pycache__`/renames via `git add -A`) →
    dropped the auto-deliver + guard, fixed the escalate-swallow, excluded skip/xfail from the floor.
    **Deferred to the #44 successor MR:** bound the Proctor's red-hunt (stop authoring files once it can't
    obtain a red), trip the breaker early on a degenerate/repeated plan, and benchmark-seed hygiene.
  - **[arc] Whole-suite validation** (`#45`, ADR-0054, **red-team: done**) — validation ran only
    `tests/` and shipped green while a root-level `test_*.py` never ran and regressed → false-green ship
    (the scoreboard baseline named `false_ship` the TOP offender: 3 of 4 failures — MCB-05/09/10).
    **DONE (`fix/whole-suite-validation`):** `_pytest_plan` now runs `pytest -q --import-mode=importlib`
    — pytest's OWN config-driven discovery from the root (no hard-coded `tests/`, no synthesized paths),
    honoring the repo's `testpaths`/`python_files`. A scope fix, not a new oracle — a caught out-of-scope
    regression parks; `strength="suite"` unchanged. **Red-teamed (3 agents):** the first cut synthesized
    explicit path args, but that OVERRODE `testpaths` (false-park on committed examples/vendor), read a
    300-capped listing (false-ship on a truncated big-repo suite), and collided on duplicate basenames →
    reverted to config-driven bare pytest + importlib; end-to-end proofs added. **Proof: re-baseline
    `mosaera-bench --all`** and confirm the 3 false-ships convert + the clean rate rises from 83.3%.
  - **[arc] Drive to ~99% + live demo-repo validation** (`#49`, **decomposed 2026-07-17** into
    `#51`/`#52`/`#53`) — the next reliability push. Target: clean-conclusion holds **≥~99% denoised**
    (`repeat=3`) with `false_ship`/`thrash` → ~0, and each demo shape concludes honestly on the webUI.
    **Shared prereq — `repeat=3` denoise:** `mosaera-bench --all --compare` already runs repeat=3; the
    "thrash case moving run-to-run" is **LLM variance, not seed pollution** (each bench run is
    `run_id`-isolated: own seed + workspace, `memory=None`), so repeat=3 *is* the denoiser — it grounds
    the true baseline (91.7% was a noisy repeat=1). **Build order:** denoise → `#51` → `#52` (red-team
    gate) ; `#53` in parallel (disjoint files).
    - **[arc] Thrash reducer + sensitivity dial** (`#51`, #44-successor, **ADR-0056**, **no red-team**) —
      **DONE** (branch `feat/thrash-reducer`). Reframed by the owner around a **model-strength sensitivity
      dial** `reliability_sensitivity` (`cautious`/`balanced`/`persistent`, default balanced) that scales
      EVERY self-stop budget at one `dataclasses.replace` seam in `build_graph` (idempotent; applied in
      `recursion_limit_for` too; within `max_iterations_ceiling` so ADR-0046 composes). Plus: (1) a
      **plan-level breaker** — a fallback/identical plan at `plan_stall_limit` sets `plan_unworkable_reason`
      and `route_after_plan` sends it to the gate BEFORE design/implement → an **honest EARLY park**
      (`honest_park`, not the late `supervise` give-up `thrash_park`); a genuine `coder_escalated` still
      reaches supervise; (2) **Proctor red-hunt bound** via `ToolCallLimitMiddleware(write_file)` at
      `tester_file_cap`; (3) a **classifier measurement fix** — `classify_outcome` reads `final["iteration"]
      >= max_iterations` (the gate's `iteration_limit` reason parks-then-never-commits, so a ride-to-cap
      mis-bucketed as honest_park); (4) bench-seed teardown. Domain: `graph/{build,nodes_plan,state,nodes_review}`
      · `config/{_knobs,_settings}`+`settings_store` · `agents/{tester,agents_bridge}` · `bench/{reliability,cli,harness}`
      · `apps/api/.../runner/_base`. Deterministic + safe; de-risks `#52`.
    - **[arc] Oracle gap → autonomous oracle posture** (`#52`, **ADR-0057** + TM-0001, **red-team:
      DONE**) — **DONE + red-teamed** (blocked-by `#51` ✅). The trace REFUTED the
      "obvious" fix: the persistent `false_ship` (MCB-09) is a bug fix on lines the seed tests EXECUTE but
      don't ASSERT — deterministic coverage+mutation alone can't catch it (coverage credits executed lines;
      the single mutation is fooled by an unrelated test) and would PARK correct additive work (MCB-10).
      The durable fix is the **Proctor's authored asserting test** (ADR-0020), already ON for real
      autonomous API runs but run OFF in the benchmark → 91.7% measured a weaker oracle than ships.
      Decision (owner): **layered OR-oracle** (keep the gate's OR structure, ACTIVATE the supports) +
      **autonomous-only**. **Enable-not-rewrite:** `apply_oracle_posture(settings)` (`config/_posture.py`)
      flips the five knobs when `autonomous_verified`; `_verify_overlay` delegates + the **benchmark
      applies the same fn** (so scoreboard↔production can't drift; `MOSAERA_AUTONOMOUS_VERIFIED=0` = the
      pre-#52 A/B baseline). NO gate/oracle/policy/graph edit. Domain: `config/_posture` (+`__init__`) ·
      `apps/api/…/factory` · `bench/cli`. **Red-team DONE (3 agents):** 3 FIX-NOW — resume rebuilt
      oracle-less (`_rehydrate` RunSubmit missing `autonomous`, could auto-ship a parked run on restart);
      the mutation check crashed-to-`error` instead of parking (missing `try/except`); and **gap-fill is a
      confirmation oracle** (it ratifies delivered behaviour → a coverage-credited ship) so it was REMOVED
      from the posture — an uncovered change now parks. **STOP-rule tripped** on the executed-but-unasserted
      MCB-09 class (recurred across all lenses) → escalated to the **successor** (a Proctor-hard-gate /
      stronger mutation-coverage oracle), do NOT patch the supports further. Then re-baseline.
    - **[prereq] Oracle successor (Proctor-hard-gate + stronger mutation)** — the deferred MCB-09 class:
      require a red-verified asserting suite to ship in autonomous (strictness could scale with the `#51`
      sensitivity dial), a union/stronger mutation set, non-pytest (TS/JS+SQL) oracle. Small follow-ups: a
      mutation file-cap (cost), a `mosaera run --approve-all ⇒ apply_oracle_posture` hook.
    - **[arc] The Proctor validates/repairs tests + reactive test-review park** (`#54`, child of `#51`/`#43`,
      **ADR-0058** + TM-0001, **TRUST-BOUNDARY → red-team DONE**, MR !269) — **BUILT + RED-TEAMED** (branch
      `feat/proctor-validates`). The repeat=3 re-baseline is **thrash-dominated (~46%)**: the local coder
      can't satisfy an acceptance test — either **(a)** a bad/over-strict/wrong test nobody may fix, or **(b)**
      a faithful test the weak coder can't pass. Owner steer: the **Proctor (Tester role) OWNS the tests** and
      may validate/repair a bad one, but ONLY before the coder runs (**coder-blind ⇒ ungameable**), NOT a new
      role. **(a) Proactive:** Tester gains `edit_file` (CODEOWNERS; still `tests/`-confined, still NO
      `delete_file`); `author_tests_node` → `_proctor_validate_repair` repairs unfaithful/over-strict +
      strengthens weak tests vs the SPEC. Its edits to **pre-existing** tests get an actor-scoped,
      content-pinned excuse (`proctor_edits` in the guard's integrity hash space — fixes the gap_fill CRLF
      bug); a coder re-weakening/deletion/out-of-space hash still trips; a `proctor_edits` run vouches only on
      a PROVEN mutation-catch (`is True`). Mutation FEEDBACK is post-impl → NOT in the coder-blind pass
      (relaxes + assertion-floor only); the strengthen hook is **Phase-2**. **(b) Reactive:** on a genuine
      test-kind PARK, `react_on_bad_test` runs a TOOL-LESS `diagnose_test_review` (reviewer model, NO tools) →
      a `test_review_needed` NOTE + park for a human (`_termination_reason` surfaces it); **ZERO write
      authority**. Plus a bench-only `cloud_tier_allowed` confound fix. Two knobs (default OFF, ON in the
      posture → 6 knobs). Domain: `policies/allowlist` · `graph/nodes_plan`/`nodes_impl`/`nodes_review` ·
      `testintegrity` · `agents_bridge` · `agents/prompts`+`personas/tester` · `config/_from_env`+`_posture` ·
      `runner/_base` · `bench/cli` · `oraclecheck` (floor). **Red-team DONE (2 rounds, 7 agents): 3 FIX-NOW
      fixed** — a Proctor **gutting/emptying** a pre-existing test was self-excused → shipped wrong code (fixed:
      builder assertion-floor gate + consumer EMPTY-content-always-tampering); the repair **re-ran post-impl on
      a gate-deny re-plan** (coder-blind violated) → gated to the first pass (`iteration<=1`); the assertion
      floor was **reachability-blind** (nested-uncalled/dead-branch/lambda/empty-parametrize) → made
      reachability-aware. **STOP-rule tripped** (gut-a-test class R1→R2) → the residual **partial weakening that
      still asserts** (sibling catches the single whole-suite mutation) escalates to the successor below.
      **Next:** re-baseline (`tester_repairs_tests` on, `MOSAERA_MODEL_ESCALATION=0`) → thrash →
      (clean|honest_park); Phase-2 post-impl mutation-feedback strengthen; provider-aware `cautious` default.
      **Slice 0 — acceptance spec-lint at the decompose boundary (ADR-0073, 2026-07-22) DONE** (branch
      `feat/backlog-spec-lint`; from the #53 backlog-drive findings): upstream of the Proctor entirely —
      deterministic lint (`spec_lint.py`: exact-value over-specification / refactor-phrase collision via
      `preservation_matches` / near-duplicate Jaccard) on freshly-decomposed items → ONE bounded
      `curate_backlog` pass → the deny-by-default applier; `backlog_spec_lint` default ON + a
      `_DECOMPOSE_SYSTEM` doctrine sentence. Fixes the SPEC before tests are pinned to it (the #53
      exact-tuple thrash + redundant-item classes); no trust-boundary touch, no red-team. The #54
      escalation confound (cost $0) was resolved the same day: the ladder targeted an unpriced
      `claude-sonnet-5` (`cloud_tier_allowed` refuses unpriced cloud) and no tester ladder existed —
      settings-fixed; NOTE `role_escalation` still has no UI/API write surface (UI backlog).
      **Slice-0 follow-up (2026-07-22): both validation-drive findings closed** — R4 `no_behaviour`
      lint rule + doctrine (existence-only scaffolding acceptance can never earn oracle credit;
      recuration-path linting = residual) and retry-on-empty in `robust_invoke` (local models
      intermittently return a fully empty reply; only exceptions retried → decompose silently
      collapsed to the single-item fallback). ADR-0073 addendum.
    - **[prereq] Dynamic per-repaired-test verification** (the #54 red-team successor; folds into the #52
      **Proctor-hard-gate** successor) — a STATIC assertion floor can't prove a repaired pre-existing test still
      catches its requirement at runtime (a runtime-opaque non-executing assert passes any static check). The
      durable fix is DYNAMIC: run the repaired test under coverage to confirm its asserts execute, and/or a
      per-requirement mutation that verifies the repaired test specifically still catches a mutation of the code
      it covers (require a red-verified asserting suite to ship, strictness scaled by the `#51` dial). Kills the
      executed-but-unasserted / partial-weakening class for BOTH the authored-oracle (#52) and the Proctor
      test-repair (#54) paths at once.
    - **[arc] Coder reliability toolkit** (`#55`, successor to `#51`/`#54`, **ADR-0059** + TM-0001,
      **TRUST-BOUNDARY → red-team DONE**) — **BUILT + RED-TEAMED** (branch `feat/coder-toolkit`). The re-baseline left
      `thrash_park` ≈ 45% FLAT: #54 fixed the *bad-test* half; the dominant remainder is the coder **flailing
      blind** (MCB-01, a trivial todo-CLI, 3/3 thrash ~11 min: built the app but couldn't match a one-space
      output detail, wrote 7 debug scripts into `tests/`, never converged). Four deterministic levers (owner
      scoped: toolkit now, honest-stop next): **(1)** `sandbox_exec` READ-ONLY probe (`python -B -c` via a new
      `readonly_work` Docker `:ro` mount + writable `/tmp`, network-off → observe behaviour, can't persist →
      no write-gate/tamper bypass; subprocess fails closed; CODEOWNERS allowlist + AGENTS.md + capability drift
      + `coder_repl_enabled`) — the trust-boundary piece; **(2)** `pytest -q -o verbosity_assertions=2` so a
      FAILING assertion shows the FULL expected-vs-actual (plain `-q` truncates it) — the MCB-01 fix, zero
      extra cost (beats a targeted `-vv` re-run); **(3)** diagnose-before-edit — `fix_instruction` requires a
      `HYPOTHESIS:` before editing + a convergence line from new `progress.parse_failing_count`
      (`coder_diagnose_loop`); **(4)** acceptance-test BODIES in the coder handoff (not just names). Domain:
      `sandbox/*` (readonly_work) · `tools/repo/factory`+`_capabilities` · `policies/allowlist`+`AGENTS.md` ·
      `languages/python` · `graph/instructions`+`nodes_impl`+`nodes_plan`+`nodes_reason`+`state` · `progress` ·
      knobs · `agents/prompts`. **Red-team DONE** (3 agents incl. a live-Docker battery, no security break;
      1 MED fixed = a hard total-probe cap for the digit-stripped identical-snippet weakness, 1 LOW accepted).
      **Next:** re-baseline → measure thrash↓ / clean_deliver↑ (watch MCB-01/05); then the honest-stop
      companion below.
    - **[arc] The honest-stop + lean engine** (`#56`, **ADR-0060** + TM-0001, the #55 successor — **BUILT,
      red-team on the P3 demotion + re-baseline pending merge**) — the "get all thrash gone" other half,
      shaped by the 5-agent engine deep-dive (2026-07-18: seven mechanisms BOUND loops, zero CONCLUDE them;
      the supervise give-up itself set `stalled` → auto-thrash). **(P1 lean)** deleted `gap_fill` (posture-
      excluded confirmation oracle) + `react_on_bad_test` (an LLM call that only reworded a park note) — 2
      knobs gone, RunState net −1. **(P2 honest-stop)** `bump_progress` BEST-SO-FAR failing-count breaker
      (catches 5→6→5 oscillation; K = `stall_limit`, NO new knob → the #51 dial scales it) → budget-aware
      ladder (reason pass → NEW `test→supervise` edge with the deterministic diagnosis: count trend +
      trapping test names → give-up) → **`give_up_reason`** (the `plan_unworkable_reason` pattern
      generalized; `stalled` stays False; always strictly below the cap) → `classify_outcome` buckets it
      `honest_park` BY CONSTRUCTION — the classifier is FROZEN (honesty by stopping earlier, never by
      relabeling). Give-up honesty covers ALL supervise origins (a believed hand-raise was always the
      honest_park spec). A give-up park still diagnoses `coder` → the ADR-0016 escalation re-run fires on
      exactly these parks. **(P3 oracle demotion — CONSIDERED, red-teamed, DEFERRED)** demoting the per-run
      cost layers (coverage out of the posture; mutation proctor-scoped) was built and **reverted**: the
      red-team (claim A) reproduced end-to-end that it reopens the **executed-but-unasserted park→ship
      channel** on the standing/authored path (a park→approve flip on reviewer silence; fires on every
      gate-deny re-plan, not just Proctor flake) — the class the #52 red-team already STOP-ruled.
      Correctness-first: the oracle keeps FULL strength (`oracle_coverage` + unscoped mutation in the
      posture); the demotion rides with the dynamic per-test verification successor (which makes it safe).
      **So #56 makes NO trust-boundary change.** **(P4)** re-baseline matrix A (esc OFF, repeat=3,
      false_ship 0-1 gate) + B (esc ON, local qwen2.5-coder:32b ladder, repeat=1 smoke) — the first
      measurement of the REAL product config.
    - **[arc] The honest-stop projected-non-convergence breaker** (`#65`, **ADR-0067**, direct successor
      to `#56`/ADR-0060 — **BUILT**, no red-team: graph routing + an honest field around the gate, like
      ADR-0060) — the local baseline surfaced the #1 remaining thrash cause the best-so-far breaker can't
      see: the **slow crawl** (12 → 11 → 10 → … always beats its best → the streak never trips → rides to
      the cap as `thrash_park`, chasing a bar it can't clear in budget). **(1)** `progress.wont_converge`
      — a pure, conservative optimistic-average-rate projection (`current/avg_rate > remaining`;
      `min_history=3`, requires net progress so it never fights the streak breaker / never trips a
      converger). **(2)** a **projected trip FORCES give-up, never a re-scope** (a crawl's re-scope only
      re-thrashes): it skips the reason-pass rung and carries a `projected` flag on `progress_trip` that
      `supervise_node` reads to override the autonomous "re-scope" → `give_up_reason`/`stalled=False` →
      `honest_park` strictly below the cap (the two trip kinds mutually exclusive; the reason string
      distinguishes "improving too slowly" vs "non-improving"). **(3)** `honest_stop_projection` knob
      (default ON) + `MOSAERA_BENCH_HONEST_STOP_PROJECTION_OFF` A/B lever; classifier FROZEN. **Next:**
      the repeat=5 local baseline (qwen3 + scaffold + honest-stop, esc-OFF) lands the thrash delta.
    - **[arc] Honest-stop for the GATE / re-plan loop** (`#67`, `#65`/`#56` successor; run-reliability arc
      `#43`; **NOT a trust-boundary change** — routing + an honest field around `evaluate_gate`, like
      ADR-0060; downgrade-safe: can only turn a would-be thrash into an honest park, never a park into a
      ship). The repeat=5 baseline exposed the honest-stop's blind spot: `#56`/`#65` conclude the **test-fix
      loop** (failing-count breaker), but the DOMINANT residual thrash lives in the **gate-deny → re-plan
      loop** — validation never greens (or the reviewer objects) → the gate denies → re-plan → re-author →
      repeat → ride to the iteration cap as `thrash_park` (**MCB-11 confirmed:** no give-up fired,
      `termination_reason` empty, hit the cap). That loop has NO honest-stop equivalent — only the iteration
      cap and `plan_stall_limit` (identical/fallback plans only) bound it. **Build:** a gate-loop progress
      breaker — track gate-deny/re-plan cycles; after N cycles with the gate never approving (or validation
      never going green), conclude HONESTLY (`give_up_reason`, `stalled=False` → `honest_park`) strictly
      below the cap — the `#56` pattern applied to the gate cycle — with a reason that NAMES the cause ("the
      acceptance suite I authored rejects work I can't further improve"), which also FEEDS `#66` (a
      false-red-on-correct-code signal). **Converts the residual false-park thrash to clean-conclusion NOW,
      before the oracle is perfected** — the fast, cheap Reliability-gate win (`#66` is the deeper
      Correctness-gate delivery fix; the two are complementary and disjoint enough to run in parallel, `#67`
      first). **Domain:** `packages/core` graph (`nodes_plan`/`nodes_review` routing + a gate-cycle counter
      in RunState/`progress.py`); minimize `graph/build.py`/`graph/state.py`. **blockedBy:** none. **Measure:**
      `thrash_park`↓ / `honest_park`↑, clean-conclusion↑, no new `false_ship`.
      - **[prereq] Thrash-cause instrumentation** (the diagnostic that DECIDES the `#66`-vs-`#67`-vs-
        scaffold-fix priority; bench-measurement only, **not a trust-boundary change**, no ADR — extends
        the ADR-0053 scoreboard) — **BUILT (Phase 1).** The `#65` baseline settled ~59% (below `#56`'s
        65.3%) with ~89% of parks being CORRECT code the engine rejected, but *why* each run thrashed was
        **invisible** (the scoreboard recorded `outcome` but not `iteration`/gate-reasons/`stalled`), so the
        cause was inference. A capability scan hinted the mass is refactor+scaffold (12 runs, a likely
        regression from the just-shipped scaffold) + Proctor over-strictness (`#66`), NOT the gate-deny loop
        `#67` targets. Ships a pure `classify_park_cause(final, max_iterations)` sibling to
        `classify_outcome` (`bench/reliability.py`) that NAMES the terminal mechanism 1:1 with the bucket
        (`give_up`/`plan_unworkable`/`stalled:<kind>`/`iteration_limit`/`rode_to_cap`/`parked`) + additive
        scoreboard-meta fields (`thrash_cause`, the full `gate_reasons`, `iteration`, `stalled`,
        `stall_reason`, `give_up_reason`, `plan_unworkable_reason`). Classifier FROZEN (adds a diagnostic,
        never changes `classify_outcome`). **PAYOFF (it worked immediately):** the instrumented split
        named ONE self-inflicted cause for ~100% of the thrash → **ADR-0068** below.
      - **[prereq→BUILT] Tamper-guard false-positive fix — author tests ONCE** (**ADR-0068**, the #1
        thrash lever; **RED-TEAM-REQUIRED** — tamper/integrity surface). The `thrash_cause` split was
        decisive: every instrumented `thrash_park` stalls at iteration 2 with `stall_reason="pre-existing/
        protected tests … were modified"` naming an **engine-authored** test (the scaffold's
        `test_refactor_golden_*` / a Proctor `test_*`) on code the hidden grader confirms CORRECT — NOT
        the `#66`/`#67`/scaffold-false-red split we inferred. **Root cause (nailed by capturing the golden
        test at authoring vs check — two earlier hypotheses, run-once then CRLF, were REFUTED by Phase-0
        live runs first):** the scaffold writes the golden test with `_CASES` in **single** quotes
        (`tests_baseline=hash(v1)`); the **hygiene gate** then runs `autofix`=`ruff format` on the run's
        changed files — the golden test is in that diff — so ruff rewrites its quotes **single→double**
        (same length, different bytes) → the baselined test's hash changes → `tampered_files` trips →
        `thrash_park`. The engine authors → formats → then flags its OWN format change. **Fix (Decision 1,
        dominant, MEASURED):** `hygiene_node` EXCLUDES `ctx.protected_tests` from autofix/lint (the oracle
        is the engine's, not the coder's code) → **MCB-13 4/4 `thrash_park` → `clean_deliver`/`honest_park`,
        MCB-14 too, tamper GONE**. **(Decision 2, defensive):** newline-normalize `hash_files`
        (`CRLF→LF`, matching `tampered_integrity`). **(Decision 3, correctness):** `author_tests_node`
        runs once + idempotent scaffold `_write` (stops a re-plan re-freeze tautology + trip). Guard
        protection UNCHANGED (a real coder edit still trips; only the engine's own reformatting/newline
        noise is ignored). **RED-TEAM DONE** (3 agents): **2 FIX-NOW fixed + re-verified** — the idempotent
        scaffold `_write` opened an oracle **pre-plant** hole (seed-predictable paths + untrusted repo →
        a planted weak file became the oracle; fix: `_write` OVERWRITES, run-once already covers the
        re-freeze) and `protected_tests` wasn't rehydrated on resume (fix: repopulate on the run-once
        return); hygiene/CRLF lenses all FALSE-POSITIVE (guard fires independently; `\r\n`→`\n` is a
        subset of CPython's own normalization). **Next:** a fresh esc-OFF baseline (expect thrash↓ hard,
        clean-conclusion back above 65% and beyond; `false_ship`≈0). Then `#66`/`#67` re-ranked.
      - **[arc→BUILT] The gate-loop honest-stop** (`#67`, **ADR-0069**; the honest-stop family's last
        uncovered loop; NOT a trust-boundary change). **MEASURED post-fix baseline: 55.9%→81.2%** (the
        tamper fix); the residual `thrash_cause` split three ways and only ONE is a clean fix: the
        gate-deny → `plan` loop had NO breaker (the #51 plan-breaker only trips on a fallback/identical
        plan), so a gate that keeps DENYING re-plans to the cap on CORRECT code (`rode_to_cap`) → thrash.
        (`stalled:plan` = the fingerprint-stall fallback ADR-0060 deliberately KEEPS as thrash — left
        alone; the tamper-gaming catch = trust-boundary + owner call — deferred.) **Fix:** `gate_node`
        deny path fingerprints the gate's blocking reasons and after `gate_stall_limit` **consecutive
        SAME-reason** denials (while `iteration < max_iter`) sets `give_up_reason`/`stalled=False` →
        `route_after_gate` finalizes → `honest_park` by construction. **Fingerprint, not raw count** — a
        CHANGED reason (progress through blockers) resets the streak, so a run still working toward a ship
        is never cut off (guardrail against parking shippable code). The named blocker FEEDS `#66`. Knob
        `gate_stall_limit` (default 2, dial-scaled). **Framing (owner-corrected): honest_park is the
        FLOOR, not the win** — if code is correct, autonomy means SHIP it; `#67` only catches the residue
        the oracle genuinely can't verify. **The real lever is `#66`** (a two-sided oracle that ships
        correct code it now denies → `clean_deliver`) — next.
      - **[arc→BUILT Phase A] The two-sided oracle: ship correct code the Proctor false-fails** (`#66`,
        **ADR-0070** Phase A; oracle-authoring surface → RED-TEAM-REQUIRED). MEASURED: of correct code
        (grader Impl ≥85) that didn't ship, the dominant cause is the **Proctor authoring a WRONG test**
        (contradicts / over-specifies the spec) → the coder writes correct code, can't touch the protected
        test, parks `blocked: the test is wrong` (~9/48 ≈ 19% of runs; verbatim MCB-16#1 "test counts
        bool, task excludes bool", MCB-18#0). **Key reframe (from reading the code):** the catch mechanisms
        ALREADY existed and were ON in the baseline — `tester_repairs_tests` (#54) + `proctor_faithfulness_
        guard` (#57) — but the AST detector is SYNTACTIC (blind to a semantic spec-contradiction) and the
        repair turn is the **self-same weak Proctor reviewing its own tests**. **Phase A BUILT →
        RED-TEAMED → MEASURED → REVERTED (ADR-0070 SUPERSEDED, code removed 2026-07-21).** A held-out judge
        (the critic's different model) named authored-test spec-conflicts for the coder-blind repair turn.
        The A/B (DeepSeek-R1:32B judge, both arms → only the spec-review differs, repeat 3, $0) first
        exposed a **latent bug the red-team couldn't** — the review reused the critic AGENT, whose "judge
        the OUTCOME" persona made it silently INERT (0 conflicts, judged nonexistent code); caught ONLY by
        logging the raw judge output. ★ LESSON: measure-then-decide is not optional; static analysis
        (the red-team verified the wiring) can't see a runtime persona-override. Fixed (critic MODEL + a
        dedicated test-review prompt; live-confirmed it then named a real over-spec) — and the WORKING
        mechanism is **net-null-to-negative: 0 park→ship in 15 ON runs**, mild regression where it acted
        (MCB-02), `false_ship` unchanged-by-it (the +1 is MCB-05 variance — a refactor case where the
        deterministic scaffold authors the tests so the review never runs). ★★ **STRUCTURAL LESSON: fixing
        the Proctor's wrong test — even with a strong judge — does NOT make correct code ship.** Correct
        code parks for DEEPER reasons (the gate can't confidently VERIFY it; planner budget; coder
        non-convergence). The whole LLM-judge oracle-authoring premise — **Phase A AND the more-aggressive
        Phase B (ship-despite-red-test)** — does not crack throughput on these models. **Phase B: NOT built
        (killed by the measurement).** The `_proctor_authoring` module extraction is KEPT (good refactor).
      - **[arc→BUILT behind knob] Comprehensive mutation — the deterministic per-behaviour gate** (`#74`,
        **ADR-0071**; the twice-deferred `catches-some ≠ enforces-all` killer, escalated by #52/#54 and now
        the #66 measurement). The mutation check (ADR-0049/#39) made ONE mutation/file and returned True on
        the FIRST catch → a change with multiple behaviours could hide a SECOND executed-but-unasserted
        region (the MCB-09 false_ship). **BUILT:** `oracle_mutation_comprehensive` (default OFF, needs
        `oracle_mutation_check`) — mutate EVERY eligible construct in the changed region (cap 20), require
        the suite to catch ALL; any survivor → downgrade. Deterministic, judge-INDEPENDENT, downgrade-only,
        fail-closed, byte-revert. `oraclecheck` 496→334 (mutation → new `mutation.py`); tests prove
        comprehensive catches a 2nd region single misses. Gates green. **Honest limits:** doesn't catch a
        DROPPED requirement (no code to mutate); **parks more** (equivalent mutant → false park) — the
        safety/throughput trade, safe direction. **NEXT (DoD): red-team the gate evidence + A/B
        (`MOSAERA_ORACLE_MUTATION_COMPREHENSIVE`) to quantify false_ship↓ vs extra parks BEFORE the posture
        activates it** (mirrors the #60/#66 measure-first discipline). It prevents wrong-ships; it does not
        by itself ship more correct code (that axis is model-capability-bound — a stronger/cloud coder).
      - **[arc] Structural-spec oracle — refactor tasks with a structural acceptance criterion** (`#80`,
        owner 2026-07-21; the MCB-05 false_ship class — a SIBLING of #74's executed-but-unasserted class
        → RED-TEAM-REQUIRED, feeds `oracle_verified` + #76). **Diagnosed (15/15 deterministic, both
        surviving workspaces):** MCB-05 asks for a behavior-preserving refactor into a SHORT orchestrator
        (≤6 stmts) delegating to ≥3 helpers; the engine delivers behavior-preserved + 3–4 helpers but a
        **7–8-statement orchestrator** (leaves the `if member:` branch inline) → fails the one structural
        check `test_checkout_total_is_a_short_orchestrator` → impl 88 = 7/8 → **false_ship**. The refactor
        oracle (behavior-preservation golden-master) verifies BEHAVIOR but has NO check for the STRUCTURAL
        shape the task requested — a criterion with **no behavioral signature**, so #74 comprehensive
        mutation cannot catch it (nothing to mutate; behavior is perfect). A MILD false_ship (correct +
        well-decomposed, misses a precise structural bar by 1–2 statements) — but a lie by the contract.
        **Fix — two-layer, SEQUENCED so the contract can't break.** **Phase 1 (Layer-1 floor — first +
        red-teamed + measured):** a DETERMINISTIC structural check for refactor/structural tasks — extract
        the structural asks from the brief (explicit `≥N helpers`/`≤N lines` deterministically; soft
        `short`/`a handful` via a bounded body-length mapping), verify the delivered AST, and
        **deny-by-default: unmet OR unverifiable ⇒ downgrade `oracle_verified` ⇒ honest_park** ("refactor
        didn't reach the requested orchestrator shape"). This alone moves MCB-05 false_ship → honest_park
        (the reliability win). **Phase 2 (Layer-2 conversion — stacks on top):** on a structural miss, a
        BOUNDED iterate — feed the coder the named gap ("orchestrator is 7 stmts; fold the member branch")
        → retry → **re-run the SAME Phase-1 gate**; success → gate-verified `clean_deliver`, exhaustion →
        falls through to the Phase-1 park. **CONTRACT-SAFE BY CONSTRUCTION: the deterministic gate stays
        the SOLE ship-authority — Phase 2 adds ATTEMPTS, not authority; the iterate loop can only ever
        produce a gate-verified ship or an honest park, never a false_ship.** **The 'don't miscalculate'
        guardrail (measure-first, #60/#74 discipline):** the soft-constraint bound risks OVER-PARKING good
        refactors (trading false_ship for false-park — still honest, but costs delivery) → an A/B across
        ALL refactor + the clean 22 must confirm it kills MCB-05's false_ship WITHOUT over-parking BEFORE
        it enters the posture; if the soft bound over-parks, loosen it + log MCB-05 as a measured residual
        rather than break the contract. The floor (explicit constraints, deny-by-default) is safe
        regardless; only the soft-bound aggressiveness is the measured dial. Files: a new
        `structural_spec.py` (extract + AST check) + refactor-oracle wiring (`oraclecheck`/`graph/nodes_*`)
        + a knob (default OFF, posture-HELD until measured) + the Phase-2 iterate route. Own ADR +
        threat-model note. NOT #74 (different class); FEEDS #76 (the disposition harness).
        **★ Phase-1 BUILT + A/B + RED-TEAM DONE (2026-07-21, ADR-0072).** Target A/B: MCB-05 x5 clean
        flip false_ship→honest_park 5/5. Over-park A/B: MCB-15 confirmed over-park (a correct impl=100
        delivery parked; no-ask controls MCB-13/14 = true no-op). **Red-team (3 lenses) tripped the
        STOP-rule:** the soft `len(fn.body)` "short orchestrator" check is unsound BOTH ways — over-parks
        (MCB-05 ≤6 vs MCB-15 ≤7 for IDENTICAL language, no fixed `_HANDFUL` works) AND is defeated by one
        level of nesting / class-methods / a same-named decoy file. **Crash FIX-NOWs DONE** (broadened the
        `ast.parse`/`_num` guards, regression-tested). **Disposition: DEFER the soft body-check (drop
        `_SOFT_BODY`/`_HANDFUL`); keep only a hardened helper-count check** (explicit min_helpers, recurse
        ClassDef, count `self.x()`, worst-verdict-across-files). **MCB-05 → DEFER residual** (fuzzy body-bar
        indistinguishable from MCB-15's from the brief — the deterministic cousin of #66's dead-end). Bench
        inconsistency flagged (MCB-05 ≤6 vs MCB-15 ≤7, identical asks). **Reliability-mode (owner): keep ON
        for the reliability climb** (over-park is free for clean-conclusion; converts MCB-05 false_ship →
        honest_park); soundness debt deferred to Layer-2/#76 at maturity; NOT posture-activated as built.
      - **[arc→PARKED] Residual-thrash arcs — the last ~3pp to ~100% clean-conclusion** (diagnosed
        2026-07-21; **PARKED by owner 2026-07-21** — ~97% honest-on-suite is a fine maturity signal; the
        real leverage is Layer-2/Quincy, not the last two points. Both are ALREADY-DEFERRED doctrine
        cases, NOT quick relabels). (a) **`#81` non-pytest convergence
        signal** (the ADR-0060 "measured follow-up"): MCB-26 (`kind=sql` greenfield, impl=100) stalls on
        SQL validation with NO pytest failing-count → the fingerprint-stall fallback sets `stalled=True` →
        thrash, which ADR-0060 DELIBERATELY keeps ("no count signal → relabeling flatters the metric"). Fix
        = a real convergence signal for SQL/node validators (a failing-count/assertion-count parser per
        language) so a genuinely non-converging non-pytest run concludes `honest_park` via
        give_up_reason/stalled=False, like #56 does for pytest. Own arc. (b) **`#82` tamper-caught
        relabel** (trust-boundary, owner call): MCB-22 (tamper — coder edited a protected `tests/test_calc.py`,
        impl=100) is caught + `stalled=True` → thrash; relabeling a caught-cheating run as `honest_park`
        flips the ADR-0060 tamper security invariant (tamper sets stalled + early-returns so it can never
        reach supervise). Needs a security review + a compensating route guard before any relabel — the
        `#67`-plan-deferred case. Until these land, clean-conclusion ceilings at ~97% (via #80) on this suite.
      - **[arc] Quincy-layer post-run disposition — park→ship OUTSIDE the graph** (`#76`, owner insight
        2026-07-21; the ARCHITECTURAL home for #66's goal → RED-TEAM-REQUIRED, feeds `oracle_verified`).
        Many `honest_park`s are impl-correct code the oracle simply couldn't VERIFY (the cautious dial
        parks some shippable work early — honest_park is the FLOOR, not the win). Instead of adding more
        nodes/breakers INSIDE the run graph (fights de-god-filing, grows `graph/build.py`, adds coupling),
        the run concludes and emits its full evidence + the `give_up_reason` naming the exact unverified
        blocker (#56/#65/#67 were BUILT to be this input); then **Quincy, at the orchestration layer
        (hub-and-spoke north star), disposes**: (a) **close the named gap deterministically** — author the
        missing asserting test for exactly the flagged behaviour, re-run the REAL sandboxed oracle → green
        ships VERIFIED, red stays parked; or (b) **escalate** the named blocker — stronger/cloud model, or
        a human one-click/posture approval. **Hard invariant: NEVER an LLM green-light override** — that is
        the ADR-0070 LLM-judge dead-end reintroduced + a false_ship hole; the deterministic gate still
        makes the ship call, Quincy only PRODUCES the missing proof (capability-through-verification —
        prove the output at the door, a workbench not a straitjacket). Bench `impl=100` exists only via the
        held-out grader; a real repo has none, so "which parks are correct" IS the oracle problem, correctly
        relocated to the orchestration layer (win bounded by re-verify/escalation quality, not Quincy's
        confidence). Depends on: the reliability arc (honest-stop reasons) + the Quincy orchestration seam.
        Own ADR + red-team when built.
        **★ MVP BUILT + MERGED (2026-07-22, ADR-0074; knob `disposition_gap_close` default OFF; red-team
        DONE + bench DoD DONE 2026-07-23).** The `oracle_unverified` convertible class only: a new leaf
        `packages/core/mosaera_core/disposition.py` `close_oracle_gap` (author → assertion floor → green
        on the delivered tree → comprehensive mutation ADR-0071 → `verified` ships, else stays parked —
        deterministic ship authority, the model only authors, the ADR-0070 successor) + a sweep rung
        `_try_close_named_gap` in `_after` (between model-escalation and recurate/defer) that detects the
        convertible signal, reopens the parked clone WITHOUT reset (the diff is uncommitted — disposition
        runs in place), and on `verified` commits + `in_review` + per-item MR + advances. The escalate arm
        REUSES the existing model-escalation rung (ADR-0022) + the pause-and-surface human fallthrough
        (posture UI = #46/#48 territory). **RED-TEAM DONE (2026-07-22, pre-merge, 4 refute-agents;
        ADR-0074 §Red-team): claim BROKEN → 8 FIX-NOW fixed + adversarially re-verified** (convertible-
        signal honest-stop bypass; mutation-source authored-file leak; release-before-dispose reset
        race; empty/tests-only ship; unguarded gap-closer silent-halt; unguarded status-mark duplicate;
        baselined-test-edit laundering; spec-nudging prompt). DEFER-TO-SUCCESSOR #74 (non-mutable region
        free-ride); ACCEPT (who-tests-the-test residual — bounded by tester independence). **BENCH
        LAYER-2 MEASURED (2026-07-22, real qwen3-coder tester + Docker): conversion 5/5 on correct
        parked code, FALSE-SHIP 0/7 on wrong code** (`observed-outcomes.md`) — the spec-anchored
        authoring caught wrong code every rep. Both DoD gates (red-team + bench) DONE → ready to
        merge; full-bench conversion hook over the MCB corpus is follow-up instrumentation.
        **★ ADR-0075 WIDENING (2026-07-23, from the 4-lens deep dive; red-team DONE, 2 rounds):**
        the full-MCB Layer-2 drive found the MVP's `oracle_unverified` class barely forms in the
        accepted config — the measured convertible pool (44% of runs hold hidden-grader-PERFECT code
        that doesn't ship; 16/34 parks = give_up ALL grader-100) lives in the **engine-blocked
        give-up**: the run gave up because the ONLY failing tests were the ENGINE'S own
        authored/protected oracle (≥11/16 reasons name a wrong authored test; some unsatisfiable by
        any correct code). Second convertible class `is_engine_blocked_give_up` (deny-by-default:
        give_up only + every other honest-stop channel quiet + failing set ⊆ engine-owned tests,
        empty ⇒ not convertible) + **supersession** (delete the trapping engine tests — retract,
        never repair) + the unchanged `close_oracle_gap` gate + a post-verify WHOLE-SUITE green
        check. Same knob, still default OFF. Counterfactuals priced: balanced dial dominated (0
        conversions, 3.3× tokens), tester-off catastrophic (false_ship 5/105), repair
        measured-dead twice (ADR-0070/MR-C). #54-as-a-role re-confirmed dead (roadmap's own "NOT a
        new role" + ADR-0058 rejected-options). Sibling fix: the scaffold arming bug (MCB-11) —
        task-only arming, see the #60 arc note + ADR-0072.
        **RED-TEAM DONE (2 rounds, 2026-07-23; ADR-0075 §Red-team; STOP rule tripped on both classes).**
        R1 broke it (a reproduced false-ship: supersession deleted a `proctor_edits` baselined HUMAN
        test → wrong code shipped by green-by-omission) → 5 FIX-NOW fixed. R2 re-attacked: the
        delete-a-human-test class RECURRED via a new route (a baselined test leaks into `authored_tests`
        when the run's tester edits it in the first authoring turn) → **closed at the source with a
        POSITIVE ALLOWLIST** (supersede only a path proven NOT in the pristine `integrity_baseline`/
        `proctor_edits`). The who-tests-the-test residual also recurred and is INHERENT (the blind spot
        is in the ACCEPTANCE, the shared input — so the held-out-tester mitigation is near-theater for
        the dominant case, and it fires on MUTABLE regions too) → **ACCEPT, escalated to the
        oracle-successor** (the deterministic per-requirement / acceptance-completeness verifier — the
        SAME successor #74/ADR-0071 + the ADR-0074 residual already name). Class 2 stays default OFF and
        is NOT recommended for enable ahead of class 1 pending that successor. **All MRs MERGED**
        (!293–!296 feature + red-team R1/R2; !297 DoD docs) and the **class-2 DoD measurement DONE
        (2026-07-23, 12 runs: 0 false-ships / 0 true conversions — the class barely forms; prevention
        carries the give-up slice, MCB-11 clean-delivered 3/3 via the scaffold fix)** — recorded in
        `demos/observed-outcomes.md` + ADR-0075 §Measurement. **#76 arc CLOSED.** NEXT LEVER chosen by
        owner (2026-07-23): the **independent security gate** (`#83`/ADR-0076, MR-1 built) — a different
        evidence dimension (product security), inserted AHEAD of the oracle-successor + the fat-cut wave
        (lazy coverage, dead `reviewer_advisory` knob, mutation-strength reconcile), which stay queued.
        **TWO-LAYER CONTRACT (owner framing 2026-07-21) — the north star crystallized.** The ENGINE
        (Layer 1) is a reliability machine whose output is a TWO-SYMBOL contract — `clean_deliver` OR
        `honest_park(reason)` — and **100% reliability = it is NEVER anything else** (never `false_ship`,
        never `thrash`, never uncaught `crash`). Killing the residual `false_ship`/`thrash` cases
        (MCB-05/MCB-26 today) converts them to **`honest_park`, NOT to `clean_deliver`** (the oracle
        catches the blind spot → park; the honest-stop closes the loop → park), so reaching 100%
        reliability *slightly LOWERS raw delivery, honestly* — reliability means every output is
        trustworthy, not that everything ships. QUINCY (Layer 2 = this issue, OUTSIDE the graph) then
        converts `honest_park`→`clean_deliver` per the disposition above; the residual truly-unshippable
        parks route to a human (posture). **Why Layer-1 reliability GATES Layer 2:** the park `reason` IS
        the contract surface — a noisy engine (thrashing / false-shipping) hands up untrustworthy reasons
        the harness cannot safely act on, so reliability is the ENABLER of the harness, not a parallel
        goal. **Metric split:** Layer-1 = **reliability** `1−(thrash+false_ship+crash)` (target 100%;
        structural, $0, model-independent); Layer-2 = **conversion rate** `verified-ships / total-parks`
        (the frontier — where model capability, oracle quality, and cloud COST live, spent per-park on
        demand, never on every run). The engine stops being where delivery is chased; it becomes the
        thing you TRUST, and delivery becomes orchestration on top.
      - **[sequence] Post-reliability go-forward order** (owner 2026-07-21) — gate on reliability
        **≥95% clean-conclusion at 120 (x5, esc-OFF)** → (1) **`#53` demo-repo validation** (real
        small/medium repos: prove the bench number generalizes off MCB + surface real UX/flow friction) →
        (2) **resume `#42` onboarding→map** (the substrate Quincy plans the backlog against; demo repos
        harden it) → (3) **Quincy wiring + `#76` disposition** (narrate the honest read —
        status/`termination_reason`/park-reason — and own the backlog/work-packet flow). Each feeds the
        next; matches the north-star arc order. Reliability (now) is the gate that makes the read
        trustworthy enough to build the operator surface on.
      - **[debt] Budget gate: in-flight node spend** (`#57`, filed 2026-07-22 from a live operator
        report). The soft-park/hard-cap check sits in the runner's stream-consumer loop and parks by
        blocking consumption — but LangGraph runs each node task in its own executor thread, so the
        CURRENT node's internal agent loop keeps calling the model while the run shows parked
        (measured: 406k→485k tok, 44→53 calls after the park; heavier nodes + armed cloud escalation
        made the old architectural hole visible AND expensive). Proposed in the issue: a call-boundary
        budget-gate callback (`on_chat_model_start` blocks on the resume event / raises typed
        cancellation) — overshoot drops from a whole node to one generation. Not scheduled; the
        runner's money guard, no CODEOWNERS paths.
      - **[debt] Engine lean-detailing pass** (`#77`, from the 6-agent teardown 2026-07-21). The audit
        VERDICT: the engine is NOT an amalgamation — 0 god-files, one-responsibility modules, DI seams,
        deterministic-first, the model-agnostic `get_chat_model` seam clean (zero bypasses), no ADR-0070
        remnants. So this is *detailing, not a rebuild* — rides with `#53` (disjoint, low-risk). **Safe
        tier:** CUT dead `bench/scorecard.py` `_PROCESS`/`_SIGNAL` constants (zero readers); RELOCATE
        `bench/escalation.py` → `mosaera_core.escalation` (the repo's ONLY product→bench import — apps/api
        imports it for live escalation; repoint + fix the "bench-only" docstring); WIRE-OR-DROP
        `compare.py` `critic_vetoes`/`behavior_preservation_runs` dead aggregates; SPLIT
        `tools/repo/factory.py` (475→~350, extract pure guards → `_guards.py`) before it crosses 500;
        SURFACE `reliability_sensitivity` in the UI (the #1 reliability lever, currently env-only) +
        `hygiene_unavailable` (write-only field → report-or-drop) + decide the dormant coverage-region
        ledger (written, never read — P3 impact-selection unwired); TIDY dead `plan_task`/`design_item`
        no-tool fallback, stale "five oracle knobs"→8 comment, `graph/__init__.__all__` gaps. **NOT in
        this pass — trust-boundary-adjacent, surfaced + light red-team separately:** CUT the DEAD
        `reviewer_advisory` knob (zero engine reads, an honesty-hazard next to gate policy; ADR-0029 →
        ADR-0034 supersession) and RETIRE `behavior_preservation_guard` once `refactor_oracle_scaffold`
        is measured correctness-neutral. **Guardrail held: none of the moves touch the protected wall**
        (breakers / gate / oracle pipeline / tamper / sandbox containment / frozen classifier).
    - **[arc] Live demo-repo validation** (`#53`, no red-team, no ADR) — parallelizable (disjoint new
      files). Author three seed repos — **greenfield** / **brownfield** (suite in `tests/` **and** root; an
      out-of-scope regressing change → expect a caught `validation_failed` park) / **script-kiddie
      spaghetti** (no tests, tangled, no pytest config — **no current MCB analog**) — a webUI runbook, and
      an observed-outcomes-vs-scoreboard writeup. Zero engine plumbing (CLI + `POST /projects`/`/runs`
      already drive arbitrary repos). Live-run after `#51`/`#52` land.
      **Full backlog-sweep drive DONE (2026-07-21, engine 0.6.0 @ `bf8b36c`)** — greenfield driven
      end-to-end (intake → decompose → autonomous sweep → operator remediation → re-run): 1 delivered /
      2 honest parks / 0 false-ship / 0 crash (`docs/demos/observed-outcomes.md`). **Findings dispositioned:**
      (1) `is_behavior_preserving` comparative-"same output as \<input path\>" false positive armed the
      #80 structural oracle on a feature task → **FIX-NOW** (pattern fix + ADR-0072 addendum, red-team
      pending); (2) Quincy decompose over-specifies acceptance + emits redundant items → **DEFER to #54**
      (spec-lint is the successor); (3) parked-run work unrecoverable (`/runs/{id}/patch` 404 on
      incomplete) → **[debt]** logged; (4) local-path projects can't `/merge` (GitLab-MR-only, item
      `branch` never recorded) → **[debt]** logged; (5) live escalation was dark — ladder targeted an
      unpriced model (`cloud_tier_allowed` refuses) and no tester ladder existed → **config fix** (priced
      `claude-sonnet-5`, tester ladder added; `role_escalation` still has NO UI/API write surface —
      UI-backlog item).
- **[prereq] Coverage-based oracle arc** (`#29`, Phase A) — runtime line coverage (code↔test map),
  a durable test ledger, change-coverage gate, and the token-saver. Unlocks the oracle **and** the
  project map **and** cheaper runs. → also NS-3-adjacent (the grader shares the exec seam).
  Phase shape `P0 → { P1 ∥ P2 } → P3`:
  - **P0 DONE** — `mosaera_core.coveragemap.CoverageMap` (two-way code↔test map) + scaffolding +
    sandbox image (!235/!236).
  - **P1 DONE** (`#29`, ADR-0049, !243) — the **change-coverage gate** in `packages/core`:
    `test_node` computes `change_is_covered`; the gate uses it to decide the standing-suite credit,
    replacing the import heuristic (opt-in; the heuristic is retained as the `None` fallback).
    **Red-teamed (2 rounds, 2026-07-16): four orchestration bugs FIXED** (a critical `analysis2`-cwd
    false-park, repo-config clobber, wrong interpreter, a diff-parser mis-count); **A1** (line
    coverage credits an unexecuted branch) DEFERRED to the mutation check — pair `oracle_coverage` +
    `oracle_mutation_check`; **A2** (test-named source bypasses coverage) logged below.
  - **P2 DONE** (`#32`, !244) — the **durable test ledger** in `packages/memory` (disjoint from P1):
    `coverage_ledger` table (Alembic **0014**) + `CoverageMixin` (upsert / impact-selection / rot
    detection) + churn-stable region fingerprints (`_fingerprint.py`), keyed by `file::qualname` +
    a normalized content fingerprint that survives line churn; `source_hash` drives rot. **Graph
    write-wiring (`test_node` → ledger) is a later integration step** (kept disjoint from P1).
  - **P3** (`#35`) — the **line→region adapter** (`coverage_regions.py`, part 1, merged) + the
    **`test_node` → ledger write-wiring** (part 1, merged) + the **gap-fill token-saver** (part 2):
    a `test → gap_fill → test` loop (opt-in `coverage_gap_fill` + `tester_enabled`) where the tester
    authors delta tests for ONLY the uncovered changed lines, capped at one pass. **Red-teamed
    (2 rounds): B-4 (iteration starvation) FIXED; A-1 (pre-existing-test-edit tamper) → STOP-rule
    ESCALATION — the round-1 re-baseline was broken (wrong hash space) + opened a weakening hole, so
    reverted: new-files-only + deny-by-default park, weakening-detection deferred to the mutation
    check; A-2b/A-3 (coverage credits execution) also DEFER to it. Pair `coverage_gap_fill` +
    `oracle_mutation_check`.** **Holistic arc red-team (2026-07-17): B-1 (unguarded coverage block
    crashed a green run on a DB/coverage fault) FIXED; A-1 (mutation successor can't catch NON-mutable
    changes → false-credit even in the hardened config) **FIXED (`#39`, ADR-0049)** — a no-op /
    statement-deletion mutation operator deletes the first bare side-effecting call (`Expr(Call)` /
    `Expr(Await(Call))` only, targeted to the changed lines) → `pass`; credit-soundness rests on the
    gate wiring (`tests_mutation_caught` ANDed as a DOWNGRADE-only signal, no upgrade path), ships PURE
    (no logging denylist — over-park is the safe deny-by-default direction). **Red-teamed (3 agents):
    a multi-file park→ship (early-return masked a later rubber stamp) + a walrus-in-call-args
    error-as-caught + a non-byte-exact revert (LF↔CRLF/U+FFFD corruption) all FIXED; a targeting-abstain
    residual + a collection-error-as-caught ACCEPTED (fail-safe, downgrade-only).** Rot detection keys
    off the churn-stable `region_fingerprint` (DONE). Still open: union the mutation test-set (A-3).
- **[prereq] PM session / context management** (`#30`, Phase B) — **per-project sessions DONE**
  (ADR-0045): the single "forever chat" is replaced with named per-project chat threads
  (`pm_sessions` + `project_messages.session_id`, Alembic 0013 backfills the existing chat into a
  default session). **Chat history is session-scoped; project knowledge stays project-shared.**
  Store `SessionsMixin` + session API routes + a web switcher; the agent stays session-agnostic.
  **Prerequisite for the firm** (Quincy can't front multiple teams/projects from one chat) and it
  cut daily friction now. Remaining for the firm: **per-team** sessions (a clean future `team`
  column on `pm_sessions`) + folding the switcher into the cockpit (`#11`).

### Wave B — Know the project (Phase B: Profiles, Routing & Quincy)
- **[arc] BYOM capability-hardening — degrade or park, never thrash/false_ship on a model gap** (`#78`,
  owner insight 2026-07-21; extends the model-agnostic DNA + the `#21`/`#28` BYOM-discovery work). The
  engine ASSUMES model capabilities that not every model has — and the capability lives in the **(model
  × provider × serving-stack) triple, not the model**: DeepSeek-R1 *has* tool-calling in principle but
  **R1-on-Ollama does not expose it** (same weights, different capability). **Capability dimensions,
  ranked by blast radius:** (1) **tool-calling** — the killer; coder/reviewer/tester are tool-using
  agents, no tools ⇒ the coder can't touch the repo; (2) **structured/JSON output** — reasoning models
  interleave `<think>` + ignore `response_format` ⇒ parse-fail ⇒ stall/thrash (the
  `_BUDGET_SENTINEL`/`strip_preamble` fallbacks already exist for a flavour of this); (3)
  **system-prompt honoring** — R1 wants no system role ⇒ persona/instructions lost ⇒ drift (the Phase-A
  inert-critic bug); (4) **context window** ⇒ truncation ⇒ the head/tail-cap honest-stop lesson; (5)
  reasoning tokens (cost/latency/think-vs-answer parse); (6) rate-limits/temperature/streaming; (7)
  **egress/privacy** — BYOM-to-cloud sends repo code off-box, governed by posture + `allow_cloud_egress`
  (Regulated may forbid a provider). **The response — a capability LAYER on top of `get_chat_model`
  (stays model-agnostic):** a capability set per triple `{tool_calling, json_mode, system_prompt,
  ctx_window, reasoning_tokens, temperature_honored, streaming}` from a known-capabilities table + a
  **cheap CACHED PROBE** per `(model,provider,base_url)` (deterministic-first: probe once, reuse; the
  probe catches serving-stack quirks a static table misses). **FAIL CLOSED at config time, not mid-run**
  — validate a role's required capabilities when the model is bound + refuse clearly ("R1-on-Ollama has
  no tool-calling, which the coder role requires"); a gap discovered mid-run is the worst case (flail ⇒
  thrash/false_ship). **Degrade or park — never a dishonest outcome (ties to #76's two-layer contract):**
  an unsatisfiable gap resolves to `honest_park("model lacks capability: tool_calling")`, plus two
  degradation paths — **(a) no tool-calling → patch-emission mode** (coder emits a diff/full-file as
  text, engine applies it deterministically — MORE DNA-aligned + unlocks strong non-tool reasoners as
  coders); **(b) no JSON → prompt-and-parse** (`<think>`-strip + JSON-repair + the critic's verdict-parse
  hardening). **Capability × role matching = the right model for the right role:** judgment roles
  (PM/reviewer/critic/reason) run prompt-and-parse; only coder/tester must *act* — so R1 routes to
  reviewer/critic and is refused as the Ollama tool-coder (or dropped to patch-mode). **DoD: a BYOM
  conformance suite** — the agent loop survives on Ollama / OpenAI-compat / Anthropic / a no-tool model.
  Files: `models.py` capability resolver + a new `capabilities.py` (table + probe), config-time
  validation in the role-binding path, the patch-emission coder path in `agents`, and the capability
  info surfaced in the redesigned Models settings page (**`#79`**, `[debt]`, minimal/intuitive rework of
  the current 3-stacked-cards). Own ADR + threat-model note (egress). Trust-boundary-adjacent (egress +
  the honest-outcome guarantee) → surface + light red-team.
- **[arc] Project onboarding + recon + durable map** — `#6` (Capability profiles + fit/scope step,
  "Atlas seed"). The interview → multi-dimensional recon → durable map + charter. Coverage (Wave A)
  is its tests dimension. **Design is now recorded: [ADR-0047](../adr/ADR-0047-project-onboarding-and-the-durable-map.md)**
  (`#31`) — the trusted charter vs. the **untrusted** map (a poisoned map is *persistent* compromise);
  the map informs scoping but **never** the gate; deterministic-first recon with per-dimension
  fingerprints. Two real dependencies it names: the tests dimension needs `#29`, and the durable
  fingerprint store should **land with** `#23` (rescoped) rather than build a second cache.
  **Foundation landed (`#40`, #6a — ADR-0047 follow-ups 1/2/3/7):** the durable **charter** (trusted,
  operator-authored, edited-never-recomputed, carries posture) + **map** (untrusted, provenance-required
  observations, tri-state finding/clean/unavailable, per-dimension fingerprint freshness where unknown ⇒
  stale) stores in `packages/memory` (Alembic `0017`), plus the ★ **structural map→gate guard**:
  `scripts/check_layer_imports.py` now bans `packages/policies` from importing the map (with a CI-failing
  proof test), so "the map never reaches the gate" is un-writable, not just agreed. **Red-team DONE**
  (2026-07-17, 3 lenses + a fix-verify round): 6 FIX-NOW breaks fixed — the `from mosaera_memory import
  MemoryStore` re-export bypass, the store not enforcing tri-state status↔evidence consistency
  (clean-with-a-finding / finding-with-no-evidence / unavailable-with-no-reason all persisted), and an
  empty-string fingerprint reading fresh; posture/charter separation + provenance held. **Two DEFERs
  logged:** (a) `#42` must pass the FULL `MAP_DIMENSIONS` set to `stale_map_dimensions` or omitted
  dimensions read fresh by omission; (b) `#41` should fold an **analyzer-version salt** into each
  dimension's fingerprint so a recon *logic* change (not just input change) busts freshness.

  Split into three parallel, disjoint issues:
  - `#40` (**#6a**) — the durable map + charter stores (`packages/memory`) + the structural
    map→gate layer guard. **DONE** — see the foundation paragraph above.
  - `#41` (**#6b**) — **the deterministic recon engine — BUILT** (`packages/core/mosaera_core/recon/`):
    one function per dimension (deps/CI/tests/quality/cleanliness/security/structure/docs), each
    returning a tri-state `finding`/`clean`/`unavailable` result + per-dimension content
    fingerprint. **Pure** — returns results, persists nothing, so it stayed parallel with `#40`.
    Host tools go through a seam that pins tool config *by construction* (the ADR-0033 `plugins=`
    RCE is re-pinned by a sentinel test); scanners run in the sandbox with exit-code
    classification. The `tests` dimension reuses `#29`'s coverage map. See ADR-0047's amendments
    for the three design changes the build forced (`security` keys on the whole tree; fingerprints
    are content-hashed, not `tree_hash`; the CI **API query** defers to `#42` for layering). The #40
    DEFER (b) analyzer-version salt lands here.
  - `#42` (**#6c**) — the onboarding flow + synthesis (the one model call). Blocked by `#40`+`#41`.
    Must pass the FULL `MAP_DIMENSIONS` set to `stale_map_dimensions` (the #40 DEFER a).
    **RESUMED 2026-07-22 (post-reliability-gate). MR3 BUILT** (branch `feat/onboarding-charter-synthesis`,
    ADR-0047 amendment): charter GET/PUT (admin-gated write; posture = recorded declaration, ADR-0046
    enforcement deferred), the chat's ```charter proposal pattern (LLM proposes, operator writes),
    gap-driven intake questions (`render_map_gaps` over the full dimension set — nothing reads
    established by omission, the DEFER-a doctrine; fingerprint-diff staleness stays with the future
    incremental-recon `stale_map_dimensions` wiring), and synthesis consuming charter+map. Synthesis caching deferred
    (one explicit call). **red-team DONE (3 lenses, 2026-07-22): 1 FIX-NOW** (a quadratic-backtracking
    ReDoS in the `_CHARTER_BLOCK` proposal regex on the human-blocking pm_chat path — fixed +
    ReDoS-tested) + **1 DEFER-TO-MR4** (the confirm card MUST render the parsed posture, not the model
    prose — a hard requirement) + ACCEPT residuals (the LLM-proposes/human-confirms boundary); admin
    gate + gap renderer verified sound. **MR4 BUILT** (branch `feat/onboarding-map-charter-ui`): the
    onboarding web UI — `CharterProposalCard` (renders the PARSED posture + its meaning, confirms the
    exact value via the admin PUT — the red-team hard requirement discharged), `CharterCard` (admin
    edit; posture = `<Select>`, never free text), `ProjectMapCard` (tri-state + provenance + stale
    badge + re-run recon). 5 vitest cases, full web suite (316) + build green. **#42 (MR1-MR4)
    COMPLETE** — remaining = deferred synthesis caching + posture enforcement (the ADR-0046 arc).
    **Map follow-up (2026-07-22, branch `feat/recon-observation-severity`): advisory per-observation
    SEVERITY** (from a live thrashed-project screenshot where inventory read as alarming as real
    concerns). `Observation` gains `severity` (default info); the 8 dimensions grade their elevate
    sites (security→critical, mypy/scanner→high, no-manifest/empty-repo/uncovered→medium,
    lint/format/no-CI→low, inventory→info); plumbed through recon.py + mapview (`[high]` tag) + a
    store clamp; `ProjectMapCard` colours a finding by its worst observation (inventory→neutral,
    concern→destructive) + severity dots. Advisory hint, recon-assigned never from repo content,
    never a gate input → no red-team. **[debt] suite-failed vs no-coverage.py discrimination
    DEFERRED** (a `run_coverage` precision change entangled with the B3 red-team's infra-vs-failure
    ambiguity; would flip Tests `unavailable→finding` — its own careful fix).
  - **[debt] Host tools must not run with `cwd` inside the untrusted clone** — the `#41` red-team
    found two RCE classes (argv-filename injection; `python -m` module-shadowing) from the one root
    condition: mypy/ruff run with `cwd` = the clone. All proven vectors are pinned
    (`--config-file`/`--isolated`, `--`+`_safe_targets`, `PYTHONSAFEPATH`), but the **durable** fix is
    to run host tools from a scratch cwd with absolute target paths (or in the sandbox) so the clone
    is never on `sys.path`/config-discovery/argv. Shared-seam change (`_hosttools.run_tool` +
    `hygiene`/`quality` relative-path assumptions). Its own scoped issue — see ADR-0047 red-team.
  - **[arc → MR-1 BUILT] Independent security gate** (`#83`, NS-2 governance; **ADR-0076**,
    RED-TEAM-REQUIRED) — closes the run-gate false-green the debt bullet named: `scan_node` now emits a
    tri-state `security_status` (clean/findings/unavailable/disabled) via the recon exit-code classifier
    LIFTED into `tools/scan.py` and SHARED, and a scan that was EXPECTED but could not run parks the gate
    on a new deny-by-default `security_unverified` reason (mirrors `validation_unavailable`) instead of
    reading as clean. Conditioned on the existing `scan_enabled` knob (no new posture); severity carried
    as DATA only; **monotonic** (only adds a deny). Inserted ahead of the oracle-successor by owner
    direction (2026-07-23, from the firm research — control points, not headcount). **Red-team DONE
    (2 rounds, pre-merge): R1 → 1 FIX-NOW fixed (semgrep parse-error partial scan read clean); R2 →
    same-class recurrence (semgrep SILENTLY skips a >1MB / too_many_matches file with `errors:[]` →
    false-clean) → STOP-rule tripped → deterministic stopgap `--max-target-bytes 0` + ESCALATE.**
    **Deferred to later MRs:**
    - **[arc → successor] Coverage-based scan-completeness oracle** — the R2 escalation: trust a
      scanner's `clean` only when its `paths.scanned` covers the repo's scannable file set (not a
      skip-reason blocklist). Closes the silently-skipped-file false-CLEAN class; also gives gitleaks
      (no completeness channel) a real one. **Highest-priority security follow-up** after MR-1.
    - SCA/deps (Trivy, CODEOWNERS-gated `infra/`+`allowlist.py`), charter-posture enforcement (the
      first ADR-0046 consumer — scales the veto + enables severity tiering), a threat-model-note
      artifact, recon per-finding severity fidelity.
- **[arc] Posture profiles** — the Free/Business/Regulated posture as policy-as-code seeds `#6`
  (profiles) and `#13` (enterprise pack). **Design is now recorded: [ADR-0046](../adr/ADR-0046-posture-and-autonomy-governance.md)**
  (`#31`) — posture is a *restriction lattice* (tighten-only, a second veto over the evidence gate)
  that **clamps** the ~15 scattered autonomy knobs at the evaluation seam; the ceremony is
  dual-control + out-of-band + time-boxed + hash-chained audit, with a one-click asymmetric
  off-switch. Nothing built.
- **[arc] Persist PM proposals + structured backlog actions + risk tiers + audit** — `#8`.
- **[debt] Durable evidence/work-packet cache** — `#23` (rescoped).

### Wave C — The firm + governance + cockpit (Phase C: Persona Breadth & Cockpit)
- **[arc] Firm layer** — teams + Quincy-as-interface; generalize the four SWE seams so a new team
  plugs in. Wraps `#18` (the org) + `#10` (promote Vera/Sable/Sentinel to first-class agents; full
  Atlas; Ledger replan/stop). **Design is now recorded: [ADR-0045](../adr/ADR-0045-the-firm-teams-as-modules.md)**
  (`#31`) — and it deliberately ships **no `Team` plugin API**: per ADR-0032's *extract-from-N=3*
  rule, extraction waits for the **editorial team** as a concrete second implementation. Two things
  it pins down for whoever runs this arc:
  - **Extraction order** (cheapest/best-positioned first, hot files last): delivery (`deliver_node`
    is 39 lines) → tools (rekey the allowlist to `(team, role)`; reopens ADR-0013's closed `Role`
    `Literal`) → evidence discipline → the graph (`build.py`/`state.py` are **hot files** → schedule
    as an arc **foundation phase**).
  - **⚠ The blocking prerequisite:** `strength="suite"` means *an EXECUTED suite* and is load-bearing
    at `gate.py:117`, so an editorial team has no argv → permanently non-`suite` → **always parks**.
    The firm collides with ADR-0034. **Solve editorial evidence honestly first** (try a *deterministic*
    editorial oracle — link-check, cite-check, style lint, PII/libel scan — before designing a weaker
    `strength` ladder; an LLM-judge is **not** evidence). A per-team gate is rejected outright.
- **[arc] Posture governance + enablement ceremony** — dual-control + out-of-band + time-boxed +
  tamper-evident audit; the Regulated tier. Feeds `#13` (Enterprise policy pack: SSO/RBAC, audit
  export, SIEM, approved-model registry). Design: **[ADR-0046](../adr/ADR-0046-posture-and-autonomy-governance.md)**
  (`#31`) — see Wave B above; red-team the **composition** (posture × the 9 existing knobs) before it
  ships, since composition is where ADR-0034 broke last time.
- **[arc] Team tab cockpit** — `#11` (agents/sub-agents, state, model route, cost, last output).
  The UI face of the firm/posture work — build *with* it, not before.

### Wave D — Research & artifacts (Phase D)
- **[arc]** Lyra (research packets) + Loom (artifact curation) — `#12`. Plus near-term artifact
  curation/packaging.

### Wave E — Enterprise & benchmark-as-feature (Phase E)
- **[arc]** Enterprise policy pack — `#13` (the Regulated posture's productized surface).
- **[arc]** Capability Lab (MCB as a product feature) + MCB-03→09 + **mosaera.dev self-build** —
  `#14`; MCB-02 static-site + auto-rerun — `#4`. The self-build is the dogfood endgame (Mosaera runs
  its own roadmap as a Mosaera project).

### Continuous — independent debt (slot anytime friction demands)
- **[debt] DONE — Engine versioning** ([ADR-0055](../adr/ADR-0055-engine-versioning.md)) — the engine is
  versioned as a *measured milestone*: **`0.5.0`** (0.x, maturity-anchored; MINOR-per-arc; `1.0` =
  SWE-team production-stable). Single source `mosaera_core.__version__` (lockstep with the 7 workspace
  pyprojects), STAMPED into the scoreboard trend (`_suite/history.jsonl` + rollup + CLI), every run
  report, the API `/config`, and `mosaera --version`. `CHANGELOG.md` carries a benchmark snapshot per
  release (0.5.0 = the reliability arc, 91.7% clean). Follow-ups: a `scripts/bump_version.py` helper +
  CI-wired bump/tag on arc completion.
- **[debt] DONE** (`#36`, UI refresh) — the deferred UI-surface backlog is cleared: all 51
  `GENERAL_KNOBS` are reachable in Settings (the autonomy cluster + `mr_granularity` moved to a new
  **Autonomy** section; enum knobs render as `<Select>` per the no-free-text rule); the run card
  badges `incomplete` amber + shows its `termination_reason`; and approve/cancel failures surface a
  small in-house **toast** primitive instead of a silent no-op. Pure frontend — the API already
  exposed every knob (`general_settings_view`), so no backend change.
- **[debt]** Per-user rate limiting / quotas on the API — **`#34`, done**
  ([ADR-0050](../adr/ADR-0050-api-rate-limiting-and-run-quota.md), TM-0002). A per-credential
  in-process request window (`MOSAERA_RATE_LIMIT_PER_MIN`, default 300/min) + a durable per-account
  daily run cap (`MOSAERA_RUN_QUOTA_PER_DAY`, default off; `run_quota_usage`, Alembic `0015`,
  atomic conditional UPSERT) → 429 + `Retry-After`. Two things a later session should not re-derive:
  - **Config surface — resolved by `#37` (ADR-0050 addendum): a SPLIT.** The **quota**
    (`run_quota_per_day`) is now a `GENERAL_KNOBS` UI knob (Settings → General → Run budgets), read
    **live** on `POST /api/runs` so a save applies with no restart; it's run-adjacent + a number
    field (a bounded quantity, not an enumerable dropdown). The **rate limit stays env-only** —
    API-infra that runs on every request (ADR-0005 §2; a UI knob would cost the free hot path or a
    dishonest restart) with a loud-on-garbage parse (it's on by default). Closes ADR-0050 follow-up #1.
  - **No loopback exemption, deliberately.** Behind the recommended reverse proxy every client
    looks like `127.0.0.1`, so exempting the socket peer would silently disable the control on
    exactly the deploys that need it. The discriminator is the *credential*.
  - Login brute-force was named here as NOT covered (`/auth/login` is pre-credential) → **closed by
    `#38`** below. Multi-worker ⇒ per-worker rate limits (the quota is exact).
- **[debt]** Login brute-force protection — **`#38`, done**
  ([ADR-0051](../adr/ADR-0051-login-backoff-and-enumeration-equalization.md), TM-0002). Per-**account**
  failed-login backoff (`login_backoff`, Alembic `0016`, env-only `MOSAERA_LOGIN_BACKOFF_*`, default
  ON) → 429 + `Retry-After`; durable and **exact across workers**. Closes ADR-0050 follow-up 2.
  Three things a later session should not re-derive:
  - **The username-enumeration oracle was REAL, and TM-0002 claimed it was mitigated.**
    `creds is not None and verify_password(...)` short-circuits, so an unknown username never ran
    scrypt: **194ms vs 9ms** end-to-end. Fixed by verifying against a dummy hash. **A threat model
    that reports a hole closed is worse than one that reports it open** — it retires the fix from
    everyone's queue. That's the lesson, not the line of code.
  - **Fixing it was a prerequisite, not a nicety** — backoff branches on account state, so without
    equalization the 429 becomes a cleaner, timing-free status oracle.
  - **The slot is claimed BEFORE verification.** Counting failures after ~130ms of scrypt is
    ADR-0050 §5's read-then-write race at 130ms scale: it bounds sequential rounds, not guesses.
  - Accepted cost: **attacker-induced account lockout** (inherent to any per-account key; IP is
    proxy-shared). Bounded + admin-unlockable, and the service/admin token bypasses `/auth/login`
    entirely, so an operator is never locked out. → new TM-0002 row.
  - Still open: a **distributed** campaign across many usernames at a few attempts each stays under
    every threshold (wants credential-stuffing detection, not a counter); the login CPU sink is
    bounded by a semaphore, not eliminated.
- **[debt]** LiteLLM / OpenAI-compatible proxy + vLLM in front of the model gateway; egress-allowlisted
  install proxy.
- **[debt]** `is_test_file` review — a *source* file named `test_*.py` is mis-classified as a test and
  bypasses both coverage and the import heuristic → credited by an irrelevant suite (ADR-0049 A2,
  pre-existing, narrow). Affects the whole oracle, not just the coverage path.

## Housekeeping — DONE (2026-07-16)

1. `#28` (hosted API onboarding) **closed** — delivered by ADR-0014.
2. `#23` **rescoped** to the durable cross-run work-packet store (within-run MVP shipped).
3. **Opened `#29`** (coverage-oracle arc, Phase A) and **`#30`** (PM session/context management, Phase B).
4. `#18` **reworded** to the firm-of-teams framing (the 11-persona org = the SWE team).
5. **`#31` — the Waves B/C design ADRs are written**: [ADR-0045](../adr/ADR-0045-the-firm-teams-as-modules.md)
   (the firm), [ADR-0046](../adr/ADR-0046-posture-and-autonomy-governance.md) (posture governance),
   [ADR-0047](../adr/ADR-0047-project-onboarding-and-the-durable-map.md) (onboarding). Docs-only —
   **zero runtime change; none of Waves B/C is built.** They lock the decisions before the arcs run.
   Three findings a future session should not re-derive:
   - **The firm collides with ADR-0034** — an editorial team has no executed suite → always parks.
     That is the prerequisite, not a detail (ADR-0045).
   - **Autonomy is a ~15-knob scatter** with no artifact describing the composition — which is
     exactly how ADR-0034's "ship with no validator and no reviewer" happened. Posture is that
     artifact (ADR-0046).
   - **The durable map is a persistent injection vector** — worse than a per-run injection, since it
     re-injects every run and looks like knowledge (ADR-0047).

---

## Current-focus narrative, 2026-08-01 → 2026-08-05 (moved from the roadmap 2026-08-06)

> **Why this moved.** `docs/roadmap.md`'s *Current focus* had accreted to **680 lines** of dated
> narrative — a focus that long is not a focus, and it is where a fresh session forms its model of
> the world. Nothing is deleted; this is the full record, in order.
>
> The trigger was measured: two findings in one session were **rediscoveries** of knowledge already
> written down, one of them quoted in this very block. Research behind the split:
> [`../research/documentation-retrievability-and-staleness-2026-08-06.md`](../research/documentation-retrievability-and-staleness-2026-08-06.md)
> — a fact buried mid-document is measurably not retrieved, by humans (information scent) or by
> models (context rot, >30% drop for mid-context facts).

- **PIVOT (2026-08-02, owner-approved):** the oracle-successor search is **closed** — five
  attempts measured (Proctor real-but-wrong-class; mutation 0/3; critic abstains on the subtle
  class; structural-spec **null at n=25/arm, activation withdrawn**; differential probe = signal,
  not authority), and external research confirms no deterministic technique reconstructs absent
  intent. The blocking arc is now the **claim contract**: acceptance claims as first-class
  artifacts with provenance + one shared predicate binding
  ([ADR-0079](../adr/ADR-0079-claims-first-class-artifacts.md), proposed), intake clarification
  ([ADR-0080](../adr/ADR-0080-intake-clarification.md), proposed), and the control-liveness ladder
  ([ADR-0081](../adr/ADR-0081-control-liveness-ladder.md), proposed — measurement liveness is the
  meta-blocker: 4 controls-that-couldn't-fire found in one week). Design inputs:
  [brief-checkability-2026-08-02](brief-checkability-2026-08-02.md) (19/24
  cases fully coverable today; structural ceiling 8/24 not 2/24; the suite has zero
  under-specified briefs — a bias to fix) and
  [structural-oracle-ab-2026-08-02](structural-oracle-ab-2026-08-02.md).
  **Gate 2 restatement pending ADR acceptance:** from a bare "false_ship ≈ 0" to *no
  unestablished material claim ships*, with the false-ship rate stated as a bound on a named
  distribution (rule of three: ~3/n at 95%).
- **Blocking arc for v1.0:** the claim contract — **ADR-0079/0080/0081 ACCEPTED by the owner
  2026-08-03; Wave 1 SHIPPED same day** (MERGED 2026-08-04): execution fingerprints + the liveness
  registry + `INVALID_EXPERIMENT_IDENTICAL_EXECUTION` (ADR-0081 — 2 knobs proven C4, 1 at C5,
  **6 posture knobs honestly exposed at C2**, the sentinel backlog; instance #4 pinned as a
  regression test); the Claim schema v1 + `claims_from_acceptance` + the Checkability verdict
  wired into Quincy's existing re-curate pass + launch unflattening (claims ride
  `RunState["claims"]` beside the byte-identical task string, report-rendered; ADR-0079
  backlog-side). Verified: all 24 briefs classify with ≥1 bound material claim (consistent
  with the checkability analysis); live fingerprint smoke on MCB-03 (12 node visits, outcome
  unchanged). **Wave 2 next:** the `evaluate_gate` per-claim input + `unsatisfied_claim`
  reason + the 6-verb predicates ported from the validated experiment + Alembic-0018 ledger —
  trust-boundary work, full 3-round red-team.
- **Wave 2 BUILT (2026-08-03, MERGED 2026-08-04): the gate consumes claims.** `evaluate_gate` gains
  `claims_failed` → one stable `unsatisfied_claim` reason (ids ride
  `GateDecision.unsatisfied_claims`; the stall breaker fingerprints reasons, so the string is
  id-free); downgrade-only, parks in every mode; defaulted-off byte-identical (24-row decision
  table untouched). `claim_oracles.py` evaluates per claim (the six-verb contracts ported from
  the 18/18 offline validation, recursive counting + delivered-tree lessons kept; parameter
  extraction deny-by-default — no named target is never guessed; unbound NEVER fails, per the
  owner's gate-policy decision). Claim ledger: Alembic **0018** `run_claims` (provenance NOT
  NULL, store-validated, ordering invariant held; round-tripped against real Postgres). Bench:
  claims ride the payload behind `MOSAERA_BENCH_CLAIMS_OFF`. Live smoke MCB-13: clean_deliver,
  no false park. **Pre-registered predictions** (fingerprint-validated A/B post-merge):
  behavioral cases unchanged · MCB-13/14/21/22 wrong shapes now park, 0 false-parks ·
  **MCB-05/15 likely STILL null** — their graders assert the absolute `<=6`/`<=7` constants
  while the predicate measures relatively; a null there CONFIRMS the single-binding thesis
  (grader alignment is owner-deferred, a separate deliberate act). **Red-team: DONE (2026-08-03,
  pre-merge at the owner's direction — stricter than post-merge; findings fixed/dispositioned
  before landing).** R1 CLEAN: claims are launch-minted only (factory + bench payload; no
  graph-node writer), and a satisfied claim vouches NOTHING — the gate input is failure-ids
  only, downgrade-only by construction. R2: the nesting dodge is CAUGHT (recursive walk
  descends into inner functions); unparseable sources degrade to unevaluable (no crash, no
  vouch). **1 ACCEPT (STOP-rule escalation): the relocation/stub class** — moving the ladder
  into a helper with a fake loop evades `data_driven_single_if`, and stub modules spoof
  `layout_preserved` (round 2, SAME class → stopped per protocol, no third round). Documented
  fail-safe bound: every predicate evasion degrades to the PRE-claims baseline — claims are
  downgrade-only, so a missed catch is a missed park, never a new ship channel; behavioral
  gates are unaffected and the hidden grader stays ground truth in measurement. This is the
  same relocation class ADR-0072's red-teams ACCEPTED twice; the named successor is **Wave-3
  predicate authoring** (operator-approved predicates stating the full contract, ADR-0080
  flow). R3 CLEAN: security/tamper reasons strictly precede `unsatisfied_claim` (order-locked
  by test); the reason string is stable/id-free so the gate-stall breaker fingerprint holds.
  R4 CLEAN: a bad ledger row rejects the whole batch BEFORE any session opens; a claims-write
  fault aborts persist BEFORE record_run — the failure direction is rows-without-status,
  never status-without-evidence (verified by driving persist_run against a raising store).
  R5: C4 recorded (gate-decision divergence tests); C5 pends the post-merge A/B, honestly.
- **A/B MEASURED (2026-08-03, overnight): the first fingerprint-validated experiment.** 140
  runs, arms interleaved, validated by `liveness.experiment_verdict` BEFORE scoring — and the
  ladder fired on first use: **MCB-14's A/B self-voided (0/100 divergent pairs)**, masked by a
  pre-existing wall. Verdicts: **P1 safety CONFIRMED** (claims-caused false parks **0/140**;
  every `unsatisfied_claim` co-fired with `validation_failed`) but the catch half was
  **vacuous** — MCB-13/21/22 produced zero wrong-shape ships in EITHER arm, so the predicates
  had nothing to catch (armed, unexercised). **P2 CONFIRMED**: MCB-05/15 null (p=1.0/0.47) —
  the two-rulers thesis stands; grader-alignment data banked for the owner. **P3 CONFIRMED**
  (controls unchanged). **Two defects discovered and attributed:** the **MCB-14 vouching
  wall** (20/20 grader-correct runs refused, `oracle_unverified` both arms — no independence
  path ever vouches there) and the **critic as net false-park source** (12 over-vetoes vs 5
  true catches, ~29% precision — invisible pre-ADR-0078). The suite's false-shipping is now
  CONFINED to the two-rulers cases; the dominant local-tier defect is over-parking correct
  work (Gate 1, not Gate 2). Full record:
  [engineering-history/claims-gate-ab-2026-08-03.md](claims-gate-ab-2026-08-03.md).
  **Next levers, in measured order:** critic calibration `#61` · MCB-14 vouching wall `#60`
  · grader alignment (owner) · Wave-3 intake/predicate authoring (planned).
- **`#61` BUILT (2026-08-03, MERGED 2026-08-04): critic calibration — the critic proposes, a
  deterministic policy disposes** (ADR-0065 amendment). Per-claim
  REFUTED/SUPPORTED/INSUFFICIENT_EVIDENCE with VERBATIM quotes; `critic_policy.py` verifies
  each REFUTED quote against the operator-approved requirements AND the delivered text —
  hallucinated/paraphrased requirements (the measured over-veto shape) convict nobody.
  Gate seam byte-identical; judgement finally durable (Decision row + payload + scorecard
  `critic_rows`); knob `critic_claim_protocol` default OFF; liveness C4 (sentinel-proven).
  **Pre-registered A/B predictions (before the run, per ADR-0081):** (1) veto precision on
  the over-veto cases (03/06/13/21/22) rises >70% from 29%; (2) **the 05/15 true catches
  SURVIVE** (their quotes are real brief text — if the filter kills them it is too blunt and
  the knob does NOT activate); (3) zero new false ships (veto-only construction); (4)
  delivery on 06/21/22 rises. **red-team disposition:** no red-team-required file-domain
  touched (policies/gate/posture/auth untouched; seam byte-identical) — the deterministic
  verifier carries adversarial unit tests instead (smuggled-requirement, planted-CLAIM-line,
  short-quote, paraphrase attacks all pinned).
- **First `#61` A/B ABORTED at 20/140 (2026-08-03) — a third failure shape, diagnosed from
  the rows in minutes:** **premise poisoning** (whole-brief claims included starting-state
  descriptions; the critic refuted runs FOR SUCCEEDING — MCB-03's veto evidence was
  "exit code 0"), plus the legacy fallback leaking the old failure (3 of 5) and a
  wrong-direction materiality default. Four deterministic fixes (premise filter · unknown-id
  never material · **residual jurisdiction**: veto only what determinism can't cover ·
  noncompliance = abstention). **Re-registered predictions for the re-run:** (1) premise-class
  vetoes = 0; (2) over-veto rate on 03/06/13/21/22 drops to near-0 (jurisdiction excludes
  deterministically-covered claims); (3) the 05/15 true catches SURVIVE (their shape claims
  are unbound residual — the kill-switch stands); (4) 0 new false ships.
- **`#61` re-run MEASURED (2026-08-03, n=140): the protocol works — activation gated on the
  probe.** 6/7 cases fingerprint-VALID (MCB-15 self-voided: neither arm's critic fired).
  **Over-vetoes 8 → 1 (Fisher p=0.033)**; true catches SURVIVE (new 2 vs old 1, MCB-05);
  false ships 18=18 (none new); premise class 0; 7 hallucinated refutations caught-and-logged
  by the verifier; delivery 38 vs 31 (directional). The one residual over-veto root-caused to
  a SENTENCE-SPLITTER fragment (line-wrap orphaned a premise tail into a material unbound
  claim) — fixed same day (split on punctuation/blank-lines/bullets only; headings
  non-material; MCB-03 16→9 claims). Precision 67% at n=3 sits under the 70% bar — **the
  targeted probe decides** (05 n=15/arm · 15 n=10 · 06 n=8 · 03 n=6, running): catch events at
  real n, precision above bar, fragment class dead. Full record:
  [engineering-history/critic-calibration-ab-2026-08-03.md](critic-calibration-ab-2026-08-03.md).
- **`#61` ACTIVATED (2026-08-03, owner decision):** `critic_claim_protocol` posture-ON.
  Evidence: over-vetoes 8→1 (p=0.033) · catches preserved (sweep 2v1; probe partial 41/78
  added an old-arm catch + 2 more old-arm over-vetoes, new arm clean) · no new ship channel
  (structural) · premise/fragment classes dead + regression-pinned. Catch-retention converts
  from gate to STANDING PRODUCTION MEASUREMENT (every veto persists quoted rows). Rollback =
  one posture line (tripwire-guarded). **#61 arc CLOSED.**
- **Wave 3 BUILT (2026-08-03, MERGED 2026-08-04): intake clarification full-stack + #60 vouch +
  intake park.** Stage 1: checkability + claims on the backlog GET, chips in the UI. Stage 2:
  Quincy's ```clarify fence (charter-fence discipline) → stored ON the item (Alembic 0019) →
  resolved via the validated `enhance` path (operator acceptance mints ENTAILED). Stage 3:
  open ask ⇒ not-runnable (ItemLocked posture; override = the escape hatch; sweep skips).
  Stage 4: the clarify card (one-click accept / edit / dismiss) + Question-open badge.
  Stage 5 (#60, oracle domain): a SATISFIED material ast_transformation_contract claim
  vouches for a DETECTED behaviour-preserving refactor (trusted-task-only, tamper-clean,
  proven-satisfied; kind-scoped against double-counting; payload carries oracle_vouched_by).
  Stage 6 (ADR-0080 §2): UNDER_SPECIFIED runs park at plan-entry with ZERO model calls via
  the plan-unworkable seam (frozen classifier untouched; diagnostic `under_specified` cause).
  `ApproveBody.answers` DEFERRED (recorded: the runner auto-approves unknown interrupt
  actions — a new action is a footgun; answers belong at backlog time per §1).
  **Pre-registered #60 A/B (before the run):** MCB-14 claims-ON vs claims-OFF n=10/arm —
  ON converts the 20/20 wall to deliveries (grader-passing work ships); OFF stays walled;
  MCB-05/15 spot n=5/arm UNAFFECTED (their structural claims are not satisfied — any
  movement means the vouch leaks). 0 new false ships anywhere. **Red-team: DONE** — R1-R4
  clean; 1 FIX-NOW (the preservation-claim loophole: layout-style predicates are true before
  any work — vouching restricted to DELTA-PROVING claims, applied same day). **A/B MEASURED
  (n=40):** no-leak CONFIRMED (05/15 byte-identical); the-wall-falls REFUTED — and diagnosed
  to the conjunct within the hour via two new always-on meta fields (`vouch` self-explaining
  diagnosis + `mutation_caught`): **the vouch FIRES live; a comprehensive-mutation survivor
  (ADR-0071, correct under doctrine) ANDs the oracle dead.** The wall's complete anatomy is
  now named per-scorecard. **Owner decision queued:** does a mutation survivor still block a
  vouched pure refactor with a green differential golden-master? Record:
  [engineering-history/refactor-vouch-ab-2026-08-03.md](refactor-vouch-ab-2026-08-03.md).
- **DECIDED (2026-08-03, owner-ratified — ADR-0071 amendment): the mutation AND stands.**
  The survivor is the map of the equivalence proof's holes (same blind spot as the
  differential inputs), so the evidence rises to the bar, never the reverse. Successor lever
  tracked: **`#62` mutation-guided differential inputs** (survivors become input-generation
  targets; killing them strengthens the proof and the vouch stands on it — no policy change).
  Meanwhile the park is a PRICED residual: the gate payload's `oracle_residual` receipt
  (shape proven / equivalence sampled / unproven branch named) + the API termination line
  "vouched refactor blocked by a surviving mutation" — a human approval accepts a NAMED
  residual with `human_override` on record.
- **`#62` BUILT (2026-08-03, MERGED 2026-08-04): the differential now REACHES the branch.** Root
  cause of the MCB-14 survivor, corrected from my wrong hypothesis by exploration: it is a
  **noop mutant deleting the shared validation call** (isinstance/not/and-or/constants have no
  mutator at all), surviving because every generated input was valid — the module's limits are
  0 and 150 while `_NUM_BOUNDARIES` had no negatives and nothing above 100, plus no string or
  type variants. Fix: numeric literals mined from the module under refactor become off-by-one
  TRIPLES, plus one type-confusion per arg per family (bool-in-int, empty string, stringified
  number, None); both ordered before the generic flood so the cap can't evict them.
  Offline-verified red/green: golden oracle green on a correct refactor, **KILLS** the
  deleted-validation mutant. **Pre-registered A/B (before the run):** MCB-14 n=10/arm,
  scaffold-generator ON vs OFF — (1) `mutation_caught` flips False→True; (2) the 20/20 wall
  falls (grader-passing work delivers, vouched); (3) 0 new false ships anywhere (MCB-05/15
  n=5 spot — more inputs can only find MORE differences, never fewer); (4) no new false parks
  on behavioural cases (the differential compares real-vs-frozen, so an unreachable input
  raises identically on both sides).
- **`#62` MEASURED + CLOSED (2026-08-03, n=30): THE WALL IS DOWN — with no policy change.**
  All four predictions CONFIRMED: `mutation_caught` **False→True on 20/20** (was False 20/20);
  **MCB-14 20/20 `clean_deliver`, grader-passing** (the case that refused correct work every
  prior sweep); MCB-15 5/5 unchanged (no leak); no new false parks. Recorded observations:
  MCB-05 moved toward parking (2/5, n=5 — unpredicted, worth a powered re-measure, NOT claimed);
  the OFF arm also delivers, i.e. once the golden oracle is strong enough the standing-suite
  leg vouches on its own — **the deeper fix was the evidence, not the vouching rule**, exactly
  the ADR-0071-amendment thesis. **Stage B (survivor-feedback re-author) dropped as provably
  unnecessary.** Record:
  [engineering-history/mutation-guided-inputs-2026-08-03.md](mutation-guided-inputs-2026-08-03.md).
- **`#58` IN PROGRESS (2026-08-04): the evidence surface itself was failing open.** `sandbox-e2e` —
  the job whose whole purpose is running the Docker/Postgres-gated tests — **skipped them and reported
  success**, and had done since 2026-07-16. Reconfirmed on pipeline #826: `1398 passed, 116 skipped,
  job succeeded`, where the same selection with services up gives **1515 passed, 2 skipped** (the 2 are
  by design). **114 tests had never executed in CI** — all of them pass, so nothing was hiding, but
  nothing was watching either. Three compounding causes, all now closed in the harness: `-q` suppressed
  skip *reasons* so a vacant run and a real one logged identically · the gates were eight copy-pasted
  `skipif`s each probing at its own import · nothing anywhere asserted a run/skip count (pytest's exit-5
  can't fire while ~1400 ungated tests pass alongside). Landed: `-rs`, a gate summary printed on EVERY
  run, the gates centralised as two markers probed once with the underlying error in the reason, and
  `MOSAERA_INTEGRATION=required` making a missing precondition an **ERROR not a skip** — pinned by
  `test_integration_gates.py`. **ROOT CAUSE NAMED on the first instrumented run (#828): the CI Postgres
  service is stock `postgres:16`, which has no pgvector** — `store.init()` runs `CREATE EXTENSION IF
  NOT EXISTS vector` and the models map `Vector(768)`, so the DDL raised on every connection and every
  `requires_db` test skipped. Docker was never implicated. The dev container is `pgvector/pgvector:pg16`;
  CI is `postgres:16`. **Pending the owner (CODEOWNERS), in this order:** correct the image, THEN set
  `MOSAERA_INTEGRATION: required` — arming the gate first would make the job permanently red. Note a
  `pg_isready` precondition would NOT have caught this: the server was up the whole time, the failure
  was one DDL deeper. Record:
  [engineering-history/sandbox-e2e-vacancy-2026-08-04.md](sandbox-e2e-vacancy-2026-08-04.md).
  This is *Evidence-Gated Advancement* applied to our own instruments, and the same silently-inert
  class as the ADR-0070 ★ LESSON.
- **Intake DECIDABILITY (2026-08-04): the axis the checkability verdict could not see.** Three demo
  runs supplied the evidence: **brownfield** (a brief stating a *rule*) → correct code, **0 fix
  iterations**; **greenfield** (a brief naming an *output shape*) → run 1 thrash-parked
  `5→5→5`, run 2 **passed the gate with 48 green tests** over a scoring model where a 40-char
  single-class password scores the same 4 as a mixed one. One brief, **two different invented
  models**. Both briefs scored `PARTIALLY_CHECKABLE`: `checkability` measures **bindability**
  (*can a checker attach*), never whether the value is **computable from the text**. Bound-and-
  undecidable is the *dangerous* cell precisely because binding grants confidence. **Pre-registered
  as an executable test before the detector existed**, then scored exactly: **2 of 24 MCB cases
  flagged — MCB-05 and MCB-15, 100% of the suite's `false_ship`** — plus greenfield UNDECIDABLE
  and brownfield DECIDABLE, from brief text alone with **zero runs**. Prediction 4 ("at most one
  further case ⇒ else narrow the detector, never relax the prediction") did its job: two rounds of
  narrowing (bare adjectives describe the *project* not a requirement; a scale noun is required;
  the suppressor is **clause**-scoped, since MCB-05's one sentence carries "a handful of statements"
  *and* "at least three helper functions"). Independent corroboration: an existing test's sample of
  a **clean** item — *"returns a score 0-4 and a non-empty list of reasons"*, written months ago —
  flagged CHECKABLE ∧ UNDECIDABLE, the greenfield shape verbatim; the sample moved, the assertion
  did not. Shipped **report-only**: a sibling verdict on the backlog GET, a **second marker so
  Quincy can see it** (only `UNDER_SPECIFIED` was tagged before — the exact blind spot), and the
  findings joined into the existing one-pass re-curate. The launch gate, the clarify fence and the
  plan-entry park are untouched — ADR-0080 calls the ask-rate *"a measured dial, not a promise"*,
  so this cut measures before it asks. **Validates the detector, NOT effectiveness** (`#59` MCB-D
  is that instrument; today's greenfield observation is the new case class ADR-0080 requires).
  Record: [engineering-history/intake-decidability-2026-08-04.md](intake-decidability-2026-08-04.md).
- **The BACKFILL (2026-08-04, same arc): the same mechanism pointed backwards.** Both intake
  verdicts judge `todo` items only — correct for the run path, and precisely why work authored
  before they existed is invisible to them. `diagnose_item`/`diagnose_backlog` are a **status-blind
  sibling primitive, not a widened filter** (widening would silently change what the clarification
  gate and the re-curate pass see; pinned by a test that the run-path verdicts still return `{}`
  for a settled item). Non-compliant = the two states the engine actually treats as broken (`UNDER_SPECIFIED`, which parks
  a run today; `UNDECIDABLE`, which ships invented evidence); `reasons` names every failure, not the
  first. Surfaced as `compliant`/`compliance_reasons` on every backlog row, a
  read-only `GET /projects/{id}/compliance` summary, and a quiet "Pre-standard" card chip
  (suppressed on `todo`, which already carries live chips). **Derived at read, never stored** — a
  column would freeze two-week-old detectors into the schema and go stale as they improve; storing
  the verdict would cross the schema/artifact bar and need an ADR + migration + replay, so read-only
  and derived it sits with `GET /metrics`, which has none. **A flag is not an accusation:** for
  settled work it says the acceptance could not have gated the work, NOT that the delivered code is
  wrong — carried in the API `note`, the card hover and the docstrings, because that over-claim is a
  backfill's obvious failure mode.
- **DRIVEN AS OPERATOR (2026-08-04) — two defects no test I'd have written would have caught.**
  Both found by *using* the check against the live API rather than reading it. (1) **A rule one
  sentence later still fixed nothing:** a brief repaired EXACTLY as the finding instructed still
  scored UNDECIDABLE, because the rule landed in the next sentence and the suppressor was
  clause-scoped — a false flag on correctly-repaired work, harmless while report-only and
  trust-destroying the moment it gates. The two patterns now take different scopes: vague magnitude
  stays CLAUSE-scoped (a countable elsewhere doesn't fix "a handful" — the MCB-05 shape), a named
  output scale is BLOCK-scoped (bullet/paragraph, NOT document — greenfield's `->` sits in another
  bullet and must still flag). Corpus re-scored, prediction unchanged at 2/24. (2) **The compliance
  rule reintroduced the very failure this arc exists to fix, one layer up:** `CHECKABLE ∧ DECIDABLE`
  made the *brownfield* brief — correct code, zero fix iterations, our exemplar of a GOOD brief —
  read non-compliant, identical to greenfield. `PARTIALLY_CHECKABLE` is the modal state of a real
  brief and blocks nothing today; a marker that fires on the best input we own gets ignored.
  **Verified live end-to-end:** item flags → operator states the rule via PATCH → flag clears →
  rule removed → flags again; Quincy's real context line carries `[decidability=UNDECIDABLE]` and
  NO checkability marker (the blind spot, visible); scratch item deleted, project as found. Lesson,
  the same one `#58` taught about our own CI: **an instrument nobody has driven is an untested
  instrument**, however green its unit tests are.
- **REPAIRING THE ASK — MEASURED (2026-08-04, n=3/cell): stating the rule clears MCB-05/15.**
  Paired arms, graders + seeds byte-identical, only the brief text differing; contamination declared
  (the graders were read first) and designed around — ONE rule in both briefs, *"at most 5
  statements"*, matching NEITHER grader number (6 and 7 appear nowhere in either repaired brief),
  derived from the brief's own "at least three helpers", and STRICTER than both so it clears them by
  construction rather than by aiming. Gate before running: control must score UNDECIDABLE and
  treatment DECIDABLE. **Control 0/6 grader-clean; treatment 5/6 (Fisher exact two-tailed
  p = 0.015).** Mechanism visible, not inferred: controls deliver **8 and 9 statement** orchestrators
  against limits of 6 and 7 — "a handful" read as roughly double, not a 6-vs-7 margin call.
  **The false-ship framing was WRONG:** all 24 runs across both matrices ended `honest_park`,
  `delivered=False`, `unsatisfied_claim` — **zero ships, zero false ships in either arm**. A vague
  brief here does not buy a bad ship, it buys a GUARANTEED PARK: work that cannot satisfy a rule
  nobody stated, burning a full run to find out. The `false_ship 6.9% (MCB-05/15 only)` attribution
  belongs to another configuration and must be re-derived before being repeated. **Correction on
  record:** the first matrix was uninterpretable and I raised it as a scoreboard-integrity problem —
  wrong. `overstrict_vs_reference` overlays the case REFERENCE onto the workspace after grading
  (documented, `shutil.copy2` preserving mtime), so a post-mortem bench workspace holds the reference
  wearing the seed's timestamp, not the delivery. The instrument was right; the post-hoc method was
  not. **Caveat that sets the next move:** the repair was authored by a HUMAN — nothing recorded that
  "short orchestrator" means ≤5, so case 3 asks again. That is ADR-0082's standing-standards tier.
  Record: [engineering-history/ask-repair-mcb-2026-08-04.md](ask-repair-mcb-2026-08-04.md).
- **THE ASK ACTIVATED + DoD-1 MEASURED (2026-08-05).** Two results, one positive and one negative,
  and the negative is the more useful. **(a) The ask works end-to-end.** An undecidable claim now
  raises an OPERATOR question at decompose instead of Quincy silently rewriting the acceptance —
  he cannot know the intended scoring rule, so he was inventing one, the same defect the detector
  exists to catch, one level up. He still authors the proposal (an `enhance` op already IS a
  proposal); he no longer decides. `intake_ask.py` is the single askability authority for all three
  fence sites, with `clauses` a REQUIRED positional so a ratified decision suppresses the ask as
  well as the finding. Knob-gated `intake_ask_undecidable`, default OFF, with a set-equality
  inertness proof. **Demonstrated live:** greenfield item lands CHECKABLE+UNDECIDABLE → ask raised
  with a rule-bearing proposal → launch 409s with per-axis wording → operator states the rule →
  verdict flips → the build implements THAT rule, **10/10 on the pre-registered vectors**, including
  the 40-char single-class password that scored 4 in the morning and now correctly scores 1.
  **(b) DoD-1: the clause CHANNEL does not reproduce the brief edit — REFUTED.** control 0/12
  grader-clean, treatment 0/4, statement counts indistinguishable (8-9, one run 10);
  `experiment_report` SCOREABLE via the new engagement path. A standing decision riding BESIDE the
  task changes nothing; the same number written INTO the brief moved 0/6→5/6. Design implication:
  a clause must reach the item's ACCEPTANCE TEXT the way an operator's answer does. DoD-1 itself is
  satisfied trivially — clauses moved nothing, 16/16 honest_park, zero false ships.
  **And the instrument caught a dead control on its first real use, in the feature that added it:**
  `clauses` was seeded at launch but never DECLARED in `RunState`, so LangGraph dropped it and the
  oracle overlay had never fired — in the bench or the product — while the unit tests passed by
  calling `apply_to_constraints` directly. Now declared, and the state contract is a test.
  Records: [engineering-history/clauses-ab-2026-08-05.md](clauses-ab-2026-08-05.md).
- **ADR-0082 ACCEPTED + tiers 1-2 BUILT (2026-08-05): a decision recorded once.** The arc's own
  caveat was that the repair was HUMAN-authored and nothing recorded it, so the next item asks
  again. Now: tier 1 **standards** code-declared and bootstrapped from the four guards that already
  fail CI (a standard is a fact about the repo, changed by a reviewed diff — which also buys
  staleness for free: rename one and every clause citing it stops validating at load, ADR-0082's
  "no expiry dates" implemented); tier 2 **clauses** stored append-only (Alembic **0021**), value a
  NUMBER never prose, no `scope` column (inherited), no `expires_at`. **A third limit not in the
  ADR:** each standard declares the parameters it leaves OPEN, so `module.max_lines` is not in the
  registry at all and "waive the 500-line ceiling" is *unsayable* rather than denied — §4's prose
  turned into data, leaving the deny-list a genuinely independent net. The consult path closes the
  gap end-to-end: the finding is answered (suppression by PARAMETER, never prose), the board says
  `decided_by`, the number reaches the coder (the half that carried the measured effect), and
  `apply_to_constraints` BINDS the oracle so an over-long delivery now fails where it was inert.
  **Deny-by-default:** `clauses_enabled` OFF and `load_clauses(enabled=False)` by default — a
  caller that forgets the setting gets today's behaviour. Load-bearing detail: the live-row unique
  index is over `COALESCE(project_id,'')`, because NULLs are distinct in Postgres and the obvious
  index would enforce nothing for exactly the rows that apply everywhere — two live contradictory
  clauses on one parameter being the two-readers-two-numbers failure this arc exists to kill
  (verified both directions on real Postgres). **NOT built, still DIRECTION:** the computed gate
  option surface + `ApproveBody.option_id` (§1/§5 — the first real use case turned out to be
  INTAKE, not the gate), counsel routing (§6), tier 3 taste. **Still owed by ADR-0082's own DoD:**
  the clauses ON/OFF bench A/B validated by `experiment_report` (which still has no production
  caller), the clause-resolution rate as the rubber-stamping metric, and C4 before any
  effectiveness claim — `clauses_enabled` is not a posture knob, so the liveness guard's silence
  about it is NOT compliance.
- **`#63` MERGED (2026-08-04, MR !322).** *Numbering note: the receipt/ledger/engine-view arc is
  tracked here as `#63` but was never filed on the board — GitLab `#63` is now the unrelated
  checkpointer-reconnect debt item. Don't conflate them.*
- **[arc] PROPOSED (2026-08-04, owner-directed): the gate asks a question — ADR-0082.** The gate hands
  the operator evidence and asks for a binary; the operator needs to know what happens if they pick
  each thing, and today the decision evaporates the moment it is made. Same root as the remaining
  `false_ship`: **MCB-05/15 disagree with the engine because the contract was never written down**
  (one sentence, two readers, `<=6` and `<=7`). Three tiers: standing **standards** (bootstrapped from
  the guards that already have teeth — the 500-line ceiling, layer direction), derived **clauses** that
  *cite* a standard and may be conditional (*"no fixed statement count — unless the module would cross
  500"*), and inferred **taste** that orders and phrases options but never gates. Scope is **inherited**
  from the cited parent, so widening requires changing the standard — a visible act, not a slider; and
  clauses carry **no expiry**, because a derived clause is stale by construction when its parent moves.
  The taste/proof line is held by two independent limits: a clause may only bind a **registered oracle
  parameter** (removing an oracle is not expressible), and a deny-list bars proof-bearing reasons at
  write AND read. Options are **computed** from gate reasons + claim dispositions — a model writes
  wording only — and the honest-park option exists by construction. **Counsel** (route a gate to
  Atlas/Quincy/Sentinel for a whole-project read) is DIRECTION with its own ADR; the invariant is
  already fixed: counsel drafts, the operator ratifies. **Pre-registered DoD:** clauses must not move
  `false_ship` (bench A/B validated by `experiment_report` before scoring) · the clause-resolution rate
  is watched as the rubber-stamping metric · C4 before any effectiveness claim · **MCB-05/15 is the
  first use case and the honest test**. [ADR-0082](../adr/ADR-0082-gate-decisions-and-standards.md),
  proposed — awaiting ratification.
- **Instruments (2026-08-04): "zero executed checks is never a pass."** #58 prompted the question
  *do we actually have the instrumentation to diagnose?* Two audits said no, twice over. **The ladder
  built to catch this class was itself inert:** `experiment_verdict` had **zero production callers**
  (an A/B whose arms never diverged still produced numbers — ADR-0081's own instance #4),
  `check_control_liveness.py` was wired into nothing and returned 0 on every finding, and 7 of 12
  knobs sat at C2 on "verified by inspection" prose. **And a live vacancy could manufacture ship
  evidence:** `check_structural_compliance` returned `True` = *satisfied* after executing **zero
  predicates**, reachable with no knob gate via the ADR-0079 claims path, and that verdict is the
  sole input to the #60 refactor vouch → `oracle_verified` → the gate. Reproduced end-to-end, then
  closed. Landed: predicates counted (requested AND run — a partially measurable ask no longer
  vouches, and a decoy definition no longer shadows the real target, both red-team findings);
  `run_scan([])` → `unavailable`, not `clean`; `experiment_report()` making ADR-0081 Decision 3
  mechanical (INVALID ⇒ **no numbers**); a forward ratchet on the liveness guard (a new sub-C4
  posture knob fails; the six existing are grandfathered **shrink-only**; evidence naming a
  non-existent test fails). New artifact:
  [architecture/control-register.md](../architecture/control-register.md) — every verdict-producing
  control with its rung, its evidence, and **what it reports when it checked nothing**. Red-team:
  3 rounds, 2 FIX-NOW fixed, 1 ACCEPT (the relocation class ADR-0072 already accepted twice; STOP
  rule respected) ([record](redteam-structural-vouch-2026-08-04.md)).
  **Pending the owner:** an ADR-0081 amendment extending the ladder past its bench-first scope
  (#58 = instance #5, in CI; the structural vouch = #6, in the product path) and wiring the guard
  into `make lint` — both CODEOWNERS-protected, drafted not taken. Accepted residual, documented
  with its reasoning: the `is_test_file` basename rule stays, because a location rule would
  misclassify *colocated* tests in user repos and deny independence → over-park, which is the
  dominant Gate-1 defect.
- **`#63` REDESIGNED AGAIN (2026-08-04, owner-directed): the ledger became the ENGINE view.**
  Converged over five throwaway HTML prototypes (no production code touched until the design was
  ratified) after the phase-grouped ledger + flow band were rejected as "not the flow". The run
  page now showcases the engine as a **team drawn from the run's own events**: an agent band
  (Quincy → Proctor* → Forge → Vera → Rook → Critic* → You → Drift; *conditional on that node
  having run — hygiene/scan fold into Vera, gate+operator into You), a subtle timeline strip, ONE
  work panel showing only the selected agent (shadcn/ai idiom: plan/chain-of-thought steps,
  terminal, check runs, tool-call blocks — no per-row dropdowns), and a closing **verdict band**
  ("Why this delivered" — every claim beside the check it stands on + how strong the proof is /
  "Why this run stopped") sealed by the RECORD strip. The band is a trace, not a diagram: send-back
  lanes exist only because that loop ran, are routed deterministically (one lane per return edge,
  stacked by span — declaration order cannot change the picture), and carry real counts. Edge
  state machine: exactly one edge animates (the one the run is traversing, live only), quiet once
  passed, red where a run died — an edge counts as crossed only when its TARGET was reached.
  Honesty carried over intact and re-pinned: claimSegments still owns the claim rule (an unchecked
  claim can never render PROVEN), a stopped run never speaks delivered language, and the ending is
  named for what it was (DECLINED / STOPPED BY AN ERROR / CANCELLED / HONEST PARK — a crash is not
  a park). Also fixed here: the run's events now come from ONE source in both modes (durable
  `run_events`, polled live), so a live page survives a refresh instead of restarting empty.
  Retired: `Ledger`, the row modules, `RowDisclosure`, the flow band, `lib/phases.ts`, `lib/flow.ts`
  (~1,700 lines deleted). Prior composition, superseded, below.
- **`#63` REDESIGNED (2026-08-03, owner-directed): the Receipt card became the LEDGER view.**
  The stacked ReceiptCard composition was rejected in favour of a chronological ledger — one
  numbered-rail timeline of the item's whole life (brief → Quincy's claim decomposition →
  clarification ask/answer → run start → gate events → operator answer → critic review →
  green DELIVERED table → sealed footer), with claims-summary chips + a DERIVED honesty badge
  ("NOTHING SHIPPED UNPROVEN" only when delivered ∧ every material claim satisfied). One
  component, two states: `/runs/:id` renders it LIVE (the delivery gate and intake clarify are
  INTERACTIVE ledger rows — GatePanel/ClarifyCard embedded, contracts untouched); `/history/:id`
  renders it SEALED + diffs. Enablers: migration 0020 (`runs.finished_at/engine_version/
  receipt_id` — the seal, deterministic sha256, never proxied when NULL), resolved
  clarifications retained (`status resolved|dismissed + resolution + resolved_at`; open-only
  field unchanged), and the previously-unread durable `run_events` stream now drives honest
  per-step chronology (decision timestamps cluster at persist and never order the ledger).
  Tool-level transcript demoted to the engine-detail drawer.
- **`#63` first cut (same day, superseded composition): Receipt view — the priced-residual receipt durable + rendered.**
  Implements ADR-0071 (the named residual at the approval moment), ADR-0079 (the `run_claims`
  ledger finally readable — it rides `run_detail`, no new endpoint), ADR-0063 (the receipt on
  the durable commit page). Core: `oracle_residual` + `tests_mutation_caught` now COMMIT into
  `gate_state` (previously live-only in the interrupt payload); persist writes an additive JSON
  `receipt` decision kind (the `critic` precedent — no migration; the flat `gate_decision`
  string stays byte-identical, it's a parsing contract). ADR-0078-compliant capture: a
  resilient giveup (a parking gate visit that never resumes) `_safe`-writes the receipt +
  claim ledger from the widened interrupt stash. Web: one shared `ReceiptCard` (gate line ·
  validation strength, shallow never green · humanized vouch · amber priced-residual callout ·
  claims table · critic veto) mounted at the live gate (GatePanel), the run evidence tab
  (Receipt replaces Gate — a strict subset), and the history page; per-run reports relocated
  from Artifacts into the Receipt tab; mutation tri-state rendered honestly (None = "not
  measured", never a verdict).
- **FULL-SUITE REBASELINE MEASURED (2026-08-04, 72/72; pre-registered 2026-08-03 BEFORE the
  run).** The new standing reliability figures at `405ded5`: **clean-conclusion 87.5%** (36
  clean_deliver + 27 honest_park) · **false_ship 6.9%** (MCB-05 ×2 + MCB-15 ×3, nowhere else) ·
  **delivery 50.0%** · 0 crashes. Predictions scored verbatim: **4 CONFIRMED, 1 narrow miss** —
  (1) clean-conclusion 88–92% → 87.5%, 0.5 pt below the band (the shortfall is exactly the four
  thrash_parks, all in the four historical thrash cases MCB-01/21/23/26); (2) false_ship
  confined to 05+15 at ~7% → exact; (3) **MCB-14 delivered 3/3 grader-passing** (was 20/20
  refused pre-#62); (4) delivery up materially → 50.0% vs 34.7–41.7% on the July-18 like-for-
  like sweeps; (5) no new thrash class. Rule-of-three at n=3: ≤63% per non-observing case
  (weak by design; the informative bound is suite-level Wilson ≈3.0–15.2%). The
  `rebaseline_80on_x3` 94.4% headline is RETIRED (not a like-for-like control). Record:
  [engineering-history/rebaseline-2026-08-03.md](rebaseline-2026-08-03.md).
  Path back above 90%: the four named thrash cases + the two grader-alignment calls.
- **Tracked (2026-08-02): `#59` [arc] MCB-D — operator-in-the-loop dialogue benchmark suite**,
  blocked by ADR-0079/0080 acceptance. MCB grades only the headless leg: Quincy has zero benchmark
  coverage, all 24 briefs are fully specified so ask-quality is unmeasurable (optimizing MCB
  selects AGAINST asking), and parks are graded as endpoints where the product treats them as
  messages. MCB-D = under-specified cases + a deterministic scripted operator (answer bank, never
  an LLM roleplay) + frontier metrics (ask precision/recall, decomposition fidelity, park
  actionability, resume-to-delivery, cost per delivered claim, interruption budget). Doubles as
  the ADR-0080 measurement instrument.
- **North-star amended (2026-08-02, owner-stated):** Mosaera's purpose widened — a guardrail for
  industry-standard engineering practice (zero-to-flagship senior team; greenfield foundations,
  brownfield assess-repair-or-rebuild), and Quincy as the operator's collaborative partner with
  grounded institutional memory (answers from recorded decisions, never guesswork). The flagship
  is governed collaboration, not full autonomy — see `architecture/north-star.md` §"What Mosaera
  is for".
- **Fixed (2026-08-02):** **terminal gate visibility** / ADR-0078 — the benchmark could not see WHY
  a run parked. A parking gate visit never resumes, so the gate node never commits its decision:
  `gate_reasons` was `[]` on **all 526 instrumented scorecards**, and `critic_vetoed` — derived from
  it — was `False` on **643/643**, i.e. ADR-0065's arc metric has been **structurally zero since it
  shipped** (a veto PARKS, and a park is the case whose evidence was discarded). The decision is now
  captured off the interrupt payload, as the live runner already did. ⚠ **Historical comparisons
  across this boundary are invalid — every pre-ADR-0078 `critic_vetoed: False` means UNMEASURED, not
  "no veto".** The frozen classifier (ADR-0069) is deliberately NOT fed the captured reasons, so the
  94.4% clean-conclusion figure is unmoved by construction.
- **ANSWERED (2026-08-02) — the held-out critic is NOT inert; it DECLINES.** Measured once
  ADR-0078 made vetoes visible. Wiring verified sound end-to-end (`outcome_verdict` DECLARED in
  RunState, node spliced on the `review→gate` edge, `critic_enabled` posture-ON, `held_out_ok()`
  True). Via the real `judge_outcome` path: a **blatant** MCB-05-shaped defect (0 helpers) →
  **VETO**, with correct reasoning quoting the spec — so model, prompt, parse and calibration all
  work. The **subtle** shape (3 helpers, 7-statement body — MCB-05's *actual* defect per ADR-0072)
  → **no confident verdict → no veto**. Live: MCB-05 ×3 → 0 vetoes; MCB-10 ×3 → 0 vetoes (no
  over-veto). So the 643/643 was **two things compounded**: the ADR-0078 blind spot *and* the
  critic correctly refusing a judgement it cannot make ("when unsure, SHIP" — the safe direction).
  *Not established:* whether that abstention is genuine uncertainty or an empty/unparseable reply;
  the raw-capture harness used was flawed and its output is discarded rather than reported.
- **What that implies for Gate 2.** MCB-05's defect is a **fuzzy shape judgement** ("a handful of
  statements"), and BOTH roads to it are currently compromised: an LLM judge **abstains** (confirmed
  here; [ADR-0070](../adr/ADR-0070-independent-spec-review.md) already measured that path net-null),
  while a deterministic rule **can** call it but only via an arbitrary constant
  ([ADR-0072](../adr/ADR-0072-structural-spec-oracle.md)'s `max_body=6`, contradicted by MCB-15's ≤7).
  That is exactly why the structural oracle converts MCB-05 3/3 where the critic cannot — and why it
  does so through the *unsound* check. **Next arc: ADR-0072's named successor** — measure the
  orchestrator against its own PRE-REFACTOR self (the diff's old side), which removes the constant
  and is the only option on the table that is neither an abstention nor a guess.
- ⛔ **ACTIVATION WITHDRAWN (2026-08-02, same day) — the conversion did not replicate.** The
  n=3 result below (MCB-05 3/3 `false_ship` → 3/3 `honest_park`) was sampling noise: a frozen
  n=25/arm interleaved A/B (100 runs, `MOSAERA_BENCH_STRUCTURAL_SPEC_OFF`) shows **no effect** —
  MCB-05 ON 21/25 vs OFF 23/25 `false_ship` (Fisher two-sided p=0.667), MCB-15 ON 25/25 vs OFF
  24/25 (p=1.0), pooled p=1.0. The **safety half held**: 0 false-parks in all 100 runs (95% upper
  bound ~3%, rule of three), superseding the static 0-of-20-references bound below. Ambient
  false-ship on these two cases is 84–100% in BOTH arms — beyond `qwen3-coder:30b` regardless of
  gating (a model-capacity observation). `oracle_structural_spec` removed from `_posture.py`
  (knob stays, default OFF); the pure check + bench lever retained for re-test once acceptance
  claims are first-class. Full record:
  [engineering-history/structural-oracle-ab-2026-08-02.md](structural-oracle-ab-2026-08-02.md).
  **Red-team: DONE, 1 revert-scoped verification pass** (the successor itself had its own 3
  rounds, above): no residual activation via stored settings (`.mosaera/settings.json` carries no
  structural key); the gate conjunction is untouched by the revert (`structural_ok` unchanged,
  absent-key → no effect, deny-by-default preserved); the documented re-measure path verified
  live (env ON → posture True; + bench OFF-lever → False). Anti-gaming note addressed: this
  superficially resembles "weaken a gate to improve a benchmark," but the removed check had a
  **measured-zero** effect (pooled p=1.0, ON/OFF arms indistinguishable) — there is no benchmark
  benefit to gain, and the revert returns to the previously red-teamed baseline. 0 findings.
  *Kept below as the record of how the activation was carried and retired:*
- ~~✅~~ **RISK ACCEPTANCE RETIRED (2026-08-02, same day) — the successor landed.** The unsound
  `max_body` constant is gone from the bare-"handful" path: shape is now measured **relatively**,
  against the function's own pre-refactor body (the diff's old side via `HEAD`). Measured on the
  known-correct references — MCB-05 8→4 statements (50%), MCB-15 8→3 (38%), both 1 loop → 0 —
  versus 7-of-8 (88%) for a delivered-but-wrong shape. **One dimensionless ratio (2/3) separates
  both references from that, where no absolute could separate MCB-05's ≤6 from MCB-15's ≤7.** Plus
  a genuinely constant-free companion: an orchestrator that shrank but STILL ITERATES kept the work
  it was asked to delegate. Deny-by-default preserved — **no pre-refactor body → no claim**, so
  greenfield is inert rather than judged against an invented number. 0 false-parks across all 20
  references; engagement still confined to the 2 refactor cases. The retire-signal test fired and
  was replaced by the successor's proof. **Measured** (×3/arm): MCB-05 3/3 `false_ship` →
  3/3 `honest_park` (identical to the unsound version, constant removed); MCB-15 ON prevents a
  `false_ship` the OFF arm shows (0/3 vs 1/3) and lifts Governance 67 → 83 — **at a measured
  cost: MCB-15 delivery 2/3 → 0/3, with 1 of 3 parks refusing grader-passing code.** Safe
  direction, real cost, n=3. **Red-team DONE** (3 rounds): 2 FIX-NOW — nesting could hide the
  body (the SAME defect ADR-0072's first red-team found, whose mitigation was never written
  because that check was dropped), fixed by counting statements in full; and a false-park
  generator on small originals, fixed with a floor DERIVED from the brief's helper count.
  1 ACCEPT: relocating the target leaves no baseline and the check goes inert — the
  deny-by-default contract, returns to the pre-oracle baseline, opens no new false-ship
  channel. STOP rule not triggered. **Open:** widen the false-park measurement before
  tightening the 2/3 ratio.
  *Superseded, kept as the record of how the accept was carried:*
- ~~⏳ **EXPIRING RISK ACCEPTANCE — review by 2026-11-02 or at v1.0 release-readiness, whichever is
  first.**~~ The **structural-spec oracle** (ADR-0072) was ACTIVATED in the autonomous posture on
  2026-08-02 because it converts the Gate 2 blocker: MCB-05 (**48/91 = 52.7% false_ship** on record)
  went **3/3 false_ship → 3/3 honest_park**, overall 74-77 → 90-94. Comprehensive mutation
  (ADR-0071) moved it **0/3** — a different class. **But the catch rests on the `max_body` statement
  count ADR-0072's own red-team called provably unsound**, whose "drop it" disposition was recorded
  and never implemented (MCB-05 and MCB-15 use near-identical language, both extract `max_body=6`,
  graded ≤6 and ≤7). Bounded and pinned by tests: engages on **2 of 22** cases, false-parks **0 of
  20** known-correct references, error direction is honest-park-never-false-ship. **At the review it
  must be retired, re-justified, or withdrawn — not renewed by silence.** Successor: a RELATIVE
  measure (orchestrator body vs its pre-refactor self, from the diff's old side) which removes the
  magic constant entirely — ADR-0072 §Successor. Re-measure with
  `MOSAERA_BENCH_STRUCTURAL_SPEC_OFF=1`.
- **Shipped (2026-08-02):** `#81` **language-native convergence signal** / ADR-0077 — a LanguagePack
  now interprets its OWN result into a structured `TestReport`, so the engine stops regexing pytest
  out of every language's stdout. SQL became countable (`SQL_BOOTSTRAP` tallies instead of aborting
  on the first assertion); Node's count was **wrong, not missing** (jest/vitest double-counted the
  per-file summary line → 4 when the answer was 3; mocha yielded nothing) and is now correct. The
  honest no-signal STOP (decision 6) is **built, activation HELD — and (corrected 2026-08-02) the
  measurement behind the hold was VOID**: the knob's only behavioural read (`convergence.py`,
  `_no_signal_path`) is reachable only when the validator yields no countable result, and #81 made
  MCB-26 (SQL) countable — so the "ON arm" A/B ran byte-identical code (the distinctive reason
  string appears in 0 of 1,233 scorecards, ever; "Reliability 67 vs 83, +22% tokens" was
  run-to-run noise). The hold STANDS, for the honest reason: **not measurable on the current
  suite** — MCB-02 (static-site, the obvious uncountable case) stalls in 1 of 76 recorded runs,
  on a different path; the mechanism needs identical-repeated failure against an uncountable
  validator, a conjunction the suite never produces. **Open:** a purpose-built case (tracked
  issue) before any activation decision. **Red-team DONE** (3 rounds): 1 FIX-NOW — the untrusted
  workspace could FORGE a count line (its own test output is parsed), fixed by taking the last
  match + line-anchoring; bounded pre-fix (no count reaches the gate, `tests_passed` is exit-code
  derived, so thrash not false-ship). R2/R3 clean; STOP rule not triggered.
- **Experiment (2026-08-01, no ADR):** *Acceptance Differential Probe* Stage 0 — offline test of
  whether an independently-authored implementation detects an over-strict authored suite. Result:
  **INCONCLUSIVE (underpowered, leaning positive)** — precision 1.00 but on only 5 FAIL events
  (Wilson 95% low 0.57), recall 0.36, assertion overlap 0.78, **0 false positives / 47 rows**. No
  abandon threshold fired; no ADR is authorized on this evidence. Two durable findings: the
  over-strictness label is **stochastic** (9/22 cases flip across repeats — single-pass
  `overstrict_vs_ref` is noise), and the sweep banked a **labeled corpus of provably over-strict
  assertions** for extending `faithfulness.py`'s deterministic detectors. Full record:
  [`engineering-history/probe-stage0-2026-08-01.md`](probe-stage0-2026-08-01.md).
  Note this targets **delivery rate**, not Gate 2 — it does not change the sequence above.
