"""Helpers for extracting plain text from LangChain messages.

Lives in core so core consumers can read message text without importing
``mosaera_agents`` (which would create an upward core→agents edge). The agents
package re-exports ``message_text`` for its own use.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage


def message_text(message: BaseMessage) -> str:
    """Return the text content of a message, tolerating block-style content."""
    content: Any = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)
