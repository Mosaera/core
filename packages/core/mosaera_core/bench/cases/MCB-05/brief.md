# Refactor the checkout function (Python)

You are working in an existing Python project. `checkout.py` contains a single
`checkout_total(cart, member=False)` function that has grown into one long, branchy
block computing line discounts, a member discount, shipping, and tax. It works and
has a passing test.

## Task

**Refactor** `checkout_total` into a short orchestrator that delegates to small,
well-named helper functions — without changing its behaviour or output for any
input.

Specifically, after your change:

- `checkout_total` should read as a short orchestrator (a handful of statements)
  that **delegates to at least three helper functions** in the module (e.g. for the
  subtotal / line discounts, the member discount, shipping, and tax).
- Its results must be identical to before for every input, including the edge cases
  (empty cart, bulk-quantity line discount, member discount, the free-shipping
  threshold, and invalid quantities that raise `ValueError`).

## Constraints

- Keep the public signature `checkout_total(cart, member=False)` and keep it in
  `checkout.py` (importable as `from checkout import checkout_total`).
- Do not change any observable behaviour — this is a pure refactor. The existing
  test must still pass.
- Standard library only.
