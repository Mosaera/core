# Add tagging to the `journal` CLI (Python)

The repository is a small, working command-line journal: a Python package named
`journal`, run as `python -m journal`, backed by a JSON file. It already supports
`add` and `list`, split across `journal/cli.py`, `journal/store.py`, and
`journal/model.py`. Add tagging so entries can be labelled and found.

## Existing behaviour (must keep working)

- `python -m journal add "<text>"` — add an entry; print its new integer id.
- `python -m journal list` — print every entry, one per line, in id order.
- The JSON file path comes from the `JOURNAL_FILE` environment variable when set,
  otherwise `journal.json` in the current directory. Entries persist across
  invocations.

## New behaviour

- `python -m journal tag <id> <label>` — attach the tag `<label>` to the entry
  with that id, and persist it. Attaching a tag the entry already has must not
  duplicate it.
- `python -m journal find <label>` — print every entry that has the tag `<label>`,
  one per line, in id order, in the same format `list` uses. With no matches,
  print nothing and exit 0.
- `tag` on an id that does not exist exits with a non-zero status and does not
  crash with a traceback. An unknown command or a missing argument likewise exits
  non-zero without a traceback.

## Quality

- Add your own pytest tests under `tests/` that exercise the tag and find
  behaviour, including persistence across invocations.
- Standard library only. Keep the existing module layout (`cli`, `store`,
  `model`) — extend it, don't collapse it into one file.
