"""Operator-facing surfacing for the repo tools: the activity-stream emit and the
edit-diff preview.

Split out of ``factory.py`` (god-file guard) — these are pure display/telemetry helpers
with no trust-boundary logic, so the write-gate/scope guards stay concentrated in the
factory. Both are best-effort and must never break a tool call.
"""

from __future__ import annotations

import difflib
from typing import Any


def emit_activity(kind: str, detail: str = "", result: str = "") -> None:
    """Surface a coder milestone to the run's custom activity stream so the
    implement node isn't an opaque box (read X → N lines / wrote Y → N chars).

    ``result`` is a SHORT outcome string (a count or a brief tail) so the run
    transcript shows each tool call AND what it produced — never a large payload.
    Best-effort: a no-op outside a LangGraph run (e.g. direct tool unit tests),
    and never allowed to break a tool call.
    """
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return
    if writer is None:
        return
    try:
        writer({"activity": kind, "detail": detail, "result": result})
    except Exception:  # noqa: S110 — telemetry must never fail a tool
        pass


def edit_diff(old_str: str, new_str: str, limit: int = 4_000) -> str:
    """A compact, human-readable ``-old / +new`` preview for the edit_file approval
    gate. Rendered generically by the run UI (GatePanel shows the payload's
    ``content``), so the operator sees exactly what changes before approving."""
    old_lines = [f"- {line}" for line in old_str.splitlines() or [old_str]]
    new_lines = [f"+ {line}" for line in new_str.splitlines() or [new_str]]
    return "\n".join([*old_lines, *new_lines])[:limit]


def overwrite_diff(
    rel: str, existing: str, proposed: str, limit: int = 4_000
) -> tuple[str, int, int]:
    """``(unified_diff, added, removed)`` for a full-file rewrite of an EXISTING file.

    The write gate used to show a whole-file rewrite as a wall of text, so an operator could
    not tell a fix from a REVERT — the coder was observed re-proposing a file with an earlier
    correction undone and a test deleted, and approving it looked identical to approving
    progress. Disk is the last APPROVED state (``write_file`` only writes after the gate
    returns approved), so diffing against it answers the question the operator actually has:
    what does this change about what I already said yes to.

    Git-style so the existing ``DiffView`` renderer parses and counts it unchanged. Not
    reusing ``edit_diff``: it emits every old line followed by every new line, which on a
    whole-file rewrite is both copies of the file back to back — worse than no diff at all.

    The counts are taken BEFORE truncation, so a capped diff still reports the true totals
    rather than only what happened to fit.
    """
    old_lines = existing.splitlines()
    new_lines = proposed.splitlines()
    hunks = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""
        )
    )
    added = sum(1 for ln in hunks if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in hunks if ln.startswith("-") and not ln.startswith("---"))
    if not hunks:  # identical content — the churn guard normally catches this first
        return "", 0, 0
    body = "\n".join([f"diff --git a/{rel} b/{rel}", *hunks])
    if len(body) > limit:
        body = body[:limit] + "\n... (diff truncated — approve on the summary counts, or deny)"
    return body, added, removed


def diff_against_disk(rel: str, existing: str | None, proposed: str) -> tuple[str, str]:
    """``(summary_suffix, unified_diff)`` for an approval gate, or ``("", "")`` when there is none.

    Shared by write_file and edit_file so the two cannot drift: both are "replace what is on disk",
    and an operator needs the same answer from each — what does this change about the version I
    already approved. Empty for a CREATE (nothing to diff) and for a no-op.
    """
    if existing is None:
        return "", ""
    diff, added, removed = overwrite_diff(rel, existing, proposed)
    return (f" (+{added} -{removed} vs disk)", diff) if diff else ("", "")


# How much proposed file content the approval gate carries (F40). The old 4,000 was BELOW real
# agent writes and truncated SILENTLY while the summary reported the true length — measured live
# 2026-08-06: `tests/test_storage.py` (5,530 chars) and `tests/test_cli_add.py` (4,443) were both
# cut, and BOTH tails contained a defect that was then approved, while the byte-identical defect
# inside the visible window was caught and rejected. For a NEW file the content exists nowhere else
# — not on disk, not in the transcript — so a truncated payload makes the remainder unreachable and
# review impossible. Generous enough for any real authored file; still bounded, because the payload
# is checkpointed and streamed over SSE.
_GATE_CONTENT_LIMIT = 32_000
# Mirrors `_activity`'s diff-truncation marker: never let "approve" be clicked over hidden bytes.
_TRUNCATED_NOTE = "\n... ({n} more chars not shown — approve on the summary length, or deny)"


def gate_content(content: str) -> str:
    """Proposed content for an approval payload, explicitly marked if it had to be cut."""
    if len(content) <= _GATE_CONTENT_LIMIT:
        return content
    hidden = len(content) - _GATE_CONTENT_LIMIT
    return content[:_GATE_CONTENT_LIMIT] + _TRUNCATED_NOTE.format(n=hidden)


def note_degradation(sink: dict[str, int] | None, kind: str) -> None:
    """Count one way `sandbox_exec` fell short of what was asked (slice 2.1).

    Advisory like `emit_activity` — nothing routes or gates on it, and it must never break a tool
    call. Unlike `emit_activity` it lands in a **caller-owned map** that reaches RunState, because
    the activity stream is ephemeral: it feeds the live UI and then it is gone, reaching no
    checkpoint and no scorecard. That is why *"does the 30s / 4KB ceiling actually bind?"* had no
    answer, and why raising the ceiling without this would have been a guess.

    Caller-owned rather than a module global so two concurrent runs in one process cannot pollute
    each other's counts — the same shared-mutable ownership `coder_validation` uses.
    """
    if sink is None:
        return
    sink[kind] = sink.get(kind, 0) + 1


def note_weakening(
    summary: str, payload: dict[str, Any], rel: str, before: str | None, after: str
) -> str:
    """Annotate an approval request when it lowers the test bar; return the (possibly
    amended) summary. Mutates ``payload`` so the SPA can render it distinctly."""
    note = _weakening_note(rel, before, after)
    if note is None:
        return summary
    payload["weakening"] = note
    return f"{summary} — WEAKENS THE TEST BAR: {note}"


def _weakening_note(rel: str, before: str | None, after: str) -> str | None:
    """ "You are about to remove assertions" — or None (#66, ADR-0087 §6).

    The tamper guard asks *was this touched?*; that is a different question from *was the bar
    lowered?*, and on 2026-08-06 the two came apart in both directions: a run that DELETED an
    assertion from a delivered test shipped, and a run that RESTORED one was blocked.

    A human MAY authorize a weakening — they own the requirements, and refusing them would just
    rebuild the deadlock ADR-0087 exists to dissolve. What they may not do is authorize one WITHOUT
    BEING TOLD, so this rides the approval payload rather than blocking the write. It is surfacing,
    not enforcement — which is why it belongs here and not in the factory's guard block. The
    UNATTENDED paths (the Proctor's repair, the escalation-gate amendment) refuse instead: no
    human is looking at those.

    Silent on anything it cannot measure — a new file removes nothing, a non-test asserts nothing,
    and an unparseable side is unknown rather than clean. A gate that cries wolf gets clicked
    through, so the false-alarm direction is the expensive one here.
    """
    if before is None:
        return None  # a new file removes nothing
    # Local imports: testintegrity imports Workspace from this package, so a module-level import
    # would be circular. oraclecheck rides along for the same reason.
    from mosaera_core.oraclecheck import assertion_profile, profile_regression
    from mosaera_core.testintegrity import is_test_file

    if not is_test_file(rel):
        return None  # a non-test file asserts nothing
    prior, proposed = assertion_profile(before), assertion_profile(after)
    if prior is None or proposed is None:
        return None  # unparseable either side — say nothing rather than guess
    lost = profile_regression(prior, proposed)
    return "removes assertions: " + "; ".join(lost) if lost else None
