"""Implementation-loop nodes: test / fix / hygiene / hygiene_fix and their routers.

The no-progress breakers and the fix loop's convergence decision live in ``graph.convergence``
(extracted for the #81 arc); the reason nodes are in ``nodes_reason``."""

from __future__ import annotations

import contextlib
from typing import Any

from langchain_core.messages import HumanMessage

from mosaera_core.graph._baseline import record_verdict, regressions_in
from mosaera_core.graph._coverage_ledger import persist_coverage_ledger
from mosaera_core.graph._tamper import destruction_verdict, tamper_verdict
from mosaera_core.graph._validation_activity import validation_progress
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.convergence import apply_trip, convergence_update, stall_bump
from mosaera_core.graph.instructions import fix_instruction
from mosaera_core.graph.state import RunState
from mosaera_core.hygiene import autofix, hygiene_findings, hygiene_targets
from mosaera_core.quality import changed_python_files
from mosaera_core.seedcheck import seed_failures_from_output
from mosaera_core.testintegrity import (
    is_collection_control,
    is_test_file,
)
from mosaera_core.validation import resolve_plan, run_plan


def test_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Detection runs per iteration, INSIDE the node: files the coder just
    # wrote (new tests, new pages) upgrade the plan on the next loop. cwd is
    # the workspace root so the install-stamp host-skip can fire. Detection is
    # a pure function of the tree, so memoize it by tree hash (#23): a new test
    # file changes the hash and re-detects; an unchanged tree reuses the plan.
    key = ("valplan", ctx.workspace.tree_hash())
    plan = ctx.evidence_memo.get(key)
    if plan is None:
        plan = resolve_plan(
            ctx.workspace,
            ctx.test_cmd,
            install=ctx.settings.sandbox_install,
            install_timeout=ctx.settings.sandbox_install_timeout,
        )
        ctx.evidence_memo[key] = plan
    # Stamp BEFORE the run, not after. The suite is pointed at the tree as it stands here; the
    # install/test phases then execute TARGET-REPO code with the workspace mounted writable, so a
    # post-run stamp certifies a tree including whatever validation itself wrote — the one phase an
    # adversarial repo controls. (This slid to post-run in f0666bfa, unnoticed because the comment
    # explained walk-vs-git and never mentioned timing; red team caught it.) Affordable precisely
    # because the stamp is git-sourced: install churn (.venv, caches) sits in the clone's
    # info/exclude and does not move it. A validation step that writes an untracked-not-ignored
    # file WILL move it and make `delivery_check` re-verify — the safe direction.
    tree_before_run = ctx.workspace.evidence_hash()
    outcome = run_plan(plan, ctx.sandbox, cwd=ctx.workspace.root, on_step=validation_progress)
    tests_passed = outcome.passed
    result: dict[str, Any] = {
        "test_output": outcome.output,
        "validation_plan": {**plan.as_dict(), "results": outcome.step_results},
        # The tree this verdict belongs to. Without it `tests_passed` is a claim about no
        # particular tree, and `deliver` cannot tell whether what it is about to commit is what
        # was actually validated.
        #
        # NOT `key[1]`. That is the memo key — `tree_hash`, the PRESENTATION walk — and it is right
        # for memoizing a plan and wrong for evidence: it cannot see `htmlcov/`, `node_modules/`,
        # `src/.mosaera/` or anything else under a `_SKIP_DIRS` name at any depth, while the
        # delivery path commits all of them (red team 2026-08-22). `delivery_check` compares this
        # against `evidence_hash` too, so both sides moved together. Taken before `run_plan` —
        # see the comment at the capture site.
        "verified_tree": tree_before_run,
    }
    record_verdict(
        ctx,
        key[1],
        {
            "green": outcome.passed is True,
            "failing": seed_failures_from_output(outcome.output) or [],
            "read": outcome.passed is not None,
        },
    )
    # Deliver-with-caveat (P3, opt-in): no automated validator exists for this
    # project type (passed is None) → instead of parking forever, deliver and let
    # the reviewer gate acceptance, recorded honestly as "unverified" (not a pass).
    if tests_passed is None and ctx.settings.deliver_unverified:
        tests_passed = True
        result["validation_unverified"] = True
    result["tests_passed"] = tests_passed
    # A run must never "pass" by weakening the tests it was judged against. Two baselines:
    #  - tests_baseline: the tester's PROTECTED authored acceptance tests (ADR-0013), off by
    #    default; the coder is also refused these at the tool level.
    #  - integrity_baseline: the PRE-EXISTING tests + pytest collection-config surface,
    #    snapshotted from the pristine clone (ADR-0036). This is the one that closes the
    #    ADR-0034 residual — a green "suite" is only trustworthy if the coder didn't edit the
    #    tests, delete one, or add a `collect_ignore`/`addopts=--ignore` to shrink collection.
    # BOTH sanction sources, deliberately. `ctx.operator_sanctioned` is process-local — the repo
    # tools write into it live, but `build_graph` rebuilds it EMPTY when a parked run rehydrates in
    # a fresh process. The checkpointed `operator_edits` key is what survives that restart. Reading
    # only the closure lost every approval a human had already given and re-parked the run on it —
    # F35's defect class again, and F63's own fix not working across the restart the durable
    # PostgresSaver exists for. State first so a live sanction wins any collision.
    # ONE ORIGIN (`graph/_tamper.py`): `capture_node` computes the identical verdict on the
    # hand-raise branch, which never enters this node. A copy here would be the second-origin shape
    # this repo keeps paying for — on a signal where the two disagreeing is a security hole.
    tamper = tamper_verdict(ctx, state)
    result.update(tamper)
    # `operator_edits` (the merged, auditable sanction set) rides the verdict — see `_tamper`.
    tampered = tamper["tampered_paths"]
    if tampered:
        result["tests_passed"] = False
        result["stalled"] = True
        result["stall_reason"] = "pre-existing/protected tests or their collection config " + (
            f"were modified: {', '.join(tampered[:5])}"
        )
        # tests_modified (set above) is what diagnose_bottleneck reads to attribute the failure
        # to the CODER not a weak tester (ADR-0026), and what gate_node turns into a dedicated
        # `tests_tampered` reason autonomous mode can never ship past. Both keys are DECLARED in
        # RunState now, so LangGraph keeps them — ADR-0026 wrote tests_modified undeclared, so
        # it was silently dropped and the rule never actually fired.
        return result
    # Mutation check (oracle-make-real Phase 1b, opt-in): a passing suite is only an oracle if it
    # can actually FAIL bad code. On a GREEN run vouched by a suite, apply one deterministic
    # mutation to the coder's OWN changed source and confirm the suite goes red; a surviving
    # mutation ⇒ rubber stamp ⇒ oracle_verified is downgraded at the gate. Memoized by tree hash so
    # it runs at most once per distinct tree. Deny-by-default: only a proven-False (survived)
    # downgrades — None (inconclusive) never parks.
    # WHY there is no verdict, when there is none. `tests_mutation_caught=None` collapses at
    # least four unrelated situations, and under a sanctioned test edit (ADR-0087's backstop) a
    # None REFUSES the run — so "we never looked" is currently indistinguishable from "we looked
    # and could not tell", while both park. Measured 2026-08-12: 5 of 47 baseline over-parks are
    # exactly `mutation_raw=None` + `sanctioned=True`. Recording only; nothing branches on it.
    #
    # The cause is written ONLY where the verdict is decided, never unconditionally. An earlier
    # draft set it at the top of this block on every implement call, while the verdict is written
    # only when the check actually runs — so a later iteration overwrote the cause and left it
    # disagreeing with the verdict it explains. A record that can drift from the thing it records
    # is the defect this whole field exists to remove. An ABSENT cause therefore means the check
    # was never attempted on any iteration.
    if tests_passed is True and ctx.settings.oracle_mutation_check:
        from mosaera_core.coveragemap import changed_lines
        from mosaera_core.oraclecheck import suite_catches_a_mutation

        # `.py` ONLY. `authored_tests` is derived from `protected_test_paths`, which includes
        # everything under a `tests` dir — so a `tests/fixtures/golden.json` the tester wrote
        # alongside its test landed in the pytest target list, pytest exited 4 (usage error,
        # nothing collected), and the mutation check read that non-zero exit as "the mutation was
        # caught". A rubber-stamp suite was promoted to a vouch because pytest refused to start.
        test_files = [f for f in (state.get("authored_tests") or []) if f.endswith(".py")] or [
            # C = baseline MINUS collection controls. NOT `is_test_file`, which is pytest's
            # DEFAULT naming and answers False for every real test on a `python_files` repo —
            # re-introducing, one line later, the blindness the config-aware baseline just fixed.
            # Controls are config-independent, so this needs no workspace.
            p
            for p in (state.get("integrity_baseline") or {})
            if not is_collection_control(p)
        ]
        if not test_files:
            result["tests_mutation_cause"] = "no_test_files"
        if test_files:
            mkey = ("mutcheck", ctx.workspace.tree_hash())
            caught = ctx.evidence_memo.get(mkey)
            if caught is None:
                diff = ctx.workspace.diff_all()
                source = [
                    f
                    for f in changed_python_files(diff)
                    if not is_test_file(f) and (ctx.workspace.root / f).is_file()
                ]
                # Confine each file's mutation to its CHANGED lines so it exercises the coder's
                # actual change (not a well-tested construct elsewhere in the file) — this is what
                # lets the no-op operator target a non-mutable change (ADR-0049 / #39).
                changed = {f: ls for f, ls in changed_lines(diff).items() if not is_test_file(f)}
                # A fault in the mutation check (a malformed tree, a sandbox raise) must degrade to
                # None (inconclusive → deny-by-default: never downgrades, never vouches), NOT crash
                # the run to status="error" and discard a deliverable diff (#52 red-team, mirroring
                # run_coverage's own try/except which was hardened for exactly this — B-1).
                try:
                    caught = suite_catches_a_mutation(
                        ctx.workspace,
                        ctx.sandbox,
                        source,
                        test_files,
                        changed=changed,
                        # Comprehensive (ADR-0071): mutate EVERY changed construct, require ALL
                        # caught — closes the executed-but-unasserted gap a single mutation misses.
                        comprehensive=ctx.settings.oracle_mutation_comprehensive,
                    )
                except Exception as exc:
                    caught = None
                    result["tests_mutation_cause"] = f"faulted:{type(exc).__name__}"
                ctx.evidence_memo[mkey] = caught
            result["tests_mutation_caught"] = caught
            if not str(result.get("tests_mutation_cause", "")).startswith("faulted"):
                result["tests_mutation_cause"] = (
                    "measured" if caught is not None else "no_mutable_construct"
                )
    # Structural-spec check (#80, ADR-0072, opt-in): a refactor task can ask for a SHAPE — a short
    # orchestrator delegating to >= N helpers — that has no behavioural signature, so behaviour-
    # preserving code can still miss it (the MCB-05 false_ship the mutation oracle can't see). On a
    # green run, check the delivered function's AST against the structural asks in the brief; a
    # STATED-but-unmet constraint downgrades oracle_verified at the gate → honest_park. Pure AST, no
    # sandbox. Deny-by-default: only a proven-False parks; None (no constraint / unverifiable / a
    # parse fault) never downgrades. Memoized by tree hash.
    if tests_passed is True and ctx.settings.oracle_structural_spec:
        from mosaera_core.structural_spec import evaluate_structural_spec

        skey = ("structspec", ctx.workspace.tree_hash())
        if skey not in ctx.evidence_memo:
            try:
                diff = ctx.workspace.diff_all()
                sources = {
                    f: (ctx.workspace.root / f).read_text(encoding="utf-8", errors="replace")
                    for f in changed_python_files(diff)
                    if not is_test_file(f) and (ctx.workspace.root / f).is_file()
                }
                # The PRE-refactor source of each changed file, for the relative "short
                # orchestrator" measure (ADR-0072 successor). HEAD is still the base commit here:
                # `deliver` commits later, and this runs inside test_node. A file that did not
                # exist at HEAD (a new module) simply has no baseline, which makes the relative
                # check inert for it — deny-by-default, never judged against an invented constant.
                originals: dict[str, str] = {}
                for f in sources:
                    # suppress: a new file / unreadable blob simply has NO baseline, which makes
                    # the relative check inert for it. Silence is the intended outcome, not a
                    # swallowed error.
                    with contextlib.suppress(Exception):
                        originals[f] = ctx.workspace.repo.git.show(f"HEAD:{f}")
                verdict, _reason = evaluate_structural_spec(state["task"], sources, originals)
            except Exception:
                verdict = None
            ctx.evidence_memo[skey] = verdict
        result["structural_spec_ok"] = ctx.evidence_memo[skey]
    # Change-coverage (oracle-make-real #29, P1, opt-in): a passing suite is only an oracle for THIS
    # change if a test EXECUTES the changed lines. On a GREEN run, run the suite under coverage and
    # check every changed source line is covered (a changed file no test runs ⇒ uncovered). The gate
    # uses this instead of the coarse import heuristic. Memoized by tree hash. Deny-by-default: True
    # all changed executable lines covered, False = some uncovered, None = not measurable (coverage
    # off / not in the sandbox image) ⇒ the gate falls back to the heuristic.
    if tests_passed is True and ctx.settings.oracle_coverage:
        from mosaera_core.coveragemap import change_is_covered, changed_lines, run_coverage

        ckey = ("cov", ctx.workspace.tree_hash())
        if ckey not in ctx.evidence_memo:
            cmap = run_coverage(ctx.workspace, ctx.sandbox)
            if cmap is None:
                ctx.evidence_memo[ckey] = None
            else:
                changed_src = {
                    f: ls
                    for f, ls in changed_lines(ctx.workspace.diff_all()).items()
                    if not is_test_file(f)
                }
                ctx.evidence_memo[ckey] = change_is_covered(cmap, changed_src)
                # We just paid for one instrumented run — compound it: persist the covered regions
                # to the durable per-project ledger (#29 P3). Once per distinct tree (this branch),
                # best-effort, never affects the gate verdict above.
                persist_coverage_ledger(ctx, cmap)
        result["changed_lines_covered"] = ctx.evidence_memo[ckey]
    # ADR-0095 Amendment 2 — the UNDECLARED removal. A pre-existing file the producer reduced
    # to nothing is a removal wearing an edit's clothes: still tracked, still present, holding
    # nothing. Measured live 2026-08-10 (item 88), where the coder emptied four build artefacts
    # to simulate a delete it had no tool for, and NO control examined it.
    #
    # Computed unconditionally, NOT inside the knob-gated structural-spec block above: that
    # knob's posture activation was withdrawn on a null result, and a check that only runs when
    # a disabled knob is on is the inert-mechanism defect this arc has produced five times.
    # Never let a new check break a run: an unreadable tree (no git dir, a torn clone) raises
    # from `diff_all`. The key is left ABSENT in that case rather than set to `[]`, so the
    # record distinguishes "checked, nothing destroyed" from "could not check" — the
    # security_unavailable_reason lesson. HONEST LIMIT: the gate reads truthiness, so an
    # uncheckable tree fails OPEN here. Every real run works on a git clone, and a workspace
    # this broken fails validation long before the gate.
    result.update(destruction_verdict(ctx))
    convergence_update(ctx, state, outcome, plan, result)
    # Slice 2.1: pin the probe's degradation counts (timeout / truncated / unavailable / the two
    # budget STOPs). Cumulative for the whole run — the map is owned by `build_graph`, the same
    # shared-mutable ownership as `coder_validation` — so writing it here each iteration keeps the
    # latest total. Advisory ONLY: nothing routes or gates on it.
    #
    # Written HERE and not in `capture_node`, which would have covered every iteration: that file
    # sits at the 500-line ceiling. NOT in `gate_node` either, deliberately — the gate interrupts
    # before its returns, so nothing it computes reaches the checkpoint (ADR-0078's measured
    # defect). The cost is honest and one-directional: a run that hand-raises from `capture`
    # straight to `supervise` skips `test`, so its counts go unrecorded. That UNDER-counts, which
    # biases the ceiling question toward "no raise needed" — the conservative wrong answer, not the
    # dangerous one.
    if degraded := dict(getattr(ctx, "exec_degradations", None) or {}):
        result["exec_degradations"] = degraded
    # The denominator, on the same seam. Without it a zero degradation count cannot be read: the
    # first 52-run sweep returned zero and it was impossible to say whether the ceiling never bound
    # or the probe was never called. Same under-count caveat as above, and it biases the same
    # conservative way — both numerator and denominator are lost together, never one alone.
    if usage := dict(getattr(ctx, "exec_usage", None) or {}):
        result["exec_usage"] = usage
    return result


def fix_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Self-heal a failing test suite: hand the coder the failure and let it
    # patch, instead of parking a human for the most common failure. Only the
    # failure delta is fed back (test_output is already step-capped) so the
    # coder transcript doesn't balloon vs num_ctx. Increments `iteration`
    # itself — it bypasses plan_node (the usual counter) so it must share the
    # same budget, which keeps route_after_test/route_after_gate bounded. The prompt
    # (with its over-specification escalation valve) lives in fix_instruction() so it's
    # unit-testable outside the graph.
    return {
        "iteration": state.get("iteration", 0) + 1,
        "messages": [
            HumanMessage(
                content=fix_instruction(
                    state.get("test_output", ""),
                    # #55: require a root-cause HYPOTHESIS + show the failing-count trend so the
                    # coder diagnoses instead of guess-and-rerun. Opt-in (default on); the counts
                    # come from test_node (None on a non-pytest validator → the trend is omitted).
                    diagnose=ctx.settings.coder_diagnose_loop,
                    failing_now=state.get("test_failing_now"),
                    failing_prev=state.get("test_failing_prev"),
                    # #81: the ONLY feedback available when the validator reports no count.
                    repeat=int(state.get("test_repeat", 0) or 0),
                    # Which failing tests were PASSING at run start — the fact that redirects the
                    # search from "the tests are wrong" to "my change broke something".
                    regressions=regressions_in(state),
                )
            )
        ],
    }


def route_after_test(ctx: RunContext, state: RunState) -> str:
    # Reason-before-park (ADR-0017): a first no-progress trip diverts to the reason pass
    # BEFORE the fix branch (tests_passed is still False at the trip, which would else
    # steal the route). needs_reason and stalled are mutually exclusive.
    if state.get("needs_reason"):
        return "reason"
    # A stalled run (tamper park, or the unparseable-output fingerprint breaker) skips
    # every self-heal loop and falls toward the gate — a tampering run in particular
    # must never earn a supervise re-scope.
    if state.get("stalled"):
        return "hygiene" if ctx.settings.hygiene_gate_enabled else "scan"
    # The honest-stop (#56, ADR-0060): a tripped progress breaker routes to `supervise`
    # for a DECISION (re-scope once vs give up honestly) instead of grinding to a park.
    if state.get("progress_trip"):
        return "supervise"
    # A real test FAILURE (not None/unavailable) self-heals via the coder,
    # while there's budget left; otherwise fall through to hygiene→scan→review→gate,
    # where evaluate_gate parks on ["validation_failed", "iteration_limit"].
    if state.get("tests_passed") is False and state.get("iteration", 0) < ctx.max_iter:
        return "fix"
    # Working code next runs the in-loop hygiene gate (format/lint/types); when the
    # gate is off it goes straight to scan, preserving the legacy pipeline.
    return "hygiene" if ctx.settings.hygiene_gate_enabled else "scan"


def _never_rewrite(ctx: RunContext, state: RunState) -> set[str]:
    """Every path the TAMPER GUARD judges — the set hygiene's autofix must not touch.

    The filter here read `ctx.protected_tests` alone, directly beneath a comment saying the point
    was to avoid rewriting a BASELINED test. `ctx.protected_tests` is the AUTHORSHIP set (Proctor
    output); it has no defined relationship to the baseline and none at all to a human sanction. So
    `ruff format` would normalise an operator-approved amendment (`'`->`"`, `==` spacing), its
    `integrity_hash` would move off the content the human approved, the content-pinned excuse
    would stop matching, and the run parked `tests_tampered` — TERMINAL, on a change the operator
    had explicitly authorised. Verified end to end; `route_after_hygiene` sends a rewriting pass
    straight back to `test`, so the trip is same-iteration and deterministic.

    The stated purpose and the implementation had simply never agreed. It stayed dormant only
    because the baseline was empty on this repo shape; 1f710222 populated it and woke it.

    BOTH sanction sources, deliberately: `ctx.operator_sanctioned` is process-local and lost on
    rehydrate, `state["operator_edits"]` is durable. `_tamper.tamper_verdict` merges both for
    exactly this reason; a set that disagrees with the guard it protects is how this started.

    Skipping formatting can never hide a tamper, so over-inclusion here is free; under-inclusion
    costs a terminal park. `eligibility.py` already derives its protected set from state this way.
    """
    return (
        set(ctx.protected_tests)
        | set(state.get("integrity_baseline") or {})
        | set(state.get("tests_baseline") or {})
        | set(state.get("proctor_edits") or {})
        | set(state.get("operator_edits") or {})
        | set(ctx.operator_sanctioned or {})
    )


def hygiene_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Deterministic-first: auto-format + apply safe lint autofixes (zero model),
    # then surface the residual BLOCKING issues (mypy types + ruff F-class real-bug
    # lint) for the coder to fix in-loop. Runs on the run's CHANGED python files only.
    diff = ctx.workspace.diff_all()
    files = hygiene_targets(ctx.workspace, diff)
    # NEVER reformat/lint the engine's OWN protected tests (ADR-0068). They are the oracle,
    # authored by the tester/scaffold, not the coder's code. Reformatting them (e.g. ruff's
    # single→double quotes on the scaffold's `_CASES`) rewrites a BASELINED test → the tamper
    # guard false-trips on the engine's own file → a self-inflicted thrash_park on CORRECT code
    # (the dominant measured thrash cause). The coder can't touch these anyway; hygiene must
    # leave them exactly as authored.
    files = [f for f in files if f not in _never_rewrite(ctx, state)]
    if not files:
        # A non-python change (or only protected tests). NOT "clean" — nothing was checked, and
        # that distinction is the whole reason `HygieneReport` carries `unavailable` separately.
        return {
            "hygiene_findings": [],
            "hygiene_unavailable": [],
            "hygiene_status": "not_applicable",
        }
    # Autofix WRITES. It used to write and route on, so the tree that shipped was not the tree
    # that passed on every Python delivery — `--select F --fix` removes "unused" imports, which can
    # change import side effects. It already reports whether it changed anything; the run re-tests
    # when it did, through the existing spine, so a real regression reaches the fix loop.
    rewrote = autofix(ctx.workspace, files)
    report = hygiene_findings(ctx.workspace, files)
    findings = report.findings
    if report.unavailable:
        # An unavailable tool is not a clean bill of health, and it is not something the
        # coder can fix — so record it honestly and warn, but don't spin the fix loop.
        print(
            f"  WARNING: hygiene tools unavailable ({', '.join(report.unavailable)}) — "
            "those checks did NOT run on this change."
        )
    # Refresh the diff so review/gate/quality see the auto-formatted code.
    result: dict[str, Any] = {
        "hygiene_rewrote": bool(rewrote),
        "hygiene_findings": findings,
        "hygiene_unavailable": report.unavailable,
        # Deny-by-default ordering: an unavailable tool outranks a clean result, because a
        # partially-run check is not a clean bill of health and must never be rounded to one.
        "hygiene_status": (
            "unavailable" if report.unavailable else ("findings" if findings else "clean")
        ),
        "diff": ctx.workspace.diff_all(),
    }
    # No-progress detector (hygiene loop): the same lint/type issue surviving the
    # coder means it isn't converging → trip the breaker and park honestly.
    if ctx.settings.stall_detection_enabled and findings and not state.get("stalled"):
        by_kind, count, tripped = stall_bump(ctx, state, "hygiene", "\n".join(findings))
        result["stall_by_kind"] = by_kind
        if tripped:
            apply_trip(
                ctx,
                state,
                result,
                "hygiene",
                "\n".join(findings),
                f"the same lint/type issue persisted {count + 1} times in a row",
            )
    return result


def route_after_hygiene(ctx: RunContext, state: RunState) -> str:
    # Reason-before-park (ADR-0017): a first no-progress trip reasons before parking.
    if state.get("needs_reason"):
        return "reason"
    # Residual blocking issues loop the coder (bounded by max_iter AND a hygiene
    # sub-cap so it can't starve the reviewer loop); a stalled run skips the loop
    # and parks honestly. Otherwise proceed to scan.
    if (
        ctx.settings.hygiene_gate_enabled
        and not state.get("stalled")
        and state.get("hygiene_findings")
        and state.get("iteration", 0) < ctx.max_iter
        and state.get("hygiene_fixes", 0) < ctx.settings.hygiene_max_fixes
    ):
        return "hygiene_fix"
    # Autofix rewrote the tree, so the green behind us describes a tree that no longer exists —
    # re-validate through the normal spine before scan/review/gate see it. Checked AFTER the
    # residual-findings branch: a tree that still needs a coder edit will be re-tested once that
    # edit lands, and testing it twice buys nothing. `autofix` is idempotent, so the next visit
    # reports no change and proceeds — that is the termination bound.
    if state.get("hygiene_rewrote"):
        return "test"
    return "scan"


def hygiene_fix_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Targeted repair for the residual lint/type findings, modeled on fix_node /
    # review_fix_node: hand the coder the concrete findings (bypassing plan/design);
    # increments `iteration` (shares max_iter) and its own hygiene sub-cap counter.
    findings = list(state.get("hygiene_findings", []))
    instruction = ctx.agents.hygiene_fix_instruction(findings)
    note = f"hygiene fix {state.get('hygiene_fixes', 0) + 1}: {len(findings)} lint/type issue(s)"
    return {
        "iteration": state.get("iteration", 0) + 1,
        "hygiene_fixes": state.get("hygiene_fixes", 0) + 1,
        "hygiene_fix_log": [note],
        "messages": [HumanMessage(content=instruction)],
    }
