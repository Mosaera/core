"""JSON-file-backed persistence for journal entries (reference solution).

Adds tag attachment and tag lookup on top of the seed's add/list.
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
        return sorted(self._read(), key=lambda e: e.id)

    def add(self, text: str) -> Entry:
        entries = self._read()
        next_id = max((e.id for e in entries), default=0) + 1
        entry = Entry(id=next_id, text=text, tags=[])
        entries.append(entry)
        self._write(entries)
        return entry

    def add_tag(self, entry_id: int, label: str) -> bool:
        """Attach ``label`` to the entry with ``entry_id`` (no duplicates); persist.
        Returns False when no such entry exists."""
        entries = self._read()
        for entry in entries:
            if entry.id == entry_id:
                if label not in entry.tags:
                    entry.tags.append(label)
                self._write(entries)
                return True
        return False

    def find(self, label: str) -> list[Entry]:
        """Every entry carrying ``label``, in id order."""
        return [e for e in self.all() if label in e.tags]
