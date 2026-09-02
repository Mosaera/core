"""Package entry point: ``python -m journal``."""

from __future__ import annotations

from journal.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
