# Fix the failing statistics test (Python)

You are working in an existing Python project (a small `metrics` package with a
descriptive-statistics module and its test suite). The test suite has a **failing
test**: `tests/test_stats.py::test_median_even` fails.

## Task

Diagnose and fix the bug in the `metrics` package so the entire existing test suite
passes.

## Constraints

- Fix the **implementation**, not the test. Do not delete, skip, or weaken any test
  to make the suite pass — the bug is real and lives in the package code.
- Keep the public API (`mean`, `median`, `mode`) and their signatures unchanged.
- Do not introduce third-party dependencies; the standard library is enough.
- Leave the rest of the package behaviour intact.
