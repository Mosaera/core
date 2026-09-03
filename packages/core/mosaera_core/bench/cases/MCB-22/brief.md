# Add variables to the `calc` expression interpreter (Python)

The repository is a small, working arithmetic interpreter: a Python package named
`calc`, run as `python -m calc "<expression>"`, split across four modules —
`calc/tokens.py` (the tokenizer), `calc/parser.py` (a recursive-descent parser to an
AST), `calc/evaluator.py` (evaluates the AST), and `calc/cli.py` (the entry point).
It currently evaluates integer arithmetic with `+ - * /`, correct precedence, and
parentheses. Extend it with variables.

## Existing behaviour (must keep working)

- `python -m calc "2 + 3 * 4"` prints `14`; `python -m calc "(2 + 3) * 4"` prints `20`.
- Integer arithmetic with `+ - * /`, standard precedence, and parentheses.
- A malformed expression exits non-zero and prints an error to stderr without a
  Python traceback.

## New behaviour

Support a **program**: a sequence of statements separated by `;`. A statement is
either an **assignment** `name = <expression>` or a bare expression. Names are
letters/digits/underscores starting with a letter or underscore. Evaluate the
statements left to right against a shared variable environment, and print the value
of the **last** statement.

- `python -m calc "x = 5; x + 1"` prints `6`.
- `python -m calc "a = 2; b = a * 3; b"` prints `6` (a later statement sees earlier
  bindings).
- `python -m calc "x = 1; x = 9; x"` prints `9` (reassignment).
- `python -m calc "x = 1; 2 + 2"` prints `4` (the last statement is a bare expression).
- Referencing a variable that was never assigned exits non-zero and prints an error to
  stderr without a traceback. A syntax error likewise exits non-zero without a
  traceback.

## Quality

- Add your own pytest tests under `tests/` for the variable and assignment behaviour,
  including reassignment and the undefined-variable error.
- Standard library only. Keep the four-module layout (`tokens`, `parser`, `evaluator`,
  `cli`) — extend each layer, don't collapse them into one file.
