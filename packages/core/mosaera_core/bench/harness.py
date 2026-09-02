"""Headless benchmark harness — drive the governed loop over a fixed brief.

Mirrors the API worker (`runner.py`), not the CLI: it attaches a `CostMeter` for
the Efficiency numbers (the CLI omits this) and resolves the deliver gate with the
REAL `autonomous_resolution` policy, so Governance and Autonomy are measured
faithfully — the run genuinely refuses to ship work that fails its evidence.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from git import Repo
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from mosaera_policies import autonomous_resolution

from mosaera_core.bench._clauses import _bench_clauses
from mosaera_core.bench.cases import BenchCase, is_python_kind
from mosaera_core.bench.grade import GraderOutcome
from mosaera_core.bench.operator import WRITE_ACTIONS, OperatorPolicy, answer_write_gate
from mosaera_core.bench.quality import QualityReport, analyze
from mosaera_core.bench.scorecard import ScoreInputs
from mosaera_core.claim_oracles import reset_clauses_applied
from mosaera_core.clauses import weave_criteria
from mosaera_core.config import Settings
from mosaera_core.cost import CostMeter, UsageCallback
from mosaera_core.graph import build_graph, recursion_limit_for
from mosaera_core.quality import changed_python_files
from mosaera_core.sandbox import SandboxWorker, create_sandbox
from mosaera_core.tools.repo import Workspace, clone_repo
from mosaera_core.verdict import parse_reviewer_verdict

_TEST_FILE = re.compile(r"^\+\+\+ b/(.*/)?(test_[^/]+\.py|[^/]+_test\.py)$", re.MULTILINE)


@dataclass
class RunOutcome:
    final: dict[str, Any]
    rollup: dict[str, Any]
    elapsed_s: float
    parked: bool = False
    revised: bool = False
    error: str | None = None
    workspace: Workspace | None = None
    # The gate decision from the interrupt PAYLOAD at the last deliver gate this run reached.
    #
    # WHY THIS EXISTS: `gate_node` puts its decision in the interrupt payload and only returns
    # `gate_decision` into STATE after the interrupt resumes. `_resolve` parks by returning without
    # resuming, so the terminating visit never commits — `final["gate_decision"]` is empty on a
    # single-visit park and STALE (an earlier, resumed deny) on a deny→replan park. The measured
    # cost: `gate_reasons` was `[]` on all 526 instrumented scorecards and `critic_vetoed`, derived
    # from it, was False on 643/643 — always False BY CONSTRUCTION, since a veto causes the very
    # park whose evidence is discarded. The live runner hit this first and fixed it the same way
    # (apps/api `runner/_loop.py`, "escalation silently no-ops on every gate-blocked item").
    #
    # NEVER MERGE THIS INTO `final`. `reliability.classify_outcome` reads
    # `final["gate_decision"]["reasons"]` and checks for `iteration_limit`; making it visible there
    # would flip runs `honest_park → thrash_park` and silently move the clean-conclusion headline.
    # That classifier is FROZEN (ADR-0069) and its `rode_to_cap` check exists precisely to
    # compensate for this gap. Read it via `terminal_reasons`; leave `final` alone.
    terminal_gate_decision: dict[str, Any] | None = None
    # Execution fingerprint (ADR-0081): the DETERMINISTIC projection of this run's path — ordered
    # (node, keys-written) visits, the interrupt actions encountered, and the terminal
    # disposition. Deliberately NO prompt hashes or model payloads: those differ run-to-run under
    # a stochastic model even on identical code paths, which would mark every A/B divergent and
    # void the check in the opposite direction. Settings-READ tracking is deferred — graph-level
    # divergence (nodes/keys/interrupts) is what all four liveness incidents needed. Consumed by
    # `bench/liveness.py::compare_fingerprints` to stamp an A/B whose arms ran identical paths
    # INVALID_EXPERIMENT_IDENTICAL_EXECUTION instead of scoring it.
    fingerprint: dict[str, Any] | None = None
    # #60: the gate payload's self-explaining vouch diagnosis at the terminal visit.
    terminal_vouch: str = ""
    # Which term of the oracle AND refused, at that same terminal visit. Same seam and the same
    # reason: a park never commits the payload, and parks are exactly what needs explaining.
    terminal_oracle_legs: dict[str, Any] | None = None
    # The two-bars question (#129), payload-only for the same reason as the decision itself: a
    # park never commits the gate node's work, so reading it off `final` returns "" on exactly
    # the runs the question exists for -- the ADR-0078 residual, re-made and caught in a sweep.
    terminal_oracle_dispute: str = ""
    # The terminating visit's claim evidence — same seam as `terminal_gate_decision`. Uncaptured
    # until 2026-08-08, which is why `unsatisfied_claim_kinds` read `{}` on a parked card.
    terminal_claim_dispositions: list[dict[str, Any]] | None = None
    terminal_claims: list[dict[str, Any]] | None = None
    # Guided posture (`#64`): one row per WRITE gate this run reached — what was proposed, whether
    # it carried the F43 oracle-fitting signature, and how the scripted operator answered. Captured
    # from the interrupt payload for the same reason `terminal_gate_decision` is: a denied or
    # rescoped proposal never lands on disk, so this is the only record it existed. Empty on every
    # headless run, so nothing that reads MCB today sees a change.
    write_proposals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def corrupting_proposals(self) -> list[dict[str, Any]]:
        """Write gates where the producer proposed fitting the code to the oracle (F43)."""
        return [p for p in self.write_proposals if p.get("oracle_fitting")]

    @property
    def terminal_reasons(self) -> list[str]:
        """The gate's blocking reasons at the LAST deliver gate this run reached.

        Prefers the captured payload; falls back to the committed decision, which is correct for
        an APPROVED run (its reasons are empty either way) and for a crashed run that never
        reached a gate (nothing captured, nothing committed → empty)."""
        gate = self.terminal_gate_decision
        if not isinstance(gate, dict):
            committed = self.final.get("gate_decision")
            gate = committed if isinstance(committed, dict) else {}
        return [str(r) for r in (gate.get("reasons") or [])]

    @property
    def critic_rows_summary(self) -> dict[str, Any] | None:
        """Compact #61 record: the committed outcome_verdict's row-verdict counts + how many
        REFUTED proposals the deterministic verifier DISCARDED (the calibration signal)."""
        ov = self.final.get("outcome_verdict")
        if not isinstance(ov, dict):
            return None
        rows = ov.get("rows") or []
        counts: dict[str, int] = {}
        discarded = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            v = str(r.get("verdict", "?"))
            counts[v] = counts.get(v, 0) + 1
            if v == "REFUTED" and not r.get("verified", True):
                discarded += 1
        return {
            "vetoed": bool(ov.get("vetoed")),
            "verdicts": counts,
            "discarded_refutations": discarded,
            "reason": str(ov.get("reason", ""))[:200],
        }

    @property
    def terminal_state(self) -> dict[str, Any]:
        """``final`` plus the TERMINATING gate visit's facts — for readers that judge the park.

        A park never commits the gate node's work, so `final` is blank exactly where a judgement
        about the park must look: Layer 2 was eligible ZERO times across 2,049 cards (ADR-0078's
        fourth residual). Falls back per key, so an approved run reads exactly as before.

        **Never merged into `final`** — `reliability.classify_outcome` is FROZEN (ADR-0069) and
        would bucket the captured `iteration_limit` as thrash, moving the headline. ADR-0078's
        rule, *measurement may see more than the classifier does*, given a name.
        """
        layered = {
            "gate_decision": self.terminal_gate_decision,
            "claim_dispositions": self.terminal_claim_dispositions,
            "claims": self.terminal_claims,
        }
        return {**self.final, **{k: v for k, v in layered.items() if v is not None}}

    @property
    def terminal_unsatisfied_claims(self) -> list[str]:
        """The failing claim ids at the terminal gate visit (ADR-0079 W2) — same capture seam
        and same fallback semantics as ``terminal_reasons``."""
        gate = self.terminal_gate_decision
        if not isinstance(gate, dict):
            committed = self.final.get("gate_decision")
            gate = committed if isinstance(committed, dict) else {}
        return [str(c) for c in (gate.get("unsatisfied_claims") or [])]


def _greenfield_seed(settings: Settings, run_id: str) -> Path:
    """An empty git repo (no commits) — cloning it triggers the greenfield init
    path (`_init_empty`), so Mosaera scaffolds the whole project from the brief."""
    seed = settings.home / "bench" / "seed" / run_id
    seed.mkdir(parents=True, exist_ok=True)
    Repo.init(seed)  # no commit → clone has no valid HEAD → _init_empty establishes main
    return seed


def _existing_seed(case: BenchCase, settings: Settings, run_id: str) -> Path:
    """Materialise a case's committed ``seed/`` repo as a real git repo with one
    commit, so cloning it is an ordinary clone (valid HEAD) and the agent must read
    the existing code before it writes — the existing-codebase capability path."""
    seed = settings.home / "bench" / "seed" / run_id
    if seed.exists():
        shutil.rmtree(seed)
    seed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(case.seed_dir, seed)
    repo = Repo.init(seed)
    # A committer identity may not exist in CI/headless — set it on the seed repo so
    # the initial commit never depends on global git config.
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Mosaera Bench")
        cw.set_value("user", "email", "bench@mosaera.local")
    repo.git.add(A=True)
    repo.index.commit("seed: initial project state")
    return seed


def _seed_for_case(case: BenchCase, settings: Settings, run_id: str) -> Path:
    """The starting repo for a case: its committed ``seed/`` when present (read
    before you write), otherwise an empty repo (greenfield scaffold)."""
    if case.has_seed:
        return _existing_seed(case, settings, run_id)
    return _greenfield_seed(settings, run_id)


def _revision_feedback(payload: dict[str, Any]) -> str:
    review = str(payload.get("review", "")).strip()
    return review or "Address the reviewer's requested changes."


def run_case(
    case: BenchCase,
    settings: Settings,
    *,
    run_id: str,
    sandbox_backend: str,
    max_rounds: int | None = None,
    approve_writes: bool = False,
    operator: OperatorPolicy | None = None,
) -> RunOutcome:
    """Run the governed loop over ``case`` and return its raw outcome.

    ``approve_writes`` defaults False — the headless posture every MCB run and the standing
    baseline were measured under, unchanged. Set it True (with an ``operator`` policy) for the
    GUIDED posture `#64` measures: per-file write gates really interrupt, so the interrupt/resume
    path is exercised and what the producer proposes at each gate can be scored.
    """
    seed = _seed_for_case(case, settings, run_id)
    workspace = clone_repo(str(seed), settings.workspaces_dir, run_id)
    sandbox: SandboxWorker = create_sandbox(
        sandbox_backend,
        workspace.root,
        image=settings.sandbox_image,
        docker_bin=settings.docker_bin,
        default_timeout=settings.sandbox_timeout,
        install_network=settings.sandbox_install_network,
        index_url=settings.sandbox_index_url,
        allow_install=settings.sandbox_install,
    )
    meter = CostMeter(prices=settings.model_prices)
    # The bench provisions no scan container, so it does not require security scanning:
    # declare scan_enabled=False so scan_node reads "disabled" (ADR-0076) rather than the
    # parking "unavailable" — the reliability baseline measures correctness, not scanning.
    settings = replace(settings, scan_enabled=False)
    config: dict[str, Any] = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": recursion_limit_for(settings),
        "callbacks": [UsageCallback(meter)],
    }
    graph = build_graph(
        settings,
        workspace,
        sandbox,
        run_id,
        source=str(seed),
        approve_writes=approve_writes,  # False (headless) unless a guided-posture run asks
        max_iterations=case.max_iterations,
        checkpointer=InMemorySaver(),
        project_brief=case.brief,
    )

    out = RunOutcome(final={}, rollup={}, elapsed_s=0.0, workspace=workspace)
    # The clause joins the TASK, mirroring the launch seam — which is what the manual brief edit
    # did, and the reason it worked where the overview block did not (measured 2026-08-05).
    payload: Any = {"task": weave_criteria(case.brief, _bench_clauses()), "iteration": 0}
    # Claim contract (ADR-0079 Wave 2): the bench mirrors the launch path — claims derived from
    # the brief ride alongside the task string, so the gate's per-claim input is measurable on
    # MCB. MOSAERA_BENCH_CLAIMS_OFF=1 is the A/B OFF arm (ADR-0081: the arms must be provably
    # divergent via the fingerprint before any effectiveness claim).
    _claims_off = os.environ.get("MOSAERA_BENCH_CLAIMS_OFF", "").strip()
    if _claims_off in ("", "0", "false", "False"):
        from mosaera_core.claims import claims_as_dicts, claims_from_acceptance

        # Minted from the WOVEN task, so the claim set covers what the prompt actually asks.
        payload["claims"] = claims_as_dicts(claims_from_acceptance(None, payload["task"]))
    # Standing decisions (ADR-0082 tier 2). The bench has no database, so the arm's clause is
    # declared by env — but built through the SAME validation as a ratified one, because a bench
    # arm able to express something the product cannot would measure a feature we do not ship.
    #   MOSAERA_BENCH_CLAUSES="structural.body_statements=5"
    # Absent ⇒ the OFF arm, byte-identical to today. This is the ADR-0082 DoD-1 lever.
    bench_clauses = _bench_clauses()
    if bench_clauses:
        payload["clauses"] = [dataclasses.asdict(c) for c in bench_clauses]
    reset_clauses_applied()  # engagement is per-run, never carried across cases
    rounds, cap = 0, (max_rounds or case.max_iterations * 3 + 5)
    t0 = time.monotonic()
    trace: list[list[Any]] = []  # ordered [node, sorted-keys-written] visits (ADR-0081)
    interrupt_actions: list[str] = []
    try:
        while True:
            rounds += 1
            if rounds > cap:
                out.error = "drive exceeded max rounds without terminating"
                break
            interrupts = _drain(graph, payload, config, trace)
            if not interrupts:
                break
            interrupt_actions.extend(
                str(i.value.get("action", "")) for i in interrupts if isinstance(i.value, dict)
            )
            resume, stop = _resolve(interrupts, out, workspace, operator)
            if stop:
                break
            payload = Command(resume=resume)
    except Exception as exc:  # a crashed run is a scored outcome, never a harness crash
        out.error = f"{type(exc).__name__}: {exc}"
    out.elapsed_s = time.monotonic() - t0
    out.final = dict(graph.get_state(config).values)
    out.rollup = meter.rollup()
    out.fingerprint = {
        "schema": 1,
        "nodes": trace,
        "interrupts": interrupt_actions,
        "terminal": ("error" if out.error else "parked" if out.parked else "delivered"),
    }
    # Seed hygiene (#51, ADR-0056): the per-run seed repo is consumed only by clone_repo (above)
    # and passed to build_graph as the `source=` STRING (report metadata, never re-read as a tree),
    # so it is safe to drop now. The grader + scorecard read the WORKSPACE (not the seed) after
    # run_case returns. Left unbounded, `home/bench/seed/*` accumulates a copy per run+repeat.
    shutil.rmtree(seed, ignore_errors=True)
    return out


def _drain(
    graph: Any, payload: Any, config: dict[str, Any], trace: list[list[Any]] | None = None
) -> list[Any]:
    interrupts: list[Any] = []
    for chunk in graph.stream(payload, config, stream_mode="updates"):
        for node, update in chunk.items():
            if node == "__interrupt__":
                interrupts.extend(update)
            elif trace is not None:
                # ADR-0081 fingerprint: node visit + which DECLARED keys it wrote. Key NAMES only,
                # never values — values vary under a stochastic model on identical paths.
                keys = sorted(update.keys()) if isinstance(update, dict) else []
                trace.append([node, keys])
    return interrupts


def _resolve(
    interrupts: list[Any],
    out: RunOutcome,
    workspace: Workspace | None = None,
    operator: OperatorPolicy | None = None,
) -> tuple[dict[str, Any], bool]:
    """Resolve each interrupt via the real autonomous policy. Returns (resume map,
    stop) — stop is True when the gate parks (a human would be needed)."""
    resume: dict[str, Any] = {}
    for intr in interrupts:
        value = intr.value if isinstance(intr.value, dict) else {}
        action = str(value.get("action", ""))
        # A supervise escalation (a coder hand-raise, or the #56 honest-stop breaker) resolves
        # with the API runner's autonomous semantics (_budget._resolve_escalation): non-blocking
        # re-scope. supervise_node then decides re-scope vs give-up (budget/escalation-bounded) —
        # the bench must mirror production, not park (else matrix runs measure nothing).
        if action == "escalation":
            kind = str(value.get("kind", "escalate"))
            reason = str(value.get("reason", ""))
            resume[intr.id] = {
                "resolution": "rescope",
                "feedback": f"autonomous re-scope after {kind}: {reason}",
            }
            continue
        if action in WRITE_ACTIONS:
            # Guided posture (`#64`): a real write gate. Score what was proposed, then answer it
            # with the scripted operator. Recorded on the outcome from the PAYLOAD, for the same
            # reason `terminal_gate_decision` is — a denial or a park means it never reaches
            # `final`, and this is the only moment it exists outside the graph.
            resume_val, record = answer_write_gate(value, workspace, operator)
            out.write_proposals.append(record)
            resume[intr.id] = resume_val
            continue
        if action != "deliver":
            resume[intr.id] = {"approve": True}  # some other gate — autonomous default
            continue
        gate = value.get("gate_decision")
        if isinstance(gate, dict):
            # Capture the decision BEFORE resolving — a park returns without resuming, so this is
            # the only moment it exists outside the graph. LAST-WINS is correct by construction:
            # this loop returns immediately on a park, so the final assignment is the visit that
            # actually terminated the drive; earlier assignments were denials the run moved on
            # from. Copied, not aliased — the payload dict is not ours to hold a reference into.
            out.terminal_gate_decision = dict(gate)
            # #60 diagnosis field (payload-only, so same capture seam as the decision).
            out.terminal_vouch = str(value.get("oracle_vouched_by", ""))
            legs = value.get("oracle_legs")
            out.terminal_oracle_legs = dict(legs) if isinstance(legs, dict) else None
            out.terminal_oracle_dispute = str(value.get("oracle_dispute") or "")
            # ADR-0079 W2 evidence, same seam: `failed_claim_kinds` needs both to say WHICH kind
            # of claim failed, and neither survives a park in the checkpoint.
            out.terminal_claim_dispositions = list(value.get("claim_dispositions") or [])
            out.terminal_claims = list(value.get("claims") or [])
        res = autonomous_resolution(gate) if isinstance(gate, dict) else "park"
        if res == "approve":
            resume[intr.id] = {"approve": True}
        elif res == "deny_with_feedback":
            out.revised = True
            resume[intr.id] = {"approve": False, "feedback": _revision_feedback(value)}
        else:  # park — faithful autonomy stops for a human
            out.parked = True
            return resume, True
    return resume, False


def _ran_validation(vp: dict[str, Any]) -> bool:
    """Did the run's own validation EXECUTE a correctness check?

    ``python-pytest`` and ``sql`` project types are emitted ONLY when a real executed
    step exists (pytest / sql-validate), so the type alone is sufficient — preserving
    the historical Python behaviour. ``node`` is emitted even when "unavailable" (no
    tsconfig and no test suite → empty steps), so it's gated on a real non-install
    step so that case honestly reads False."""
    pt = str(vp.get("project_type", ""))
    if pt in ("python-pytest", "sql"):
        return True
    if pt == "node":
        steps = vp.get("steps")
        steps = steps if isinstance(steps, list) else []
        return any(isinstance(s, dict) and not s.get("network", False) for s in steps)
    return False


def build_inputs(run: RunOutcome, grader: GraderOutcome, case: BenchCase) -> ScoreInputs:
    """Extract the scorecard's objective signals from a run + its grade."""
    final = run.final
    diff = str(final.get("diff", ""))
    vp_raw = final.get("validation_plan")
    vp: dict[str, Any] = vp_raw if isinstance(vp_raw, dict) else {}
    gate_raw = final.get("gate_decision")
    gate: dict[str, Any] = gate_raw if isinstance(gate_raw, dict) else {}
    verdict = str(gate.get("reviewer_verdict") or "") or parse_reviewer_verdict(
        str(final.get("review", ""))
    )
    rollup = run.rollup
    # Craftsmanship gates: static analysis of the code the run *changed* (Python
    # cases only; ruff/mypy don't execute code, so this is safe host-side). Scoping
    # to the changed files — not the whole tree — means an existing-codebase case is
    # never judged on pre-existing seed debt. For greenfield the diff lists every new
    # file, so this is equivalent there. Best-effort; no delivery → N/A, not a free 100.
    if is_python_kind(case.kind) and run.workspace is not None:
        changed = [f for f in changed_python_files(diff) if (run.workspace.root / f).is_file()]
        quality = analyze(run.workspace, changed) if changed else QualityReport()
    else:
        quality = QualityReport()
    return ScoreInputs(
        kind=case.kind,
        style_violations=quality.style_violations,
        type_errors=quality.type_errors,
        complex_functions=quality.complex_functions,
        cleanliness_issues=len(quality.cleanliness_issues),
        has_plan=bool(str(final.get("plan", "")).strip()),
        has_design=bool(str(final.get("design", "")).strip()),
        grader_ran=grader.ran,
        grader_passed=grader.passed,
        grader_total=grader.total,
        delivered_test_files=len(_TEST_FILE.findall(diff)),
        validation_ran_tests=_ran_validation(vp),
        tests_passed=final.get("tests_passed"),
        reviewer_verdict=verdict,
        errored=bool(run.error),
        iteration=int(final.get("iteration", 0) or 0),
        max_iterations=case.max_iterations,
        approved=bool(final.get("approved")),
        usd=float(rollup.get("usd", 0.0) or 0.0),
        total_tokens=int(rollup.get("total_tokens", 0) or 0),
        calls=int(rollup.get("calls", 0) or 0),
        elapsed_s=run.elapsed_s,
        parked=run.parked,
        revised=run.revised,
        budget_usd=case.budget_usd,
        budget_tokens=case.budget_tokens,
        budget_iterations=case.budget_iterations,
    )
