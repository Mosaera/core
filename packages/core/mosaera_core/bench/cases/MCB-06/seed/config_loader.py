"""Load application config from a JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_config(path: str) -> dict[str, Any]:
    """Return the config dict with ``name`` and ``port``.

    Requires a JSON object with a string ``name`` and an integer ``port``.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"name": data["name"], "port": data["port"]}
