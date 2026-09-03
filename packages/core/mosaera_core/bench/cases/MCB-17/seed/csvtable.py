"""Parse a small comma-separated table into a list of row dicts."""

from __future__ import annotations


def parse_table(text: str) -> list[dict]:
    """Return one dict per data row, keyed by the header columns.

    The first non-empty line is the comma-separated header; every subsequent
    non-empty line is a row. Blank lines are ignored.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    header = lines[0].split(",")
    rows = []
    for line in lines[1:]:
        rows.append(dict(zip(header, line.split(","))))
    return rows
