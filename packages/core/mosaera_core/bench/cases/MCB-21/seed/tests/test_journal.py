"""The seed's own tests — add/list/persistence. Context for the agent."""

from __future__ import annotations

from pathlib import Path

from journal.store import Store


def test_add_returns_entry_with_id_one(tmp_path: Path) -> None:
    store = Store(tmp_path / "j.json")
    entry = store.add("first thing")
    assert entry.id == 1
    assert entry.text == "first thing"
    assert entry.tags == []


def test_ids_increment_and_persist_across_stores(tmp_path: Path) -> None:
    path = tmp_path / "j.json"
    Store(path).add("a")
    Store(path).add("b")
    assert [e.id for e in Store(path).all()] == [1, 2]
    assert [e.text for e in Store(path).all()] == ["a", "b"]


def test_all_is_in_id_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "j.json")
    store.add("one")
    store.add("two")
    assert [e.id for e in store.all()] == [1, 2]
