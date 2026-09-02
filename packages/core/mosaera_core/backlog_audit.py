"""Audit an EXISTING backlog — which items would be locked if intake ran over them today.

The launch gate already refuses an item with an open clarification (ADR-0080 §1, `launch_item`):
running an item whose material claim has no binding burns tokens toward an uncheckable "done". But
the detectors run at DECOMPOSE and RE-CURATE time, so an item that predates them — or that arrived
through a path that never ran intake — carries no ask, and therefore no lock. It launches happily
with acceptance criteria nothing can check.

That is the legacy-backlog case: a real project whose items were written before any of this
existed. This module answers "how many, and which?" **without changing anything.**

Read-only ON PURPOSE, and that is the whole design. Three of the graders authored during the
2026-08-05 governance sweeps were wrong in the OVER-STRICT direction and scored correct work as
failures. A detector that over-fires here does not produce a bad number — it locks an operator's
real backlog. So the sweep reports first, a human reads it, and only then does anything get locked.

Reuses `intake_ask.askable_items` rather than re-deriving: a second copy of "what counts as
unaskable" would drift from the one the launch gate enforces, and then the audit would describe a
system that does not exist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mosaera_core.clauses import Clause
from mosaera_core.intake_ask import askable_items, undecidable_ask
from mosaera_core.spec_lint import checkability


@dataclass(frozen=True)
class AuditRow:
    """One item's verdict. ``would_lock`` is the actionable bit; the rest is the evidence."""

    item_id: int
    title: str
    status: str
    axis: str  # "checkability" | "decidability" — which detector flagged it
    checkability: str  # CHECKABLE | PARTIALLY_CHECKABLE | UNDER_SPECIFIED
    claim_text: str  # the specific claim that cannot be bound
    why: str  # why it cannot be bound, in the operator's words
    already_asked: bool  # an ask is ALREADY open — the launch gate refuses it today
    would_lock: bool  # a NEW ask would be raised: today it launches, and should not


@dataclass(frozen=True)
class AuditReport:
    rows: tuple[AuditRow, ...]

    @property
    def would_lock(self) -> tuple[AuditRow, ...]:
        """Items that launch TODAY and would not after a repair pass — the legacy backlog."""
        return tuple(r for r in self.rows if r.would_lock)

    @property
    def already_locked(self) -> tuple[AuditRow, ...]:
        return tuple(r for r in self.rows if r.already_asked)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [r.__dict__ for r in self.rows]


def audit_backlog(
    items: Sequence[Mapping[str, Any]],
    clauses: tuple[Clause, ...] = (),
    *,
    open_asks: Mapping[int, Any] | None = None,
    decidability_asks: bool = True,
    reachability_asks: bool = True,
) -> AuditReport:
    """Which of ``items`` intake would raise a question about. Changes nothing.

    ``open_asks`` maps item id → the clarification already recorded, so an item the launch gate
    ALREADY refuses is reported as such rather than counted as a new find. ``decidability_asks``
    defaults TRUE here — unlike the knob, which defaults False — because the audit's job is to show
    the operator everything both detectors can see, and it locks nothing by seeing it.
    """
    listed = [dict(i) for i in items]
    axes = askable_items(
        listed,
        clauses,
        decidability_asks=decidability_asks,
        reachability_asks=reachability_asks,
    )
    verdicts = checkability(listed)
    open_asks = open_asks or {}

    rows: list[AuditRow] = []
    for item in listed:
        item_id = int(item.get("id") or 0)
        axis = axes.get(item_id, "")
        if not axis:
            continue
        claim_text, why = "", ""
        ask = undecidable_ask(item, clauses)
        if ask is not None:
            claim_text, why = ask
        elif axis == "checkability":
            claim_text = str(item.get("acceptance") or "").strip()
            why = "no material claim here binds to a check the engine can run"
        already = item_id in open_asks
        rows.append(
            AuditRow(
                item_id=item_id,
                title=str(item.get("title") or ""),
                status=str(item.get("status") or ""),
                axis=axis,
                checkability=verdicts.get(item_id, ""),
                claim_text=claim_text[:2000],
                why=why[:2000],
                already_asked=already,
                would_lock=not already,
            )
        )
    return AuditReport(tuple(sorted(rows, key=lambda r: r.item_id)))


def render_audit(report: AuditReport, *, total_items: int) -> str:
    """A plain-text report for a terminal. Reports the CLEAN count too — a sweep that only lists
    problems gives no sense of proportion, and "9 of 11" and "9 of 400" are different situations."""
    lines = [
        f"Backlog audit — {total_items} item(s) examined, {len(report.rows)} flagged "
        f"({len(report.would_lock)} would be newly locked, "
        f"{len(report.already_locked)} already have an open question)",
        "",
    ]
    if not report.rows:
        lines.append("  Nothing flagged: every item binds a material claim to a check.")
        return "\n".join(lines)
    for row in report.rows:
        mark = "LOCK" if row.would_lock else "open"
        lines.append(f"  [{mark}] #{row.item_id} ({row.checkability}, {row.axis}) {row.title}")
        if row.claim_text:
            lines.append(f"          claim: {row.claim_text[:120]}")
        if row.why:
            lines.append(f"          why:   {row.why[:120]}")
    lines += [
        "",
        "Nothing was changed. `would_lock` items launch TODAY with acceptance criteria the",
        "engine cannot check — read the list before deciding whether to lock or repair them.",
    ]
    return "\n".join(lines)
