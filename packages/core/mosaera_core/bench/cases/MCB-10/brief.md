# Add `delete` and `items` to the KVStore (Python)

You are working in an existing, working module `kvstore.py` with a class
`KVStore` that persists a key/value mapping to a JSON file. It already has
`get`, `set`, `save`, and `load`. `set` persists the change via `save`, and a
fresh `KVStore(path)` reloads the mapping from disk.

## Task

Add two methods, conforming to the existing style:

- `delete(self, key)` — remove `key` if present, do nothing (no error) if it is
  absent, and persist the change so a fresh `KVStore(path)` no longer has it.
- `items(self) -> list[tuple]` — return the `(key, value)` pairs sorted by key.

## Constraints

- Follow the existing structure and conventions — the in-memory mapping and the
  `save()`/`load()` persistence layer are already established; your methods must
  fit in, not reinvent them.
- Keep the existing `get`, `set`, `save`, and `load` behaviour unchanged.
- Standard library only.
