#!/usr/bin/env python3
"""Apply Alembic migrations to head — the target behind ``make db-migrate``.

Alembic in this repo is driven PROGRAMMATICALLY (there is no ``alembic.ini``), so a bare
``alembic upgrade head`` cannot work. This calls ``MemoryStore.open_or_reason``, which opens
the database and runs ``init()`` — bringing a fresh, legacy (pre-Alembic ``create_all``), or
already-versioned database to head, and reporting WHY on failure instead of degrading silently.

Reads the target from ``MOSAERA_DB_URL`` (fallback ``MOSAERA_TEST_DB_URL``), loading ``.env``
first so it behaves like the CLI/API entrypoints (which call ``load_env``) — an operator whose
``MOSAERA_DB_URL`` lives in ``.env`` shouldn't have to also export it for ``make db-migrate``.
"""

from __future__ import annotations

import os
import sys

from mosaera_core.config import load_env, undeclared_bundled_db
from mosaera_memory import MemoryStore


def main() -> int:
    load_env()  # honor .env, matching mosaera-api / the CLI
    url = os.environ.get("MOSAERA_DB_URL") or os.environ.get("MOSAERA_TEST_DB_URL")
    if not url:
        print(
            "db-migrate: set MOSAERA_DB_URL (or MOSAERA_TEST_DB_URL) to the target database.",
            file=sys.stderr,
        )
        # The bundled URL lives only in scripts/dev-up.sh, so `make db-migrate` outside a
        # `make up` shell lands here with Postgres already running and reachable.
        bundled = undeclared_bundled_db()
        if bundled:
            print(f'\n  export MOSAERA_DB_URL="{bundled}"\n', file=sys.stderr)
        return 2
    store, reason = MemoryStore.open_or_reason(url)
    if store is None:
        print(f"db-migrate: could not migrate — {reason}", file=sys.stderr)
        return 1
    print("db-migrate: database is at Alembic head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
