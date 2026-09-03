"""Slice a list of items into fixed-size pages.

Pages are 1-based: ``paginate(items, 1, per_page)`` returns the first page. An
out-of-range page (or a non-positive ``page``/``per_page``) returns an empty list.
"""

from __future__ import annotations


def paginate(items: list, page: int, per_page: int) -> list:
    """Return the ``page``-th slice of ``per_page`` items (1-based)."""
    if page < 1 or per_page < 1:
        return []
    start = (page - 1) * per_page
    return items[start : start + per_page]
