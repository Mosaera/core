"""Load and validate application config from a JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when a config file is missing, malformed, or fails validation."""


def load_config(path: str) -> dict[str, Any]:
    """Return the config dict with ``name`` (str) and ``port`` (int).

    Raises ``ConfigError`` with a human-readable message for a missing file,
    malformed JSON, a missing required key, or a wrong-typed value.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"config file {path} must contain a JSON object")

    for key, typ, label in (("name", str, "a string"), ("port", int, "an integer")):
        if key not in data:
            raise ConfigError(f"config is missing required key {key!r}")
        # bool is a subclass of int — reject it explicitly for an integer field.
        if not isinstance(data[key], typ) or isinstance(data[key], bool):
            raise ConfigError(f"config key {key!r} must be {label}")

    return {"name": data["name"], "port": data["port"]}
