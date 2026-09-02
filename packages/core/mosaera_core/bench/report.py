"""Versioned scorecard report — a machine-diffable JSON (for regression tracking,
#4) plus a human-readable Markdown summary, written side by side, plus the terminal summary.

All three render from ONE bucket list (`BUCKETS`). They used to carry their own copies, which is
how a dimension can be computed, written to JSON, and never shown to the person reading the run.
"""

from __future__ import annotations

import json
from pathlib import Path

from mosaera_core.bench.scorecard import Scorecard

# Display order. `governance` prints but never reaches `overall`, which averages `capability`
# alone — the two suites share a report, never a headline.
BUCKETS = (
    ("capability", "Capability"),
    ("process", "Process"),
    ("signal", "Signal"),
    ("governance", "Governance"),
)


def print_summary(card: Scorecard) -> None:
    """The terminal summary for one scorecard.

    The headline is printed only when the card HAS capability dimensions. A governance-only sweep
    has `overall == 0` by construction — `overall` averages the capability bucket and governance
    never reaches it — so printing "Capability 0/100" over three 100s reads as a failing score for
    a passing sweep. Stating a number that does not apply is the same defect class as a control
    that reports a verdict it did not earn.
    """
    if any(d.bucket == "capability" for d in card.dimensions):
        print(f"\n=== {card.case_id}: Capability {card.overall}/100 ===")
    else:
        print(f"\n=== {card.case_id} ===")
    for bucket, label in BUCKETS:
        rows = [d for d in card.dimensions if d.bucket == bucket]
        if not rows:
            continue
        print(f"  [{label}]")
        for d in rows:
            s = "N/A" if d.score is None else str(d.score)
            print(f"    {d.name:<14} {s:>4}   {d.rationale}")
    cost = card.cost
    print(
        f"  cost: {cost.get('total_tokens', 0)} tok  ${cost.get('usd', 0.0)}  "
        f"{cost.get('calls', 0)} calls"
    )


def write_scorecard(reports_dir: Path, card: Scorecard, stamp: str) -> tuple[Path, Path]:
    out = reports_dir / card.case_id
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{stamp}.json"
    json_path.write_text(json.dumps(card.to_dict(), indent=2) + "\n", encoding="utf-8")
    md_path = out / f"{stamp}.md"
    md_path.write_text(_render_md(card, stamp), encoding="utf-8")
    return json_path, md_path


def _render_md(card: Scorecard, stamp: str) -> str:
    lines = [
        f"# Capability scorecard — {card.case_id}",
        "",
        f"- Run: `{stamp}`",
        f"- **Capability: {card.overall} / 100**",
    ]
    for bucket, label in BUCKETS:
        rows = [d for d in card.dimensions if d.bucket == bucket]
        if not rows:
            continue
        lines += ["", f"## {label}", "", "| Dimension | Score | Notes |", "| --- | ---: | --- |"]
        for d in rows:
            score = "N/A" if d.score is None else str(d.score)
            lines.append(f"| {d.name} | {score} | {d.rationale} |")
    cost = card.cost
    lines += [
        "",
        "## Cost",
        f"- tokens: {cost.get('total_tokens', 0)}  ·  ${cost.get('usd', 0.0)}  "
        f"·  {cost.get('calls', 0)} model calls",
    ]
    if card.meta:
        lines += ["", "## Run", ""]
        for k, v in card.meta.items():
            lines.append(f"- {k}: {v}")
    return "\n".join(lines) + "\n"
