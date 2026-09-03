"""A tiny URL router.

Registers ``(pattern, handler)`` pairs and matches a request path against them.
Matching is segment-wise: the pattern and path are split on ``"/"`` and compared
positionally. A pattern segment beginning with ``:`` captures the corresponding
path segment as a named parameter; any other segment must match exactly. A pattern
matches only when it has the same number of segments as the path.
"""

from __future__ import annotations

from typing import Any


class Router:
    """Maps request paths to handlers by segment-wise match with ``:param`` capture."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, Any]] = []

    def add(self, pattern: str, handler: Any) -> None:
        """Register ``handler`` for the given path ``pattern``."""
        self._routes.append((pattern, handler))

    def match(self, path: str) -> tuple[Any, dict[str, str]] | None:
        """Return ``(handler, params)`` for the first matching route, else ``None``."""
        path_segments = path.split("/")
        for pattern, handler in self._routes:
            pattern_segments = pattern.split("/")
            if len(pattern_segments) != len(path_segments):
                continue
            params: dict[str, str] = {}
            matched = True
            for pat, seg in zip(pattern_segments, path_segments):
                if pat.startswith(":"):
                    params[pat[1:]] = seg
                elif pat != seg:
                    matched = False
                    break
            if matched:
                return (handler, params)
        return None
