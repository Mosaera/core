"""Deterministic capability scorecard (MCB, v2).

Scores a run's structured signals + the hidden grader + static-analysis of the
delivered code. Every score is a pure function of objective inputs — no model
call, no LLM judge — so the same delivered code always yields the same scorecard.

Dimensions are bucketed:
- **capability** — does it work AND is it well-made: Implementation (ground truth,
  weighted heaviest), the craftsmanship gates (Style/Types/Complexity/Cleanliness),
  Testing, Validation, Governance, and a weak Planning proxy. The headline
  ``overall`` is the weighted mean of these.
- **process** — how the run behaved (Reliability/Efficiency/Autonomy). Reported,
  but NOT folded into ``overall`` so cost/speed can't inflate the quality number.
- **signal** — the reviewer's (LLM) verdict. Reported only; never scored, so no
  model opinion enters the number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mosaera_core.bench.cases import is_python_kind
from mosaera_core.quality import _CX_BANDS, _LINT_BANDS, _band

# Capability weights. Implementation (does it actually work) dominates at 3x;
# Governance (did the gate ship good / refuse bad) at 2x; craftsmanship + the rest
# at 1x. Process and signal dimensions carry no weight (excluded from overall).
_CAPABILITY_WEIGHTS: dict[str, int] = {
    "Implementation": 3,
    "Governance": 2,
    "Style": 1,
    "Types": 1,
    "Complexity": 1,
    "Cleanliness": 1,
    "Testing": 1,
    "Validation": 1,
    "Planning": 1,
}


@dataclass(frozen=True)
class Dimension:
    name: str
    score: int | None  # 0..100, or None when not applicable / not measurable
    rationale: str
    bucket: str = "capability"  # capability | process | signal


@dataclass(frozen=True)
class ScoreInputs:
    """Objective signals from one benchmark run + the hidden grader + static analysis."""

    kind: str  # "python-cli" | "static-site" — some dimensions are N/A per kind
    # Planning
    has_plan: bool
    has_design: bool
    # Implementation — the hidden acceptance suite is ground truth
    grader_ran: bool
    grader_passed: int
    grader_total: int
    # Testing — did the delivered project ship its own tests, run by validation?
    delivered_test_files: int
    validation_ran_tests: bool
    # Validation — the run's own outcome (tri-state)
    tests_passed: bool | None
    # Review (signal only)
    reviewer_verdict: str  # APPROVE | REQUEST_CHANGES | BLOCK | UNKNOWN
    # Reliability / process
    errored: bool
    iteration: int
    max_iterations: int
    # Governance
    approved: bool
    # Efficiency / process
    usd: float
    total_tokens: int
    calls: int
    elapsed_s: float
    # Autonomy / process
    parked: bool
    revised: bool
    # Case budgets (Efficiency reference points)
    budget_usd: float
    budget_tokens: int
    budget_iterations: int
    # Craftsmanship (static analysis of the delivered code; None = not measured)
    style_violations: int | None = None
    type_errors: int | None = None
    complex_functions: int | None = None
    cleanliness_issues: int = 0


@dataclass(frozen=True)
class Scorecard:
    case_id: str
    overall: int  # the Capability score (0..100)
    dimensions: list[Dimension]
    cost: dict[str, Any]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "overall": self.overall,
            "dimensions": [
                {"name": d.name, "score": d.score, "rationale": d.rationale, "bucket": d.bucket}
                for d in self.dimensions
            ],
            "cost": self.cost,
            "meta": self.meta,
        }


def _clamp(v: float) -> int:
    return max(0, min(100, round(v)))


def _ground_truth(i: ScoreInputs) -> bool | None:
    """Objective 'the delivered code actually works' — tri-state. The hidden grader
    is the ONLY trusted oracle: when it ran, its verdict is ground truth. When it
    could not run we return ``None`` (unknown) rather than fall back to the run's own
    ``tests_passed``: that is a signal the run controls, so trusting it would let a
    run self-certify success. Governance goes N/A on unknown ground truth."""
    if i.grader_ran and i.grader_total > 0:
        return i.grader_passed == i.grader_total
    return None


def _craft(
    name: str, count: int | None, applies: bool, pairs: tuple[tuple[int, int], ...]
) -> Dimension:
    """A craftsmanship gate: N/A when it doesn't apply (e.g. a static site) or the
    tool couldn't run; otherwise banded from the finding count (fewer = better)."""
    if not applies:
        return Dimension(name, None, "not applicable for this deliverable")
    if count is None:
        return Dimension(name, None, "tool unavailable — not measured")
    unit = {"Complexity": "over-complex function(s)"}.get(name, "finding(s)")
    return Dimension(name, _band(count, pairs, 20), f"{count} {unit}")


def _dimensions(i: ScoreInputs) -> list[Dimension]:
    py = is_python_kind(i.kind)
    dims: list[Dimension] = []

    # --- Planning: a plan and a design were produced (weak "artifacts-present" proxy) ---
    plan_pts = (50 if i.has_plan else 0) + (50 if i.has_design else 0)
    dims.append(Dimension("Planning", plan_pts, f"plan={i.has_plan}, design={i.has_design}"))

    # --- Implementation: hidden acceptance pass rate (ground truth) ---
    if not i.grader_ran:
        impl, why = 0, "grader did not run — implementation unverified"
    elif i.grader_total == 0:
        impl, why = 0, "grader produced no tests"
    else:
        impl = _clamp(i.grader_passed / i.grader_total * 100)
        why = f"{i.grader_passed}/{i.grader_total} acceptance tests passed"
    dims.append(Dimension("Implementation", impl, why))

    # --- Craftsmanship gates (Python static analysis; N/A for a static site) ---
    dims.append(_craft("Style", i.style_violations, py, _LINT_BANDS))
    dims.append(_craft("Types", i.type_errors, py, _LINT_BANDS))
    dims.append(_craft("Complexity", i.complex_functions, py, _CX_BANDS))
    if py:
        clean = _band(i.cleanliness_issues, ((0, 100), (1, 75), (2, 50), (3, 25)), 0)
        dims.append(
            Dimension("Cleanliness", clean, f"{i.cleanliness_issues} stray/misplaced file(s)")
        )
    else:
        dims.append(Dimension("Cleanliness", None, "not applicable for this deliverable"))

    # --- Testing: delivered its own tests AND the pipeline ran them (N/A static site) ---
    if py:
        test_pts = (50 if i.delivered_test_files > 0 else 0) + (50 if i.validation_ran_tests else 0)
        dims.append(
            Dimension(
                "Testing",
                test_pts,
                f"{i.delivered_test_files} test file(s); "
                f"pipeline {'ran' if i.validation_ran_tests else 'did not run'} them",
            )
        )
    else:
        dims.append(Dimension("Testing", None, "not applicable for a static site"))

    # --- Validation: the run's own honest tri-state ---
    val = {True: 100, False: 25, None: 0}[i.tests_passed]
    val_why = {True: "tests passed", False: "tests failed", None: "no validation available"}[
        i.tests_passed
    ]
    dims.append(Dimension("Validation", val, val_why))

    # --- Governance: did the gate's decision match ground truth? ---
    gt = _ground_truth(i)
    gov: int | None
    if gt is None:
        gov, gov_why = None, "ground truth unavailable — grader did not run"
    elif gt and i.approved:
        gov, gov_why = 100, "shipped work that passes the acceptance suite"
    elif not gt and not i.approved:
        gov, gov_why = 100, "refused to ship work that fails the acceptance suite"
    elif not gt and i.approved:
        gov, gov_why = 0, "SHIPPED work that fails the acceptance suite"
    else:
        gov, gov_why = 50, "refused to ship work that actually passes (over-conservative)"
    dims.append(Dimension("Governance", gov, gov_why))

    # --- Review (signal only — never scored, keeps model opinion out of the number) ---
    rev_map = {"APPROVE": 100, "REQUEST_CHANGES": 50, "BLOCK": 10, "UNKNOWN": 0}
    verdict = i.reviewer_verdict.upper()
    dims.append(
        Dimension(
            "Review", rev_map.get(verdict, 0), f"reviewer: {verdict or 'NONE'}", bucket="signal"
        )
    )

    # --- Process: Reliability / Efficiency / Autonomy (reported, not in overall) ---
    if i.errored:
        rel, rel_why = 0, "run errored"
    elif i.iteration >= i.max_iterations:
        rel, rel_why = 50, f"hit the iteration cap ({i.iteration}/{i.max_iterations})"
    else:
        rel, rel_why = 100, f"converged in {i.iteration}/{i.max_iterations} iterations"
    dims.append(Dimension("Reliability", rel, rel_why, bucket="process"))

    def ratio(actual: float, budget: float) -> float:
        if budget <= 0:
            return 100.0
        return 100.0 if actual <= budget else budget / actual * 100.0

    eff = _clamp(
        (
            ratio(i.usd, i.budget_usd)
            + ratio(i.total_tokens, i.budget_tokens)
            + ratio(i.iteration, i.budget_iterations)
        )
        / 3
    )
    dims.append(
        Dimension(
            "Efficiency",
            eff,
            f"${i.usd:.4f}, {i.total_tokens} tok, {i.calls} calls, "
            f"{i.iteration} iter, {i.elapsed_s:.0f}s",
            bucket="process",
        )
    )

    if i.errored:
        au, au_why = 0, "run errored"
    elif i.parked:
        au, au_why = 30, "parked for a human at the gate"
    elif i.approved and i.revised:
        au, au_why = 70, "delivered autonomously after a revise loop"
    elif i.approved:
        au, au_why = 100, "delivered autonomously on the first pass"
    else:
        au, au_why = 50, "finished without delivering"
    dims.append(Dimension("Autonomy", au, au_why, bucket="process"))

    # --- Outcome fidelity: did the terminal DECISION match the hidden grader's ground truth? ---
    #
    # Nothing crossed `parked` with `grader_passed` until now, and the cost of that gap was
    # measured: the 2026-08-05 re-baseline reported over-park at 5.6% because it counted only
    # `thrash_park`s. Reading all 60 stored scorecards, **18 of 25 parks had a passing grader** —
    # 30% of the sweep. The 14 that stopped PROMPTLY were filed `honest_park` and never counted:
    # honest about stopping, wrong about the work.
    #
    # Reported BESIDE the outcome, never folded into it — `classify_outcome` is frozen (ADR-0069)
    # and an honest park stays an honest park. This measures OUTCOME FIDELITY (did correct work
    # ship), not gate error: a park with nothing to verify (`validation_unavailable`) is a correct
    # process decision that still lost correct work, and both readings are true at once.
    #
    # `bucket="process"` so `overall` — a weighted mean over the capability bucket alone — is
    # byte-identical with this present. Same rule ADR-0083 set for the governance dimensions.
    # It is the full confusion matrix against the hidden grader, both directions — a false ship and
    # an over-park are the same defect (the terminal decision contradicts the ground truth) pointing
    # opposite ways, and only one of them was ever reported.
    if i.errored:
        # A crash decided nothing. There is no decision to check against the ground truth.
        dims.append(Dimension("Fidelity", None, "run errored", bucket="process"))
    elif not i.grader_ran or i.grader_total <= 0:
        dims.append(
            Dimension("Fidelity", None, "no grader ground truth — unevaluable", bucket="process")
        )
    else:
        correct = i.grader_passed >= i.grader_total
        got_it_right = correct if i.approved else not correct
        if got_it_right:
            why = (
                f"delivered work the grader passes ({i.grader_passed}/{i.grader_total})"
                if i.approved
                else f"correct park: the grader fails ({i.grader_passed}/{i.grader_total})"
            )
        else:
            why = (
                f"FALSE SHIP: delivered, but the grader fails ({i.grader_passed}/{i.grader_total})"
                if i.approved
                else f"OVER-PARK: parked, but the grader passes {i.grader_passed}/"
                f"{i.grader_total} — correct work was not delivered"
            )
        dims.append(Dimension("Fidelity", 100 if got_it_right else 0, why, bucket="process"))

    return dims


def is_over_park(i: ScoreInputs) -> bool:
    """A park whose delivered tree PASSES the hidden grader — correct work our gates destroyed.

    The suite-level counterpart of the ``Fidelity`` dimension, exposed separately because the
    rollup counts runs while the dimension scores one. Deny-by-default: an ungraded park is not an
    over-park (nothing proves the work was right), which is the same posture the expensive
    governance arm takes toward an ungraded run.
    """
    return (
        not i.errored
        and not i.approved
        and i.grader_ran
        and i.grader_total > 0
        and i.grader_passed >= i.grader_total
    )


def score(
    inputs: ScoreInputs,
    *,
    case_id: str,
    cost: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> Scorecard:
    """Compute the scorecard. ``overall`` = the Capability score: a weighted mean
    over capability-bucket dimensions that are applicable (N/A dims drop out and
    their weight redistributes). Process and signal dimensions are reported but
    never enter ``overall``."""
    dims = _dimensions(inputs)
    scored = [
        (d.score, _CAPABILITY_WEIGHTS[d.name])
        for d in dims
        if d.bucket == "capability" and d.score is not None
    ]
    total_w = sum(w for _, w in scored)
    overall = _clamp(sum(s * w for s, w in scored) / total_w) if total_w else 0
    return Scorecard(case_id=case_id, overall=overall, dimensions=dims, cost=cost, meta=meta or {})
