from pathlib import Path

from kvstore import KVStore


def test_set_then_get(tmp_path: Path) -> None:
    store = KVStore(str(tmp_path / "kv.json"))
    store.set("a", 1)
    assert store.get("a") == 1


def test_persists_across_reload(tmp_path: Path) -> None:
    path = str(tmp_path / "kv.json")
    store = KVStore(path)
    store.set("a", 1)
    reloaded = KVStore(path)
    assert reloaded.get("a") == 1
