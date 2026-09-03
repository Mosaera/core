"""Command-line entry point: evaluate an arithmetic expression."""

from __future__ import annotations

import argparse
import sys

from calc.evaluator import EvalError, evaluate
from calc.parser import ParseError, parse
from calc.tokens import TokenizeError, tokenize


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="calc", description="Evaluate an arithmetic expression.")
    ap.add_argument("expression", nargs="?", help="expression to evaluate; read stdin if omitted")
    args = ap.parse_args(argv)
    source = args.expression if args.expression is not None else sys.stdin.read()
    try:
        result = evaluate(parse(tokenize(source)))
    except (TokenizeError, ParseError, EvalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0
