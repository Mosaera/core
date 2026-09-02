"""The live caller — proves `render_row` must survive the removal."""

from __future__ import annotations

from reporting.exporters import render_row


def report(rows: list[list[str]]) -> str:
    return "\n".join(render_row(r) for r in rows)
