# ADR-0077: Language-native convergence signal — a run concludes honestly in every language

- Status: accepted (decisions 1–5 landed; **decision 6 built + measured, activation HELD** —
  see §Measured result. **red-team DONE — 3 rounds, 1 FIX-NOW fixed pre-merge**, §Red-team)
- Date: 2026-08-02
- Owners: @Ashura
- Related issue: `#81` (non-pytest convergence signal)
- Amends: [ADR-0060](ADR-0060-honest-stop-lean-engine.md) (the no-count branch was deliberately
  left as a thrash park — see §The amendment)
- Related: [ADR-0032](ADR-0032-adding-a-languagepack.md) (the pack seam this extends),
  [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (`strength` — the contract hole),
  [ADR-0059](ADR-0059-coder-reliability-toolkit.md) (the convergence signal),
  [ADR-0026](ADR-0026-tamper-to-escalation.md) (DECLARED state keys)

## Context

`graph/nodes_impl.py` forked the fix loop on one question: could a failing **count** be parsed out
of the validator's stdout?

- **Count present** (pytest) → `bump_progress` best-so-far tracking → `wont_converge` projection →
  a trip routes to `supervise`, a budget-aware *decision* node → `give_up_reason` with
  `stalled=False` → `classify_outcome` → **`honest_park`**.
- **Count absent** → the fingerprint breaker → `stalled=True` → `route_after_test` **skips every
  self-heal loop** and falls to the gate → bucketed **`THRASH_PARK`**.

So a `kind=sql` run whose psql error was byte-identical three times parked as *thrash*, while an
identical pytest run took the honest ladder. **Same failure, different label, purely because one
runner prints a number.** That is `#81`, and it is half the remaining gap to 100% clean-conclusion.

Three things made it worse than a missing feature:

1. **`SqlPack` declared `strength="suite"`** (ADR-0034) while producing nothing countable — a pack
   asserting suite-grade worth with no measurable result.
2. **The coder got no feedback at all** on that path: `_convergence_line` returned `""` when the
   count was `None`, so it saw raw psql text with no indication its last edit changed anything.
3. **Node's count was WRONG, not missing.** `parse_failing_count` sums every `N failed` match and
   every major JS runner prints two — one per-file, one per-test. Measured: jest
   `Test Suites: 1 failed` + `Tests: 3 failed` → **4**; vitest the same; mocha's `3 failing` matched
   nothing and yielded `None`. A wrong count feeds the best-so-far tracker, so a run improving 4→3
   could read as 5→4.

The precedent was already in the repo: `bench/grade.py` normalises pytest, a node driver and psql
to one uniform `N passed, N failed` line. The *grading* path solved this; the *engine* never did.

## Decision

**A LanguagePack owns the reading of its own result, not just the building of its command.**

1. **`TestReport`** (`mosaera_core/testreport.py`) — a frozen, JSON-safe result
   (`failed`/`errors`/`total`/`passed`/`failing_ids`). `.failing` sums failures and errors.
2. **`LanguagePack.interpret(outcome) -> TestReport | None`**. `None` means *this pack genuinely
   cannot count* — an honest no-signal, explicitly **not** zero failures, because zero would tell
   the best-so-far breaker the run is perfect.
3. **`ValidationPlan.pack_name`**, stamped by the registry (the only thing that knows which pack won
   the confidence contest). A **string**, never the pack or a callable: the plan is checkpointed
   into `RunState` and LangGraph checkpoints must stay JSON-serializable. An unstamped plan (the
   operator's `--test-cmd`, or a pre-`pack_name` checkpoint) falls back to the old parser.
4. **SQL becomes countable.** `SQL_BOOTSTRAP` runs each `tests/*.sql` individually and tallies,
   instead of aborting on the first under `set -e`.
5. **Node becomes correct.** `NodePack.interpret` reads the runner's per-*test* summary, anchored on
   the runner's label so the per-file line cannot match. Unrecognised summary → the generic parser,
   so an unknown runner is never *newly* blind.
6. **The no-count branch climbs the same ladder** (knob `honest_stop_no_signal`):
   reason → supervise → `stalled` only at/over the cap. **Ships default OFF — built and
   measured, activation HELD; see §Measured result.**

### The amendment to ADR-0060

ADR-0060 deliberately left this branch as a thrash park, reasoning that with no count signal a
relabel *"flatters the metric"*. **That reasoning was correct when it was written and is now
narrower.** It rested on an implicit premise — that no language could count — which decisions 4 and
5 remove. What remains uncountable is genuinely uncountable: a well-formedness check, a schema that
never applied, an operator `--test-cmd`.

For those, the conclusion is *earned*, on the same evidential standard #56 set:

- the trip fires only **after real fix iterations** (`route_after_test` sends the run to `fix` until
  the streak reaches `stall_limit`);
- the give-up lands **strictly below the cap** — rode-to-cap remains thrash (rung 3);
- and the reason names a **concrete failure signature** (`first_error_lines`), not an anonymous
  "failed the same way N times". A human reading the park learns what failed.

Only the *unit* of evidence differs from #56: an identical outcome rather than a flat count trend.

## Security — the invariant this could have broken

`stalled` is **overloaded**. Three producers set it: the no-progress breaker, the **tamper** branch,
and rode-to-cap. `route_after_test` checks `stalled` *before* `progress_trip` precisely so a
tampering run can never earn a supervise re-scope (ADR-0060; the same invariant `#82` is parked on).

**Only one producer moves.** The tamper branch is untouched and returns earlier in `test_node`, so
the ordering that enforces the invariant is unchanged. Pinned by
`test_tampering_with_an_uncountable_validator_still_stalls`: a tampering run with uncountable output
still sets `stalled`, never populates `progress_trip`, never reaches `supervise`, and still
classifies `thrash_park`.

## Measured result — decision 6 ships DORMANT (activation HELD)

MCB-26 (`kind=sql`, the exact case `#81` was diagnosed on), ×3 per arm, local models,
`MOSAERA_BENCH_HONEST_STOP_NO_SIGNAL_OFF` as the lever:

| | ON | OFF |
|---|---|---|
| Capability | 79 | 77 |
| Implementation | 100 | 100 |
| Validation | 50 | 42 |
| **Reliability** | **67** | **83** |
| Autonomy | 30 | 30 |
| Efficiency | 93 | 96 |
| Tokens | 509,718 | 416,984 (**+22% on ON**) |

**The predicted conversion did not happen, and the metric that would have shown it moved the wrong
way.** Reliability is the score that rewards concluding below the iteration cap — exactly what
decision 6 was meant to buy — and it is *worse* on the ON arm. Autonomy and Governance are
identical, so nothing shipped either way.

Two honest readings, both recorded:

1. **Decision 6 does not apply to MCB-26 any more.** Stage 2 gave SQL a real count, so the run now
   takes the *counted* path; the no-signal ladder never fires for it. `#81`'s original diagnosis
   ("stalls with NO pytest failing-count") was fixed by decisions 4–5, not by decision 6.
2. **There is a plausible mechanism for active harm.** A granted re-scope consumes iterations; if
   the re-scoped episode also fails, the run rides to the cap — which is thrash, i.e. *worse* than
   the immediate park it replaced. The Reliability delta is consistent with that.

`n=3` with a stochastic local model is underpowered, so this refutes nothing outright. But the rule
is that an activation must be *earned*: absent measured benefit, shipping it ON would be exactly the
metric-flattery this ADR's own STOP rule names. **`honest_stop_no_signal` therefore defaults OFF** —
the mechanism is built, tested (including the tamper regression) and one flag away, the same
disposition ADR-0066 took after its ON arm showed a `false_ship` the OFF arm did not.

MCB-26 also reports **Implementation 100 with its own validation failing** — the hidden grader
passes code the run's own authored SQL assertions reject. That is the *over-strict Proctor* class,
a different defect from `#81`, and it is what actually blocks this case.

## Red-team — DONE (3 rounds, 2026-08-02)

Scoped to the merged change (the `interpret` seam + the no-signal ladder), not the codebase.

**R1 — forged/mis-parsed counts. FIX-NOW, fixed.** The `interpret` hook produces a number the
best-so-far breaker trusts, and **the untrusted workspace controls the text it is parsed from**: a
`tests/*.sql` file's `SELECT` output is echoed into the validation output, and a JS test file can
print anything. Both parsers took the *first* match, so a forged line beat the real one — measured
`failing=0 passed=999` against a truth of `1/1` (SQL) and `0/99` against `3/5` (Node).
*Blast radius was bounded:* `test_failing_now`/`test_report` have exactly two consumers (the
breakers and the coder prompt); no count reaches `evaluate_gate`, and `tests_passed` comes from exit
codes — so **no false-ship path**, worst case riding to the cap (thrash + token burn, bounded by
`max_iterations` and the budget gate). Fixed anyway: take the **last** match (the real tally is
always emitted last) and, for SQL, anchor at line start (psql indents result rows). Regression tests
added.

**R2 — escaping the breakers via the no-signal path. FALSE-POSITIVE / no finding.** Forcing
`interpret` to return `None` every iteration (emit `schema-error` forever) does **not** escape: the
fingerprint breaker still trips (verified, 6 identical iterations → `stalled`). `None` is never read
as zero failures (verified: `test_failing_now is None`, `test_report` absent). A descending trend
that avoids both breakers turned out to be a genuinely *converging* run — correct behaviour, not an
escape.

**R3 — laundering + state integrity. No findings.** `pack_name` is stamped only by `dispatch()`
from the `REGISTRY`; the workspace never supplies it and `interpret_outcome` receives the *live*
plan, not one rehydrated from state. Hostile/stale values (`""`, `"../../etc"`, `"python "`) fall
back to the generic parser rather than raising or losing signal. The tamper branch **precedes**
`convergence_update` in `test_node` *and returns*, verified by source inspection — so a tampering
run provably cannot reach any of the new code.

**STOP rule: not triggered.** The pre-committed class was *metric flattery*; R1's class (forged
counts) appeared once, was fixed, and did not recur in R2 or R3.

## Consequences

- A SQL/Node/no-signal run now concludes as `honest_park` where it was bucketed `thrash_park`.
  **This moves a reliability metric, so it ships behind a knob** (`honest_stop_no_signal`) giving a
  one-flag rollback and a clean bench A/B.
- `disposition._failing_test_files` is deliberately **not** rewired to `TestReport.failing_ids`: it
  parses uncapped because it is a *security subset check*, while `failing_ids` is display-capped.
  Connecting them would open a supersession-allowlist hole.
- `bench/reliability.py` is driven as a **consumer only** — the frozen classifier gains no bucket.
- Two new DECLARED `RunState` keys (ADR-0026): `test_report`, `test_repeat`.

## Alternatives rejected

- **Make SQL emit a pytest-shaped line** (the cheapest fix, and what `bench/grade.py` does). It
  works, but leaves the contract implicit — a language *pretending* to be pytest — which is the
  thing `#81` says is wrong. The typed hook makes "I cannot count" a first-class, testable answer.
- **Structured signal only, leaving the `None` branch as thrash.** Insufficient: `static_site`,
  `config_data` and any operator `--test-cmd` can never count, so the dishonest branch would
  survive for exactly the repos Gate 3 ("drops into *any* repo") cares about.
- **Narrow `PythonPack.interpret` to the pytest step's own output.** Tempting (today's aggregate
  read means an install-phase "1 error" counts), but it is a real behaviour change to the
  best-tested path and needs its own evidence. Deliberately not smuggled into this arc.

## Definition of done

- [x] Stages 0–5 landed, each with the four gates green.
- [x] Python proven a strict no-op (golden equivalence test + the honest-stop integration block
      passing unedited).
- [x] Tamper regression asserted.
- [x] **Red-team, 3 rounds — DONE** (see §Red-team; 1 FIX-NOW, fixed)
      Pre-committed STOP rule (*metric flattery*) **did not trigger** — R1's class appeared
      once, was fixed, and did not recur.
- [x] **Bench:** MCB-26 ×3, both arms — RUN. The success criterion was **not met**; see
      §Measured result. Decisions 1–5 ship ON; decision 6 ships **OFF (activation HELD)**.
- [ ] **Re-measure decision 6** against a case that still has NO countable validator (static-site
      or config-data), since MCB-26 no longer exercises it. Until then the knob stays OFF.
      **Still open as of 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`): `honest_stop_no_signal` is still default `False` and no
      such case exists. This box is the ONLY live tracker — `docs/roadmap.md` has no entry, while
      `bench/liveness.py` cites "roadmap Open", a pointer to an item that does not exist.
