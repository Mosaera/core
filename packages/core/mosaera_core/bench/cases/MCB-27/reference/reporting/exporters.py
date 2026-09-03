"""Row rendering for the reporting package."""

from __future__ import annotations


def render_row(fields: list[str], width: int = 12) -> str:
    """Render one report row. LIVE — the CLI calls this on every run."""
    return " | ".join(f.ljust(width)[:width] for f in fields)
