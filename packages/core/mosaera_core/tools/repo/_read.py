"""How much of a file a read returns — the cap, and the window that avoids hitting it.

Split out of ``factory.py`` (which owns the tool definitions and the policy guards) because
read SIZING is its own concern with its own measured rationale, recorded below.

The coder's context is not accidentally large, it is a configured equilibrium: the trim
middleware trips at ~60% of ``num_ctx`` and keeps the last 3 tool outputs, so three capped
whole-file reads (~12k tokens) alone exceed a 16k-context trigger of ~9.8k. Measured
2026-08-05: the coder averaged 9,816 and 9,916 tokens per call across two runs — i.e. the
transcript sits pinned at the trim ceiling, and a re-read pays full price every time.
"""

from __future__ import annotations

from mosaera_core.tools.repo._activity import emit_activity as _emit_activity

# Kept modest so a single read can't dominate the coder's context window (a 40k read ≈ 10k
# tokens) and truncate the next tool call. The cap is the BACKSTOP; a range is the way not
# to reach it — at this cap a whole-file read is still ~4k tokens.
_MAX_READ_CHARS = 16_000


def windowed_read(path: str, text: str, start: int | None, limit: int | None) -> str:
    """A line-numbered window of ``text`` — the cheap alternative to re-reading a whole file.

    ``start`` is 1-based and inclusive; ``limit`` is a line count. A window is NUMBERED while a
    whole-file read is not, deliberately: the reason to ask for a window is to act on specific
    lines, and unnumbered output would force a second full read to locate them — the exact cost
    this exists to avoid. The header names the file's true length so the caller can ask for the
    rest in one more call instead of guessing.

    Out-of-range inputs answer with what IS true (the file's length) rather than an empty
    string, so a wrong guess costs one corrective call, not a re-read of everything.
    """
    lines = text.splitlines()
    total = len(lines)
    if limit is not None and limit <= 0:
        return f"ERROR: limit must be a positive line count (got {limit})"
    first = 1 if start is None else max(1, start)
    if first > total:
        return f"ERROR: {path} has {total} line(s); start={start} is past the end"
    last = total if limit is None else min(total, first + limit - 1)
    width = len(str(last))
    body = "\n".join(f"{n:>{width}}\t{lines[n - 1]}" for n in range(first, last + 1))
    if len(body) > _MAX_READ_CHARS:
        body = (
            body[:_MAX_READ_CHARS]
            + f"\n... (truncated at {_MAX_READ_CHARS} chars — narrow the range)"
        )
    _emit_activity("file_read", path, f"lines {first}-{last} of {total}")
    return f"{path} lines {first}-{last} of {total}:\n{body}"
