"""Review-stage nodes: scan / review / quality_revise / review_fix / gate, plus
their routers."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from mosaera_policies import evaluate_gate, request_approval

from mosaera_core.behavior_preservation import is_behavior_preserving
from mosaera_core.claim_oracles import (
    evaluate_claims,
    failed_claim_classes,
    failed_claim_ids,
    satisfied_structural_claim_ids,
)
from mosaera_core.graph._amendment import sanctioned_test_edit
from mosaera_core.graph._freshness import is_fresh, live_tree
from mosaera_core.graph._gate_outcomes import (
    deny_finalizes,
    gate_outcomes,
    stall_sentence,
    stall_signature,
)
from mosaera_core.graph._oracle_legs import evaluate_oracle
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.convergence import apply_trip, stall_bump
from mosaera_core.graph.grounding import _review_quality_evidence, _trunc
from mosaera_core.graph.nodes_scan import (
    scan_node as scan_node,
)  # re-export: build.py imports it here
from mosaera_core.graph.state import RunState
from mosaera_core.oracle_dispute import dispute_for_state, residual_note
from mosaera_core.oraclecheck import standing_suite_is_independent_oracle
from mosaera_core.progress import bump_stall, fingerprint, stall_message
from mosaera_core.quality import (
    QualityScore,
    changed_files,
    changed_python_files,
    quality_findings,
    run_quality,
    should_revise,
    worst_dimension,
)
from mosaera_core.verdict import parse_reviewer_verdict


def review_node(ctx: RunContext, state: RunState, config: RunnableConfig) -> dict[str, Any]:
    diff = ctx.workspace.diff_all()
    # Thread config so the reviewer's read-tool calls stream as activity
    # milestones (attributed to the review node), same as the coder.
    review = ctx.agents.review(
        state["task"],
        state.get("plan", ""),
        diff,
        state.get("test_output", ""),
        state.get("findings_text", ""),
        design=state.get("design", ""),
        foresight=state.get("foresight", ""),
        quality=_review_quality_evidence(ctx.workspace, diff),
        config=config,
    )
    # A local reviewer sometimes concludes without a parseable VERDICT line, which
    # would else be read as UNKNOWN and FALSE-PARK correct, passing work. One bounded
    # direct model call recovers the reviewer's own verdict before it's read
    # downstream (ADR-0028). Only fires on UNKNOWN; the validation/tester gate is
    # independent, so a recovered APPROVE still can't ship failing code.
    if parse_reviewer_verdict(review) == "UNKNOWN":
        clarified = ctx.agents.clarify(review, config)
        if clarified:
            review = f"{review}\n\n{clarified}"
    result: dict[str, Any] = {"diff": diff, "review": review, "review_tree": live_tree(ctx)}
    # No-progress detector (reviewer loop): the reviewer↔coder fix loop closes
    # HERE now (route_after_review → review_fix → implement → … → review), so the
    # breaker lives here — a reviewer that keeps drawing the SAME REQUEST_CHANGES
    # isn't converging. Trips to an honest capability park at the gate instead of
    # looping to the iteration cap. Each loop tracks its OWN per-kind streak
    # (stall_bump), so an interleaved hygiene/test pass can't reset the reviewer's.
    if (
        ctx.settings.stall_detection_enabled
        and not state.get("stalled")
        and parse_reviewer_verdict(review) == "REQUEST_CHANGES"
    ):
        by_kind, count, tripped = stall_bump(ctx, state, "review", review)
        result["stall_by_kind"] = by_kind
        if tripped:
            apply_trip(
                ctx,
                state,
                result,
                "review",
                review,
                f"the reviewer requested the same change {count + 1} times in a row",
            )
    # Advisory code-quality of the changed python files (deterministic, off the
    # interactive path). Best-effort: a non-python change / tool miss → no ring.
    qscore = run_quality(ctx.workspace, diff)
    if qscore is not None:
        result["quality"] = json.dumps(qscore.to_dict())
    return result


def route_after_review(ctx: RunContext, state: RunState) -> str:
    # Reason-before-park (ADR-0017): a first no-progress trip reasons before parking.
    if state.get("needs_reason"):
        return "reason"
    # Correctness before craftsmanship: a reviewer REQUEST_CHANGES routes back to a
    # TARGETED coder fix (bypassing plan/design) before the delivery gate, so the
    # human gate is reserved for delivery. Bounded by the shared max_iter budget AND
    # a review_max_fixes sub-cap; a run the no-progress breaker already tripped skips
    # the loop and parks honestly.
    if (
        ctx.settings.review_fix_enabled
        and not state.get("stalled")
        and state.get("iteration", 0) < ctx.max_iter
        and state.get("review_revises", 0) < ctx.settings.review_max_fixes
        and parse_reviewer_verdict(state.get("review", "")) == "REQUEST_CHANGES"
    ):
        return "review_fix"
    # Phase 2 (opt-in): a below-bar change loops back for a TARGETED per-dimension
    # revision before the delivery gate. Best-effort — this only ever loops to
    # improve craftsmanship; it never blocks delivery (that stays the evidence
    # gate's job). The pure decision (with its budget/cap/no-regression guards)
    # lives in quality.should_revise so it's unit-testable outside the graph.
    # A run the no-progress breaker already tripped skips the quality revise and
    # heads to the gate to park honestly.
    if (
        not state.get("stalled")
        and ctx.settings.quality_revise_enabled
        and should_revise(
            state.get("quality", ""),
            state.get("quality_prev", ""),
            iteration=state.get("iteration", 0),
            max_iter=ctx.max_iter,
            revises=state.get("quality_revises", 0),
            min_composite=ctx.settings.quality_min,
            dim_floor=ctx.settings.quality_dim_floor,
            max_revises=ctx.settings.quality_max_revises,
        )
    ):
        return "quality_revise"
    return "gate"


def quality_revise_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Targeted repair modeled on fix_node: hand the coder ONLY the weak dimension
    # and its concrete findings, bypassing plan/design so the revision stays
    # scoped (uses surgical edit_file + the design already in context). Increments
    # `iteration` itself since it skips plan_node (the usual counter) — sharing the
    # budget keeps route_after_review/route_after_gate bounded.
    curr = QualityScore.from_dict(json.loads(state["quality"]))
    dim = worst_dimension(curr)
    if dim is None:  # unreachable: route_after_review only routes here with a target
        return {}
    findings = quality_findings(ctx.workspace, changed_python_files(state.get("diff", "")))
    instruction = ctx.agents.quality_revise_instruction(
        dim.name, dim.score or 0, findings.get(dim.name, [])
    )
    note = f"quality revise: {dim.name} {dim.score}/100 (composite {curr.composite})"
    return {
        "iteration": state.get("iteration", 0) + 1,
        "quality_prev": state["quality"],
        "quality_revises": state.get("quality_revises", 0) + 1,
        "quality_revise_log": [note],
        "messages": [HumanMessage(content=instruction)],
    }


def review_fix_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Targeted repair for a reviewer REQUEST_CHANGES, modeled on fix_node /
    # quality_revise_node: hand the coder the reviewer's asks (bypassing plan/design)
    # so it addresses them surgically instead of re-planning from scratch. Increments
    # `iteration` itself (it skips plan_node, the usual counter) so the loop stays
    # bounded by max_iter, and the re-review closes the loop.
    instruction = ctx.agents.review_fix_instruction(state.get("review", ""))
    note = f"review revise {state.get('review_revises', 0) + 1}: addressing reviewer changes"
    return {
        "iteration": state.get("iteration", 0) + 1,
        "review_revises": state.get("review_revises", 0) + 1,
        "review_revise_log": [note],
        "messages": [HumanMessage(content=instruction)],
    }


def gate_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # The evidence check happens BEFORE anyone approves: the decision rides
    # in the gate payload so humans decide informed and the autonomous
    # runner can apply policy (mosaera_policies.gate) — it never overrides.
    # An INDEPENDENT oracle vouched this run iff one of these holds (oracle-make-real):
    #  - the tester (Proctor) authored a suite that FAILS pre-impl (red phase, 1a) AND ASSERTS
    #    something real (assertion floor, 1c) — a tautological suite is not an oracle;
    #  - a PRE-EXISTING, tamper-guarded suite the coder cannot weaken (Phase 2): the baseline must
    #    hold actual TEST FILES that ASSERT something real — a bare `pyproject.toml`/`conftest` is
    #    collection CONTROL, not a suite (plain `bool(integrity_baseline)` credited any repo merely
    #    carrying a pyproject) — AND that suite must REFERENCE the changed code (module-reference
    #    heuristic, F1): a suite about UNRELATED modules is not an oracle for THIS change, else a
    #    brownfield change no test touches auto-ships on an irrelevant green suite. ADR-0036 keeps
    #    tests_passed False if the coder weakened it, so a green run vouches on non-coder tests;
    #  - the operator named the oracle via --test-cmd (their judgement, ADR-0034).
    # NOT coupled to the reviewer at all: oracle independence is about the SUITE (that coupling
    # over-parked genuine-oracle runs when the reviewer was made required). ADR-0029's
    # `reviewer_advisory` off-switch was RETIRED in the #81 cleanup — ADR-0031 → ADR-0034 had
    # rebuilt the silence backstop as a deterministic conjunction in `policies/gate.py` that never
    # read it. Combined with tests_passed + strength inside evaluate_gate. Deny-by-default (P3).
    tester_vouched = (
        bool(state.get("tests_baseline"))
        and state.get("tests_red_verified") is True
        and state.get("tests_assert_real") is True
    )
    # Change-coverage (#29, P1): when oracle_coverage measured this run, runtime line coverage of
    # the changed lines decides the standing-suite credit PRECISELY (does a test execute them?),
    # replacing the coarse import heuristic. None (off / unmeasurable) falls back to the heuristic.
    covered = state.get("changed_lines_covered") if ctx.settings.oracle_coverage else None
    # The two floors (mutation, #52 Phase 1b; structural-spec, #80/ADR-0072) and the four-route
    # independence OR are evaluated together in `_oracle_legs.evaluate_oracle`, which returns the
    # verdict AND the per-leg record in one pass — see that module for why they are not separable.
    # Per-claim oracle evaluation (ADR-0079 Wave 2): core evaluates every structured claim the
    # run carried (launch-minted, operator-approved acceptance — never workspace content) and
    # records the verdict rows; ONLY evaluated failures will reach the gate (owner decision
    # 2026-08-03 — unbound claims are intake's job). No claims ⇒ empty rows ⇒ gate unchanged.
    claim_dispositions = evaluate_claims(state.get("claims") or [], ctx.workspace, dict(state))
    # Refactor vouching (#60, ADR-0079 applied to the MCB-14 wall): a PURE refactor can never
    # red-verify (its behaviour is unchanged by definition, so the Proctor's tests are green
    # pre-impl) and the coverage-gated standing suite de-credits on one uncovered line — 20/20
    # grader-correct runs refused (engineering-history/claims-gate-ab-2026-08-03 §MCB-14). The
    # genuinely NEW independence evidence for a refactor is a SATISFIED material structural
    # claim: the delivered AST provably has the shape the operator asked for. Deny-by-default
    # at every guard: the task itself (TRUSTED text only — the refactor_scaffold red-team
    # lesson; never the PM paraphrase) must state behaviour preservation, the tamper guard
    # must be clean, and the claim must be proven-satisfied (never unbound/unevaluable).
    # Downgrade-safe: this only ever ADDS a disjunct to the independence OR — the behavioural
    # legs (tests_passed, mutation_ok, structural_ok) still gate exactly as before.
    _preserving = is_behavior_preserving(state["task"])
    _tamper_clean = not state.get("tests_modified")
    structural_vouch_ids = (
        satisfied_structural_claim_ids(claim_dispositions, state.get("claims") or [])
        if _preserving and _tamper_clean
        else []
    )
    # ALWAYS-set, self-explaining diagnosis (ADR-0078: an invisibly non-firing control costs a
    # day of archaeology). Vouched → the ids; not vouched → which guard said no.
    vouch_diag = (
        f"structural_claims:{','.join(structural_vouch_ids)}"
        if structural_vouch_ids
        else "no_vouch:"
        + ";".join(
            [
                *([] if _preserving else ["not_behavior_preserving"]),
                *([] if _tamper_clean else ["tests_modified"]),
                *(["no_satisfied_structural_claim"] if _preserving and _tamper_clean else []),
            ]
        )
    )
    oracle_verified, oracle_legs = evaluate_oracle(
        tester_vouched=tester_vouched,
        # A callable: it walks the workspace, so the OR short-circuits past it (unless record_all).
        standing_suite=lambda: standing_suite_is_independent_oracle(
            ctx.workspace,
            state.get("integrity_baseline"),
            changed_files(state.get("diff", "")),
            covered,
        ),
        test_cmd=bool(ctx.test_cmd),
        structural_vouch=bool(structural_vouch_ids),
        mutation=state.get("tests_mutation_caught"),
        mutation_cause=str(state.get("tests_mutation_cause") or ""),
        structural_spec=state.get("structural_spec_ok"),
        sanctioned_edit=sanctioned_test_edit(state),
        mutation_vetoes=ctx.settings.oracle_mutation_vetoes,
        record_all=ctx.settings.oracle_record_all_legs,
    )
    gd = evaluate_gate(
        tests_passed=state.get("tests_passed"),  # absent → None → parks honestly
        reviewer_verdict=parse_reviewer_verdict(state.get("review", "")),
        findings_count=len(state.get("findings", [])),
        iteration=state.get("iteration", 0),
        max_iterations=ctx.max_iter,
        oracle_verified=oracle_verified,
        # What a green run is WORTH here, declared by the LanguagePack that built the plan
        # (ADR-0034). Absent plan → "unknown" → not "suite" → never rides the silence
        # backstop. `tests_passed is True` alone is not a claim about behaviour: on a
        # testless repo the plan is `compileall`, so green just means "it parses".
        validation_strength=str((state.get("validation_plan") or {}).get("strength", "unknown")),
        # deliver_unverified coerced tests_passed None→True upstream of this gate, so the
        # True above can stand for NO executed validation at all. Tell the gate, so silence
        # can't ship it (a reviewer APPROVE still can — that is the flag's actual contract).
        validation_unverified=bool(state.get("validation_unverified", False)),
        # Did we ever GET to validation? `test_node` writes `validation_plan` whenever it runs
        # (whatever the outcome), so its absence proves the node was never entered — the run
        # routed straight to the gate from a plan-unworkable stop or a supervise give-up. Without
        # this the gate says "validation unavailable", which reads as "this project has no
        # validator" and sends a human to check the sandbox (F39, #71 — measured 2026-08-07).
        validation_attempted=bool(state.get("validation_plan")),
        # The coder weakened a pre-existing/protected test or its collection config (ADR-0036).
        # A dedicated reason so this parks even in autonomous mode and reads honestly in the
        # report — not just an anonymous validation_failed.
        tests_tampered=bool(state.get("tests_modified")),
        # The held-out critic (#60, ADR-0065) judged the delivered outcome and returned a confident
        # VETO — a specific unmet spec requirement (the executed-but-unasserted class determinism
        # can't catch). Veto-only + downgrade-only: appends `critic_vetoed` → parks in every mode.
        critic_vetoed=bool((state.get("outcome_verdict") or {}).get("vetoed")),
        # Deny-by-default security evidence (ADR-0076): scan_node's tri-state verdict. The
        # ABSENT ⇒ "unavailable", never "clean": two edges reach this gate without scan_node
        # (plan-unworkable, give-up), and defaulting those to clean is the failure ADR-0076
        # exists to prevent. Three questions, three arguments, because they fail differently:
        security_status=str(state.get("security_status") or "unavailable"),
        # ...was `scan_node` ENTERED at all? The coercion above destroys that (ADR-0107).
        scan_attempted="security_status" in state,
        # ...and does it describe THIS tree? A stale "clean" produced reasons==[] and SHIPPED.
        scan_fresh=is_fresh(ctx, state, "security_tree"),
        review_fresh=is_fresh(ctx, state, "review_tree"),
        # Per-claim evidence (ADR-0079 Wave 2): ONLY evaluated failures — unbound/unevaluable
        # claims add nothing (owner decision 2026-08-03). Empty ⇒ pre-claims gate byte-for-byte.
        claims_failed=failed_claim_ids(claim_dispositions),
        # Core classifies; the gate names only the class (ADR-0092). The flat id list above
        # is unchanged, so `GateDecision.unsatisfied_claims` — and the receipt seal over it —
        # stay byte-for-byte.
        claims_failed_classes=failed_claim_classes(claim_dispositions, state.get("claims") or []),
        # ADR-0099 — a STANDING PROHIBITION, not a criterion. A pre-existing file the producer
        # reduced to nothing is a removal that hides: still present, still tracked, empty.
        # Passed as a flag like `tests_tampered` because nobody ASKS for "do not empty this
        # file" — there is no claim, so there is no claim id, and the class-derived reasons
        # cannot carry it.
        content_destroyed=bool(state.get("destroyed_paths")),
    )
    # The no-progress breaker fires in the loops that can spin (test_node for the
    # fix loop, review_node for the reviewer loop); the gate only CARRIES a trip
    # forward into its payload so a non-converging run parks with an honest
    # capability note instead of re-looping identically to the cap.
    stalled = bool(state.get("stalled"))
    stall_reason = state.get("stall_reason", "")
    # The priced residual and the two-bars dispute: both computed AFTER `gd`, both change
    # nothing about it, both exist so an approval accepts a NAMED thing (ADR-0071/#129).
    oracle_residual = residual_note(
        structural_vouched=bool(structural_vouch_ids),
        gate_reasons=gd.reasons,
        mutation=state.get("tests_mutation_caught"),
    )
    oracle_dispute = dispute_for_state(ctx, state, gd.reasons, oracle_legs, covered)
    decision = request_approval(
        "deliver",
        f"Finalize run {ctx.run_id}: commit to branch {ctx.workspace.branch} "
        "and write the delivery report",
        {
            "task": state["task"],
            "plan": state.get("plan", ""),
            "diff": _trunc(state.get("diff", ""), 6000),
            "test_output": _trunc(state.get("test_output", ""), 2000),
            "findings": state.get("findings_text", ""),
            "review": state.get("review", ""),
            # Advisory: the code-quality score (+ any revises) so a human at the
            # gate decides quality-aware. Not a gating input (trust boundary intact).
            "quality": state.get("quality", ""),
            # Tri-state: None honestly means "no validation available".
            "tests_passed": state.get("tests_passed"),
            # Honest caveat: delivered without an automated validator (P3).
            "validation_unverified": state.get("validation_unverified", False),
            "iteration": state.get("iteration", 0),
            # The revision budget: "send back to revise" loops to planning
            # until this cap, after which the run finalizes without shipping.
            "max_iterations": ctx.max_iter,
            "gate_decision": gd.as_dict(),
            # Honest capability signal: when the run isn't converging, the human
            # sees "I can't complete this — <reason>" + Forge's own last report,
            # not a resource ask. (Assembled here — no evaluate_gate/policy change.)
            "stalled": stalled,
            "stall_reason": stall_message(stall_reason, state.get("coder_summary", ""))
            if stalled
            else "",
            # The honest-stop (#56, ADR-0060): the supervisor concluded early with an
            # accurate reason (a diagnosed no-convergence or a believed hand-raise).
            # Distinct from `stalled` — this is an honest conclusion, not a thrash park.
            "give_up_reason": state.get("give_up_reason", ""),
            # Per-claim evidence (ADR-0079 Wave 2): the human gate panel sees WHICH claim
            # stands on what. Advisory in the payload; the gating input is the reduced
            # claims_failed list inside evaluate_gate.
            "claims": state.get("claims") or [],
            "claim_dispositions": claim_dispositions,
            # #60: WHY the oracle vouched, when the structural-claim leg carried it — the
            # human panel must never see a vouched ship with no visible oracle.
            "oracle_vouched_by": vouch_diag,
            # WHICH term of the oracle AND refused (`blocked_by`), plus every leg's value. The
            # corpus could previously only infer this from a co-recorded field, and that
            # inference produced a wrong hypothesis on 2026-08-11.
            "oracle_legs": oracle_legs,
            "oracle_residual": oracle_residual,
            "oracle_dispute": oracle_dispute,  # the question, where the human reads it
            # #61: the human at the park finally sees WHY the critic vetoed (reason + rows);
            # previously only the bare critic_vetoed token reached the payload.
            "outcome_verdict": state.get("outcome_verdict"),
            # WHY an authorized amendment was refused, per path (F71 — see _proctor_authoring).
            "amendment_refusals": state.get("amendment_refusals") or {},
            # What the lint/type gate actually did (#80). Informational; nothing branches on it.
            # "disabled" when the operator turned the stage off — absent state means it never ran.
            "hygiene_status": str(
                state.get("hygiene_status")
                or ("disabled" if not ctx.settings.hygiene_gate_enabled else "unavailable")
            ),
            "hygiene_unavailable": list(state.get("hygiene_unavailable") or []),
            # What each answer will ACTUALLY do (ADR-0082 §1, F61). Computed from run state —
            # never authored by a model — and an answer that cannot function is not offered.
            # The gate previously showed "Send back to revise" at the iteration cap, where the
            # only effect was to end the run and discard the notes.
            "outcomes": [
                o.as_dict()
                for o in gate_outcomes(
                    {**state, "gate_decision": gd.as_dict()},
                    max_iter=ctx.max_iter,
                    gate_stall_limit=ctx.settings.gate_stall_limit,
                    stall_detection=ctx.settings.stall_detection_enabled,
                )
            ],
        },
    )
    # An approval over BLOCKING REASONS, made by an actual person. The old form inferred
    # this from `approved and reasons`, on the premise that "an autonomous approve only
    # ever happens with empty reasons" — which ADR-0031 falsified: the reviewer-silence
    # backstop approves with reasons == ["reviewer_unknown"]. Every autonomous silence-ship
    # was therefore recorded, and rendered in the UI, as "a human approved delivery despite
    # the reasons above". Take WHO decided from the decision itself (ADR-0034); an unmarked
    # resume reads as "unknown" and never gets branded a human override.
    gate_state = {
        **gd.as_dict(),
        "human_override": bool(decision.approved and gd.reasons and decision.actor == "human"),
        # #60/#62: the vouch diagnosis survives into committed state (additive — every reader
        # of gate_decision uses .get on named keys), so the API's termination reason can say
        # "vouched refactor blocked by a surviving mutation" instead of a generic oracle line.
        "oracle_vouched_by": vouch_diag,
        # Survives into committed state so a PARKED run's card can say which leg refused —
        # the read that matters, since parks are what we are trying to explain.
        "oracle_legs": oracle_legs,
        # The durable receipt fields (ADR-0071 amendment): the priced residual and the raw
        # mutation tri-state survive into committed state so persist can write the receipt
        # row — the residual a human accepted must be reconstructable after the run.
        "oracle_residual": oracle_residual,
        # Survives into committed state: a park that blamed the impl stays reconstructable.
        "oracle_dispute": oracle_dispute,
        "tests_mutation_caught": state.get("tests_mutation_caught"),
    }
    if decision.approved:
        return {
            "approved": True,
            "gate_decision": gate_state,
            "claim_dispositions": claim_dispositions,
        }
    out: dict[str, Any] = {
        "approved": False,
        "gate_decision": gate_state,
        "claim_dispositions": claim_dispositions,
        "feedback": [decision.feedback or "change denied at the approval gate"],
    }
    # Gate-loop honest-stop (#67, ADR-0069): the gate-deny → re-plan loop has NO breaker (the #51
    # plan-breaker only trips on a fallback/identical plan), so a run whose gate keeps denying THE
    # SAME WAY re-plans to the cap on CORRECT code → thrash. Fingerprint the blocking reasons and
    # conclude honestly (give_up_reason, stalled False → honest_park BY CONSTRUCTION) after
    # gate_stall_limit consecutive same-reason denials, STRICTLY below the cap. A CHANGED reason
    # (progress through blockers) RESETS the streak (bump_stall) → a run still working toward a ship
    # is never cut off. The named blocker feeds #66 (why correct code isn't shipping). Flows AROUND
    # evaluate_gate — no packages/policies touch, mirrors plan_unworkable_reason/#56.
    if ctx.settings.stall_detection_enabled and gd.reasons:
        # ADR-0092 amends ADR-0069: the fingerprint is over reason CLASSES, so a reason SPLIT
        # cannot silently reset a streak (see `stall_signature`). The sentence is built separately
        # and truncated structurally — the two used to share one string for no reason.
        curr = fingerprint("gate", stall_signature(gd.reasons))
        by_kind = dict(state.get("stall_by_kind") or {})
        prev = by_kind.get("gate") or ["", 0]
        count, tripped = bump_stall(str(prev[0]), curr, int(prev[1]), ctx.settings.gate_stall_limit)
        by_kind["gate"] = [curr, count]
        out["stall_by_kind"] = by_kind
        if tripped and state.get("iteration", 0) < ctx.max_iter:
            out["give_up_reason"] = stall_sentence(gd.reasons, count + 1)
            out["stalled"] = False  # route_after_gate:383 finalizes → honest_park (below cap)
    return out


def route_after_gate(ctx: RunContext, state: RunState) -> str:
    # Routing is intentionally a pure function of `approved` + the cap:
    # `approved` is only ever set by an informed human (who saw the
    # gate_decision in the payload) or the all-clear autonomous policy —
    # see mosaera_policies.gate. The cap branch FINALIZES (report/persist);
    # deliver_node still commits only when approved. A tripped no-progress
    # breaker also finalizes — re-planning identically would only burn tokens.
    # `plan_unworkable_reason` (#51): a plan-breaker park routed here (guided/resolved drive) must
    # FINALIZE, never loop back to plan — re-planning is exactly what it self-stopped to avoid.
    # `give_up_reason` (#56): the supervise give-up likewise concluded — never re-plan it.
    # The finalizing conditions live in `deny_finalizes` — ONE function, shared with the gate's
    # own presentation (ADR-0082 §1, F61). A second copy of "when does a denial terminate?" is
    # exactly the defect being fixed: the operator was shown "Send back to revise" at the cap while
    # this branch quietly finalized and discarded their feedback. Keeping routing and the sentence
    # on the same predicate makes that divergence impossible rather than merely unlikely.
    if state.get("approved") or deny_finalizes(state, ctx.max_iter):
        return "deliver"
    return "plan"
