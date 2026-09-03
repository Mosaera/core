# Fix the pagination off-by-one bug (Python)

You are working in an existing Python project (a small `pager` module that slices a
list of items into pages). Users report that **page 1 skips the first items** — the
first page of results is wrong.

## Task

Diagnose and fix the bug in `pager.py` so that pagination returns the correct slice
for every page.

Pages are **1-based**. `paginate(items, page, per_page)` returns the `page`-th slice
of `per_page` items:

- `paginate([1, 2, 3, 4, 5, 6, 7], 1, 3)` must return `[1, 2, 3]`
- page `2` must return `[4, 5, 6]`, page `3` must return `[7]`
- a `page` beyond the last page returns `[]`
- `page < 1` or `per_page < 1` returns `[]`

## Constraints

- Fix the **implementation**, not the tests. Do not delete, skip, or weaken any test
  to make the suite pass — the bug is real and lives in the module code.
- Keep the public API (`paginate`) and its signature unchanged.
- Do not introduce third-party dependencies; the standard library is enough.
- Leave the rest of the module behaviour intact.
