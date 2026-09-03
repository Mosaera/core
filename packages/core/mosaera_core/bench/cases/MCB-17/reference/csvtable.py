"""Parse and validate a small comma-separated table into a list of row dicts."""

from __future__ import annotations


class TableError(Exception):
    """Raised when a table row does not match the header's column count."""


def parse_table(text: str) -> list[dict]:
    """Return one dict per data row, keyed by the header columns.

    The first non-empty line is the comma-separated header; every subsequent
    non-empty line is a row. Blank lines are ignored. Empty input (no header)
    returns ``[]``. A row whose field count does not equal the header's column
    count raises ``TableError`` naming the offending 1-based line number.
    """
    # Keep the original 1-based line number alongside each non-empty line so an
    # error can point the reader at the real position in the input.
    numbered = [
        (lineno, line)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    if not numbered:
        return []

    _, header_line = numbered[0]
    header = header_line.split(",")

    rows: list[dict] = []
    for lineno, line in numbered[1:]:
        fields = line.split(",")
        if len(fields) != len(header):
            raise TableError(
                f"row on line {lineno} has {len(fields)} field(s) "
                f"but the header defines {len(header)} column(s)"
            )
        rows.append(dict(zip(header, fields)))
    return rows
