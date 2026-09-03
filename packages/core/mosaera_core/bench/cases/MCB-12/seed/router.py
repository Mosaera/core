"""A tiny URL router.

Registers ``(pattern, handler)`` pairs and matches a request path against them.
Today matching is exact static string comparison: a pattern matches only the path
equal to it, capturing no parameters.
"""

from __future__ import annotations

from typing import Any


class Router:
    """Maps request paths to handlers by exact string match."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, Any]] = []

    def add(self, pattern: str, handler: Any) -> None:
        """Register ``handler`` for the given path ``pattern``."""
        self._routes.append((pattern, handler))

    def match(self, path: str) -> tuple[Any, dict[str, str]] | None:
        """Return ``(handler, params)`` for the first matching route, else ``None``."""
        for pattern, handler in self._routes:
            if pattern == path:
                return (handler, {})
        return None
