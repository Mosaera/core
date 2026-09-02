# Build a command-line todo manager (Python)

Build a small, self-contained command-line todo manager in Python. Start from an
empty repository and scaffold everything needed: the package, the CLI entry
point, and its own tests.

## Requirements

- A Python package named `todo` with a console entry point invoked as
  `python -m todo`.
- Tasks persist across invocations in a JSON file. The file path comes from the
  `TODO_FILE` environment variable when set, otherwise `tasks.json` in the
  current directory. Persisting must create the file if it does not exist.
- Each task has a stable integer `id` (assigned in increasing order, never
  reused within a run), a text `title`, and a `done` boolean (default `false`).

## Commands

- `python -m todo add "<title>"` — add a task; print its new id.
- `python -m todo list` — print every task, one per line, in id order, each line
  showing the id, a `[x]` for done or `[ ]` for not done, and the title.
  With no tasks, print nothing and exit 0.
- `python -m todo done <id>` — mark the task with that id as done.
- `python -m todo delete <id>` — remove the task with that id.
- `add`, `done`, and `delete` persist the change so a later `list` reflects it.
- An unknown command, a missing argument, or an operation on a non-existent id
  exits with a non-zero status and does not crash with a traceback.

## Quality

- Include your own pytest tests under a `tests/` directory that exercise the
  add/list/done/delete behaviour and persistence.
- Keep it dependency-free where reasonable (the standard library is enough).
