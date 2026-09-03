"""Persistence for notes — a JSON list at ``NOTES_FILE`` (else ``notes.json``)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _path() -> Path:
    return Path(os.environ.get("NOTES_FILE", "notes.json"))


def load() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(notes: list[dict[str, Any]]) -> None:
    _path().write_text(json.dumps(notes, indent=2), encoding="utf-8")
