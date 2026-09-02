# Make the operation applier robust and atomic (Python)

You are working in an existing Python project with an `ops` module whose
`apply_operations(data, operations)` applies a list of operations to a **copy** of
`data` and returns the new dict — the input `data` is never mutated. Each operation
is a dict:

- `{"action": "set", "key": k, "value": v}` — set `result[k] = v`.
- `{"action": "delete", "key": k}` — remove `k`.
- `{"action": "increment", "key": k, "amount": n}` — add `n` to `result[k]`; `k`
  must already exist and hold a number, and `n` must be a number.

It works when every op is valid but is naive: it applies ops in a loop and
**crashes on the first malformed op** (an unknown action, a missing `key`, an
`increment` on a missing key, or an `increment` where the stored value or amount
is not a number) — leaking a raw `KeyError`/`TypeError` and leaving a half-applied
result.

## Task

Make `apply_operations` robust and **atomic**. Define an `OperationError` exception
that **aggregates all problems**:

- Validate **every** operation first. If any op is invalid, raise `OperationError`
  **without applying anything** — the input and the (would-be) result stay
  unchanged.
- `OperationError` must expose an `errors` attribute: a list with **one entry per
  bad op**, each entry mentioning that op's **index** in the list.
- Invalid ops include: an unknown `action`, a missing required `key`, an
  `increment` on a key that does not exist, and an `increment` where the stored
  value or the `amount` is not a number.
- If all ops are valid, apply them in order and return the new dict.

## Constraints

- Keep the `apply_operations(data, operations)` signature and the no-mutation
  contract (operate on a copy; never mutate the passed-in `data`).
- `OperationError` must be importable as `from ops import OperationError`.
- Standard library only.
