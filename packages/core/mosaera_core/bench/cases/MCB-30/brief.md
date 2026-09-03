# Fix the stale comment on TAX_RATE

The comment above `TAX_RATE` in `ledger.py` says "Returns the tally in cents.", which is left over from an older version and describes nothing in this file. It should read "The sales tax rate applied by with_tax."

## Acceptance criteria

The comment above `TAX_RATE` reads `# The sales tax rate applied by with_tax.`
No behaviour changes.
