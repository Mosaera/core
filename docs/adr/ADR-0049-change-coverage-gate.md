# ADR-0049: The change-coverage gate — runtime coverage replaces the import heuristic

- Status: accepted
- Date: 2026-07-17
- Owners: Alejandro Rengifo
- Related: [ADR-0044](ADR-0044-oracle-make-real.md) (the coarse import heuristic this replaces),
  [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (only executed evidence ships),
  [ADR-0036](ADR-0036-test-integrity-baseline.md) (tamper-guard), issue `#29`

> **Amendment (2026-08-01, #81 cleanup) — P3 part 2 was BUILT THEN DELETED; it does not exist.**
> The **gap-fill token-saver** described in *P3* below (the opt-in `coverage_gap_fill` knob, the
> `gap_fill_node`, and the `uncovered_executable` / `uncovered_changed_lines` / `gap_fill_attempts`
> / `gap_fill_log` state) was removed by
> [ADR-0060](ADR-0060-honest-stop-lean-engine.md) (*"Knobs: removed `coverage_gap_fill`,
> `react_on_bad_test`; posture 6 → 5"*), which also dropped the associated state fields.
> `packages/core/tests/test_graph_build.py` asserts `"gap_fill" not in nodes`, and no `gap_fill*`
> symbol remains anywhere in `packages/` or `apps/`. **P0–P2 and the P3 region adapter + ledger
> write-wiring shipped and are live; only the gap-fill sub-feature is gone.** The P3 prose is kept
> below as the historical record of what was decided — it is not a description of current
> behaviour. Read [ADR-0060](ADR-0060-honest-stop-lean-engine.md) for what actually runs.
>
> Separately noted while auditing: the coverage-region **ledger is written every run but never read
> back** — the P3 impact-selection consumer was never wired. Tracked as debt in
> [`docs/roadmap.md`](../roadmap.md).

## Context

ADR-0044 credited a pre-existing "standing suite" as an independent oracle for a change via a
**coarse static import heuristic** — does a baselined test *import* a changed module? That heuristic
took **four** adversarial rounds to harden (attribute-name → imported-symbol-name → single-segment
stdlib-shadow collisions) and still has inherent residuals: it answers "does a test *mention* the
changed module", never "does a test *execute the changed lines*". A test can import a module and
touch none of the changed code, and the heuristic still credits.

The durable fix has always been runtime **coverage**: run the suite, see which changed lines a test
actually executed. This is the F1 class's real death — an untested change cannot masquerade as
covered when we *measure* execution.

## Decision

Introduced across the coverage arc (`#29`); this ADR records P0 (foundation, merged) + P1 (the gate):

- **P0 — the primitive (`coveragemap.py`).** Run the suite in the sandbox under `coverage` with
  per-test **dynamic contexts** and read the `.coverage` on the host into a two-way code↔test map
  (`CoverageMap`: `covered_lines` / `tests_by_line` / `lines_by_test` / `executable_lines`). Plus
  the shared scaffolding — the `oracle_coverage` knob (env + settings) and the
  `RunState.changed_lines_covered` field — and `coverage` in the sandbox image (a CODEOWNERS infra MR).

- **P1 — the gate.** When `oracle_coverage` is ON, `test_node` runs coverage on a GREEN run and
  computes `coveragemap.change_is_covered` → `RunState.changed_lines_covered`:
  - **True** — every changed `.py` file's executable changed lines are covered by a test.
  - **False** — some changed file is UNMEASURED (no test runs it — the F1 case) or has an executable
    changed line that ran under no test.
  - **None** — no changed `.py` source lines to judge (docs/config/no-op), or coverage was
    unmeasurable (off / not in the sandbox image).

  `gate_node` passes it to `standing_suite_is_independent_oracle(..., covered=...)`, which now
  decides relevance **precisely** from coverage — replacing the import heuristic — *after* the
  assertion floor still gates (a suite must ASSERT something real; coverage can't credit a
  tautological suite). `None` **falls back** to the coarse heuristic (and its F-B inertness check for
  non-`.py` behavioural changes), so behaviour is unchanged when coverage is off or can't run.

**Deny-by-default throughout:** a changed file no test measures is treated as uncovered; `None`
never fabricates credit. Memoized by `tree_hash` (≤1 instrumented run per distinct tree). Opt-in
(`oracle_coverage` default OFF) until its cost/false-park rate is measured on real repos.

## Consequences

- The F1 defect *class* dies for the coverage path: an untested brownfield change can no longer
  credit `oracle_verified` by a green-but-irrelevant suite — coverage shows no test runs it → park.
- The coarse import heuristic is retained as the **fallback** (coverage off / unavailable), so
  nothing regresses when `oracle_coverage` is off; it is no longer the *only* answer.
- Cost: one extra instrumented sandbox run per green iteration when enabled (memoized). Needs
  `coverage` in the sandbox image (shipped).
- **This change touches the oracle (a trust-boundary path) → it is red-team-required** (the scoped
  red-team protocol): P1 is the *durable successor*, so it earns the real adversarial pass, and the
  old heuristic's residuals become DEFER-TO-SUCCESSOR = this gate.

## Red-team round 1 (2026-07-16) — dispositions

Two adversarial agents ran against P1 as its definition-of-done. Six findings; all recorded here so a
future session does not re-derive them.

**FIXED-NOW (real orchestration bugs — were latent until the coverage image ships):**
- **B1 (critical false-park):** `run_coverage` called `analysis2(relative_path)`, which resolves
  against the *host* process cwd (never the run workspace) → `NoSource` → `executable_lines` silently
  empty → `change_is_covered` returns `False` for *every* tested change. Fixed: pass `str(root / f)`
  (absolute); logic split into unit-testable `read_coverage_data`; regression test runs a REAL
  coverage suite and reads it with the host cwd elsewhere.
- **B2 (destructive):** it wrote/deleted the repo's own `.coveragerc`/`.coverage`. Fixed: unique
  `.mosaera-coveragerc` + `.mosaera.coverage` (via `data_file`), cleaned in `finally`.
- **B3 (false-park):** it used host `sys.executable` (→ container *system* python, not the repo's
  `.venv`) and only bailed on `passed is None`. Fixed: run under `.venv/bin/python` when present;
  bail on ANY non-pass (a red/broken coverage run → `None` → heuristic fallback, never trusted as
  "measured nothing = uncovered").
- **A3 (parser):** an added content line whose text starts with `++` was mistaken for a `+++` header,
  dropped, and mis-numbered the rest of the hunk. Round-2 verify caught that "require a space" was
  necessary-not-sufficient (`++ danger()` → `+++ danger()` WITH a space also slips through). Final
  fix: `+++ b/…` is consumed by the `_FILE` regex first, so `+++ /dev/null` is the ONLY real `+++ `
  header reaching the filter — match it EXACTLY; every other `+++`-prefixed line is content. Closes
  both variants; regression-tested.

**DEFER-TO-SUCCESSOR / documented residuals (NOT fixed here — by design, not oversight):**
- **A1 (false-credit — the important one):** line coverage credits a changed line on an *unexecuted
  branch / short-circuit* (`or check_token(token)` → `or True` on its own line: the statement ran, the
  operand never did). This is an **inherent limit of line coverage** — it answers "was the changed
  *line* executed", not "did the changed *sub-expression* execute". The precise answer is the
  **mutation check** (`oracle_mutation_check`, ADR-0034-adjacent): mutating that line and confirming
  the suite goes red *would* catch the backdoor. **Guidance: enable `oracle_coverage` together with
  `oracle_mutation_check` for branch-precise crediting.** Chasing perfect line-coverage precision is
  the rabbit-hole the red-team protocol exists to stop; the successor already exists.
- **A2 (pre-existing):** a *source* file named `test_*.py` is dropped by `is_test_file` before coverage
  and then by the heuristic → credited by an irrelevant suite. Inherited from `is_test_file`
  classification, affects the whole oracle, narrow (shipping a source file with a test name is an
  anti-pattern). Logged for a future `is_test_file` review; not introduced by P1.

**Refuted (attacked, held):** `covered=False` cannot veto a `tester_vouched`/`--test-cmd` credit (the
OR-structure short-circuits correctly); the assertion floor still gates before `covered`;
memoization is correct; `changed_lines_covered` is declared in `RunState`; per-test contexts parse.

**Round 2 (verify the fixes):** a second adversarial pass CONFIRMED B1/B2/B3 hold with real repros
(nested packages, Windows backslash paths, both sandbox backends, no diff leak) and caught the A3
gap above — now closed. No new false-credit/false-park in the fixes. Disposition **complete**; the
STOP rule never fired (findings were distinct, not a recurring class).

## P3 — the region adapter + ledger write-wiring + the gap-fill token-saver (`#35`)

P2 (`#32`, merged) shipped the durable ledger (`coverage_ledger`, Alembic `0014`, `CoverageMixin`)
but left its consumer for P3 — and the two arcs use *different* granularities that must be bridged.
That bridge is the load-bearing P3 decision (surfaced by the cross-arc review on `#35`):

- **Region model = `file::qualname`.** P1's `CoverageMap` is LINE-level; P2's ledger is REGION-level.
  `coverage_regions.py` (new, `packages/core`) buckets each covered line into its enclosing function
  via AST (`extract_regions` — methods/nested/decorator spans), keyed by the *same* `file::qualname`
  identity P2 fingerprints on. Fingerprints reuse `mosaera_memory._fingerprint` verbatim — the single
  source of truth for the region contract, so the two arcs cannot diverge.
- **Label normalization (the subtle part).** Coverage's `dynamic_context = test_function` emits DOTTED
  labels (`test_calc.TestCalc.test_mul`) whose module prefix drops the directory when the test dir is
  not a package — so the pytest nodeid can't be reconstructed from the label alone. We recover the
  test FILE unambiguously from `lines_by_test` (a context also covers its own test file's lines) and
  rebuild `path::A::b`. Verified empirically against a real `dynamic_context` run before coding.
- **Write-wiring.** `test_node` persists the covered regions to the ledger on a GREEN coverage run
  (once per distinct tree, reusing the instrumented run it already paid for). Per-project via
  `get_run(run_id).project_id`; **deny-by-default + best-effort**: no store / no project (headless) /
  unreadable source → skip silently, and it **never** affects the gate verdict.

**The gap-fill token-saver (P3 part 2, opt-in `coverage_gap_fill`, needs `tester_enabled`).** A new
deterministic self-heal loop `test → gap_fill → test`, mirroring the `hygiene_fix` loop but invoking
the TESTER (not the coder): on a GREEN run whose coverage shows changed lines under no test,
`test_node` stashes `uncovered_executable(cmap, changed_src)` and `route_after_test` diverts to
`gap_fill_node`, which has the tester author delta tests targeting ONLY those lines (via
`gap_fill_instruction`), then loops back to `test` to re-measure (a new test file changes the tree
hash → the coverage memo self-invalidates). **Capped at one pass** (`gap_fill_attempts < 1`); a
residual gap after that parks honestly at the gate.

- **Honest value — NOT a gate flip.** On a tester-enabled run `tester_vouched` usually already makes
  `oracle_verified` True, so closing the gap does not change the *verdict*. The value is real coverage
  of the change, a stronger mutation signal, ledger compounding, and catching bugs on
  previously-untested changed lines (a red delta test = untested-and-broken code found).
- **False-park landmine (the load-bearing correctness point):** a delta test that touches an
  already-baselined test would trip the tamper guard on re-measure. `gap_fill_node` **merges** the new
  hashes into `tests_baseline` and **unions** `authored_tests` (a plain list, not a reducer) so earlier
  authored tests stay in the integrity ignore-list; `tests_red_verified`/`tests_assert_real` are left
  untouched (these are post-impl green delta tests). Regression-tested.
- **Weak-tester risk → red-team-required:** an over-specified delta test can flip a deliverable green
  run red. Mitigated by the hard instruction constraint (pass on the current code, assert only
  implemented behaviour) + the existing over-specification→supervisor escalation valve. This touches
  the run-loop/oracle, so it earns a red-team disposition as its definition-of-done.

**Gap-fill red-team (round 1, 2 agents) — dispositions.** The loop is sound (verified: terminates in
every branch, compiles in all knob combos, no dropped state, no oracle-verdict write, `tester_vouched`
unflippable). Findings:
- **A-1 (a delta appended to a PRE-EXISTING test module tripped `tampered_integrity`) → STOP-RULE
  ESCALATION.** Round-1 tried to fix it by re-baselining `integrity_baseline` for the tester-touched
  paths — round-2 showed that was doubly wrong: it used the wrong hash space (raw `hash_files` bytes
  vs the guard's newline-normalized `_integrity_content` → *still* false-parked on CRLF/Windows) and,
  worse, would silently ACCEPT a tester WEAKENING a pre-existing test (an ADR-0036 regression).
  "Re-baseline whatever the tester wrote" fundamentally can't distinguish a legit append from a
  weakening — that is exactly the **mutation check's** job. So (2 rounds on the tamper-baseline class
  → STOP rule) the re-baseline was **reverted**: gap-fill authoring is **new-files-only** (the
  instruction), a pre-existing-test edit hits the **deny-by-default tamper park** (safe + honest), and
  the legit-vs-weakening distinction is DEFERRED to `oracle_mutation_check`. The `tests_baseline` merge
  (same hash space as its guard) + `authored_tests` union stay.
- **B-4 (starvation) FIXED:** gap_fill no longer increments `iteration` — it runs the tester, not the
  coder, so it must not spend the coder's fix budget (else a red delta near `max_iter` starves the fix
  loop). Bounded by `gap_fill_attempts`, not `iteration`.
- **A-2a (over-specified delta parks) ACCEPTED (by design):** a red delta routes to `fix` — which is
  gap_fill's *bug-catching* value (a red delta on previously-untested code = a real bug) — or escalates
  via the existing over-specification valve; with B-4 fixed it has full budget. The honest-park
  residual on a genuinely bad delta is the opt-in cost.
- **A-2b / A-3 (coverage credits execution not assertion; mutation test-set swap) DEFER-TO-SUCCESSOR:**
  the known A1 line-coverage residual — gap-fill makes it more reachable, but the successor is the
  **mutation check** (STOP rule: same class, planned successor, don't chase). **Guidance: pair
  `coverage_gap_fill` with `oracle_mutation_check`.**

## Holistic arc red-team (2026-07-17, whole assembled oracle) — dispositions

Two agents attacked the *composition* (coverage + ledger + gap-fill + mutation + gate), not the pieces.
Verified sound: the ledger is write-only from the gate's view (no poisoning), gap-fill can't flip
`tester_vouched`, the memo self-invalidates across the gap-fill loop, all 32 knob-combos compile,
termination bounded. Two real findings:

- **B-1 (HIGH crash-safety) FIXED:** the coverage/ledger block in `test_node` was unguarded, so a DB
  blip (`_persist_coverage_ledger`) or a corrupt/version-skewed `.coverage` (`run_coverage`) would
  crash a GREEN run into `status='error'` + discard the diff (latent until coverage is enabled).
  `run_coverage` now returns `None` on any read/orchestration fault (→ heuristic fallback) and
  `_persist_coverage_ledger` wraps its DB calls (→ skip the side-record) — mirroring the runner's
  `_safe` "memory writes must never break a run" discipline; the gate verdict is untouched.
- **A-1 (MEDIUM false-credit) DEFERRED — sharp:** coverage credits *execution*, its A-2b successor is
  the mutation check — but `_mutate_source` only mutates `return X`/comparisons, so for a **non-mutable**
  change (`list.append`, an attr/dict assignment, an audit-log call, `session.query().delete()`) it
  returns `None` *without running the suite*. So even in the hardened config (coverage **+** mutation),
  a non-mutable change with a non-asserting covering test can self-vouch `oracle_verified=True`. The
  "pair with mutation" guidance does NOT close this class. Fix is a substantial oracle-hardening piece
  (a **statement-deletion / no-op mutation operator**, or an assertion-reaches-the-change check) — its
  own focused effort + red-team; opt-in + latent + the reviewer/human-gate backstop it meanwhile.
  Filed as a follow-up; guidance corrected (below). LOW note: `tree_hash` truncates at 300 files and
  this arc is the first to ride a *gate-affecting* verdict on it — narrow, logged.

## #39 — no-op / statement-deletion mutation operator (2026-07-17): A-1 closed

`_mutate_source` gains a **third** operator, tried after `return X`→`None` and comparison-flip (so it
only fires on a change those two can't touch — a *purely* non-mutable one): it replaces the first bare
side-effecting **call** statement with `pass` (`x.append(y)`, `audit(...)`, `await session.delete(x)`),
runs the suite network-off, and a surviving mutation ⇒ the suite can't fail that change ⇒
`tests_mutation_caught=False` ⇒ the gate downgrades `oracle_verified`. A change that was previously
`None`-without-running (self-vouch) now gets a real verdict. Both operators are additionally **confined
to the changed lines** (`changed` threaded from `changed_lines(diff)` at the call site; range-
intersection over `lineno..end_lineno`) so the mutation lands on the coder's actual change, not a
well-tested construct elsewhere in the file — `changed=None` keeps first-in-file for the unit tests.

- **★ Credit-direction soundness — the composition is the guarantee (red-teamed).** The primary safety
  fact is the GATE wiring, not the operator: `oracle_verified = (tester_vouched or
  standing_suite_is_independent_oracle(…) or test_cmd) and tests_mutation_caught is not False`
  (`nodes_review.py`). The mutation signal is **ANDed as a downgrade only** — it can turn a base credit
  into a park, but it has **no upgrade path**, so it adds **zero** new `oracle_verified` paths no matter
  what verdict it returns. Base credit still requires the independent-oracle check, which enforces the
  assertion floor (`_asserts_something_real`) + coverage/reference. So an "error-as-caught" `True`
  (deletion crashed the code instead of failing an assertion) can at worst **fail to downgrade** a suite
  that already cleared the floor — it can never manufacture credit. That is why shipping the operator is
  safe even though a *downstream* data-dependency (`d.setdefault('k', []) … d['k']` → `KeyError`) can
  still crash a covering test: in mutation-testing terms that is a legitimate kill (the suite IS
  sensitive to the change), and the composition contains the rest.
- **The `Expr(Call)`/`Expr(Await(Call))` predicate is about SIGNAL QUALITY, not credit-soundness.** It
  excludes the *site-local structural* mutations that ANY suite would "kill" via a crash regardless of
  its quality — assignments aren't `Expr` statements at all; a bare walrus `(x:=f())` binds a name
  (→ `NameError`); a bare `yield`/`yield from` de-generators the function (→ `TypeError`); a docstring/
  bare literal is a true no-op that always survives (→ false *park*). Allowing those would make the
  check nearly always-`True` (a useless non-downgrade), not unsafe. Restricting to a bare CALL — whose
  deletion leaves valid code whose *survival* is a meaningful rubber-stamp signal — is what makes a
  `False` discriminating. Replace-with-`Pass` (not node deletion) keeps every block a valid, unparse-able
  AST.
- **Deliberate trade — the operator ships PURE (no logging denylist).** `logger.info(...)` and an
  audit-log call are syntactically identical, so a syntactic skip-list can't tell them apart — it would
  just re-open #39 for the audit-shaped calls the finding names. So with `oracle_mutation_check` ON, a
  purely-non-mutable change whose side effect **no test asserts** now downgrades → parks with an honest
  "mutation survived" note. That is correct for an unasserted `session.delete()`; the residual cost is
  parking an unasserted pure-observability change. This is the **safe** (deny-by-default) direction, it
  is **opt-in** (default OFF), and it adds no false-*credit*. An observability-skip knob is a *measured
  future* follow-up, not v1.
- **gap-fill interaction (documented, not a bug).** With coverage + `coverage_gap_fill` +
  `oracle_mutation_check` all on, a gap-fill delta test that merely *executes* (satisfying coverage) an
  appended/deleted line without *asserting* its effect leaves the no-op mutation surviving → park. That
  is arguably correct — an execute-only test is not an oracle for that line — but it is a behaviour shift
  for coverage-focused operators: turning on the mutation check alongside gap-fill demands *asserting*
  delta tests. No stale-verdict bug: gap-fill authoring changes the tree hash, so the `("mutcheck",
  tree_hash)` memo self-invalidates and the check recomputes on the re-measure pass.
- **Targeting side effect (mostly safe; one accepted residual):** confining the operators to the
  changed lines removes the *spurious* multi-function downgrades (mutating an unrelated function's
  return elsewhere in the file) — but it also drops a *legitimate* one: a single-function change on a
  non-mutable line (an assignment/literal) whose observable effect flows through the function's own
  `return` on an UNCHANGED line no longer mutates that return → `None` instead of a downgrade
  (red-team F1). It fails to **abstain**, not to a false-green (`None` never parks; base credit still
  needs asserts-real + coverage), and the precise fix is the deferred data-flow/region-aware successor,
  so it is ACCEPTED. Deletion-only changes (no added lines → no changed-line set) fall back to
  first-in-file, which is *more* aggressive (toward downgrade) — also safe (F2).

### Red-team disposition (2026-07-17, 3 adversarial agents — trust-boundary definition-of-done)
- **Finding 1 — multi-file park→ship (MEDIUM) → FIXED.** `suite_catches_a_mutation` early-returned on
  the FIRST mutable file; #39 enlarged the mutable set, so a no-op-only file could precede a genuine
  rubber-stamp file and mask its survived mutation → a correct park shipped. Now **fail-closed**: every
  changed file is checked and the first survivor returns `False`; `True` only if all checked and none
  survived. (Also fixes the pre-existing single-sample blindness.)
- **Finding 2 — walrus-in-call-args error-as-caught (LOW) → FIXED.** `_is_noopable` accepted
  `log(y := f())` (top-level `Call`), but deleting it unbinds `y` → downstream `NameError`. Now excludes
  any `Call` containing a `NamedExpr`. Legitimate side-effect calls (`next()`, starred, methods) stay
  no-opable.
- **Revert integrity A1/A2 (HIGH) → FIXED.** The `finally` restore used text I/O — newline translation
  (LF↔CRLF per `os.linesep`) and `errors="replace"` (non-UTF-8 → U+FFFD) meant the "restore" corrupted
  the delivered file, which `deliver` then commits. Now byte-exact (`read_bytes`/`write_bytes`); the
  decode is a throwaway feed for `_mutate_source`.
- **Collection-error-as-caught (C, LOW) → ACCEPT.** A no-op deletion can cause a pytest *collection*
  error (exit≠0 → `passed=False` → "caught"). Contained by the downgrade-only composition (a spurious
  "caught" only fails to fire the bonus downgrade; base credit is untouched). Documented residual.
- **Robustness B/D — SOUND.** No crash/hang across exotic Python (`match`, async, `type` aliases,
  decorators, deep nesting → `SyntaxError`→`None`); `ast.unparse` is semantics-preserving and only ever
  touches the throwaway mutant, never the reverted original.

`oraclecheck.py` (`_overlaps`, `_is_noopable`, `_NoOpMut`, the `suite_catches_a_mutation` fail-closed
loop + `changed=` param + byte-exact revert) + the `nodes_impl.py` call site (thread `changed_lines`).
No gate change — the existing `tests_mutation_caught is not False` consumes it. Scope is `packages/core`
+ this ADR; the trust boundary (`packages/policies`) is untouched.

## Still open (follow-ups)
- **DONE:** `stale_coverage_regions` now keys rot off the churn-stable `region_fingerprint` (a cosmetic
  edit no longer invalidates coverage) — finally consumes P2's fingerprint.
- Union the mutation-check test-set (authored + pre-existing) so gap-fill can't erase a rubber-stamp
  downgrade (A-3).
- **DONE (#39, below):** the no-op / statement-deletion mutation operator — the mutation successor now
  covers non-mutable changes, closing A-1's sharpest gap.

## What this does NOT fix (elsewhere in the arc)

- **A1's branch/sub-expression precision** — closed by pairing with `oracle_mutation_check`, above.
- **A2's test-named source classification** — a future `is_test_file` review.
- Non-`.py` behavioural changes (config/data) are still judged by the heuristic's F-B inertness
  check, not coverage — a future extension.
