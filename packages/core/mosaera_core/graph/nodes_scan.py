"""The security-scan stage — its own module because its verdict is a trust boundary.

Split out of ``nodes_review`` on 2026-08-07, when that file hit the 500-line ceiling and the
tempting move was to shave a comment to fit. ``scan_node`` earns the split on its own terms: it is
the sole writer of ``security_status``, the deny-by-default tri-state ADR-0076 defines, and the
gate parks on it. Keeping the only producer of a security verdict in a module named for review
made it easy to miss that **two graph edges reach the gate without ever entering this node** —
which is exactly the defect the same audit found (the gate defaulted the absent verdict to
``"clean"``).

The verdict is a TRI-STATE and every branch below is deliberate: ``disabled`` (an operator opted
out — the gate adds no deny), ``unavailable`` (scanning was expected and could not run — the gate
PARKS), and the scanner's own status. "We did not look" must never read as "we looked and it was
fine"; that sentence is the whole reason this node returns a status rather than a finding list.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mosaera_core.graph._freshness import live_tree
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState
from mosaera_core.tools.scan import format_findings, run_scan


def scan_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    # Emit a deny-by-default `security_status` (ADR-0076): "we did not look" must never
    # read as "clean". The gate reads this to decide whether to park on unverified security.
    #
    # Every return stamps `security_tree`: the verdict is a fact about a SPECIFIC tree, and
    # nothing clears it on a re-plan. Without the stamp a "clean" from iteration 1 vouched for
    # whatever the coder wrote afterwards — the audit's CRITICAL, which SHIPPED.
    tree = live_tree(ctx)
    if not ctx.settings.scan_enabled:
        # Operator opt-out: honestly "disabled", not a clean scan (the gate adds no deny).
        return {
            "findings": [],
            "findings_text": "Security scan disabled.",
            "security_status": "disabled",
            "security_tree": tree,
            "security_unavailable_reason": "",
        }
    if not ctx.scanners or ctx.scan_sandbox is None:
        # Scanning was EXPECTED but nothing can run it (no scan sandbox / no allowed
        # scanner) -> UNVERIFIED, which the gate parks on.
        return {
            "findings": [],
            "findings_text": "Security scan could not run - no scan sandbox (UNVERIFIED).",
            "security_status": "unavailable",
            "security_tree": tree,
            "security_unavailable_reason": "no-scan-sandbox",
        }
    outcome = run_scan(ctx.scanners, ctx.scan_sandbox)
    text = format_findings(outcome.findings)
    if outcome.status == "unavailable":
        text += (
            f"\n\nWARNING: {', '.join(outcome.unavailable)} produced no verdict "
            "- security UNVERIFIED."
        )
    return {
        "findings": [f.as_dict() for f in outcome.findings],
        "findings_text": text,
        "security_status": outcome.status,
        "security_tree": tree,
        # Advisory diagnostics only — the gate reads `security_status`, never this.
        "security_unavailable_reason": ", ".join(
            f"{name}:{cause}" for name, cause in outcome.unavailable_detail
        ),
    }


# The value recorded when the gate is reached without `scan_node` ever running.
NEVER_SCANNED = "never-scanned"


def security_unavailable_cause(final: Mapping[str, Any]) -> str:
    """WHY security was unverified — distinguishing *the scan failed* from *no scan was attempted*.

    `security_unverified` fires whenever `security_status == "unavailable"`, and two edges reach the
    gate without visiting this node at all: `route_after_plan -> gate` on `plan_unworkable_reason`,
    and `route_after_supervise -> gate` on a give-up. Both default the absent key to `"unavailable"`
    (correct — ADR-0076's deny-by-default; "we did not look" must never read as "clean"), but they
    leave `security_unavailable_reason` EMPTY, because this node never ran to write one.

    So an empty reason meant two different things and the record could not tell them apart: a
    scanner that ran and produced no verdict, versus a run that never scanned. Measured over the
    corpus, 73 firings ALL carried an empty reason, which is only explicable as the second.

    This node is the sole writer of `security_status`, so its absence *is* the answer — no new state
    key, no new capture point, and no change to what the gate refuses. Recording only.
    """
    if final.get("security_status"):
        return str(final.get("security_unavailable_reason") or "")
    return NEVER_SCANNED
