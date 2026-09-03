"""Planning-stage nodes: plan / design / author_tests / capture / supervise, plus
their routers."""

from __future__ import annotations

import contextlib
from dataclasses import asdict
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from mosaera_core.agents_bridge import new_corrections
from mosaera_core.assertion_digest import suite_assertion_digest
from mosaera_core.authored_overstrict import runtime_overstrict
from mosaera_core.faithfulness import authored_suite_overstrict_findings
from mosaera_core.graph import _amendment
from mosaera_core.graph._baseline import run_start_baseline
from mosaera_core.graph._design_cache import design_cache_key
from mosaera_core.graph._modify_amendment import _modify_amendment_targets
from mosaera_core.graph._proctor_authoring import (
    _acceptance_contract,
    _proctor_validate_repair,
    authored_test_files,
    authoring_instruction,
    baseline_test_sources,
    consume_amendment,
)
from mosaera_core.graph._supervise import route_after_supervise as route_after_supervise
from mosaera_core.graph._supervise import supervise_node as supervise_node
from mosaera_core.graph._tamper import tamper_signals_for_handraise
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.convergence import fallback_escalate_reason, plan_unworkable_reason
from mosaera_core.graph.grounding import build_grounding, grounded_overview, planning_overview
from mosaera_core.graph.state import RunState
from mosaera_core.inert_scaffold import scaffold_if_inert
from mosaera_core.messages import message_text
from mosaera_core.oraclecheck import authored_suite_asserts_behaviour
from mosaera_core.progress import fingerprint, parse_yield
from mosaera_core.quality import changed_files
from mosaera_core.refactor_scaffold import scaffold_if_refactor
from mosaera_core.roundtrip import unsupplied_roundtrip_findings
from mosaera_core.seedcheck import authored_seed_results
from mosaera_core.statickit import install_statickit
from mosaera_core.task_scale import (
    Scale,
    added_lines_within_budget,
    classify,
    diff_within_scope,
)
from mosaera_core.testintegrity import protected_test_paths
from mosaera_core.tools.repo import hash_files


def plan_node(ctx: RunContext, state: RunState, config: RunnableConfig) -> dict[str, Any]:
    feedback = list(state.get("feedback", []))
    # Intake park (ADR-0080 §2, Wave 3): a run whose launch-minted claims say UNDER_SPECIFIED
    # — material claims exist and NONE binds to any oracle — cannot end in an evidence-gated
    # delivery, so park BEFORE the first model call (zero tokens burnt) via the existing
    # plan-unworkable seam (routes straight to the gate; the FROZEN classifier buckets a
    # below-cap unstall park honest_park by construction). First visit only: a gate-deny
    # re-plan means a human chose to continue — their feedback may have re-scoped the work.
    claims = [c for c in (state.get("claims") or []) if isinstance(c, dict)]
    material = [c for c in claims if c.get("material", True)]
    if material and state.get("iteration", 0) == 0 and not state.get("feedback"):
        bound = [c for c in material if str(c.get("oracle_kind", "none")) != "none"]
        if not bound:
            unbindable = "; ".join(str(c.get("text", ""))[:60] for c in material[:2])
            return {
                "plan": "",
                "iteration": state.get("iteration", 0) + 1,
                "plan_unworkable_reason": (
                    f"under_specified: no material acceptance claim is checkable as written "
                    f"({unbindable}) — clarify the item and re-run"
                )[:200],
            }
    # Tool-using PM: reads the repo to ground the plan, then writes. config threads
    # the stream writer so its read-tool calls surface as activity milestones.
    plan = ctx.agents.plan(state["task"], planning_overview(ctx), feedback, config)
    # The coder instruction is assembled in design_node (which runs next and
    # owns the full plan+design message), so plan_node emits no HumanMessage.
    out: dict[str, Any] = {"plan": plan, "iteration": state.get("iteration", 0) + 1}
    # Snapshot the test-integrity surface ONCE, from the pristine clone (ADR-0036). plan_node
    # is the graph entry (START → plan) and runs before the coder's first write; it also
    # re-runs on every gate-deny re-plan, so guard on absence — we must never re-baseline a
    # tree the coder has already touched, or a real tamper would be silently absorbed.
    # Tamper hashes AND what was already failing, from the same pristine tree (`_baseline`).
    #
    # GUARD ON THE ENUMERATOR, NOT THE BASELINE (#129). A repo that starts with NO tests
    # baselines to `{}`, which is FALSY — so "captured, and there was nothing" and "not captured
    # yet" were the same value and the guard failed open on exactly those repos. The coder can
    # write anything on a greenfield tree, so a gate-deny re-plan re-baselined the Proctor's
    # authored suite (and the coder's edits to it) as PRISTINE: the absorption this comment
    # forbids, on the repos least able to survive it. Measured on the 0.6.3 sweep, where 5 of 7
    # greenfield runs reported a `standing_suite` vouch on a repository that began empty.
    # `integrity_enumerator` is a non-empty constant stamped in the SAME update as the baseline,
    # so its presence is an unambiguous "we have already baselined". Kept as an OR with the
    # baseline itself: either marker means captured, so a caller that carries only the older
    # field still skips, and the fix ADDS a way to be sure rather than replacing one.
    if not (state.get("integrity_enumerator") or state.get("integrity_baseline")):
        out.update(run_start_baseline(ctx))
        # LANE, decided ONCE on the first plan (#118 Approach A). Deliberately not re-decided on a
        # gate-deny re-plan: a run that has already been refused must not be able to slide onto the
        # cheaper lane on its way round again. Deterministic — no model call — and deny-by-default,
        # so every shape the classifier does not recognise stays on the full spine.
        # getattr, not attribute access: a partial Settings must mean FULL SPINE, not a crash.
        if getattr(ctx.settings, "reduced_lane", False):
            scale = classify(state["task"], plan, ctx.workspace.committable_paths())
            out["lane"] = scale.lane
            out["lane_reason"] = scale.reason
            out["lane_paths"] = list(scale.paths)
    # Plan-level no-progress breaker (#51, ADR-0056). A FALLBACK plan (the planner produced nothing
    # usable) or one IDENTICAL to the last is no-progress; after `plan_stall_limit` attempts the
    # run self-stops as an HONEST EARLY park (route_after_plan → gate, BEFORE design/implement)
    # rather than burning a coder cycle first. A fallback counts at its FIRST occurrence (a
    # definitive "planner gave up"); an identical non-fallback plan needs a repeat to be evidence.
    # Below the threshold, keep the degraded-plan → supervise re-scope. A genuinely NEW plan resets.
    # WHY it fell back and WHAT the model returned (F39, #71) — reason builders in `convergence`;
    # the evidence is diagnostic only, nothing branches on it.
    is_fallback = ctx.agents.plan_is_fallback(plan)
    why = ctx.agents.plan_fallback_reason() if is_fallback else ""
    if is_fallback:
        out["plan_fallback_evidence"] = ctx.agents.plan_fallback_evidence()
    if ctx.settings.stall_detection_enabled:
        fp = fingerprint("plan", "<<FALLBACK>>" if is_fallback else plan)
        by_kind = dict(state.get("stall_by_kind") or {})
        prev = by_kind.get("plan") or ["", 0]
        no_progress = is_fallback or fp == str(prev[0])
        streak = int(prev[1]) + 1 if no_progress else 0
        by_kind["plan"] = [fp, streak]
        out["stall_by_kind"] = by_kind
        if no_progress and streak >= max(1, ctx.settings.plan_stall_limit):
            out["plan_unworkable_reason"] = plan_unworkable_reason(ctx, streak, why)
            return out
    if is_fallback:
        out["escalate_reason"] = fallback_escalate_reason(ctx, why)
    return out


def design_node(ctx: RunContext, state: RunState, config: RunnableConfig) -> dict[str, Any]:
    # Elaborate the plan into an architecture the coder builds against and the
    # reviewer checks (#3). Design once per item and reuse across runs: a stored
    # design with no new feedback is reused verbatim (no model call —
    # deterministic-first); otherwise (re)generate feedback-aware and persist it
    # to the item so a later run reuses it.
    feedback = list(state.get("feedback", []))
    plan = state.get("plan", "")
    design = ""
    # The stored design is a CACHE, and a cache needs a key over its real inputs (ADR-0084 §3).
    # "No feedback" was the only test, which is not a key but the absence of one — measured
    # 2026-08-06: a design authored on 08-05 told the coder to import `src.budget_tracker.cli`,
    # the operator corrected exactly that at a write gate, and the next run was served the old
    # design and wrote the forbidden import anyway. Operator corrections land in `corrections`,
    # not `feedback`, so correcting the thing the design mandates did not invalidate it.
    key = design_cache_key(state, plan)
    if ctx.memory is not None and ctx.item_id is not None and not feedback:
        existing = ctx.memory.get_backlog_item(ctx.item_id) or {}
        # NULL/absent key = unknown freshness = STALE (deny-by-default), the same rule the recon
        # map applies to a NULL dimension fingerprint. Pre-0023 rows regenerate once, then settle.
        if existing.get("design_key") == key:
            design = str(existing.get("design", ""))
    if not design:
        # Tool-using PM: grounds the design in the actual contents of the files the
        # plan names (the deterministic grounding is a prior it can read past).
        design = ctx.agents.design(
            state["task"], plan, grounded_overview(ctx, plan), feedback, config
        )
        if ctx.memory is not None and ctx.item_id is not None:
            # Design and key are written together — a design stored without its key would read
            # as stale forever, and a key without its design would serve the wrong text.
            with contextlib.suppress(Exception):
                ctx.memory.update_backlog_item(ctx.item_id, design=design, design_key=key)
    # Foresight (actuated): the design's pre-mortem (RISK → MITIGATION → CHECK) is
    # extracted so the coder MUST implement the mitigations and the reviewer verifies
    # the checks — turning risk prose into build requirements, not decoration.
    foresight = ctx.agents.extract_foresight(design)
    instruction = (
        f"Implement this task in the repository.\n\nTask: {state['task']}\n\n"
        f"Plan:\n{plan}\n\nDesign:\n{design}"
    )
    if foresight:
        instruction += (
            "\n\n## Mitigations you MUST implement\n"
            "The design anticipated these risks; implement each MITIGATION so its "
            f"CHECK holds:\n{foresight}"
        )
    # PREFETCH (#129 slice 4): hand the coder the same plan-named file contents the DESIGNER was
    # given. Reuses `grounded_overview`'s memoized grounding -- deterministic, no model call, no
    # second read of the tree. Appended last so the task/plan/design ordering the coder is used to
    # is unchanged, and only what the plan actually names is included.
    if getattr(ctx.settings, "coder_prefetch", False):
        grounding = build_grounding(ctx.workspace, plan)
        if grounding:
            instruction += f"\n\n{grounding}"
    if feedback:
        instruction += "\n\nEarlier feedback that must be addressed:\n" + "\n".join(
            f"- {f}" for f in feedback
        )
    return {
        "design": design,
        "foresight": foresight,
        "messages": [HumanMessage(content=instruction)],
    }


def author_tests_node(ctx: RunContext, state: RunState, config: RunnableConfig) -> dict[str, Any]:
    # Test-first (ADR-0013): Proctor authors the acceptance tests from the spec BEFORE
    # the coder implements. The tests it writes under tests/ become PROTECTED (the coder
    # is refused on them) and are the gate's ground truth via the normal validation path.
    # Runs once per item; the fix/revise loops re-enter at implement, not here, so the
    # tests are authored once and then held fixed.
    if not ctx.agents.tester_enabled:  # defensive: the node is only wired when enabled
        return {}
    # The operator authorized amending a blocking test (ADR-0087, #65) — handled BEFORE the
    # run-once guard and INSTEAD of it (see consume_amendment; it is an edit, not a re-authoring).
    amendment = consume_amendment(ctx, state, config)
    if amendment is not None:
        return amendment
    # RUN ONCE (ADR-0068): re-authoring on a re-plan rewrites the engine's own baselined tests → a
    # self-inflicted tamper thrash (the dominant cause). Author once. Also repopulate the process-
    # local protected set on a resume (red-team FN2, not rehydrated) so tool-refusal survives.
    if state.get("authored_tests"):
        ctx.protected_tests.update(state.get("authored_tests") or [])
        ctx.protected_tests.update(state.get("proctor_edits") or {})
        return {}
    # BEFORE the snapshot: engine ENVIRONMENT, not Proctor output (#129, see `statickit`).
    if getattr(ctx.settings, "static_testkit", False):
        install_statickit(ctx.workspace, state["task"])
    before = set(protected_test_paths(ctx.workspace))
    before_hashes = hash_files(ctx.workspace, before)
    # Pristine test TEXT for the weakening measure (#66) — taken BEFORE the Proctor writes, since
    # a count only means something against what was there first. Node-local, never in RunState.
    srcs = baseline_test_sources(ctx, state.get("integrity_baseline") or {})
    # Deterministic refactor scaffold (#60, ADR-0066 follow-up): for a DETECTED refactor the ENGINE
    # authors the differential golden-master oracle (freeze the original + a differential behaviour
    # test over generated inputs + a name-agnostic decomposition check), REPLACING the weak Proctor
    # over-strict/wrong authoring that reopened false-ship in the prompt-led form. `[]` (deny-by-
    # default) when off or it cannot confidently author → the Proctor authors as usual (below).
    # ENGINE-AUTHORED INERT ORACLE (#118 Approach B). Tried FIRST, and only for a lane the
    # deterministic classifier certified: it pins the falsifiable half of "this changes no
    # behaviour" -- the module still imports and its public surface is identical -- with no model
    # call at all. `[]` when it cannot confidently author, and the Proctor then authors as usual,
    # the same deny-by-default contract `scaffold_if_refactor` holds itself to.
    authored = scaffold_if_inert(
        ctx.workspace,
        enabled=getattr(ctx.settings, "inert_oracle_scaffold", False)
        and state.get("lane") == "reduced",
        certified_paths=tuple(state.get("lane_paths") or ()),
    )
    authored = authored or scaffold_if_refactor(
        ctx.workspace,
        enabled=ctx.settings.refactor_oracle_scaffold,
        task=state["task"],
        plan=state.get("plan", ""),
        design=state.get("design", ""),
        existing_tests=sorted(before),
    )
    proctor_edits: dict[str, str] = {}
    modify_targets: list[str] = []
    # None means the repair pass did not run, which is a different fact from "it ran and
    # changed nothing" -- collapsing those two is what makes a mechanism unmeasurable.
    pre_repair: list[str] | None = None
    # Same reason: computed inside the authoring branch, read unconditionally in the return.
    # An empty list means "the detector looked and found nothing", which is the right default for
    # a path that never authored -- there was no suite to flag.
    overstrict_findings: list[str] = []
    # Standing operator corrections (F17). The Proctor is invoked with a hand-built payload, not
    # wired as a node, so RunState reaches it only if we put it there — and each invocation is a
    # FRESH conversation, so this is the only channel that survives the boundary.
    carried = [str(c) for c in (state.get("corrections") or [])]
    captured: list[str] = []
    if not authored:
        result = ctx.agents.author_tests(authoring_instruction(ctx, state), config, carried)
        captured.extend(new_corrections(result, carried))
        after = sorted(protected_test_paths(ctx.workspace))
        after_hashes = hash_files(ctx.workspace, after)
        authored = authored_test_files(
            after, after_hashes, before_hashes, set(state.get("integrity_baseline") or {})
        )
        # Proactive validate/repair (#54, ADR-0058): coder-blind (no impl exists), the Proctor
        # repairs an over-strict/wrong test + strengthens a weak one. CODER-BLIND ONLY (red-team #54
        # FN2): only the FIRST authoring pass (iteration<=1) grants the tamper excuse — a gate-DENY
        # re-plan re-enters with the coder's code on disk, where a repair could fit a test to wrong
        # code and launder it (proctor_edits); a re-plan re-authors WITHOUT the excuse (deny-by-
        # default). Not reached when the deterministic scaffold authored (nothing to repair).
        # The detector's findings as the REPAIR SEES THEM. Computed here, before the repair pass,
        # because that is the only moment they exist: a post-repair read returned 0 findings on a
        # run whose `overstrict_static` was 8 -- the repair had already fixed them, so the sweep
        # would have recorded zeros and proved nothing. Caught by the pre-sweep verification.
        overstrict_findings = [
            f"{f.file}:{f.line} {f.kind} {f.snippet}"
            for f in authored_suite_overstrict_findings(
                ctx.workspace, authored, state.get("task", "")
            )
        ]
        # Snapshot BEFORE the repair pass so its effect is observable (#129). Only taken when
        # the pass will actually run -- an unconditional snapshot would double the digest on
        # every run for nothing.
        if getattr(ctx.settings, "tester_repairs_tests", False) and state.get("iteration", 0) <= 1:
            pre_repair = suite_assertion_digest(ctx.workspace, authored)
            # WHAT the Proctor was pointed at, recorded before it answers (ADR-0098). Without this,
            # an empty `proctor_edits` cannot distinguish "the model ignored a target it was given"
            # from "no target was ever named" — on 2026-08-11 that had to be reconstructed by
            # replaying the targeting against the case seed by hand.
            modify_targets = sorted({t[2] for t in _modify_amendment_targets(ctx, state)})
            authored, proctor_edits = _proctor_validate_repair(
                ctx, state, config, authored, before_hashes, carried + captured, captured, srcs
            )
    ctx.protected_tests.update(authored)  # live set → the coder's tools now refuse these
    # The Proctor's repaired PRE-EXISTING tests are part of the bar too — refuse the coder on them
    # at the tool level (defense in depth; the integrity guard already parks a coder re-weakening).
    ctx.protected_tests.update(proctor_edits)
    # Hand the acceptance tests to the coder as an explicit, must-pass contract — with their
    # BODIES (#55, ADR-0059), not just names, so it codes to the EXACT expected values/format the
    # tests assert instead of an imagined spec (the top source of first-pass misses). Capped.
    contract = _acceptance_contract(ctx.workspace, authored)
    msg = (
        "## Acceptance tests you must pass\n"
        "The tester (Proctor) authored these acceptance tests from the spec. Make them "
        "pass WITHOUT modifying them — they are protected, so a write/edit/delete to them "
        "is refused. Read the assertions below carefully: match the EXACT values, format, and "
        "behaviour they expect. If the task genuinely conflicts with one, do not route around it: "
        "reply 'SUMMARY: escalate — the task conflicts with a test: name it and the "
        f"contradiction'.\n{contract}"
    )
    # The RED PHASE (oracle-make-real Phase 1a): the suite must fail against the tree the coder
    # hasn't touched yet, or it isn't a test-first oracle. Runs the authored tests network-off
    # before implement; False here means they passed with no implementation.
    # A test that pins a value it never supplied can NEVER pass (F36). Deterministic, no model
    # call, and shown to the operator here rather than discovered ~250k tokens later at an
    # escalation. Detection only — ADR-0062 reverted mechanical loosening.
    unsatisfiable = [
        asdict(f)
        for f in unsupplied_roundtrip_findings(
            ctx.workspace,
            authored,
            f"{state.get('task', '')}\n{state.get('plan', '')}\n{state.get('design', '')}",
        )
    ]
    # One run, two answers (P2 Stage A): the red-verify boolean plus WHICH tests fail on the
    # seed — the raw signal for the runtime over-strict split (`authored_overstrict`).
    red_verified, seed_failures = authored_seed_results(ctx.workspace, ctx.sandbox, authored)
    # P2 Stage B: which of those seed failures provably assert PRE-EXISTING behaviour (their
    # reachable source mentions no new-behaviour token from the material claims). Recording
    # only in this stage — nothing reads it as a control input.
    overstrict_runtime = runtime_overstrict(
        {
            f: (ctx.workspace.root / f).read_text(encoding="utf-8", errors="replace")
            for f in authored
            if (ctx.workspace.root / f).is_file()
        },
        seed_failures,
        [c for c in (state.get("claims") or []) if isinstance(c, dict)],
    )
    # The ASSERTION FLOOR (Phase 1c): static AST check that the suite asserts something real.
    assert_real = authored_suite_asserts_behaviour(ctx.workspace, authored)
    out: dict[str, Any] = {
        "authored_tests": authored,
        # ADR-0098 diagnostic: the pre-existing tests the Proctor was TOLD to restate.
        # Always written, so "" and "never asked" stay distinguishable.
        "modify_amendment_targets": modify_targets,
        "tests_baseline": hash_files(ctx.workspace, authored),
        "tests_red_verified": red_verified,
        # None = unparseable/never-ran; [] = ran green. Distinct by contract (Stage A).
        "authored_seed_failures": seed_failures,
        # Recorded beside the assertion FLOOR, which already parses these same files --
        # the floor asks whether anything real is asserted, this records WHAT. Analysis-only.
        "authored_assertion_digest": suite_assertion_digest(ctx.workspace, authored),
        "authored_assertion_digest_pre_repair": pre_repair,
        "overstrict_findings": overstrict_findings,
        "authored_overstrict_runtime": overstrict_runtime,
        "tests_assert_real": assert_real,
        # ALREADY-SATISFIED (#44, ADR-0052): a real-asserting suite GREEN with no implementation is
        # a HINT the task may already be done — enough to conclude early + honestly instead of
        # thrashing to a mislabeled give-up, but NOT enough to auto-deliver (the suite could miss
        # the requirement; red-team found green-for-the-wrong-reason + skip/xfail cases). So it only
        # keeps route_after_capture from giving up and drives an honest "appears already satisfied"
        # reason; the run still parks on oracle_unverified for a human to confirm. assert_real here
        # ignores skip/xfail tests (a skipped suite reads green but never runs — see oraclecheck).
        "already_satisfied": bool(authored) and red_verified is False and assert_real is True,
        "messages": [HumanMessage(content=msg)],
    }
    if proctor_edits:
        # Emit only when non-empty: the sanctioned-edit overlay the tamper guard reads, and the flag
        # gate_node uses to require a PROVEN mutation-catch (a weakening can't launder). Declared in
        # RunState (ADR-0026) so LangGraph keeps it.
        out["proctor_edits"] = proctor_edits
    if unsatisfiable:
        out["unsatisfiable_tests"] = unsatisfiable
    if captured:
        # Only the DELTA — `corrections` has an `add` reducer, so returning everything carried in
        # would re-append it and the standing block would grow by its own length every turn.
        out["corrections"] = captured
    return out


def capture_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    summary = ""
    for message in reversed(state.get("messages", [])):
        if message.type == "ai":
            summary = message_text(message)
            break
    out: dict[str, Any] = {
        "coder_summary": summary,
        "coder_test_output": _amendment.pinned_coder_validation(ctx),
    }
    # THE LANE IS EARNED, NOT GRANTED (#118 Approach A). The classifier read a brief and a plan;
    # this reads what the coder actually did. A reduced-lane run that left its certified scope, or
    # wrote more than a non-behavioural change can, was misclassified — and because that lane
    # authored no acceptance test, it must not reach the gate on the cheap oracle. Recorded here
    # and turned into an honest park by the gate, never silently absorbed.
    if state.get("lane") == "reduced":
        diff = ctx.workspace.diff_all()
        scale = Scale("reduced", "", tuple(state.get("lane_paths") or ()))
        # The certified scope constrains the CODER's change, never the engine's own oracle. Tests
        # the engine or the Proctor authored are in the same diff and are not what was certified;
        # counting them made the engine refuse its own test (measured 2026-08-29, 3/3 park).
        engine_authored = set(state.get("authored_tests") or []) | set(
            (state.get("proctor_edits") or {}).keys()
        )
        violation = diff_within_scope(
            scale, changed_files(diff), engine_authored
        ) or added_lines_within_budget(diff, scale.paths)
        if violation:
            out["lane_violation"] = violation
            # Fail closed through machinery that ALREADY EXISTS, and deliberately not by teaching
            # the delivery gate a new reason: `packages/policies` is the trust boundary, and an
            # approach that leaves it byte-identical can prove it did not widen the acceptance
            # class rather than arguing it. A `blocked_reason` routes to supervise exactly as a
            # coder hand-raise does, and the run parks honestly with the measurement in its text.
            out["blocked_reason"] = (
                f"reduced lane misclassified: {violation}. The change was certified as "
                "non-behavioural, so no acceptance test was authored for it -- re-run on the full "
                "lane rather than shipping it on an oracle that was not built for this diff."
            )[:400]
    # Parse a structured hand-raise from the coder's final SUMMARY (the convention
    # repo.py already emits). Emit keys ONLY when present so an escalation set
    # upstream (e.g. plan_node's budget-exhausted note) is never clobbered. When set,
    # route_after_capture sends the run to the mode-gated supervisor.
    blocked, escalate = parse_yield(summary)
    if blocked:
        out["blocked_reason"] = blocked
    if escalate:
        out["escalate_reason"] = escalate
        # Mark this as a CODER-originated escalate (distinct from plan_node's degraded-plan
        # artifact, which reuses escalate_reason). route_after_capture reads this so an
        # already-satisfied run never swallows a genuine coder hand-raise (red-team ADR-0052).
        out["coder_escalated"] = True
    # THE TAMPER EVIDENCE, on the branch that needs it (red team 2026-08-21, R1+R2).
    #
    # A hand-raise routes implement -> capture -> supervise and never enters `test_node`, the only
    # writer of `tests_modified`/`tampered_paths`/`destroyed_paths`. Every reader — the gate, both
    # disposition arms, the `tests_unmodified` oracle, the amendment guard — then consulted a key
    # nobody had written and read the falsy `.get()` as CLEAN. Hardening the readers was tried and
    # was wrong in both directions; evidence that was never gathered cannot be recovered by the
    # thing reading it. Same move #75 made for `test_output` on this exact branch.
    #
    # Computed HERE rather than at supervise because here it is fresh: a producer that tampers
    # after the last validation is caught, which the presence check could never see.
    # `_tamper` fails closed — on an unreadable tree the keys stay ABSENT and
    # `ask_withheld_reason` withholds, so a torn clone costs a question instead of granting one.
    out.update(tamper_signals_for_handraise(ctx, state))
    return out


def route_after_plan(ctx: RunContext, state: RunState) -> str:
    # Plan-level no-progress breaker (#51, ADR-0056): a fallback/repeated plan that reached
    # `plan_stall_limit` self-stops as an HONEST EARLY park — straight to the gate, BEFORE
    # design/implement, so it never burns the coder cycle or the supervise give-up (thrash_park).
    # Everything else proceeds down the normal spine.
    if state.get("plan_unworkable_reason"):
        return "gate"
    # APPROACH B KEEPS THE FULL SPINE. The lane still means something -- it selects a
    # DETERMINISTIC oracle inside author_tests instead of routing around it -- but no node is
    # skipped, so every control that reads `authored_tests` (coder file protection, the tamper
    # guard, the amendment path, mutation targeting) keeps working unchanged. That is the whole
    # trade against A: more wall clock, nothing to argue about.
    return "design"


def route_after_capture(ctx: RunContext, state: RunState) -> str:
    # An agent hand-raise (parsed in capture_node, or set by plan_node on a degraded
    # plan) diverts to the mode-gated supervisor before the normal test path.
    #
    # ALREADY-SATISFIED (#44, ADR-0052): the Proctor's suite is green pre-impl, so an
    # `escalate_reason` here is almost always plan_node's degraded-plan artifact ("produced no
    # grounded plan") — the exact path that used to mislabel an already-done task "beyond what I can
    # complete" and thrash-park. Send it to the normal test→…→gate path so the gate concludes it
    # honestly ("appears already satisfied — confirm"), never an unattended deliver. But a GENUINE
    # coder hand-raise must still reach the supervisor: `blocked_reason` OR a coder-originated
    # `coder_escalated` both win (red-team ADR-0052 — the override used to swallow real escalates).
    if (
        state.get("already_satisfied")
        and not state.get("blocked_reason")
        and not state.get("coder_escalated")
    ):
        return "test"
    if state.get("blocked_reason") or state.get("escalate_reason"):
        return "supervise"
    return "test"
