# pager

A tiny pagination helper: `paginate(items, page, per_page)` returns one 1-based page
of a list.

```python
from pager import paginate

paginate([1, 2, 3, 4, 5], 1, 2)  # -> first page
```

Run the tests with `python -m pytest`.
