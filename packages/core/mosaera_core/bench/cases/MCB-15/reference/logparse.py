"""Parse a single structured log line into its parts."""

from __future__ import annotations

from typing import Any


def _tokens(line: str) -> list[str]:
    """Split ``line`` into its space-separated tokens."""
    return line.split(" ")


def _message(body_tokens: list[str]) -> str:
    """The message words (tokens without ``=``) joined by a single space, in order."""
    return " ".join(token for token in body_tokens if "=" not in token)


def _fields(body_tokens: list[str]) -> dict[str, str]:
    """The ``key=value`` tokens as a dict; a value keeps everything after the first ``=``."""
    fields = {}
    for token in body_tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    return fields


def parse_log_line(line: str) -> dict[str, Any]:
    """Parse ``line`` into ``{level, timestamp, message, fields}``.

    The line is space-separated: token[0] is the level, token[1] is the
    timestamp, and every remaining token is either a message word (no ``=``) or a
    ``key=value`` field token (the value keeps everything after the first ``=``).
    ``message`` is the message words joined by a single space, in order; ``fields``
    is the dict of key/value tokens.
    """
    tokens = _tokens(line)
    body = tokens[2:]
    return {
        "level": tokens[0],
        "timestamp": tokens[1],
        "message": _message(body),
        "fields": _fields(body),
    }
