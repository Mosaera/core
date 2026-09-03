# intervals

A tiny helper that merges overlapping or touching integer intervals.

```python
from intervals import merge

merge([(1, 3), (2, 6), (8, 10)])  # -> [(1, 6), (8, 10)]
```

Run the tests with `python -m pytest`.
