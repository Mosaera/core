# Acceptance criteria

Acceptance criteria are the testable contract for a change: what must be true for it
to be "done". They are the single most effective lever a PM has — sharp criteria turn
a thrashing coder into a targeted one, and give the reviewer something objective to
verify.

## Write them as checkable conditions

- State exact **inputs → outputs**: "`median([1,2,3,4])` returns `2.5`", not "median
  works".
- Pin the **edge and error behaviour**: empty input, missing/absent values, wrong
  types, boundaries, and how failure is signalled (exception type, exit code, message)
  — including "no traceback leaks to the user".
- Name **preserved behaviour** for a change to existing code: "all existing tests
  still pass" and any specific invariant that must not change.
- For structural work (a refactor), state the **structural** acceptance too — e.g.
  "the function is decomposed into helpers and its body is short" — because behaviour
  alone is unchanged and cannot prove the work was done.

## Make them independent of the implementation

Describe observable behaviour, not how it is coded. A criterion the coder could satisfy
by hard-coding the test's expected value is a weak criterion — prefer black-box
conditions over several representative cases.

## One criterion, one check

Each criterion should map to one concrete test or observation. If you cannot imagine
the test, the criterion is too vague — rewrite it until you can.

## Example

Task: "add a `search` command to the notes CLI." Acceptance:
- `search <term>` prints notes whose text contains `<term>`, case-insensitively, in id
  order, in the same format `list` uses.
- No match prints nothing and exits 0.
- A missing term exits non-zero with no traceback.
- `add` and `list` behave exactly as before.
