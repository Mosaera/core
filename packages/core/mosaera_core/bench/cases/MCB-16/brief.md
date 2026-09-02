# Harden the numeric summary (Python)

You are working in an existing Python project with a `summary` module whose
`summarize(values)` returns `{"count", "mean", "min", "max"}` for a list of
numbers. It works on clean numeric input but **crashes with raw tracebacks** on
messy input — an empty list (`ZeroDivisionError` / `ValueError`) or a list that
contains non-numeric entries like strings or `None` (`TypeError`).

## Task

Make `summarize` robust so it never raises on a well-formed list argument:

- **Ignore non-numeric entries.** Only `int` and `float` values count; exclude
  `bool` (a `bool` is not a number here), `None`, and strings.
- **Guard the empty result set.** When no numeric values remain, return
  `{"count": 0, "mean": 0.0, "min": None, "max": None}`.
- For the numeric values that remain, `count` is how many there are, `mean` is
  their arithmetic mean, and `min` / `max` are the smallest / largest.

A clean numeric list must still summarize exactly as before.

## Constraints

- Keep the `summarize(values)` signature and keep it in `summary.py`
  (importable as `from summary import summarize`).
- Standard library only.
