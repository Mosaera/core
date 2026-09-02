"""Pure title derivation for PM chat sessions.

Single-sourced so the store (on the first user turn) and the 0013 backfill migration
derive a session's title from the opening message the same way. No I/O, no ORM."""

from __future__ import annotations


def derive_session_title(text: str, limit: int = 60) -> str:
    """A short, human-readable session title from the first user message.

    The first non-empty line, whitespace-collapsed and trimmed to ``limit`` chars
    (with an ellipsis when cut). Empty string when there's nothing to name it by —
    callers then fall back to a generic label."""
    if not text or not text.strip():
        return ""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    first = " ".join(first.split())  # collapse runs of whitespace
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first
