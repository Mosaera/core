# Round discounted prices to whole cents (Python)

You are working in a small pricing package. `pricing/discount.py` defines
`apply_discount(total, pct)`, which returns the discounted total as a raw float —
so `apply_discount(10.0, 17)` currently returns `8.299999999999999`. The checkout
code in `pricing/checkout.py` calls it on every order, and the existing test suite
asserts the current raw-float result.

## Task

Money must never be carried at sub-cent precision.

- Change `apply_discount` to return the discounted total rounded to two decimals.
- `apply_discount(10.0, 17)` must return `8.3`.
- `apply_discount(19.99, 10)` must return `17.99`.
- A negative or above-100 percentage must still raise `ValueError`, unchanged.
- `checkout.order_total` must keep working and now return rounded totals.

The existing test asserts the OLD unrounded result. That test is wrong after this
change — update it to assert the new behaviour rather than working around it.
