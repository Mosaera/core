# Harden the CSV table parser (Python)

You are working in an existing Python project with a `csvtable` module whose
`parse_table(text)` turns a small comma-separated table into a list of dicts. The
first non-empty line is the header (comma-separated column names); each subsequent
non-empty line is a row, mapped to a dict keyed by the header. Blank lines are
ignored.

It works on a well-formed table but is naive: it **crashes on empty input** and
**silently mis-parses a ragged row** — a row whose field count does not match the
header just gets truncated or misaligned by `zip`, losing data with no complaint.

## Task

Make `parse_table` robust. Define a `TableError` exception in the module and handle
the edge cases explicitly instead of crashing or losing data:

- Empty input (no header line at all) returns `[]`.
- A header with zero data rows returns `[]`.
- A data row whose field count does not equal the header's column count raises
  `TableError` with a helpful message that includes the offending row's **1-based
  line number**.
- A well-formed table still parses to the correct list of dicts.

## Constraints

- Keep the `parse_table(text)` signature.
- `TableError` must be importable as `from csvtable import TableError`.
- Standard library only.
