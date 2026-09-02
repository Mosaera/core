# Build a command-line todo manager (TypeScript / Node)

Build a small, self-contained command-line todo manager in **TypeScript** running
on Node. Start from an empty repository and scaffold everything: the `package.json`,
the TypeScript sources, the CLI entry point, its `tsconfig.json`, and its own tests.

## Requirements

- A Node package written in **TypeScript**. The CLI must be runnable as
  **`npm start --silent -- <args>`** (define a `start` script that runs your CLI
  and forwards the arguments). Example: `npm start --silent -- add "buy milk"`.
- Tasks persist across invocations in a JSON file. The path comes from the
  `TODO_FILE` environment variable when set, otherwise `tasks.json` in the current
  directory. Persisting must create the file if it does not exist.
- Each task has a stable integer `id` (assigned in increasing order, never reused
  within a run), a text `title`, and a `done` boolean (default `false`).

## Commands

- `npm start --silent -- add "<title>"` — add a task; print its new id.
- `npm start --silent -- list` — print every task, one per line, in id order, each
  line showing the id, a `[x]` for done or `[ ]` for not done, and the title. With
  no tasks, print nothing and exit 0.
- `npm start --silent -- done <id>` — mark the task with that id as done.
- `npm start --silent -- delete <id>` — remove the task with that id.
- `add`, `done`, and `delete` persist the change so a later `list` reflects it.
- An unknown command, a missing argument, or an operation on a non-existent id
  exits with a non-zero status and does not crash with an unhandled stack trace.

## Quality

- Include a `tsconfig.json` and keep the project type-clean (`tsc --noEmit` must
  pass — a `typescript` dev dependency).
- Include your own tests (vitest or jest as a dev dependency) under `test/` or
  `src/` that exercise add/list/done/delete and persistence, wired to `npm test`.
- Keep runtime dependencies minimal — Node's standard library is enough for the
  logic and JSON persistence.
