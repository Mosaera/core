"""A tiny persistent key/value store backed by a JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class KVStore:
    """A dict-like store persisted to a JSON file at ``path``."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        p = Path(self.path)
        if p.exists():
            self._data = json.loads(p.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def save(self) -> None:
        Path(self.path).write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()
