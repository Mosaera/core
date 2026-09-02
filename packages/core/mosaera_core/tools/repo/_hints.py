"""Coder-facing guidance strings the repo tools hand back at a dead end.

A sibling of ``_read`` / ``_scratch`` / ``_activity``, split out of ``factory`` when that module
hit the 500-line ratchet. These are prose, not guards — the deterministic refusal has already
happened by the time one of these is shown; the string only tells the coder what to do instead of
retrying. Kept together so the "stop and report honestly" wording stays consistent across the
places that offer it.
"""

from __future__ import annotations

# Shown when a write makes no progress (no-op / repeated). Redirects the coder to
# stop and report honestly instead of churning writes (each of which, in guided
# mode, prompts the human) on a goal its tools can't reach — e.g. deleting a file.
STUCK_HINT = (
    "Your tools cannot delete, rename, or move files. If the task needs that, stop "
    "now and reply with 'SUMMARY: blocked — <what you cannot do and the manual step "
    "the user must take>' rather than writing the file again."
)
# When deletion is enabled (admin opt-in), the coder CAN delete via delete_file, so
# the churn hint must not tell it deletion is impossible.
STUCK_HINT_WITH_DELETE = (
    "Your tools cannot rename or move files or run git/shell commands. If the task "
    "needs that, stop now and reply with 'SUMMARY: blocked — <what you cannot do and "
    "the manual step the user must take>' rather than writing the file again."
)
