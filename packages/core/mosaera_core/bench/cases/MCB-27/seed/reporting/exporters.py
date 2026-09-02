"""Row rendering for the reporting package."""

from __future__ import annotations


def render_row(fields: list[str], width: int = 12) -> str:
    """Render one report row. LIVE — the CLI calls this on every run."""
    return " | ".join(f.ljust(width)[:width] for f in fields)


def legacy_export(fields: list[str], sep: str = ",") -> str:
    """The old CSV exporter, kept "just in case" when the CSV path was replaced.

    Nothing calls this. It is the removal target.
    """
    return sep.join(str(f).strip() for f in fields)
