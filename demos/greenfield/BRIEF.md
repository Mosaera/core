# Task

Build a small command-line **password strength checker** from scratch.

- A CLI entry point that reads a password (from `argv` or stdin) and prints a
  strength **score 0–4** plus a short list of the reasons (length, character
  classes used, common-password check).
- A reusable `strength(password) -> (score, reasons)` function the CLI calls.
- Tests covering the scoring rules.

The repository is empty — scaffold the whole project (module + CLI + tests).
