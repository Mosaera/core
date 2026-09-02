"""Package entry point: ``python -m calc "<expression>"``."""

from __future__ import annotations

from calc.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
