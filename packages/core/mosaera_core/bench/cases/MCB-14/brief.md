# Extract the duplicated validation (Python)

You are working in an existing Python project. `accounts.py` defines two functions,
`create_user(name, age)` and `update_user(name, age)`, that **both** contain the
same block of input validation, copy-pasted into each. It works and has a passing
test.

## Task

**Refactor** `accounts.py` to remove the duplication: extract the shared validation
into **one** module-level helper function that both `create_user` and `update_user`
call — **without changing any observable behaviour**.

The validation rules (unchanged) are:

- `name` must be a non-empty `str`, else raise `ValueError`.
- `age` must be an `int` in `0..150` inclusive, else raise `ValueError`.

And the return values are unchanged:

- `create_user("alice", 30)` -> `{"action": "create", "name": "alice", "age": 30}`
- `update_user("bob", 40)` -> `{"action": "update", "name": "bob", "age": 40}`

## Constraints

- Keep the public signatures `create_user(name, age)` and `update_user(name, age)`
  in `accounts.py` (importable as `from accounts import create_user, update_user`).
- The extracted validation must live in a **single** module-level helper that both
  functions call; the validation logic must not remain duplicated inline.
- Do not change any observable behaviour — this is a pure refactor. The existing
  test must still pass.
- Standard library only.
