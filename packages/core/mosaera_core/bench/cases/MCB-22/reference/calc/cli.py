"""Command-line entry point: evaluate a calc program (statements with variables)."""

from __future__ import annotations

import argparse
import sys

from calc.evaluator import EvalError, evaluate_program
from calc.parser import ParseError, parse_program
from calc.tokens import TokenizeError, tokenize


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="calc", description="Evaluate a calc program.")
    ap.add_argument("expression", nargs="?", help="program to evaluate; read stdin if omitted")
    args = ap.parse_args(argv)
    source = args.expression if args.expression is not None else sys.stdin.read()
    try:
        result = evaluate_program(parse_program(tokenize(source)))
    except (TokenizeError, ParseError, EvalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0
