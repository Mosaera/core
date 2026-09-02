"""Command-line entry point for the stats CLI.

Usage:
    python -m stats_cli <number> [<number> ...]
    python -m stats_cli --json <number> [<number> ...]
"""

from __future__ import annotations

import json
import sys


def _fmt(x: float) -> str:
    """Render a whole number without a trailing ``.0``; else its float repr."""
    return str(int(x)) if x == int(x) else str(x)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    rest = [a for a in argv if a != "--json"]
    if not rest:
        print("usage: stats_cli <number> [<number> ...]", file=sys.stderr)
        return 2
    values = [float(a) for a in rest]
    mean = sum(values) / len(values)
    mx = max(values)
    mn = min(values)
    if as_json:
        print(json.dumps({"mean": mean, "max": mx, "min": mn}))
    else:
        print(f"mean: {_fmt(mean)}")
        print(f"max: {_fmt(mx)}")
        print(f"min: {_fmt(mn)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
