# Add a `search` command to the notes CLI (Python)

You are working in an existing, working Python CLI: a `notes` package invoked as
`python -m notes`, with `add` and `list` commands that persist notes to a JSON file
(path from the `NOTES_FILE` environment variable, else `notes.json`).

## Task

Add a new command:

- `python -m notes search <term>` — print every note whose text contains `<term>`,
  matched **case-insensitively**, one per line in the same `"<id>: <text>"` format
  `list` uses, in id order. Print nothing (and exit 0) when nothing matches.

## Constraints

- Follow the existing structure and conventions of the package — the command
  dispatch, the storage layer, and the output format are already established; your
  command must fit in, not reinvent them.
- Keep the existing `add` and `list` behaviour unchanged.
- A missing search term exits non-zero without a traceback, like the other commands.
- Standard library only.
