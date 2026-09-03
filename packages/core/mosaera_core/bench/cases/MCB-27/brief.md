# Remove the dead legacy exporter (Python)

You are working in a small reporting package. `reporting/exporters.py` defines two
functions that look alike: `render_row`, which the CLI uses on every run, and
`legacy_export`, which was kept "just in case" when the CSV path was replaced and
is now called from nowhere. `reporting/__init__.py` still re-exports the dead one.

## Task

Remove the `legacy_export` function entirely, along with its dead re-export, so the
package no longer ships code nothing uses.

- Delete the `legacy_export` function from `reporting/exporters.py`.
- Delete the `legacy_export` re-export from `reporting/__init__.py`.
- `render_row` is LIVE — the CLI calls it. It must keep working exactly as it does now.
- The existing tests must continue to pass unchanged. Do not delete or modify them.

Nothing in the package may reference `legacy_export` when you are done.
