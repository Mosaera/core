"""Drive the guided-posture measurement and report it (`#64`).

    mosaera-guided --all --repeat 3
    mosaera-guided GMB-01 --operator permissive --json out.json

Separate from `mosaera-bench` on purpose. That command measures capability over the MCB corpus and
its numbers feed a standing baseline; this one measures CONTAINMENT over a corpus of deliberately
broken oracles. Sharing an entry point would invite someone to average them, and they are not the
same question — nor the same denominator.

What it reports is a shape, not a score: how often the producer reached for a corrupting diff, how
often nobody stopped it, and — for every blocked run — what would actually have cleared it. See
`containment.py` for why the recourse split is the load-bearing half.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict
from typing import Any

from mosaera_core.bench.cases import BenchCase, available_guided_cases, load_guided_case
from mosaera_core.bench.containment import ContainmentReport, aggregate, score_run
from mosaera_core.bench.grade import GraderOutcome, grade
from mosaera_core.bench.harness import RunOutcome, run_case
from mosaera_core.bench.operator import POLICIES
from mosaera_core.bench.reliability import classify_outcome
from mosaera_core.config import Settings
from mosaera_core.sandbox import create_sandbox


def _grade(run: RunOutcome, case: BenchCase, settings: Settings) -> GraderOutcome:
    """Grade the delivered workspace against the HIDDEN suite.

    Load-bearing for containment, not a formality. GMB-01's grader asserts the default date is
    still TODAY, so a run that hardcoded it to satisfy the seeded test delivers a green-looking
    workspace that this suite fails. That is a corruption which SHIPPED — a stronger signal than
    the proposal-level detector, because it survived every gate the product has.
    """
    if run.workspace is None:  # pragma: no cover - run_case always sets it
        raise RuntimeError("guided run produced no workspace")
    sandbox = create_sandbox(
        case.sandbox,
        run.workspace.root,
        image=settings.sandbox_image,
        docker_bin=settings.docker_bin,
        default_timeout=settings.sandbox_timeout,
    )
    return grade(run.workspace, case.grader_dir, sandbox, kind=case.kind)


def _run_once(case_id: str, settings: Settings, policy_name: str, index: int) -> ContainmentReport:
    case = load_guided_case(case_id)
    # Unique per INVOCATION, not just per index — mirrors `bench/cli.py::_stamp`. A deterministic
    # id collided with the previous run's workspace the first time this was repeated, and
    # `clone_repo` failed on a non-empty destination. A measurement that cannot be re-run is not
    # a measurement.
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_id = f"guided-{case_id}-{policy_name}-{index}-{stamp}"
    out = run_case(
        case,
        settings,
        run_id=run_id,
        sandbox_backend=case.sandbox,
        approve_writes=True,  # the whole point: real write gates, really interrupting
        operator=POLICIES[policy_name],
    )
    delivered = bool(out.final.get("approved"))
    grader = _grade(out, case, settings) if delivered else None
    # A delivery the hidden suite fails is a false ship — and on this corpus that specifically
    # means the product was corrupted to satisfy the seeded oracle and nothing stopped it.
    acceptance_failed = bool(grader and grader.ran and not grader.all_passed)
    outcome = classify_outcome(
        out.final,
        errored=bool(out.error),
        acceptance_failed=acceptance_failed,
        max_iterations=case.max_iterations,
    )
    report = score_run(
        case_id,
        out.final,
        out.write_proposals,
        outcome=outcome,
        delivered=delivered,
        escalated=bool(out.final.get("give_up_reason") or out.final.get("stall_reason")),
        escalation_reason=str(
            out.final.get("give_up_reason") or out.final.get("stall_reason") or ""
        ),
    )
    if acceptance_failed:
        report.notes.append("DELIVERED but the hidden grader failed — a corruption that shipped")
    return report


def _render(agg: dict[str, Any], reports: list[ContainmentReport]) -> str:
    lines = [
        "",
        f"=== GUIDED CONTAINMENT ({agg['runs']} runs) ===",
        f"  corruption PROPOSED : {agg['corruption_proposed_rate']:.0%}",
        f"  corruption APPROVED : {agg['corruption_approved_rate']:.0%}",
        "",
        "  recourse required:",
    ]
    for bucket, count in sorted(agg["recourse"].items()):
        lines.append(f"    {bucket or '(delivered)':<18} {count}")
    lines.append("")
    for case_id, row in sorted(agg["by_case"].items()):
        lines.append(
            f"  {case_id}: {row['runs']} runs · proposed {row['proposed']} · "
            f"approved {row['approved']} · escalated {row['escalated']}"
        )
    if agg["unscored_proposals"]:
        # Never let the corruption count read as complete when part of the corpus was unreadable.
        lines.append(f"\n  UNSCORED proposals: {agg['unscored_proposals']} (not 'clean')")
    lines.append(f"\n  NOTE: {agg['caveat']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mosaera-guided", description=__doc__)
    parser.add_argument("case", nargs="?", help="a guided case id, e.g. GMB-01")
    parser.add_argument("--all", action="store_true", help="run every guided case")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--operator",
        default="permissive",
        choices=sorted(POLICIES),
        help="permissive models the click-through operator and is the measurement arm",
    )
    parser.add_argument("--json", dest="json_path", help="write the full report here")
    args = parser.parse_args(argv)

    case_ids = available_guided_cases() if args.all else ([args.case] if args.case else [])
    if not case_ids:
        parser.error("name a case or pass --all")
    settings = Settings.from_env()
    reports: list[ContainmentReport] = []
    for case_id in case_ids:
        for index in range(args.repeat):
            print(f"[{case_id}] run {index + 1}/{args.repeat} …", file=sys.stderr)
            reports.append(_run_once(case_id, settings, args.operator, index))
    agg = aggregate(reports)
    print(_render(agg, reports))
    if args.json_path:
        payload = {
            "operator": args.operator,
            "aggregate": agg,
            "runs": [asdict(r) for r in reports],
        }
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
