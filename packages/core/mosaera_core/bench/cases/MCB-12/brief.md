# Add `:param` path-segment support to the router (Python)

You are working in an existing, working module `router.py` with a class `Router`:

```python
class Router:
    def add(self, pattern: str, handler) -> None: ...
    def match(self, path: str) -> tuple | None: ...
```

- `add(pattern, handler)` registers a route.
- `match(path)` returns `(handler, params)` for the matching route, where `params`
  is a dict of captured path parameters, or `None` when nothing matches.

Today the router does **exact static string matching only**: `add("/users", h)`
matches the path `"/users"` and returns `(h, {})`; any other path returns `None`. A
pattern like `"/users/:id"` is treated as a literal string, so it only matches the
path `"/users/:id"`.

## Task

Support a `:param` path segment:

- A pattern segment beginning with `:` captures that positional segment's value.
  `"/users/:id"` matches `"/users/42"` and returns `(handler, {"id": "42"})`.
- Multiple params work: `"/users/:id/posts/:pid"` matches `"/users/42/posts/7"`
  and captures `{"id": "42", "pid": "7"}`.
- Static (non-`:`) segments must still match exactly.
- A pattern matches a path only when they have the **same number of segments** —
  `"/users/:id"` must not match `"/users/42/extra"`.
- Static routes keep working (`"/users"` → `(h, {})`), and no match still returns
  `None`.

## Constraints

- Match **segment-by-segment** — split the pattern and the path on `"/"` and compare
  positionally; a pattern segment starting with `:` captures, any other must be equal.
- Keep the existing `add`/`match` signatures and the `(handler, params)` / `None`
  return contract unchanged.
- Standard library only.
