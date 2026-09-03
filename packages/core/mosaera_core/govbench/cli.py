"""`mosaera-govbench` — run the governance sweep and PERSIST what it found.

The sweep itself already existed and already ran: `run_gov_case` + `score_governance` are pure
functions over five fixtures, sub-second and free (no model, no Docker), swept by
`test_govbench.py` on every `make test`. What did not exist was any record. The result lived only
as test assertions, so nothing accumulated, nothing could be compared to last week, and the
governance half of the product had no trend at all — while MCB had one.

That asymmetry is the same shape ADR-0083 exists to close: *"MCB grades the coder on a good brief.
These grade the system that produces the brief — the half of the product no instrument watched,
which is how a standing decision sat inert for its entire life with every unit test green."* An
instrument nobody can read the history of is one step from that.

Deliberately a SHELL. It computes nothing: it drives the existing harness, renders through the
existing report machinery (`bench/report.py` already lists `("governance", "Governance")` in its
display order), and writes a stamped scorecard beside MCB's. Stamping `engine_version` matters for
the same reason ADR-0055 gives it to the MCB trend — a result you cannot attribute to an engine is
an anecdote.

Run: ``uv run mosaera-govbench`` (whole sweep) or ``uv run mosaera-govbench G-01``.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any

from mosaera_core import __version__ as _ENGINE_VERSION
from mosaera_core.bench.report import print_summary, write_scorecard
from mosaera_core.bench.scorecard import Scorecard
from mosaera_core.config import Settings
from mosaera_core.govbench.cases import available_gov_cases, load_gov_case
from mosaera_core.govbench.harness import GovRun, run_gov_case
from mosaera_core.govbench.score import broken_cases, score_governance

_SUITE_ID = "_govbench"


def _stamp() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _card(runs: list[GovRun], dimensions: list[Any], stamp: str) -> Scorecard:
    """One scorecard for the whole sweep — the unit of governance measurement is the SWEEP.

    `overall` is 0 by construction, not by omission: it averages the `capability` bucket, every
    governance dimension is `bucket="governance"`, and the two suites must never share a headline
    (`test_governance_dimensions_cannot_reach_mcb_overall` pins exactly that). Reporting a
    governance number as capability would be the louder version of the mistake this suite exists
    to catch.
    """
    return Scorecard(
        case_id=_SUITE_ID,
        overall=0,
        dimensions=list(dimensions),
        cost={"total_tokens": 0, "usd": 0.0, "calls": 0},
        meta={
            "stamp": stamp,
            "engine_version": _ENGINE_VERSION,
            "cases": len(runs),
            "runs": [r.as_dict() for r in runs],
        },
    )


def _append_history(path: Path, card: Scorecard, stamp: str) -> None:
    """One compact line per sweep — the trend MCB has had all along and this half has not."""
    row = {
        "stamp": stamp,
        "engine_version": _ENGINE_VERSION,
        "cases": card.meta.get("cases", 0),
        "dimensions": {d.name: d.score for d in card.dimensions},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mosaera-govbench",
        description="Run the governance benchmark (deterministic, no model, no Docker).",
    )
    parser.add_argument("case", nargs="?", help="one case id (e.g. G-01); omit to run all")
    parser.add_argument(
        "--ask-off",
        action="store_true",
        help="run the intake pass with asks disabled (the OFF arm)",
    )
    parser.add_argument("--no-write", action="store_true", help="print only; persist nothing")
    args = parser.parse_args(argv)

    case_ids = [args.case] if args.case else available_gov_cases()
    cases = [load_gov_case(c) for c in case_ids]
    runs = [run_gov_case(c, ask_enabled=not args.ask_off) for c in cases]

    # A broken fixture is not a finding about the system. `score_governance` raises on one; this
    # reports it as the fixture bug it is and exits non-zero WITHOUT a score, so a sweep can never
    # be published over a fixture that drifted.
    broken = broken_cases(cases, runs)
    if broken:
        print("govbench FAILED — broken fixture(s), not a measurement:")
        for b in broken:
            print(f"    {b.case_id}: expected {b.expected}, observed {b.observed}")
        return 1

    stamp = _stamp()
    card = _card(runs, score_governance(cases, runs), stamp)
    print_summary(card)
    for run in runs:
        print(
            f"    {run.case_id}  {run.case_class:<18} check={run.checkability:<22}"
            f" decide={run.decidability:<12} reach={run.reachability:<12} asked={run.asked}"
        )

    if not args.no_write:
        reports = Settings.from_env().home / "benchmarks"
        json_path, _ = write_scorecard(reports, card, stamp)
        _append_history(reports / _SUITE_ID / "history.jsonl", card, stamp)
        print(f"\n  wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
