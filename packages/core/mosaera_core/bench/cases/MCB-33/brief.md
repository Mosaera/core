# Fix the wording of the subtotal docstring

The docstring on `subtotal` in `ledger.py` does not follow the team convention, which is imperative mood describing the return value. It should read "Return the sum of the row amounts."

## Acceptance criteria

`subtotal.__doc__` is `Return the sum of the row amounts.`
