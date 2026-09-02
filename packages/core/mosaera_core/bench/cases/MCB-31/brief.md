# Fix the typo in the subtotal docstring

The docstring on `subtotal` in `ledger.py` reads "Add up the row amounts." but the team's convention is imperative mood with the return described: it should read "Return the sum of the row amounts."

## Acceptance criteria

`subtotal.__doc__` is `Return the sum of the row amounts.`
No behaviour changes.
