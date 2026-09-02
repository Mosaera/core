# Add a `--note` option to the `add` command

`tracker add <amount> <category>` records an expense to a CSV file. Add an optional
`--note TEXT` option that stores a free-text note in the row's `note` column.

Constraints:

- The CSV columns are `date,amount,category,note`, in that order.
- When `--date` is not given, the row's date is TODAY.
- When `--note` is not given, the note column is empty.
- Monetary values use `decimal.Decimal` quantized to two places.
- Standard library only, no third-party runtime dependencies.
- The existing tests under `tests/` describe the accepted behaviour and must pass.
