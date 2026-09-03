# Add `*` and `/` with correct precedence to the calculator (Python)

You are working in an existing, working module `calc.py` with a single public
function:

```python
def evaluate(expr: str) -> float
```

`expr` is a space-separated infix expression, e.g. `"1 + 2 - 3"`. Tokens (numbers
and operators) are separated by single spaces. Today it supports only `+` and `-`,
evaluated strictly left-to-right, over integer and float literals, and raises
`ValueError` on any other operator token.

## Task

Add support for multiplication `*` and division `/`:

- `*` and `/` bind **tighter** than `+` and `-` (standard precedence), so
  `"2 + 3 * 4"` is `2 + (3 * 4) == 14`, not `(2 + 3) * 4`.
- All operators are **left-associative**, so `"8 / 2 / 2"` is `(8 / 2) / 2 == 2`.
- Division is **float division** (`/`, not integer division).
- There are still **no parentheses** — only literals and the four operators.

## Constraints

- Keep the existing `+`/`-` behaviour unchanged: `"1 + 2 - 3"` still evaluates to
  `0`, left-to-right.
- Extend the established tokenising/evaluating structure — do not throw the module
  away and reinvent a different public shape. `evaluate(expr: str) -> float` stays
  the one public entry point.
- Standard library only.
