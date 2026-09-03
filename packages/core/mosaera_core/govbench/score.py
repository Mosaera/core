"""Score a governance sweep — and refuse to score a broken one.

Three dimensions the deterministic arm can honestly report:

**detected** — did the detectors produce the verdict each case DECLARED. This is a pre-registration
check, not a result: a case whose verdict disagrees with its class is a broken case, and reporting
it as a low score would launder a fixture bug into a finding about the system.

**asked** — precision AND recall, never a count. An instrument that counts asks scores a system
that asks about everything as perfect, which is the fatigue hazard ADR-0080 names and the same
trap as MCB scoring "parked for a human" at 30/100. So a missed ask and a spurious ask are both
failures, and the control case is what makes the second one observable.

**compounded** — did a ratified decision actually stop the question recurring. This is the clause
tier's entire promise, and before this suite existed nothing checked it end to end.

Emitted with ``bucket="governance"`` so MCB's ``overall`` — which averages only the
``capability`` bucket — is byte-identical whether these are present or not.
"""

from __future__ import annotations

from dataclasses import dataclass

from mosaera_core.bench.scorecard import Dimension
from mosaera_core.govbench.cases import GovCase
from mosaera_core.govbench.harness import GovRun


@dataclass(frozen=True)
class BrokenCase:
    """A case whose pre-registered expectation did not hold — a fixture bug, not a measurement."""

    case_id: str
    expected: str
    observed: str


def broken_cases(cases: list[GovCase], runs: list[GovRun]) -> list[BrokenCase]:
    """Cases whose detectors disagreed with their declaration. Must be EMPTY before scoring."""
    by_id = {r.case_id: r for r in runs}
    broken = []
    for case in cases:
        run = by_id.get(case.id)
        if run is None:
            continue
        for field, expected in (
            ("checkability", case.expect_checkability),
            ("decidability", case.expect_decidability),
            # ADR-0089. Without this the `expect_reachability` field was declared and read by
            # nothing — a fixture could drift and the sweep would score it green.
            ("reachability", case.expect_reachability),
        ):
            observed = getattr(run, field)
            if observed != expected:
                broken.append(BrokenCase(case.id, f"{field}={expected}", f"{field}={observed}"))
    return broken


def score_governance(cases: list[GovCase], runs: list[GovRun]) -> list[Dimension]:
    """The governance dimensions for one sweep. Raises when a case is broken."""
    broken = broken_cases(cases, runs)
    if broken:
        detail = "; ".join(f"{b.case_id} expected {b.expected}, got {b.observed}" for b in broken)
        raise ValueError(
            f"cannot score a sweep with broken cases — fix the fixture, do not report it as a "
            f"finding about the system: {detail}"
        )

    by_id = {r.case_id: r for r in runs}
    scored = [c for c in cases if c.id in by_id]
    dims: list[Dimension] = []

    hits = sum(1 for c in scored if by_id[c.id].asked == c.expect_ask)
    should_ask = [c for c in scored if c.expect_ask]
    should_not = [c for c in scored if not c.expect_ask]
    missed = [c.id for c in should_ask if not by_id[c.id].asked]
    spurious = [c.id for c in should_not if by_id[c.id].asked]
    dims.append(
        Dimension(
            "Detected",
            100 if scored else None,
            f"{len(scored)} case(s) produced their declared verdicts",
            bucket="governance",
        )
    )
    dims.append(
        Dimension(
            "Asked",
            round(100 * hits / len(scored)) if scored else None,
            (
                f"{hits}/{len(scored)} correct — "
                f"{len(missed)} missed {missed}, {len(spurious)} spurious {spurious}"
            ),
            bucket="governance",
        )
    )

    compounding = [c for c in scored if c.case_class == "clause-settleable"]
    if compounding:
        silenced = sum(1 for c in compounding if by_id[c.id].asked_again is False)
        dims.append(
            Dimension(
                "Compounded",
                round(100 * silenced / len(compounding)),
                f"{silenced}/{len(compounding)} settled question(s) not re-asked",
                bucket="governance",
            )
        )
    return dims
