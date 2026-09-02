"""JSON-file-backed persistence for journal entries.

The store is constructed with a real :class:`~pathlib.Path` (not a bare string);
callers are expected to pass a ``Path``. Keeping the persistence layer separate
from the CLI is deliberate — the CLI wires user input into these calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from journal.model import Entry


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> list[Entry]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [
            Entry(id=int(r["id"]), text=str(r["text"]), tags=list(r.get("tags", [])))
            for r in raw
        ]

    def _write(self, entries: list[Entry]) -> None:
        data = [{"id": e.id, "text": e.text, "tags": e.tags} for e in entries]
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def all(self) -> list[Entry]:
        """Every entry, in id order."""
        return sorted(self._read(), key=lambda e: e.id)

    def add(self, text: str) -> Entry:
        """Append a new entry with the next id and no tags; persist and return it."""
        entries = self._read()
        next_id = max((e.id for e in entries), default=0) + 1
        entry = Entry(id=next_id, text=text, tags=[])
        entries.append(entry)
        self._write(entries)
        return entry
