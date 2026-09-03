# Refactor the log-line parser (Python)

You are working in an existing Python project. `logparse.py` contains a single
`parse_log_line(line)` function that has grown into one long, branchy block: it
splits a log line into tokens and, in one inline loop with conditionals, builds
both the message text and the fields dict. It works and has a passing test.

The log format is space-separated tokens:

- `token[0]` is the **level**, `token[1]` is the **timestamp**,
- every remaining token is either a **message word** (no `=`) or a
  **`key=value` field token**. A field value keeps everything after the *first*
  `=` (so `eq=a=b` means key `eq`, value `a=b`).

`parse_log_line` returns `{"level", "timestamp", "message", "fields"}` where
`message` is the non-field words joined by a single space in their original order,
and `fields` is a dict of the `key=value` tokens.

## Task

**Refactor** `parse_log_line` into a short orchestrator that delegates to small,
well-named helper functions — without changing its behaviour or output for any
input.

Specifically, after your change:

- `parse_log_line` should read as a short orchestrator (a handful of statements)
  that **delegates to at least three module-level helper functions** (e.g. one to
  tokenise, one to build the message, one to build the fields dict).
- Its results must be identical to before for every input, including the edge
  cases (a line with no field tokens, and a field value that itself contains `=`).

## Constraints

- Keep the public signature `parse_log_line(line)` and keep it in `logparse.py`
  (importable as `from logparse import parse_log_line`).
- Do not change any observable behaviour — this is a pure refactor. The existing
  test must still pass.
- Standard library only.
