"""Parse a single structured log line into its parts."""

from __future__ import annotations

from typing import Any


def parse_log_line(line: str) -> dict[str, Any]:
    """Parse ``line`` into ``{level, timestamp, message, fields}``.

    The line is space-separated: token[0] is the level, token[1] is the
    timestamp, and every remaining token is either a message word (no ``=``) or a
    ``key=value`` field token (the value keeps everything after the first ``=``).
    ``message`` is the message words joined by a single space, in order; ``fields``
    is the dict of key/value tokens.
    """
    tokens = line.split(" ")
    level = tokens[0]
    timestamp = tokens[1]
    message_words = []
    fields = {}
    for token in tokens[2:]:
        if "=" in token:
            key = token[: token.index("=")]
            value = token[token.index("=") + 1 :]
            fields[key] = value
        else:
            message_words.append(token)
    message = " ".join(message_words)
    return {
        "level": level,
        "timestamp": timestamp,
        "message": message,
        "fields": fields,
    }
