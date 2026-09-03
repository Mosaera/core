# Fix the interval-merge bug (Python)

You are working in an existing Python project: a tiny module `intervals.py` that
merges overlapping or touching integer intervals, with its own test suite. The
implementation is subtly wrong — it mishandles some inputs.

## Task

`merge(intervals)` takes a list of `(start, end)` integer tuples and must return the
sorted list of merged intervals. Two intervals merge when they overlap **or touch**
(the end of one equals the start of the next, e.g. `(1, 3)` and `(3, 5)` merge into
`(1, 5)`). The input may arrive **unsorted**.

The current implementation is broken in two ways: it assumes the input is already
sorted, and it only merges strictly-overlapping intervals, so it fails to merge
touching ones. Diagnose and fix both so the behaviour is correct.

## Constraints

- Fix the **implementation**, not the tests. Do not delete, skip, or weaken any test
  to make the suite pass — the bugs are real and live in `intervals.py`.
- Keep the public API: `def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]`,
  signature unchanged.
- Do not introduce third-party dependencies; the standard library is enough.
- Leave the rest of the module behaviour intact.
