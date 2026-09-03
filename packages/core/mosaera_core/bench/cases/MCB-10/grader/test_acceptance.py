"""Hidden acceptance suite for MCB-10 (add `delete` and `items` to KVStore).

Ground truth — never shown to the agent, injected at grade time. Exercises the
delivered ``KVStore`` as a black box against a fresh JSON file per test, broader
than the seed's own visible tests.
"""

from __future__ import annotations

from pathlib import Path

from kvstore import KVStore


def test_items_sorted_by_key(tmp_path: Path) -> None:
    store = KVStore(str(tmp_path / "kv.json"))
    store.set("b", 2)
    store.set("a", 1)
    store.set("c", 3)
    assert store.items() == [("a", 1), ("b", 2), ("c", 3)]


def test_delete_removes_key(tmp_path: Path) -> None:
    store = KVStore(str(tmp_path / "kv.json"))
    store.set("b", 2)
    store.set("a", 1)
    store.set("c", 3)
    store.delete("b")
    assert store.get("b") is None
    assert ("b", 2) not in store.items()


def test_delete_persists_to_disk(tmp_path: Path) -> None:
    path = str(tmp_path / "kv.json")
    store = KVStore(path)
    store.set("a", 1)
    store.set("b", 2)
    store.delete("b")
    reloaded = KVStore(path)
    assert reloaded.get("b") is None
    assert dict(reloaded.items()) == {"a": 1}


def test_delete_missing_does_not_raise(tmp_path: Path) -> None:
    store = KVStore(str(tmp_path / "kv.json"))
    store.set("a", 1)
    store.delete("missing")  # must not raise
    assert store.get("a") == 1


def test_existing_get_set_still_work(tmp_path: Path) -> None:
    path = str(tmp_path / "kv.json")
    store = KVStore(path)
    store.set("x", 42)
    assert store.get("x") == 42
    assert store.get("nope") is None
    assert store.get("nope", "fallback") == "fallback"
    assert KVStore(path).get("x") == 42
