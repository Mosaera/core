"""The run-graph state TypedDict."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class RunState(TypedDict, total=False):
    task: str
    # Structured acceptance claims (ADR-0079 Wave 1): serialized `Claim.as_dict()` rows derived
    # from the backlog item's acceptance at launch, riding ALONGSIDE the flattened task string.
    # ABSENT for headless/CLI runs without structured acceptance ⇒ pre-claims behaviour
    # byte-for-byte. DECLARED (ADR-0026) or LangGraph silently drops it between nodes.
    claims: list[dict[str, Any]]
    # Ratified standing decisions (ADR-0082 tier 2): serialized `Clause` rows resolved ONCE at
    # launch, so the claim oracle stays pure and never reaches a database mid-gate. ABSENT when
    # no clause applies ⇒ pre-clause behaviour byte-for-byte. DECLARED for the same reason as
    # `claims` — and the omission was live: seeded at launch, silently dropped between nodes, so
    # the oracle overlay never fired at all. The unit tests passed because they called
    # `apply_to_constraints` directly; the ADR-0081 engagement check is what caught it, on its
    # first real use, in the feature that added it.
    clauses: list[dict[str, Any]]
    # Per-claim verdict rows `{claim_id, verdict: satisfied|failed|unbound|unevaluable,
    # oracle_ref}` — written by gate_node via claim_oracles.evaluate_claims (ADR-0079 Wave 2).
    # Only `failed` verdicts reach the gate (owner decision 2026-08-03: unbound claims are
    # intake's job, never the gate's guess). DECLARED (ADR-0026) or LangGraph drops it and the
    # ledger/report never see the verdicts.
    claim_dispositions: list[dict[str, Any]]
    plan: str
    design: str
    foresight: str  # the design's actuated RISK→MITIGATION→CHECK pre-mortem
    messages: Annotated[list[AnyMessage], add_messages]
    iteration: int
    feedback: Annotated[list[str], add]
    # Operator send-backs given at WRITE gates, lifted out of the coder's transcript so they bind
    # for the rest of the run (F17). Deliberately NOT `feedback`: that key gates the ADR-0080
    # intake park (`nodes_plan.py`) and is persisted as `gate` decisions, so reusing it would
    # silently change routing and mislabel the audit trail. DECLARED (ADR-0026) or LangGraph drops
    # it — verified: without the matching declaration the agent subgraph's update never lands.
    corrections: Annotated[list[str], add]
    # Authored tests that pin a value the test never supplied, so they can never pass (F36).
    # Operator-facing detection only; no agent reads it. DECLARED (ADR-0026) or LangGraph drops it.
    unsatisfiable_tests: list[dict[str, Any]]
    coder_summary: str
    diff: str
    test_output: str
    # The coder's OWN last `run_tests` output, kept only when the tree did not move after it
    # (F70, #75). A hand-raise routes `implement → capture → supervise` without touching `test`,
    # so `test_output` can be absent exactly where the escalation must name what is blocking the
    # run. Read ONLY as a fallback, and never in preference to the engine's own validation.
    # DECLARED (ADR-0026) — a process-local sink is rebuilt EMPTY when a parked run rehydrates,
    # so an escalation that survives a restart needs this in the checkpoint.
    coder_test_output: str
    # Slice 2.1: how often `sandbox_exec` DEGRADED this run — {"timeout": n, "truncated": n,
    # "unavailable": n}. DECLARED (ADR-0026) or LangGraph drops it. Advisory ONLY: nothing routes
    # or gates on it. It exists because "does the 30s / 4KB ceiling actually bind?" had no answer —
    # the only telemetry went to the ephemeral activity stream, reaching no card and no state.
    exec_degradations: dict[str, int]
    # Slice 2.1's DENOMINATOR — {"calls": n}, how often the probe was invoked at all. DECLARED
    # (ADR-0026). Separate from the map above and never merged into it: a reader asking "did
    # anything degrade?" must not have to filter, and "any key means bad" is the implicit coupling
    # that already cost this arc a slice. Without this, a zero degradation count is unreadable —
    # "the ceiling never bound" and "the probe was never called" are the same zero.
    exec_usage: dict[str, int]
    # ADR-0095 Am. 2: pre-existing files the producer EMPTIED rather than deleted — an
    # undeclared removal. DECLARED (ADR-0026) or LangGraph drops it, and the gate reads it.
    destroyed_paths: list[str]
    tests_passed: bool | None  # None = no honest validation available
    validation_unverified: bool  # delivered without an automated validator (P3 caveat)
    # Failing-test count this iteration + the previous one (#55) — the coder's convergence signal
    # (getting closer vs spinning) and the seed for the honest-stop progress breaker. None = the
    # validator reports no countable result (see test_report).
    test_failing_now: int | None
    test_failing_prev: int | None
    # The structured result the owning LanguagePack read out of this iteration's validation (#81):
    # {failed, errors, total, passed, failing_ids, failing}. ABSENT (not zeroed) when the pack
    # genuinely cannot count — a well-formedness check, a schema that never applied — which is the
    # honest "no signal" the no-count path handles. `test_failing_now` is the same number flattened
    # for existing consumers; this carries the detail. DECLARED (ADR-0026) so LangGraph keeps it.
    test_report: dict[str, Any]
    # How many times in a row an UNCOUNTABLE validator produced the identical outcome (#81). The
    # only convergence feedback available when there is no count, so the fix prompt can still tell
    # the coder its last edit changed nothing the validator can see. DECLARED (ADR-0026).
    test_repeat: int
    # The honest-stop progress tracker (#56, ADR-0060): best failing-count ever seen this episode,
    # the consecutive non-improving streak, and the full per-eval count history (the trend a human
    # reads at the park). Reset on a green run and on a supervise re-scope. DECLARED (ADR-0026).
    progress_track: dict[str, Any]
    # A tripped progress breaker's deterministic diagnosis: {reason, failing_now, best, trend,
    # failing_tests}. route_after_test routes it to `supervise` (a decision: re-scope once vs give
    # up) — the trip itself is NOT a park and NOT `stalled`. Cleared on a re-scope. DECLARED.
    progress_trip: dict[str, Any]
    # The supervisor concluded the run cannot proceed and STOPPED EARLY with an accurate reason
    # (#56): the generalization of `plan_unworkable_reason`'s pattern to the supervise give-up.
    # HONEST park — `stalled` stays False ON PURPOSE (classify_outcome → honest_park, not thrash),
    # and give-up always lands strictly below the iteration cap (the budget-aware ladder). Surfaced
    # by _termination_reason ahead of the stall branches. DECLARED (ADR-0026).
    give_up_reason: str
    validation_plan: dict[str, Any]
    findings: list[dict[str, Any]]
    findings_text: str
    # scan_node's execution verdict: clean | findings | unavailable | disabled (ADR-0076).
    # DECLARED (ADR-0026) or LangGraph drops it. Deny-by-default: "unavailable" (a scan was
    # expected this run but produced no verdict — no scan sandbox / crashed scanner) → the
    # gate's `security_unverified` reason parks; "disabled" (operator opt-out) + clean/findings
    # never add that reason. "We didn't look" is never rounded to "clean".
    security_status: str
    # The tree `security_status` describes (ADR-0108). Last-write-wins means the verdict outlives
    # the tree it measured; the gate compares this to the live hash and treats a mismatch as
    # unverified. "" when the workspace could not be read — also not fresh.
    security_tree: str
    # WHY the scan produced no verdict, e.g. "semgrep:incomplete" (empty unless unavailable).
    # DECLARED (ADR-0026) or LangGraph drops it. Advisory ONLY — it never feeds a gate reason;
    # `security_status` alone still decides. Measured 2026-08-09: a 17% no-verdict rate was the
    # largest single source of discarded correct work, and four causes were indistinguishable.
    security_unavailable_reason: str
    approved: bool
    review: str
    review_tree: str  # the tree the reviewer's verdict describes (ADR-0108)
    quality: str  # JSON QualityScore of the changed files (advisory; absent if non-python)
    quality_prev: str  # JSON QualityScore that prompted the last quality revise (guard)
    quality_revises: int  # count of targeted quality revises spent this run
    quality_revise_log: Annotated[list[str], add]  # per-attempt trail for the evidence log
    review_revises: int  # count of targeted reviewer-fix revises spent this run
    review_revise_log: Annotated[list[str], add]  # per-attempt trail for the evidence log
    hygiene_findings: list[str]  # residual blocking lint/type issues (in-loop hygiene gate)
    # Tools that produced no verdict this run (e.g. ["mypy"]). Distinct from an empty
    # hygiene_findings: "nothing found" and "nothing checked" are not the same outcome.
    hygiene_unavailable: list[str]
    # hygiene_node's execution verdict, the same tri-state shape `security_status` uses:
    # clean | findings | unavailable | not_applicable | disabled. Until 2026-08-07 the two
    # fields above were DECLARED, POPULATED and read by nobody — not the gate, not the report,
    # not the API, not the UI — while TM-0001 claimed hygiene_unavailable was "a distinct,
    # warned, recorded outcome". It was a print() to engine stdout. And the node could not
    # distinguish "no python files changed" from "linted clean": both returned empty.
    # Informational only — nothing branches on it; making an unavailable linter BLOCK delivery
    # would be a new control needing its own ADR (#80).
    hygiene_status: str
    hygiene_fixes: int  # count of targeted hygiene fixes spent this run
    hygiene_fix_log: Annotated[list[str], add]  # per-attempt trail for the evidence log
    # Per-loop no-progress state: kind ("test"/"hygiene"/"review") -> [fingerprint, streak].
    # Keyed by kind so interleaved coder loops each track their OWN streak (a shared
    # counter would let one loop's outcome reset another's and defeat the breaker).
    stall_by_kind: dict[str, list[Any]]
    stalled: bool  # the circuit breaker tripped — the run isn't converging
    stall_reason: str  # honest, human-readable reason the run can't make progress
    # Plan-level no-progress breaker (#51, ADR-0056): the planner couldn't form a workable plan
    # (a fallback plan, or one identical to the last, `plan_stall_limit` times). Set once in
    # plan_node, which then routes plan→gate. Kept DISTINCT from `stalled` ON PURPOSE — this is an
    # HONEST EARLY park (stalled stays False → classify_outcome → honest_park, not thrash), carrying
    # an accurate reason the report + _termination_reason surface. A DECLARED key (ADR-0026) or
    # LangGraph drops it and the route never fires.
    plan_unworkable_reason: str
    # Was the target repo's suite GREEN before this run touched anything —
    # `{"green": bool, "failing": [...], "read": bool}` from `graph/_baseline`, taken once in
    # plan_node from the pristine clone. `integrity_baseline` beside it records the same instant as
    # HASHES (tamper), which cannot answer this question. Without it a failing count is
    # uninterpretable — a regression this run caused and a repo that was already red look
    # identical — and on 2026-08-20 the producer filled that gap by inventing "environment issues"
    # and burning $1.80 arguing with a file it had itself broken. `read` is kept separate from
    # `green` so an UNPARSEABLE validator is never read as a broken one.
    suite_baseline: dict[str, Any]
    # The tree hash `tests_passed` belongs to (`Workspace.tree_hash`). A verdict without its tree
    # is a claim about no particular tree: `hygiene`'s autofix writes AFTER validation and routes
    # on, and the give-up diversion reaches the gate carrying a verdict from before the coder's
    # last writes — so `deliver` could commit a tree nothing had ever run the suite against.
    verified_tree: str
    # Did hygiene's autofix actually rewrite anything this pass? Routes `hygiene → test` when it
    # did. `autofix` is idempotent, so the next visit reports False and the loop terminates.
    hygiene_rewrote: bool
    # Set when delivery was REFUSED because the tree about to ship failed its own suite: the work
    # is committed to this branch instead of the item branch, so the tip every later item is cut
    # from stays green and nothing is destroyed by the next run's `reset --hard`.
    quarantine_branch: str
    delivery_refused: str
    # VERBATIM what the planner's model returned when the engine had to substitute a fallback
    # (#71, F39): both channels shown separately (a reasoning model routinely leaves `content`
    # empty), `done_reason` — which distinguishes a blown context from a model that finished and
    # said nothing — and token counts. Set only ON a fallback; empty on a healthy run.
    #
    # Diagnostic, never a control input: nothing branches on this, and it must not, or an operator
    # surface becomes a decision surface. It exists because "returned nothing usable" cost an hour
    # of probing a live endpoint to answer. DECLARED or LangGraph drops it (ADR-0026).
    plan_fallback_evidence: str
    # Reason-before-park (ADR-0017): on the FIRST no-progress trip, needs_reason diverts to
    # a one-shot reason-and-change-approach pass instead of parking — distinct from `stalled`
    # so a first trip reasons+retries while a spent budget parks. Carries the tripped kind +
    # failing text for reason_node; reason_attempts (run-level) bounds it.
    needs_reason: dict[str, Any]
    reason_attempts: int
    # A coder/planner hand-raise, parsed from its 'SUMMARY: blocked/escalate — …' yield.
    # blocked = hit a wall it can't pass; escalate = needs a decision / scope change.
    # These route to the mode-gated supervisor (supervise_node).
    blocked_reason: str
    escalate_reason: str
    # Set by capture_node when the CODER (not plan_node's degraded-plan artifact) raised an
    # escalate this cycle. route_after_capture uses it so an already-satisfied run's degraded-plan
    # override (#44) never swallows a GENUINE coder hand-raise — the two share escalate_reason, so
    # this distinguishes them (red-team ADR-0052). Declared or LangGraph drops it (ADR-0026).
    coder_escalated: bool
    escalations: int  # supervisor round-trips this run — bounds the re-scope↔re-block loop
    #: The protected tests that forced the give-up, recorded BY `supervise_node` at the moment it
    #: decided (#68 / ADR-0090 MR3). The escalate arm's ask reads this rather than re-deriving
    #: `is_oracle_conflict_escalation` from a `gate_decision` that has moved on — the two halves
    #: disagreed in both directions, so the ask could be refused for a stop that had already fired.
    ask_blocking_tests: list[str]
    # Test-first tester (ADR-0013): the acceptance test files Proctor authored (protected
    # from the coder), and their content hashes for deterministic tamper detection.
    authored_tests: list[str]
    # WHICH authored tests failed against the pre-impl seed (P2 Stage A). For a test that
    # exercises only behaviour the task does not change, the seed IS the reference — a
    # failure there is provably over-strict without any hidden grader. None = unassessed.
    authored_seed_failures: list[str] | None
    # WHAT the authored suite asserts, recorded once at authoring time (#129 slice 3).
    # `overstrict_vs_ref` proves over-strict authoring is the dominant over-park driver (44%
    # vs 10%, n=163) and that the production detector catches 7% of it. Improving that recall
    # needs the assertions the detector MISSED -- and nothing recorded them: the scorecard's
    # three authoring fields are all scalars, so the corpus can say a run WAS over-strict and
    # never WHICH assertion made it so. Analysis-only; nothing branches on it and nothing
    # reads it back into a prompt. DECLARED or LangGraph drops it (ADR-0026).
    authored_assertion_digest: list[str] | None
    # The digest as it stood BEFORE the Proctor's coder-blind repair pass, recorded only when
    # that pass actually ran. Without it the repair is unobservable: the digest above is taken
    # after authoring completes, so a suite that was repaired and one that never needed it look
    # identical. A sweep could then show fewer over-parks and never show WHY.
    authored_assertion_digest_pre_repair: list[str] | None
    # WHICH assertions the over-strictness detector flagged, as `file:line kind snippet`.
    # `overstrict_static` is a COUNT; a count cannot tell 'the detector found the right things'
    # from 'the Proctor got lucky', which is exactly the question a causation sweep asks.
    overstrict_findings: list[str] | None
    # The subset of those provably asserting PRE-EXISTING behaviour (P2 Stage B) — their
    # reachable source mentions no new-behaviour token. Diagnostic; never a gate input.
    authored_overstrict_runtime: list[str]
    tests_baseline: dict[str, str]
    # Red-phase measurement (oracle-make-real Phase 1a): whether the authored suite FAILED
    # against the pre-implementation tree — True = a valid test-first oracle, False = tautological
    # (green with no code, so it can't be the oracle), None = not assessed. Folded into
    # oracle_verified so that signal MEASURES the suite instead of just asserting it exists.
    tests_red_verified: bool | None
    # Assertion floor (oracle-make-real Phase 1c): whether the authored suite makes a real
    # assertion (not just `assert True` / no asserts). Static AST check that complements the red
    # phase — a suite can red pre-impl only on a missing import yet assert nothing once it exists.
    tests_assert_real: bool | None
    # Already-satisfied (#44, ADR-0052): the Proctor's acceptance suite is GREEN on the untouched
    # tree (tests_red_verified is False) AND asserts something real via a NON-skipped test
    # (tests_assert_real is True) — the task MAY already be done. Set once in author_tests_node.
    # A DECLARED key (ADR-0026) or LangGraph drops it. It is a HINT, not a verified claim: a
    # green-pre-impl suite can't confirm the requirement is met (the tests could miss it). So it
    # does NOT auto-deliver — it (a) stops route_after_capture from giving up over a degraded-plan
    # escalate so the run concludes at the gate rather than a mislabeled give-up, and (b) drives an
    # honest termination reason ("appears already satisfied — confirm"). The run still PARKS on
    # oracle_unverified for a human to confirm; the red-team (ADR-0052) removed the auto-deliver.
    already_satisfied: bool
    # REDUCED LANE (#118 Approach A). `lane` is "reduced" only when `task_scale.classify`
    # deterministically certified a non-behavioural change scoped to one existing file;
    # everything else is absent (== full). `lane_paths` is the certified scope, and
    # `lane_violation` records a diff that LEFT it — the classifier predicts, capture_node
    # measures, and a wrong prediction costs the run its lane, never its correctness.
    # DECLARED or LangGraph drops them (ADR-0026).
    lane: str
    lane_reason: str
    lane_paths: list[str]
    lane_violation: str
    # Mutation check (oracle-make-real Phase 1b): whether the vouching suite CAUGHT a deterministic
    # mutation of the delivered code — True = went red (a real oracle), False = the mutation
    # SURVIVED (a rubber stamp → downgrades oracle_verified), None = not run / inconclusive. Only
    # computed on a green run with a suite when oracle_mutation_check is ON. Deny-by-default: only a
    # proven-False downgrades; None never parks.
    tests_mutation_caught: bool | None
    # WHY there is no mutation verdict, when there is none. `tests_mutation_caught=None`
    # collapses "never attempted", "no suite to run", "the check faulted" and "nothing
    # mutable in the changed lines" — and under ADR-0087's backstop a None REFUSES the run,
    # so absence is currently indistinguishable from proof. Diagnostic only; never a gate input.
    tests_mutation_cause: str
    # Structural-spec oracle (#80, ADR-0072): for a refactor task whose brief states a structural
    # criterion, whether the delivered function meets the requested shape — True = met, False = a
    # STATED constraint is unmet (a correct-but-mis-shaped refactor → downgrades oracle_verified →
    # honest_park), None = no constraint / unverifiable. Only computed on a green run when
    # oracle_structural_spec is ON. Deny-by-default: only a proven-False parks; None never does.
    structural_spec_ok: bool | None
    # Change-coverage oracle (#29, P0 scaffolding): whether runtime line coverage shows the changed
    # lines are exercised by a test — True = all changed executable lines covered, False = some
    # uncovered, None = not measured (coverage off / unavailable). P1 computes it in test_node and
    # the gate consumes it (replacing the import heuristic). Deny-by-default: None never vouches.
    changed_lines_covered: bool | None
    # Test-integrity baseline (ADR-0036): a run-start snapshot of the PRE-EXISTING tests +
    # the pytest collection-config surface, so the coder can't make validation go green by
    # weakening it. Distinct from tests_baseline (which is tester-authored only, and off by
    # default). Taken once at the first plan_node from the pristine clone.
    integrity_baseline: dict[str, str]
    # WHICH enumeration rules built that baseline (`testintegrity.INTEGRITY_ENUMERATOR`), stamped in
    # the same update so the two can never drift apart. ABSENT means "written before this key
    # existed", i.e. by the capped 300-path enumerator — exactly the incomparable case, so absence
    # and a mismatch are treated identically: the new-collection-control branch is suppressed and
    # the narrowed coverage is surfaced. Never used to skip the baselined-path comparison.
    integrity_enumerator: str
    # HOW the test surface was decided for this run: resolved from the target's own pytest config,
    # or INFERRED from pytest's defaults because it said nothing — plus any disagreement with
    # `pytest --collect-only`. Recorded so an unprotected repo cannot look identical to a protected
    # one; a guard nobody can see is the class this whole arc exists to close.
    test_surface_resolution: str
    # Set when the coder edited/deleted a protected or pre-existing test, or its collection
    # config. A DECLARED key so LangGraph keeps it (ADR-0026 wrote it undeclared, so it was
    # silently dropped and the tamper→escalate rule never fired). Read by diagnose_bottleneck.
    tests_modified: bool
    tampered_paths: list[str]  # which paths tripped it — for the report + the human at the gate
    # Test-steward — the Proctor's UP-FRONT, coder-blind, spec-anchored fixes to PRE-EXISTING tests
    # (#54, ADR-0058): path → the Proctor's new integrity-hash. An actor-scoped excuse from the
    # ADR-0036 tamper guard for EXACTLY these paths+content (never the coder's, never a deletion),
    # gated on the assertion floor + a proven mutation-catch (gate_node) so weakening can't launder.
    # DECLARED or LangGraph drops it (ADR-0026). Reviewable — the edit rides diff_all() → the gate.
    proctor_edits: dict[str, str]
    # ADR-0098 diagnostic, never a gate input: the PRE-EXISTING tests the Proctor was pointed
    # at for restatement this run. Empty `proctor_edits` alone cannot tell "the model ignored
    # a named target" from "no target was named" — the two need opposite fixes, and on
    # 2026-08-11 the distinction had to be reconstructed by hand from the case seed.
    modify_amendment_targets: list[str]
    # The operator's write-gate approvals (F63, #65): path → the integrity hash of content a HUMAN
    # approved. The SECOND sanctioned source for the ADR-0036 guard, in the same hash space and
    # under the same content-pinned rules as proctor_edits — never a blanket "this path may
    # change", never an excuse for an emptied/deleted test, and never settable by an autonomous
    # auto-approve. DECLARED or LangGraph drops it (ADR-0026).
    operator_edits: dict[str, str]
    # The escalation-gate amendment authorization (ADR-0087, #65): the test paths a HUMAN said may
    # be amended for THIS item, granted before the replacement content exists (so it cannot be
    # content-pinned the way operator_edits is — that is the whole difference between the two).
    #
    # ONE-SHOT AND SELF-CONSUMING. The amend pass reads it, records the resulting content into
    # proctor_edits, and CLEARS this key in the same node return. It is never a standing licence to
    # rewrite the path: after consumption the path is protected exactly as before, under a content
    # pin, and a second amendment needs a second escalation and a second human. Path-scoped and
    # unpinned is strictly weaker than every other excuse in this system — the one-shot rule, the
    # intersect-with-blocking rule, and the assertion profile are what carry it.
    # DECLARED or LangGraph drops it (ADR-0026).
    pending_amendment: list[str]
    # The operator's stated reason for that authorization — it rides into the Proctor's amend ask
    # (a requirement change needs to say WHAT changed) and into the report, so the amendment is
    # reconstructable later. DECLARED or LangGraph drops it (ADR-0026).
    amendment_reason: str
    # The PRISTINE source of each authorized path, captured when the operator authorizes and never
    # re-read. The weakening measure needs the text that was there BEFORE any amendment, and the
    # baselines keep hashes, not text — so it used to be re-read from disk inside the amend pass.
    # In guided mode that pass re-executes (the Proctor's write gate interrupts inside the node),
    # and on the second entry the "pristine" read already contained the first amendment: the
    # collateral-damage rule was then measured against the previous amendment instead of the
    # original, so a removal could be laundered across rounds. Same moving-snapshot shape as F35.
    # Anchored here because supervise_node's authorization delta is a return that COMMITS.
    # DECLARED or LangGraph drops it (ADR-0026).
    amendment_before_sources: dict[str, str]
    # Paths amended under an operator authorization this run, kept AFTER pending_amendment is
    # consumed. Audit only — the excuse itself lives in proctor_edits, content-pinned.
    amended_tests: list[str]
    # Why an authorized amendment was REFUSED, per path — `{}` when nothing was refused (F71).
    # An operator who grants an authorization and gets nothing back must be told which rule bit;
    # before this every refusal was a bare `continue` and the run simply parked on the write as
    # tampering. Audit + operator surface only; nothing branches on it. DECLARED (ADR-0026).
    amendment_refusals: dict[str, str]
    # The held-out critic's verdict (#60, ADR-0065): {"vetoed": bool, "reason": str} on a
    # confident judgement, else absent/None. Set by critic_node (between review and the gate) only
    # on a green run, memoized by tree hash, degrading to None on any fault. gate_node threads a
    # True `vetoed` into evaluate_gate as `critic_vetoed`, which appends the `critic_vetoed` gate
    # reason and PARKS in every mode (veto-only, downgrade-only — it can never create a ship). A
    # DECLARED key (ADR-0026) or LangGraph drops it and the gate never sees the veto.
    outcome_verdict: dict[str, Any] | None
    gate_decision: dict[str, Any]
    report_path: str
    commit_sha: str
