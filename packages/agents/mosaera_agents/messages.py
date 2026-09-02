"""Helpers for extracting plain text from LangChain messages."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from mosaera_core.messages import message_text

__all__ = ["fallback_evidence", "message_text", "reasoning_of"]

# How much of each channel to keep. Enough to see whether the model wrote a real answer, small
# enough that a pathological transcript can't bloat the run record.
_EXCERPT = 900
_EVIDENCE_CAP = 4_000


def reasoning_of(message: BaseMessage) -> str:
    """The agent's visible THINKING for one model turn: its narration (message text)
    plus any explicit reasoning/thinking content — reasoning content blocks and the
    provider ``reasoning_content`` (Ollama / deepseek-r1 CoT). Empty when the message
    is a pure tool-call with nothing to say. Used to stream reasoning-per-turn to the
    run transcript; never breaks a run (pure read of what the model already produced)."""
    parts: list[str] = []
    content: Any = message.content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("reasoning", "thinking"):
                parts.append(
                    str(block.get("reasoning") or block.get("thinking") or block.get("text", ""))
                )
    extra = getattr(message, "additional_kwargs", None)
    if isinstance(extra, dict):
        rc = extra.get("reasoning_content") or extra.get("thinking")
        if isinstance(rc, str) and rc.strip():
            parts.append(rc)
    reasoning = "\n".join(p for p in parts if p.strip()).strip()
    narration = message_text(message).strip()
    if reasoning and narration:
        return f"{reasoning}\n\n{narration}"
    return reasoning or narration


def _excerpt(text: str) -> str:
    """Head and tail, so a truncated middle can't hide how a message ENDED — which is exactly
    where a cut-off generation shows itself."""
    if len(text) <= _EXCERPT:
        return text
    half = _EXCERPT // 2
    return f"{text[:half]}\n… [{len(text) - _EXCERPT} chars elided] …\n{text[-half:]}"


def fallback_evidence(result: dict[str, Any]) -> str:
    """What the model ACTUALLY returned, for a turn the engine had to replace with a fallback.

    "The planner returned nothing usable" is a dead end without this. Diagnosing one such run on
    2026-08-07 took three synthetic probes against the live endpoint, all of which falsified their
    hypothesis and none of which reproduced the failure — because nothing recorded the real request
    or its response. This is that record.

    Deliberately reports BOTH channels separately rather than the merged ``reasoning_of`` view: the
    whole question in the measured case is *which channel the answer went to*, and merging them
    answers it by erasing it. ``content`` is shown as a **repr** so an empty string, three spaces
    and a newline are distinguishable — they mean different things and read identically otherwise.

    ``done_reason`` is the field that separates "context blown" (``length``) from "the model
    finished and said nothing" (``stop``). Nothing else in the engine reads it.

    Pure read of what the model already produced; never raises, never affects a run.
    """
    from mosaera_core.cost import usage_from_message  # local: keeps the import surface thin

    messages = list(result.get("messages") or [])
    ai = [m for m in messages if getattr(m, "type", "") == "ai"]
    tool_calls = sum(len(getattr(m, "tool_calls", None) or []) for m in ai)
    lines = [
        f"messages={len(messages)} ai={len(ai)} tool_calls={tool_calls}",
    ]
    for offset, message in enumerate(reversed(ai[-3:]), start=1):
        content = message_text(message)
        reasoning = reasoning_of(message)
        # reasoning_of appends the narration; strip it so the two channels don't double-count.
        if content and reasoning.endswith(content):
            reasoning = reasoning[: -len(content)].strip()
        resp = getattr(message, "response_metadata", None)
        done = (resp or {}).get("done_reason") if isinstance(resp, dict) else None
        usage = usage_from_message(message)
        lines.append(
            f"\n--- ai[-{offset}] done_reason={done!r} "
            f"in={usage.input_tokens} out={usage.output_tokens} "
            f"content_len={len(content)} reasoning_len={len(reasoning)}"
        )
        lines.append(f"content={_excerpt(content)!r}")
        if reasoning:
            lines.append(f"reasoning:\n{_excerpt(reasoning)}")
    return "\n".join(lines)[:_EVIDENCE_CAP]
