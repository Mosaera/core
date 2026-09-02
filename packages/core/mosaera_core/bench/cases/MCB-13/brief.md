# Refactor the letter-grade function (Python)

You are working in an existing Python project. `grading.py` contains a single
`grade_letter(score)` function implemented as a long `if / elif / else` ladder that
maps a numeric score to a letter grade. It works and has a passing test.

## Task

**Refactor** `grade_letter` to be table/data-driven — drive the mapping from a list
of `(threshold, letter)` bands and iterate over it, so the long `if / elif` ladder is
gone — **without changing its behaviour or output for any input**.

The rules are unchanged:

- `score >= 90` -> `"A"`
- `score >= 80` -> `"B"`
- `score >= 70` -> `"C"`
- `score >= 60` -> `"D"`
- otherwise -> `"F"`

After your change, `grade_letter` should contain a single `if` (the one threshold
comparison inside the loop) rather than a chain of them.

## Constraints

- Keep the public signature `grade_letter(score)` and keep it in `grading.py`
  (importable as `from grading import grade_letter`).
- Do not change any observable behaviour — this is a pure refactor. The existing
  test must still pass.
- Standard library only.
