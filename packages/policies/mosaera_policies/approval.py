"""Human-in-the-loop approval gate, built on LangGraph ``interrupt``.

Any action named in ``GATED_ACTIONS`` pauses the run and surfaces a payload to
the human operator; execution resumes only with their decision. Unparseable or
ambiguous answers are treated as denial (deny-by-default).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.types import interrupt

# Actions that require a human decision before they may proceed.
#   write_file — a full-file agent write into the workspace clone
#   edit_file  — a surgical anchored replace into an existing clone file
#   delete_file — removing a file from the clone (admin-enabled, destructive)
#   deliver    — finalizing a run: commit on the run branch + delivery report
#
# push / open_pr are deliberately NOT here (ADR-0102). They sat in this set for months
# while NO code path ever called request_approval() for them — an inert control whose
# non-firing was invisible (the repo's most-measured defect class). Remote operations
# happen OUTSIDE the graph, where interrupt() is unreachable; their human control is the
# authenticated API endpoint (ADR-0004) or the explicit auto_open_mr opt-in (ADR-0019,
# a human still merges). Re-adding an action here without wiring a request_approval()
# caller re-creates the theatre — test_approval.py pins the set for that reason.
GATED_ACTIONS: frozenset[str] = frozenset({"write_file", "edit_file", "delete_file", "deliver"})

_APPROVE_WORDS = {"approve", "approved", "yes", "y", "ok", "accept"}


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    feedback: str = ""
    # WHO decided. "human" only when a person actually answered THIS gate; "autonomous"
    # when the runner's policy resolved it; "unknown" when the resume value didn't say.
    # Deliberately NOT defaulted to "human": the run report brands an approval-over-
    # blocking-reasons as a human override, and we must never attribute a machine's
    # decision to a person. An unmarked resume under-claims (see ADR-0034).
    actor: str = "unknown"


def parse_decision(raw: Any) -> ApprovalDecision:
    """Parse a resume value into a decision; anything ambiguous is a denial."""
    if isinstance(raw, dict):
        return ApprovalDecision(
            approved=bool(raw.get("approve", False)),
            feedback=str(raw.get("feedback", "")),
            actor=str(raw.get("actor", "unknown")),
        )
    if isinstance(raw, str):
        # A bare string resume only ever comes from the interactive CLI prompt — i.e. a
        # person typing an answer at this gate.
        text = raw.strip()
        if text.lower() in _APPROVE_WORDS:
            return ApprovalDecision(approved=True, actor="human")
        if text.lower().startswith("deny"):
            return ApprovalDecision(approved=False, feedback=text[4:].lstrip(" :,-"), actor="human")
        return ApprovalDecision(approved=False, feedback=text, actor="human")
    return ApprovalDecision(approved=False, feedback=f"unparseable decision: {raw!r}")


def request_approval(action: str, summary: str, payload: dict[str, Any]) -> ApprovalDecision:
    """Pause the graph and ask the human to approve ``action``.

    Must be called from inside a running LangGraph graph (node or tool). Actions
    outside ``GATED_ACTIONS`` pass through without pausing.
    """
    if action not in GATED_ACTIONS:
        return ApprovalDecision(approved=True)
    raw = interrupt({"action": action, "summary": summary, **payload})
    return parse_decision(raw)
