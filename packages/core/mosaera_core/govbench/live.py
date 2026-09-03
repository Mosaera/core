"""The governance suite's expensive arm — real coder runs, opt-in, never in `make test`.

The deterministic arm measures the MACHINERY: did a detected ambiguity route to the operator, did
a ratified decision silence it. It cannot measure the two things that actually cost a delivery,
because both are downstream of intake:

- **Did asking change the answer?** (`G-01`) Run the SAME case twice — once on the raw brief, once
  on the brief the operator's reply resolved — and grade both against a suite derived from the
  operator's rule and nothing else. This is the arm that turns "it should have asked" from a
  procedural claim into a measured one: if the unasked arm scores the same, asking bought nothing.
- **Did it verify what it shipped?** (`G-05`) The seed's own suite asserts only the old contract,
  so it stays green under a no-op. A delivery whose hidden grader fails is a **false ship**, in the
  precise sense MCB-18 was one.

Run it:

    uv run python -m mosaera_core.govbench.live --case G-01 --arm both
    uv run python -m mosaera_core.govbench.live            # every gradeable case

Needs a model and Docker. Nothing here is imported by the deterministic arm.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from typing import Any

from mosaera_core.bench.cases import BenchCase
from mosaera_core.bench.grade import GraderOutcome, grade
from mosaera_core.bench.harness import run_case
from mosaera_core.config import Settings
from mosaera_core.govbench.cases import GovCase, available_gov_cases, load_gov_case
from mosaera_core.sandbox import create_sandbox

# The two arms of the asking experiment. `raw` is the brief as written; `resolved` is the brief
# after the operator's reply, which is what intake produces when the ask is answered.
ARMS = ("raw", "resolved")


@dataclass
class GovLiveRun:
    """One graded run of one case on one arm."""

    case_id: str
    arm: str
    delivered: bool
    grader: GraderOutcome | None
    elapsed_s: float
    parked_reasons: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def graded_pass(self) -> bool:
        g = self.grader
        return bool(g and g.ran and g.failed == 0 and g.errors == 0 and g.passed > 0)

    @property
    def score(self) -> float | None:
        """Fraction of the hidden suite that passed, or None when it did not run.

        The verdict alone is too coarse to compare arms. Measured 2026-08-05: an unasked arm
        scored 5/17 and an asked arm 16/17 on the same case, and because neither was a clean pass
        the run reported "asking bought nothing" — the strongest result in the sweep, invisible
        behind a boolean.
        """
        g = self.grader
        if g is None or not g.ran:
            return None
        total = g.passed + g.failed + g.errors
        return (g.passed / total) if total else None

    @property
    def verdict(self) -> str:
        """What this run proves. `unevaluable` is a real answer, not a hedge.

        A park is neither a match nor a false ship: nothing was claimed, so nothing can be wrong.
        Scoring a park as a failure here is the same error that made MCB rate "parked for a human"
        at 30/100, and the reason the over-park defect stayed invisible for a week.
        """
        if self.error:
            return "crash"
        if not self.delivered:
            return "unevaluable_park"
        if self.grader is None or not self.grader.ran:
            return "unevaluable_ungraded"
        return "matched" if self.graded_pass else "false_ship"

    def as_dict(self) -> dict[str, Any]:
        g = self.grader
        return {
            "case_id": self.case_id,
            "arm": self.arm,
            "delivered": self.delivered,
            "verdict": self.verdict,
            "grader": (
                None
                if g is None
                else {"ran": g.ran, "passed": g.passed, "failed": g.failed, "errors": g.errors}
            ),
            "score": None if self.score is None else round(self.score, 3),
            "failed_test_ids": list(g.failed_test_ids) if g else [],
            "parked_reasons": self.parked_reasons,
            "elapsed_s": round(self.elapsed_s, 1),
            "error": self.error,
        }


def brief_for_arm(case: GovCase, arm: str) -> str:
    """The task text each arm hands the loop.

    `resolved` appends the operator's reply the way intake does — as acceptance criteria — rather
    than rewriting the brief, so the two arms differ by exactly the operator's contribution and
    nothing else. A rewritten brief would confound "asking helped" with "I wrote a better brief".
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {ARMS}")
    if arm == "raw" or not case.answer:
        return case.acceptance
    return f"{case.acceptance}\n\nAcceptance criteria:\n{case.answer}"


def as_bench_case(case: GovCase, arm: str) -> BenchCase:
    """Adapt a governance case to the runner MCB already uses.

    Reusing `run_case` is deliberate: a second runner would drift, and then a governance number
    and a capability number would describe two different engines.
    """
    return BenchCase(
        id=f"{case.id}/{arm}",
        brief=brief_for_arm(case, arm),
        grader_dir=case.grader_dir,
        seed_dir=case.seed_dir,
        reference_dir=case.reference_dir,
        kind=case.kind,
        capability="governance",
        tier=case.tier,
        max_iterations=case.max_iterations,
    )


def run_live(
    case: GovCase,
    settings: Settings,
    *,
    arm: str,
    run_id: str,
    sandbox_backend: str = "docker",
) -> GovLiveRun:
    """Run one arm of one case for real, then grade it with the hidden suite."""
    bench_case = as_bench_case(case, arm)
    t0 = time.monotonic()
    try:
        outcome = run_case(bench_case, settings, run_id=run_id, sandbox_backend=sandbox_backend)
    except Exception as exc:  # a crashed run is data, not a reason to abandon the sweep
        return GovLiveRun(case.id, arm, False, None, time.monotonic() - t0, error=str(exc)[:400])

    delivered = not outcome.parked and outcome.error is None
    grader: GraderOutcome | None = None
    if outcome.workspace is not None and case.grader_dir.is_dir():
        # Graded even when the run PARKED. A park that would have passed the grader is the
        # over-park defect — 4 of 5 thrash_parks in the 2026-08-05 sweep were correct work
        # destroyed by our own gates — and an arm that only grades deliveries cannot see it.
        sandbox = create_sandbox(
            sandbox_backend,
            outcome.workspace.root,
            image=settings.sandbox_image,
            docker_bin=settings.docker_bin,
            default_timeout=settings.sandbox_timeout,
            install_network=settings.sandbox_install_network,
            index_url=settings.sandbox_index_url,
            allow_install=settings.sandbox_install,
        )
        grader = grade(outcome.workspace, case.grader_dir, sandbox, kind=case.kind)
    return GovLiveRun(
        case_id=case.id,
        arm=arm,
        delivered=delivered,
        grader=grader,
        elapsed_s=time.monotonic() - t0,
        parked_reasons=outcome.terminal_reasons,
        error=outcome.error,
    )


def _arm_stats(runs: list[GovLiveRun]) -> dict[str, Any]:
    scores = [r.score for r in runs if r.score is not None]
    return {
        "n": len(runs),
        "graded": len(scores),
        "scores": [round(s, 3) for s in scores],
        "mean": round(sum(scores) / len(scores), 3) if scores else None,
        "verdicts": sorted({r.verdict for r in runs}),
    }


def summarise(runs: list[GovLiveRun]) -> dict[str, Any]:
    """The findings this arm can honestly report, and nothing beyond them.

    The asking comparison is on the grader SCORE, not on the verdict. The first version compared
    verdicts and required `raw == false_ship and resolved == matched`; on 2026-08-05 that reported
    `asking_paid: false` for a case where the unasked arm scored 5/17 and the asked arm 16/17,
    because neither reached a clean pass. A comparison that cannot see its own largest effect is
    not a comparison.

    Separation, not just direction, is what licenses the claim: with one run per arm a difference
    cannot be told apart from run-to-run variance under a stochastic model, so `asking_paid` stays
    False and `note` says why. Use `--repeat` to earn it.
    """
    by_case: dict[str, dict[str, list[GovLiveRun]]] = {}
    for r in runs:
        by_case.setdefault(r.case_id, {}).setdefault(r.arm, []).append(r)

    asking: list[dict[str, Any]] = []
    for case_id, arms in by_case.items():
        if set(arms) != set(ARMS):
            continue
        raw, resolved = _arm_stats(arms["raw"]), _arm_stats(arms["resolved"])
        entry: dict[str, Any] = {"case_id": case_id, "raw": raw, "resolved": resolved}
        if raw["mean"] is None or resolved["mean"] is None:
            entry.update(delta=None, separated=False, asking_paid=False, note="an arm was ungraded")
            asking.append(entry)
            continue
        delta = round(resolved["mean"] - raw["mean"], 3)
        # Ranges must not overlap: every answered run beats every unanswered one. A crude bar, but
        # at these sample sizes it is the only one that means anything, and it is stated up front
        # rather than chosen after seeing the numbers.
        repeated = raw["graded"] >= 2 and resolved["graded"] >= 2
        separated = repeated and min(resolved["scores"]) > max(raw["scores"])
        entry.update(
            delta=delta,
            separated=separated,
            asking_paid=bool(separated and delta > 0),
            note=(
                ""
                if repeated
                else "n=1 per arm: a difference here is not separable from run-to-run "
                "variance — re-run with --repeat before quoting it"
            ),
        )
        asking.append(entry)
    false_ships = [r.as_dict() for r in runs if r.verdict == "false_ship"]
    over_parks = [r.as_dict() for r in runs if r.verdict == "unevaluable_park" and r.graded_pass]
    return {
        "runs": [r.as_dict() for r in runs],
        "asking": asking,
        "false_ships": false_ships,
        # A park whose grader PASSED: correct work our own gates destroyed.
        "over_parks": over_parks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the governance suite's expensive arm")
    parser.add_argument("--case", action="append", help="case id (repeatable); default: all")
    parser.add_argument("--arm", choices=[*ARMS, "both"], default="both")
    parser.add_argument("--sandbox", default="docker")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="runs per arm. 1 cannot separate a real effect from run-to-run variance; "
        "use 3+ before quoting a result",
    )
    parser.add_argument("--json", dest="json_out", help="write the summary here")
    args = parser.parse_args(argv)

    ids = args.case or [c for c in available_gov_cases() if load_gov_case(c).grader_dir.is_dir()]
    arms = list(ARMS) if args.arm == "both" else [args.arm]
    settings = Settings.from_env()
    runs: list[GovLiveRun] = []
    for case_id in ids:
        case = load_gov_case(case_id)
        if not case.grader_dir.is_dir():
            print(f"{case_id}: no grader — cheap-arm only, skipped")
            continue
        for arm in arms:
            for rep in range(max(1, args.repeat)):
                run_id = f"gov-{case_id.lower()}-{arm}-{rep}-{int(time.monotonic() * 1000)}"
                run = run_live(case, settings, arm=arm, run_id=run_id, sandbox_backend=args.sandbox)
                runs.append(run)
                score = "  n/a" if run.score is None else f"{run.score:5.2f}"
                print(
                    f"{case_id:<6} {arm:<9} rep{rep} {run.verdict:<20} "
                    f"score={score}  {run.elapsed_s:6.1f}s"
                )

    summary = summarise(runs)
    print(json.dumps(summary["asking"], indent=2))
    if summary["false_ships"]:
        print(f"FALSE SHIPS: {[r['case_id'] for r in summary['false_ships']]}")
    if summary["over_parks"]:
        print(
            "OVER-PARKS (grader passed, run parked): "
            f"{[r['case_id'] for r in summary['over_parks']]}"
        )
    if args.json_out:
        from pathlib import Path

        Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
