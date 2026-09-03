"""`mosaera-bench` — run capability benchmarks and track regressions.

Runs the governed loop over a case's fixed brief (real model + sandbox), grades
the delivered code against the hidden acceptance suite, and writes a versioned
scorecard. `--compare` diffs a fresh run against a committed baseline and exits
non-zero on a regression; `--update-baseline` records a new baseline. This is a
heavy, opt-in tool (needs a model + a Docker daemon) — it is NOT part of
`make test`.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import replace

from mosaera_core.behavior_preservation import is_behavior_preserving
from mosaera_core.bench._escalation_run import (
    run_with_escalation,
)
from mosaera_core.bench._preserve import _save_delivered_patch
from mosaera_core.bench.cases import BenchCase, available_cases, load_case
from mosaera_core.bench.compare import average, compare, load_baseline, write_baseline
from mosaera_core.bench.faithfulness import overstrict_static_count, overstrict_vs_reference
from mosaera_core.bench.grade import GraderOutcome, grade
from mosaera_core.bench.grader_probe import grader_catches_a_mutation
from mosaera_core.bench.harness import RunOutcome, build_inputs
from mosaera_core.bench.layer2 import Layer2Outcome, try_layer2_conversion
from mosaera_core.bench.reliability import classify_outcome, classify_park_cause
from mosaera_core.bench.report import print_summary, write_scorecard
from mosaera_core.bench.scorecard import Scorecard, is_over_park, score
from mosaera_core.bench.suite import SuiteReport, build_suite, write_suite
from mosaera_core.claim_oracles import clauses_applied, failed_claim_kinds
from mosaera_core.config import Settings, apply_oracle_posture
from mosaera_core.disposition import (
    convertible_decline_reason,
    convertible_park_class,
)
from mosaera_core.eligibility import effective_test_output
from mosaera_core.progress import parse_failing_tests
from mosaera_core.sandbox import create_sandbox
from mosaera_core.statickit import statickit_adopted


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def _grade_run(run: RunOutcome, case: BenchCase, settings: Settings, backend: str) -> GraderOutcome:
    """Grade one attempt's delivered workspace against the hidden acceptance suite."""
    if run.workspace is None:  # pragma: no cover - run_case always sets it
        raise RuntimeError("benchmark run produced no workspace")
    grade_sandbox = create_sandbox(
        backend,
        run.workspace.root,
        image=settings.sandbox_image,
        docker_bin=settings.docker_bin,
        default_timeout=settings.sandbox_timeout,
    )
    return grade(run.workspace, case.grader_dir, grade_sandbox, kind=case.kind)


def _run_once(case: BenchCase, settings: Settings, backend: str) -> Scorecard:
    stamp = _stamp()
    run_id = f"bench-{case.id}-{stamp}"
    run, grader, escalation_path, escalation_outcome = run_with_escalation(
        case, settings, backend, run_id, _grade_run
    )
    inputs = build_inputs(run, grader, case)
    cost = {k: run.rollup.get(k) for k in ("total_tokens", "usd", "calls", "by_agent")}
    delivered = bool(run.final.get("approved"))
    # From the interrupt PAYLOAD, not committed state: a parking gate visit never resumes, so
    # `run.final["gate_decision"]` is empty (or stale, on a deny→replan run). See RunOutcome.
    gate_reasons = run.terminal_reasons
    # The #43 reliability scoreboard (ADR-0053): classify how this run CONCLUDED. acceptance_failed
    # is the false-ship signal — delivered, but the hidden grader ran and failed (same as line 92).
    acceptance_failed = delivered and grader.ran and not grader.all_passed
    # The effective iteration cap matches build_graph's clamp (max_iterations=case.max_iterations,
    # then min with the ceiling) so a ride-to-cap park is bucketed as thrash (#51, ADR-0056).
    eff_cap = min(case.max_iterations, settings.max_iterations_ceiling)
    outcome = classify_outcome(
        run.final,
        errored=bool(run.error),
        acceptance_failed=acceptance_failed,
        max_iterations=eff_cap,
    )
    # Layer-2 conversion measurement (#76): when enabled, run the REAL disposition on a
    # CONVERTIBLE honest-park (oracle_unverified, or the ADR-0075 engine-blocked give-up) and
    # cross-tab its verdict with the HIDDEN grader (the ground truth for whether the
    # parked-but-delivered code is actually correct). This is pure OVERLAY instrumentation —
    # `outcome` stays the frozen classifier's bucket; the L2 effect is aggregated separately so a
    # false conversion is VISIBLE (verified + grader_failed) rather than hidden.
    l2 = Layer2Outcome(None)
    layer2_class: str | None = None
    layer2_decline = ""
    grader_mutation_caught: bool | None = None
    # `terminal_state`, NOT `final` — a park commits no gate decision, which is why Layer 2
    # was eligible ZERO times across 2,049 cards (ADR-0078's fourth residual). The classifier
    # calls below keep `run.final`; that asymmetry is the rule, not an oversight.
    judged = run.terminal_state
    if settings.disposition_gap_close and outcome == "honest_park":
        admit = settings.layer2_admit_structural_claim
        layer2_class = convertible_park_class(judged, admit_structural_claim=admit)
        # WHY it declined, always recorded. The 2026-08-05 sweep hit a park with the exact class-1
        # shape that Layer 2 refused, and nothing recorded the reason — the final state was gone by
        # the time anyone asked, so the cause is permanently unrecoverable.
        layer2_decline = convertible_decline_reason(judged, admit_structural_claim=admit)
    if layer2_class:
        l2 = try_layer2_conversion(run, case, settings, backend, layer2_class)
        print(
            f"  layer2: {layer2_class} park -> {l2.verdict} ({l2.reason}) "
            f"(hidden grader_passed={grader.all_passed if grader.ran else 'n/a'})"
        )
        # DIAGNOSTIC, strictly after the verdict above: would the hidden grader have caught the
        # mutation the authored test missed? It answers whether the dominant refusal is an
        # authoring-quality gap or evidence that mutation is not the discriminator. It can never
        # influence `l2` — that is already decided, and the probe purges the key again on exit.
        if l2.verdict is not None and run.workspace is not None and l2.source:
            probe_sandbox = create_sandbox(
                backend,
                run.workspace.root,
                image=settings.sandbox_image,
                docker_bin=settings.docker_bin,
                default_timeout=settings.sandbox_timeout,
            )
            grader_mutation_caught = grader_catches_a_mutation(
                run.workspace,
                probe_sandbox,
                case.grader_dir,
                list(l2.source),
                l2.changed or {},
            )
            print(f"  grader-probe: grader_mutation_caught={grader_mutation_caught}")
    # PRESERVE THE WORK PRODUCT BEFORE IT IS DESTROYED (2026-08-12). `overstrict_vs_reference`
    # below overlays the case reference solution onto the workspace, and the coder's writes are
    # not always staged — so for a run whose files were never `git add`ed, the delivered code is
    # afterwards unrecoverable: the index holds HEAD and the tree holds the reference. Measured
    # on MCB-05's false ships, which could not be diagnosed at all for exactly this reason, on
    # precisely the runs most worth diagnosing. The patch is written beside the scorecard rather
    # than onto the card (a diff is unbounded; a card is read into memory by every analysis).
    _save_delivered_patch(run, settings, case.id, stamp)
    # POISONS the workspace (overlays the case reference solution), so it must stay AFTER the
    # Layer-2 attempt and the grader probe above — both read the agent's real work product.
    # Hoisted out of the dict literal only to return a (count, denominator) pair; the ordering
    # relative to those two callers is unchanged and is what `faithfulness` warns about.
    _overstrict = overstrict_vs_reference(run, case, settings, backend)
    meta = {
        "stamp": stamp,
        "run_id": run_id,
        "sandbox": backend,
        "kind": case.kind,
        "capability": case.capability,
        "tier": case.tier,
        "elapsed_s": round(run.elapsed_s, 1),
        "delivered": delivered,
        "parked": run.parked,
        "revised": run.revised,
        "error": run.error,
        # The terminal reliability bucket (clean_deliver / honest_park / thrash_park / false_ship /
        # crash) — read by the suite rollup for the clean-conclusion rate. compare.average
        # re-aggregates these across repeats into meta["outcomes"].
        "outcome": outcome,
        # The deterministic model-escalation path taken this run (empty = no escalation).
        "escalation_path": escalation_path,
        # Proctor faithfulness (#57, ADR-0062): how over-strict the authored acceptance suite was.
        # `static` = detector findings; `vs_ref` = authored tests that FAIL against the known-good
        # reference (provably over-strict), or None when no reference. This is the lever the arc is
        # measured on -- it must DROP as the guard converts thrash to deliver.
        "overstrict_static": overstrict_static_count(run, case),
        "overstrict_vs_ref": _overstrict[0],
        # The DENOMINATOR (2026-08-11). Without it `overstrict_vs_ref` is a bare count and
        # "wrote worse tests" is indistinguishable from "wrote more tests" — the ambiguity
        # that made MCB-22's +204% uninterpretable and decided the tester-model experiment.
        "overstrict_total": _overstrict[1],
        # Held-out critic (#60, ADR-0065): did the critic actually VETO this run? The arc's effect
        # on `false_ship`/`clean_deliver` flows through `outcome` (already threaded); this is the
        # attribution — the critic's fire rate — averaged into `critic_vetoes` across repeats.
        "critic_vetoed": "critic_vetoed" in gate_reasons,
        # Behaviour-preservation refactor oracle (#60, ADR-0066): whether a refactor-oracle path
        # (the reverted prompt-led guard OR the deterministic scaffold) was ACTIVE this run for a
        # detected refactor — the A/B attribution, averaged into `behavior_preservation_runs`.
        "behavior_preservation_detected": (
            (settings.behavior_preservation_guard or settings.refactor_oracle_scaffold)
            and is_behavior_preserving(case.brief)
        ),
        # Thrash-cause diagnostic (the #66/#67 split): the terminal MECHANISM behind `outcome` plus
        # the raw signals that produced it — so a park's cause is VISIBLE instead of inferred. Pure-
        # additive; the classifier is FROZEN (this reads terminal state, never changes the bucket).
        # `thrash_cause` maps 1:1 to the bucket (give_up/plan_unworkable/stalled:<kind>/
        # iteration_limit/rode_to_cap/parked); `gate_reasons` is the full terminal WHY
        # (validation_failed / oracle_unverified / reviewer_requested_changes / critic_vetoed / …).
        # NOTE the deliberate asymmetry: `gate_reasons` comes from the captured interrupt payload
        # (the only place a parking gate's decision exists), while the classifier below is passed
        # `run.final` — UNCHANGED. Feeding it the captured reasons would expose `iteration_limit`
        # and flip honest_park → thrash_park, moving a frozen metric (ADR-0069). Measurement is
        # allowed to see more than the classifier does; that gap is the point, not an oversight.
        "thrash_cause": classify_park_cause(run.final, max_iterations=eff_cap),
        "gate_reasons": list(gate_reasons),
        "fingerprint": run.fingerprint,  # ADR-0081: liveness.py judges A/B arm divergence on this
        # What the hidden grader ACTUALLY SAW. Implementation is derived from grader_passed/total,
        # and those counts were the only surviving trace — "7/8" names no assertion, so a run was
        # undiagnosable after the fact. An instrument that reports a number keeps what produced it
        # (#58's lesson, applied to the scoreboard; ask-repair-mcb-2026-08-04.md).
        "clauses_applied": clauses_applied(),  # engagement, not config (ADR-0082 DoD-1)
        "grader_failed_tests": grader.failed_test_ids,
        "grader_output_tail": grader.output[-4000:] if grader.output else "",
        "unsatisfied_claims": run.terminal_unsatisfied_claims,  # ADR-0079 W2, terminal seam
        # WHY each claim failed, not merely which. `unsatisfied_claims` names ids and
        # `unsatisfied_claim_kinds` names classes; neither can tell "the delivered code really
        # missed the requested shape" from "the checker asked for something the acceptance
        # criteria never did". Measured 2026-08-12: MCB-15 parked 5/5 on three structural claims
        # with the hidden grader PASSING, and diagnosing it required replaying the checker by
        # hand because the reason reached no stored record.
        "claim_failure_reasons": {
            str(d.get("claim_id")): str(d.get("oracle_ref", ""))[:300]
            for d in (judged.get("claim_dispositions") or [])
            if isinstance(d, dict) and str(d.get("verdict")) == "failed"
        },
        "unsatisfied_claim_kinds": failed_claim_kinds(  # ADR-0090: ids can't tell the classes apart
            judged.get("claim_dispositions") or [], judged.get("claims") or []
        ),
        "critic_rows": run.critic_rows_summary,  # #61: verdict counts + discarded refutations
        "vouch": run.terminal_vouch,  # #60: why the oracle vouched (or which guard said no)
        "mutation_caught": run.final.get("tests_mutation_caught"),  # the AND-leg suspect
        # ...and WHY, when there is no verdict. 5 of 47 baseline over-parks are a None
        # mutation verdict refused by ADR-0087's backstop; the cause reached no record.
        "mutation_cause": str(run.final.get("tests_mutation_cause") or ""),
        # ...and which leg ACTUALLY refused, instead of inferring it from the line above. That
        # inference produced a wrong over-park hypothesis on 2026-08-11 (25 mutation=None
        # over-parks, of which only 2 were oracle refusals at all).
        "oracle_legs": run.terminal_oracle_legs,
        "iteration": int(run.final.get("iteration", 0) or 0),
        "max_iter_effective": eff_cap,
        "stalled": bool(run.final.get("stalled")),
        "stall_reason": str(run.final.get("stall_reason") or ""),
        "give_up_reason": str(run.final.get("give_up_reason") or ""),
        "plan_unworkable_reason": str(run.final.get("plan_unworkable_reason") or ""),
        # Layer-2 conversion (#76): the disposition verdict on a convertible park (None = not a
        # convertible park / disabled), WHICH class fired (ADR-0074 oracle_unverified vs ADR-0075
        # engine_blocked_give_up), what it superseded, + the HIDDEN grader ground truth, so the
        # rollup can score TRUE conversions (verified + grader_passed) vs FALSE conversions
        # (verified + grader_failed → a false_ship the disposition would have introduced).
        "layer2_verdict": l2.verdict,
        "layer2_decline": layer2_decline,  # why it was never ATTEMPTED (eligibility)
        # WHY the attempt decided what it did. `unverified` covers three opposite meanings — the
        # code failed the test, the test is a rubber stamp, or the check could not run at all —
        # and keeping only the verdict cost two hours and a wrong conclusion on 2026-08-08.
        # `mutation_caught`: True caught / False survived / None inconclusive.
        "layer2_reason": l2.reason,
        "layer2_green": l2.green,
        "layer2_mutation_caught": l2.mutation_caught,
        "layer2_class": layer2_class,
        "layer2_authored": list(l2.authored),
        "layer2_source": list(l2.source),  # re-derivable after the workspace is gone
        # WHY the scan produced no verdict — the 17% that discards correct work, decomposable.
        "security_unavailable_reason": (run.final or {}).get("security_unavailable_reason", ""),
        # TM-0001: the store this card was written to, so the corpus is self-describing and a
        # sweep that wrote somewhere unexpected is detectable by reading the cards.
        "evidence_home": str(settings.home.resolve()),
        # ADR-0099. `[]` = the check RAN and found nothing; ABSENT = it could not run (an
        # unreadable tree, since it is computed inside a suppress). Without that distinction a
        # corpus of zero `content_destroyed` reasons reads identically whether the prohibition
        # is clean or was throwing on every run — the unreadable zero this session already had
        # to fix once, for slice 2.1.
        "destroyed_paths": (run.final or {}).get("destroyed_paths"),
        # Did the escalation actually RUN? `escalation_path` only ever said what was attempted,
        # which is why a no-op cloud rung was indistinguishable from a real one on 45 cards.
        "escalation_outcome": escalation_outcome,
        # Slice 2.1: how often the coder's probe hit a ceiling this run. The corpus count is what
        # decides whether any ceiling is worth raising — before this the only telemetry went to
        # the ephemeral activity stream, reaching no stored card, so the question had no answer.
        "exec_degradations": (run.final or {}).get("exec_degradations") or {},
        # The denominator that makes the line above readable. Measured 2026-08-10: the first sweep
        # recorded 0 degradations in 52 runs and the result could not be interpreted, because
        # "the ceiling never bound" and "the probe was barely called" are the same zero.
        "exec_usage": (run.final or {}).get("exec_usage") or {},
        # #129: which assertion was over-strict, which test refused, the two-bars question off
        # the PAYLOAD (`final` is blank on a park), and whether the helpers were imported.
        "oracle_dispute": run.terminal_oracle_dispute,
        "statickit_used": statickit_adopted(run.final or {}),
        "final_failing_tests": parse_failing_tests(
            effective_test_output(run.final or {}), cap=10_000
        ),
        "final_test_output_tail": effective_test_output(run.final or {})[-6000:],
        "authored_assertion_digest": (run.final or {}).get("authored_assertion_digest") or [],
        "authored_assertion_digest_pre_repair": (run.final or {}).get(
            "authored_assertion_digest_pre_repair"
        )
        or [],
        "overstrict_findings": (run.final or {}).get("overstrict_findings") or [],
        # ADR-0098: did the Proctor actually AMEND the old-behaviour test it was pointed at?
        # Recorded because the first MCB-28 attempt could not answer it: the targeting is
        # deterministic and provably fires, but whether the MODEL acted on it reached no
        # stored record — the same unmeasurable-mechanism defect this arc keeps producing.
        "authored_seed_failures": (run.final or {}).get("authored_seed_failures"),  # P2-A
        "authored_overstrict_runtime": (run.final or {}).get("authored_overstrict_runtime")
        or [],  # P2-B
        "proctor_edits": sorted((run.final or {}).get("proctor_edits") or {}),
        # WHY a repair did not land. `proctor_edits == []` conflates "the model never edited"
        # with "it edited and the assertion-profile check refused the edit as a weakening" —
        # opposite fixes, and the reason arm 1 of the MCB-28 measurement read 0/5 ambiguously.
        "amendment_refusals": dict((run.final or {}).get("amendment_refusals") or {}),
        # WHAT the Proctor was told to restate (ADR-0098). Always present, so "named a target
        # and was ignored" stays distinguishable from "no target was ever named".
        "modify_amendment_targets": list((run.final or {}).get("modify_amendment_targets") or []),
        # DIAGNOSTIC (never a gate): did the HIDDEN grader catch the mutation the authored test
        # missed? Cross-tab against `layer2_mutation_caught` to separate an authoring-quality gap
        # from mutation simply not being the discriminator.
        "grader_mutation_caught": grader_mutation_caught,
        "layer2_superseded": list(l2.superseded),
        "grader_passed": (grader.all_passed if grader.ran else None),
        # OVER-PARK: this run parked and the hidden grader passes anyway — correct work our own
        # gates destroyed. `grader_passed` and `parked` were BOTH already recorded and nothing
        # crossed them, which is why the 2026-08-05 re-baseline read over-park at 5.6% when the
        # stored cards say 18/60. Recorded per run so it survives averaging (compare.py) and
        # reaches the suite rollup — the seam this file warns about three times above.
        "over_park": is_over_park(inputs),
    }
    card = score(inputs, case_id=case.id, cost=cost, meta=meta)
    write_scorecard(settings.home / "benchmarks", card, stamp)
    # Layer-2 measurement record (#76): one JSONL line per run when MOSAERA_LAYER2_LOG is set — the
    # frozen `outcome`, the hidden-grader ground truth, and the disposition verdict — so the rollup
    # can compute delivery-before/after and (critically) the false-conversion count out of band.
    l2log = os.environ.get("MOSAERA_LAYER2_LOG")
    if l2log:
        try:
            with open(l2log, "a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "case": case.id,
                            "stamp": stamp,
                            "outcome": outcome,
                            "grader_passed": (grader.all_passed if grader.ran else None),
                            "layer2_verdict": l2.verdict,
                            "layer2_reason": l2.reason,
                            "layer2_decline": layer2_decline,
                            "layer2_class": layer2_class,
                            "superseded": list(l2.superseded),
                            "gate_reasons": list(gate_reasons),
                        }
                    )
                    + "\n"
                )
        except OSError:
            pass
    if escalation_path:
        print(f"  escalation path: {' | '.join(escalation_path)}")
    return card


def _bench(case: BenchCase, settings: Settings, backend: str, repeat: int) -> Scorecard:
    cards = [_run_once(case, settings, backend) for _ in range(repeat)]
    return average(cards)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mosaera-bench", description=__doc__)
    parser.add_argument("case", nargs="?", help="benchmark case id (e.g. MCB-01); omit with --all")
    parser.add_argument("--all", action="store_true", help="run every benchmark case")
    parser.add_argument("--sandbox", default=None, help="override backend (docker | subprocess)")
    parser.add_argument(
        "--repeat", type=int, default=None, help="average N runs (default 1, or 3 with --compare)"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="diff vs the committed baseline; exit 1 on regression",
    )
    parser.add_argument(
        "--update-baseline", action="store_true", help="record the committed baseline from this run"
    )
    parser.add_argument(
        "--layer2",
        action="store_true",
        help="Layer-2 (#76): on each convertible honest-park (oracle_unverified or the "
        "engine-blocked give-up), run the real disposition and "
        "measure the conversion rate + false-ship rate against the hidden grader",
    )
    args = parser.parse_args(argv)
    if not args.all and not args.case:
        parser.error("provide a case id, or --all")

    # The benchmark IS the autonomous-quality measurement, so it builds with the exact production
    # autonomous oracle posture (#52, ADR-0057) — the same apply_oracle_posture the API overlay
    # uses, so the scoreboard and production can't drift. MOSAERA_AUTONOMOUS_VERIFIED=0 is the
    # opt-out that reproduces the pre-#52 all-off deterministic baseline (the A/B lever).
    settings = apply_oracle_posture(Settings.from_env())
    # Layer-2 measurement (#76): --layer2 turns the disposition ON for this bench run so an
    # oracle_unverified honest-park is re-verified in place, cross-tabbed against the hidden grader.
    if args.layer2:
        settings = replace(settings, disposition_gap_close=True)
    # A/B lever (#57, ADR-0062): MOSAERA_BENCH_GUARD_OFF=1 disables the faithfulness guard
    # AFTER the posture, so a same-version run pair isolates its effect on over-strictness/thrash.
    # Measurement-only; the product posture always applies the guard.
    if os.environ.get("MOSAERA_BENCH_GUARD_OFF", "").strip() not in ("", "0", "false", "False"):
        settings = replace(settings, proctor_faithfulness_guard=False)
    # A/B lever (#60, ADR-0065): MOSAERA_BENCH_CRITIC_OFF=1 disables the held-out critic AFTER the
    # posture, so a same-version run pair isolates its effect on false_ship (down) and clean_deliver
    # (must hold — over-park hides in the headline). Measurement-only; the product posture keeps it.
    if os.environ.get("MOSAERA_BENCH_CRITIC_OFF", "").strip() not in ("", "0", "false", "False"):
        settings = replace(settings, critic_enabled=False)
    # A/B lever (#60, ADR-0066): MOSAERA_BENCH_BEHAVIOR_PRESERVATION_OFF=1 disables the refactor
    # authoring guidance AFTER the posture, so a same-version run pair isolates its effect on a
    # refactor case (over-strict honest_park -> clean_deliver, overstrict_vs_ref down).
    _bp_off = os.environ.get("MOSAERA_BENCH_BEHAVIOR_PRESERVATION_OFF", "").strip()
    if _bp_off not in ("", "0", "false", "False"):
        settings = replace(settings, behavior_preservation_guard=False)
    # A/B lever (#65): MOSAERA_BENCH_HONEST_STOP_PROJECTION_OFF=1 disables the projected-non-
    # convergence breaker, so a run pair isolates its effect (thrash_park -> honest_park, faster
    # conclusion, clean-conclusion held — it must not convert a clean_deliver into a park).
    _hsp_off = os.environ.get("MOSAERA_BENCH_HONEST_STOP_PROJECTION_OFF", "").strip()
    if _hsp_off not in ("", "0", "false", "False"):
        settings = replace(settings, honest_stop_projection=False)
    # A/B lever (#81, ADR-0077): MOSAERA_BENCH_HONEST_STOP_NO_SIGNAL_OFF=1 restores the pre-#81
    # fingerprint park for an UNCOUNTABLE validator, so a run pair isolates the relabel
    # (thrash_park -> honest_park) from the countability work that earns it. The ON arm must show a
    # real count trend in progress_track.history, not just a nicer bucket.
    _hsns_off = os.environ.get("MOSAERA_BENCH_HONEST_STOP_NO_SIGNAL_OFF", "").strip()
    if _hsns_off not in ("", "0", "false", "False"):
        settings = replace(settings, honest_stop_no_signal=False)
    # A/B lever (#80, ADR-0072): MOSAERA_BENCH_STRUCTURAL_SPEC_OFF=1 disables the structural-spec
    # oracle. With the posture activation WITHDRAWN (2026-08-02 null n=25/arm A/B, pooled Fisher
    # p=1.0) this is a no-op by default — kept so the ON arm stays re-runnable on demand (flip the
    # knob ON via MOSAERA_ORACLE_STRUCTURAL_SPEC and this lever gives the OFF arm).
    _ss_off = os.environ.get("MOSAERA_BENCH_STRUCTURAL_SPEC_OFF", "").strip()
    if _ss_off not in ("", "0", "false", "False"):
        settings = replace(settings, oracle_structural_spec=False)
    case_ids = available_cases() if args.all else [args.case]
    repeat = args.repeat if args.repeat else (3 if (args.compare or args.update_baseline) else 1)

    regressed = False
    cards: list[Scorecard] = []
    for case_id in case_ids:
        try:
            case = load_case(case_id)
        except ValueError as exc:
            parser.error(str(exc))
        backend = args.sandbox or case.sandbox
        card = _bench(case, settings, backend, repeat)
        cards.append(card)
        print_summary(card)

        if args.update_baseline:
            print(f"  baseline updated: {write_baseline(card)}")
        if args.compare:
            baseline = load_baseline(case_id)
            if baseline is None:
                print(f"  no baseline for {case_id} — run --update-baseline first")
                regressed = True
                continue
            result = compare(card, baseline)
            for note in result.notes:
                print(f"  + {note}")
            if result.regressions:
                for reg in result.regressions:
                    print(f"  REGRESSION: {reg}")
                regressed = True
            else:
                print("  no regression vs baseline")

    # Suite rollup — the capability picture across every case run this invocation.
    if len(cards) > 1:
        report = build_suite(cards)
        _print_suite(report)
        json_path, _ = write_suite(settings.home / "benchmarks", report, _stamp())
        print(f"  suite rollup: {json_path}")

    return 1 if regressed else 0


def _print_suite(report: SuiteReport) -> None:
    _order = ("trivial", "moderate", "hard")
    tiers = sorted(
        {c.tier for c in report.cases},
        key=lambda t: (_order.index(t) if t in _order else len(_order), t),
    )
    print(
        f"\n=== SUITE (engine v{report.engine_version}): Capability {report.overall}/100 "
        f"({report.delivered}/{report.total} delivered) ==="
    )
    o = report.outcomes
    print(
        f"  clean-conclusion {report.clean_conclusion_rate * 100:.1f}% of {report.runs} runs "
        f"(#43 target ~99%) — "
        f"deliver {o.get('clean_deliver', 0)} · honest-park {o.get('honest_park', 0)} · "
        f"thrash {o.get('thrash_park', 0)} · false-ship {o.get('false_ship', 0)} · "
        f"crash {o.get('crash', 0)}"
    )
    header = f"  {'capability':<12}" + "".join(f"{t:>10}" for t in tiers) + f"{'overall':>10}"
    print(header)
    for cap, stats in report.by_capability.items():
        cells = ""
        for t in tiers:
            v = report.matrix.get(cap, {}).get(t)
            cells += f"{'—' if v is None else v:>10}"
        print(f"  {cap:<12}{cells}{str(stats['score']) + ' (' + str(stats['n']) + ')':>10}")
