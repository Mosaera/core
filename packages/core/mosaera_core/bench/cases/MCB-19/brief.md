# Fix the business-days off-by-one (Python)

You are working in an existing Python project: a tiny module `bizdays.py` that counts
business days (weekdays, Monday–Friday) between two dates, with its own test suite.
The count is subtly wrong.

## Task

`business_days(start, end)` takes two `datetime.date` values and must return the number
of weekdays (Mon–Fri) in the range `[start, end]` **inclusive** of both endpoints.

The current implementation undercounts by one: it walks an **exclusive** range and so
never considers the `end` date itself, dropping it whenever `end` falls on a weekday.
Diagnose and fix the off-by-one so the range is counted inclusively.

## Constraints

- Fix the **implementation**, not the tests. Do not delete, skip, or weaken any test
  to make the suite pass — the bug is real and lives in `bizdays.py`.
- Keep the public API: `def business_days(start, end) -> int`, signature unchanged.
- Do not introduce third-party dependencies; the standard library is enough.
- Leave the rest of the module behaviour intact.
