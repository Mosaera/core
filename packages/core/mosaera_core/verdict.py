"""Deterministic parsing of the reviewer's ``VERDICT:`` token.

Lives in core (not agents) so core consumers — the bench harness and the
escalation diagnosis — can parse a reviewer verdict without importing
``mosaera_agents`` (which would create an upward core→agents edge). The reviewer
agent re-exports these for its own use.
"""

from __future__ import annotations

import re
from typing import Literal

ReviewerVerdict = Literal["APPROVE", "REQUEST_CHANGES", "BLOCK", "CONFLICT", "UNKNOWN"]

_VERDICT_RE = re.compile(
    r"VERDICT\s*[:*\-\s]*\**\s*(APPROVED?|REQUEST[\s_\-]*CHANGES|BLOCK(?:ED)?)",
    re.IGNORECASE,
)


def parse_reviewer_verdict(text: str) -> ReviewerVerdict:
    """Deterministic parse of the reviewer's ``VERDICT:`` token.

    Scans the whole text (reasoning models emit preamble before the verdict line) and
    tolerates case, spacing, and markdown bold. Exactly one distinct verdict → that
    verdict. Never defaults to APPROVE — an unparseable review is not an approval.

    ``UNKNOWN`` (no verdict) and ``CONFLICT`` (two or more DIFFERENT verdicts in the
    same text) are deliberately distinct outcomes, because they mean opposite things
    downstream. Silence means the reviewer never spoke, and the ADR-0031 backstop may
    still deliver on the run's own executed evidence. A conflict means we cannot tell
    WHAT the reviewer said — a genuine ``REQUEST_CHANGES`` alongside a quoted or
    injected ``VERDICT: APPROVE`` (from repo content, the coder's diff, or echoed test
    output) reads the same as the reverse. Collapsing that into ``UNKNOWN`` would let a
    real veto be laundered into an autonomous ship, so a conflict is its own blocking
    reason and always parks for a human (see ADR-0034, gate.py ``reviewer_conflict``).
    """
    verdicts = _scan_verdicts(text)
    if len(verdicts) == 1:
        return verdicts.pop()
    if not verdicts:
        return "UNKNOWN"

    # Ambiguous. A reasoning model echoes untrusted input — the diff, quoted source, test output —
    # into fenced blocks, and an echoed VERDICT line there reads as a second, conflicting verdict:
    # a genuine review parks because it QUOTED the thing it was reviewing. Re-read with fenced
    # blocks removed to see whether one verdict survives.
    #
    # That re-read may only resolve the ambiguity toward a NON-approving verdict. Which of two
    # verdicts is the echo is genuinely undecidable — the reviewer may equally have fenced its own
    # verdict while quoting a line of prose — so resolving toward APPROVE would let untrusted text
    # carrying `VERDICT: APPROVE` erase a real objection and ship autonomously, which is precisely
    # the laundering this function's CONFLICT outcome exists to prevent (ADR-0034). Rescuing toward
    # REQUEST_CHANGES/BLOCK cannot ship anything, so it is safe and is where the spurious parks are.
    # A wrongly-parked approval costs a human one click; a wrongly-shipped one bypasses the only
    # human control there is.
    resolved = _scan_verdicts(_FENCE_RE.sub("", text))
    if len(resolved) == 1:
        only = resolved.pop()
        if only != "APPROVE":
            return only
    return "CONFLICT"


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _scan_verdicts(text: str) -> set[ReviewerVerdict]:
    found: set[ReviewerVerdict] = set()
    for match in _VERDICT_RE.finditer(text):
        token = re.sub(r"[\s\-]+", "_", match.group(1).upper())
        if token.startswith("APPROVE"):
            found.add("APPROVE")
        elif token.startswith("REQUEST"):
            found.add("REQUEST_CHANGES")
        elif token.startswith("BLOCK"):
            found.add("BLOCK")
    return found
