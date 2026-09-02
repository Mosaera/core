"""Suite rollup — aggregate per-case scorecards into a capability picture.

A single case answers "can it do this one task"; the suite answers "where do we
stand, and is it moving as we mature the engine". It groups the per-case cards by
the capability taxonomy and difficulty tier (carried on each card's ``meta``),
reports a capability x tier matrix + per-capability means + a suite headline, and
appends a compact row to a history log so the trajectory is trackable across
releases. Pure aggregation — no model, no new scoring; the numbers are the ones
the deterministic scorecard already produced.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mosaera_core import __version__ as _ENGINE_VERSION
from mosaera_core.bench.reliability import (
    OUTCOMES,
    clean_conclusion_rate,
    merge_counts,
)
from mosaera_core.bench.scorecard import Scorecard

# Display order for the rollup (any capability/tier a case actually uses is shown;
# these just fix the ordering and give the matrix stable columns/rows).
# The verb arc added two capabilities after this tuple was written: "subtract" (ADR-0095, MCB-27)
# and "modify" (ADR-0097, MCB-28). Unknown values were never LOST — `_ordered` appends them sorted
# after the known ones — but they sorted last instead of in canonical position (2026-08-20,
# `docs/audits/adr-corpus-review-2026-08-18.md`).
_CAPABILITY_ORDER = (
    "greenfield",
    "bug-fix",
    "feature",
    "refactor",
    "robustness",
    "modify",
    "subtract",
)
_TIER_ORDER = ("trivial", "moderate", "hard")


def _card_outcomes(meta: dict[str, Any]) -> dict[str, int]:
    """The terminal-bucket counts a card contributes: an averaged card carries a full
    ``outcomes`` map; a single run carries one ``outcome`` string (⇒ a count of 1)."""
    counts = meta.get("outcomes")
    if isinstance(counts, dict):
        return {b: int(n) for b, n in counts.items() if b in OUTCOMES}
    one = meta.get("outcome")
    return {str(one): 1} if one in OUTCOMES else {}


def _card_over_parks(meta: dict[str, Any]) -> int:
    """Over-parks a card contributes: an averaged card carries the ``over_parks`` COUNT across its
    repeats, a single run carries the ``over_park`` BOOL. Same two shapes as ``_card_outcomes``,
    and the same trap — reading only one of them silently under-counts by the repeat factor."""
    count = meta.get("over_parks")
    if isinstance(count, int):
        return count
    return 1 if meta.get("over_park") else 0


@dataclass(frozen=True)
class CaseRow:
    case_id: str
    capability: str
    tier: str
    overall: int
    delivered: bool
    outcome: str  # the representative terminal bucket (worst across repeats)


@dataclass(frozen=True)
class SuiteReport:
    overall: int  # mean of case overalls — the suite headline
    delivered: int  # count of cases the run actually delivered
    total: int  # number of cases
    by_capability: dict[str, dict[str, Any]]  # cap -> {score, n, delivered}
    by_tier: dict[str, dict[str, Any]]  # tier -> {score, n}
    matrix: dict[str, dict[str, int | None]]  # cap -> tier -> mean overall (or None)
    cases: list[CaseRow]
    cost: dict[str, Any]  # summed tokens/usd/calls
    # Reliability scoreboard (#43, ADR-0053): the fraction of RUNS that concluded cleanly
    # (true-deliver or honest-park) — the arc's headline, target ~0.99 — and the per-bucket
    # tally across every run (repeats included), so a false-ship or thrash is never hidden.
    clean_conclusion_rate: float
    outcomes: dict[str, int]
    runs: int  # total runs counted into the rate (cases x repeats)
    # OUTCOME FIDELITY: runs that PARKED while the hidden grader passes — correct work our own
    # gates destroyed. Deliberately NOT folded into `outcomes`: `classify_outcome` is frozen
    # (ADR-0069) and an honest park stays an honest park. This is the second axis, reported beside
    # it, because a run can be honest about STOPPING and wrong about the WORK at the same time.
    over_parks: int
    engine_version: str  # the engine that produced this suite (ADR-0055) — the trend's x-axis

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "overall": self.overall,
            "delivered": self.delivered,
            "total": self.total,
            "clean_conclusion_rate": round(self.clean_conclusion_rate, 4),
            "outcomes": self.outcomes,
            "over_parks": self.over_parks,
            "runs": self.runs,
            "by_capability": self.by_capability,
            "by_tier": self.by_tier,
            "matrix": self.matrix,
            "cases": [
                {
                    "case_id": c.case_id,
                    "capability": c.capability,
                    "tier": c.tier,
                    "overall": c.overall,
                    "delivered": c.delivered,
                    "outcome": c.outcome,
                }
                for c in self.cases
            ],
            "cost": self.cost,
        }


def _mean(values: list[int]) -> int:
    return round(statistics.mean(values)) if values else 0


def _ordered(present: set[str], order: tuple[str, ...]) -> list[str]:
    """Known values first in canonical order, then any unexpected ones sorted."""
    known = [x for x in order if x in present]
    extra = sorted(present - set(order))
    return known + extra


def build_suite(cards: list[Scorecard]) -> SuiteReport:
    """Aggregate per-case cards (capability/tier read from each card's ``meta``)."""
    rows: list[CaseRow] = []
    per_card_outcomes: list[dict[str, int]] = []
    for c in cards:
        meta = c.meta or {}
        counts = _card_outcomes(meta)
        per_card_outcomes.append(counts)
        rows.append(
            CaseRow(
                case_id=c.case_id,
                capability=str(meta.get("capability", "greenfield")),
                tier=str(meta.get("tier", "trivial")),
                overall=c.overall,
                delivered=bool(meta.get("delivered")),
                # The averaged card records the worst-of-repeats representative; a single run just
                # carries its one bucket. Fall back to "" if a card predates the scoreboard.
                outcome=str(meta.get("outcome") or ""),
            )
        )
    outcomes = merge_counts(per_card_outcomes)
    over_parks = sum(_card_over_parks(c.meta or {}) for c in cards)

    caps = _ordered({r.capability for r in rows}, _CAPABILITY_ORDER)
    tiers = _ordered({r.tier for r in rows}, _TIER_ORDER)

    by_capability = {
        cap: {
            "score": _mean([r.overall for r in rows if r.capability == cap]),
            "n": sum(1 for r in rows if r.capability == cap),
            "delivered": sum(1 for r in rows if r.capability == cap and r.delivered),
        }
        for cap in caps
    }
    by_tier = {
        tier: {
            "score": _mean([r.overall for r in rows if r.tier == tier]),
            "n": sum(1 for r in rows if r.tier == tier),
        }
        for tier in tiers
    }
    matrix: dict[str, dict[str, int | None]] = {}
    for cap in caps:
        matrix[cap] = {}
        for tier in tiers:
            cell = [r.overall for r in rows if r.capability == cap and r.tier == tier]
            matrix[cap][tier] = _mean(cell) if cell else None

    cost = {
        "total_tokens": sum(int(c.cost.get("total_tokens") or 0) for c in cards),
        "usd": round(sum(float(c.cost.get("usd") or 0.0) for c in cards), 6),
        "calls": sum(int(c.cost.get("calls") or 0) for c in cards),
    }
    return SuiteReport(
        overall=_mean([r.overall for r in rows]),
        delivered=sum(1 for r in rows if r.delivered),
        total=len(rows),
        by_capability=by_capability,
        by_tier=by_tier,
        matrix=matrix,
        cases=sorted(rows, key=lambda r: r.case_id),
        cost=cost,
        clean_conclusion_rate=clean_conclusion_rate(outcomes),
        outcomes=outcomes,
        runs=sum(outcomes.values()),
        over_parks=over_parks,
        engine_version=_ENGINE_VERSION,
    )


def render_suite_md(report: SuiteReport, stamp: str) -> str:
    tiers = _ordered({r.tier for r in report.cases}, _TIER_ORDER)
    lines = [
        "# Mosaera Capability Benchmark — suite rollup",
        "",
        f"- Engine: **v{report.engine_version}**",
        f"- Run: `{stamp}`",
        f"- **Suite capability: {report.overall} / 100**",
        f"- Delivered: {report.delivered}/{report.total} cases",
        f"- **Clean-conclusion rate: {report.clean_conclusion_rate * 100:.1f}%** "
        f"({report.runs} runs) — #43 target ~99%",
        f"- **Over-parks: {report.over_parks}/{report.runs}** "
        f"({(report.over_parks / report.runs * 100) if report.runs else 0:.1f}%) — runs that "
        f"parked while the hidden grader PASSES: correct work that did not ship",
        "",
        "## Reliability (#43 scoreboard)",
        "",
        "How runs CONCLUDED. Clean = true-deliver or honest-park; the rest are the failures to "
        "drive down.",
        "",
        "| Outcome | Runs |",
        "| --- | ---: |",
        f"| clean_deliver | {report.outcomes.get('clean_deliver', 0)} |",
        f"| honest_park | {report.outcomes.get('honest_park', 0)} |",
        f"| thrash_park | {report.outcomes.get('thrash_park', 0)} |",
        f"| false_ship | {report.outcomes.get('false_ship', 0)} |",
        f"| crash | {report.outcomes.get('crash', 0)} |",
        "",
        "## Capability x difficulty",
        "",
        "Cell = mean capability score for that bucket (N/A = no case yet).",
        "",
        "| Capability | " + " | ".join(t.capitalize() for t in tiers) + " | Overall |",
        "| --- | " + " | ".join("---:" for _ in tiers) + " | ---: |",
    ]
    for cap, stats in report.by_capability.items():
        cells = []
        for t in tiers:
            v = report.matrix.get(cap, {}).get(t)
            cells.append("—" if v is None else str(v))
        lines.append(f"| {cap} | " + " | ".join(cells) + f" | {stats['score']} ({stats['n']}) |")

    lines += ["", "## By difficulty tier", "", "| Tier | Score | Cases |", "| --- | ---: | ---: |"]
    for tier, stats in report.by_tier.items():
        lines.append(f"| {tier} | {stats['score']} | {stats['n']} |")

    lines += [
        "",
        "## Cases",
        "",
        "| Case | Capability | Tier | Score | Delivered | Outcome |",
        "| --- | --- | --- | ---: | :---: | --- |",
    ]
    for c in report.cases:
        lines.append(
            f"| {c.case_id} | {c.capability} | {c.tier} | {c.overall} | "
            f"{'✓' if c.delivered else '—'} | {c.outcome or '—'} |"
        )

    cost = report.cost
    lines += [
        "",
        "## Cost",
        f"- {cost['total_tokens']} tokens  ·  ${cost['usd']}  ·  {cost['calls']} model calls",
    ]
    return "\n".join(lines) + "\n"


def write_suite(reports_dir: Path, report: SuiteReport, stamp: str) -> tuple[Path, Path]:
    """Write the suite rollup (JSON + Markdown) and append a history row."""
    out = reports_dir / "_suite"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{stamp}.json"
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    md_path = out / f"{stamp}.md"
    md_path.write_text(render_suite_md(report, stamp), encoding="utf-8")
    _append_history(out / "history.jsonl", report, stamp)
    return json_path, md_path


def _append_history(path: Path, report: SuiteReport, stamp: str) -> None:
    """One compact JSON line per suite run — the trend log for 'are we maturing'."""
    row = {
        "stamp": stamp,
        # ADR-0055: the engine version this trend point was produced by — the x-axis of "how it
        # progresses". Every history row is now attributable to a released engine version.
        "engine_version": report.engine_version,
        "overall": report.overall,
        "delivered": report.delivered,
        "total": report.total,
        # #43 scoreboard trend: the clean-conclusion rate + per-bucket tally per suite run.
        "clean_conclusion_rate": round(report.clean_conclusion_rate, 4),
        "outcomes": report.outcomes,
        # The SECOND axis, and it was missing from the trend for the whole life of this log
        # (2026-08-07 audit): `over_parks` reached `to_dict` and the rendered report but not the
        # history row, so the one metric the reliability program targets — correct work our own
        # gates destroyed — had no trend line at all. A run can be honest about STOPPING and wrong
        # about the WORK, and only this number says so. The RATE rides along because a bare count
        # is unreadable across sweeps of different sizes.
        "over_parks": report.over_parks,
        "over_park_rate": round(report.over_parks / report.runs, 4) if report.runs else 0.0,
        "runs": report.runs,
        "by_capability": {k: v["score"] for k, v in report.by_capability.items()},
        "cost": report.cost,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
