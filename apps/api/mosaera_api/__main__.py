"""Run the Mosaera API server: `mosaera-api` or `python -m mosaera_api`."""

from __future__ import annotations

import os

import uvicorn
from mosaera_core.config import load_env

# guard_bind now lives in app.py so create_app() enforces it too (a --factory /
# gunicorn entrypoint skips main()); re-imported here for main() + the tests.
from mosaera_api.app import create_app, guard_bind


def main() -> None:
    load_env()
    # A blank MOSAERA_API_HOST (e.g. `MOSAERA_API_HOST=` in .env) must mean the
    # safe default, NOT bind-all-interfaces — `or` handles unset and blank alike.
    host = os.environ.get("MOSAERA_API_HOST") or "127.0.0.1"
    guard_bind(
        host,
        os.environ.get("MOSAERA_API_TOKEN", ""),
        os.environ.get("MOSAERA_SANDBOX", "docker"),
    )
    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=int(os.environ.get("MOSAERA_API_PORT", "8000")),
        # Hard cap so Ctrl+C always stops the server even if a client holds an
        # SSE stream open.
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
