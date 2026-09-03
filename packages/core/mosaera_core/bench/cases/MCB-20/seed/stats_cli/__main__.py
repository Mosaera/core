"""Command-line entry point for the stats CLI.

Usage:
    python -m stats_cli <number> [<number> ...]
"""

from __future__ import annotations

import sys


def _fmt(x: float) -> str:
    """Render a whole number without a trailing ``.0``; else its float repr."""
    return str(int(x)) if x == int(x) else str(x)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: stats_cli <number> [<number> ...]", file=sys.stderr)
        return 2
    values = [float(a) for a in argv]
    mean = sum(values) / len(values)
    print(f"mean: {_fmt(mean)}")
    print(f"max: {_fmt(max(values))}")
    print(f"min: {_fmt(min(values))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
