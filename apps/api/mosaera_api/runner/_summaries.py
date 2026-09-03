"""Per-agent executive summaries — a MODEL-AUTHORED display artifact, never evidence.

At each park and at finalize, one small model call turns the run's recorded events into
plain-English one-liners per agent, persisted as an ``agent_summaries`` decision the run
page reads. Deterministic-First note: this call gates nothing and vouches for nothing —
it narrates the record for the operator (a model may author/analyze, never green-light).
Best-effort throughout: a summarizer failure must never break a run.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

# Graph node → the run page's agent seat (mirrors apps/web lib/engine NODE_AGENT).
_NODE_SEAT: dict[str, str] = {
    "plan": "quincy",
    "supervise": "quincy",
    "design": "architect",
    "author_tests": "proctor",
    "implement": "forge",
    "capture": "forge",
    "fix": "forge",
    "hygiene_fix": "forge",
    "review_fix": "forge",
    "quality_revise": "forge",
    "reason": "forge",
    "test": "vera",
    "hygiene": "vera",
    "scan": "vera",
    "review": "rook",
    "critic": "critic",
    "deliver": "drift",
}

_SEATS = ("quincy", "architect", "proctor", "forge", "vera", "rook", "critic", "drift")
_CLIP = 700  # per-digest chars — keeps the one call small


def _digest(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Per-seat raw material from the emitted events (updates + activity counts)."""
    texts: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for e in events:
        data = e.get("data") or {}
        node = str(data.get("node") or e.get("node") or "")
        seat = _NODE_SEAT.get(node)
        if seat is None:
            continue
        if e.get("type") == "activity":
            counts[seat] = counts.get(seat, 0) + 1
            continue
        if e.get("type") != "update":
            continue
        update = data.get("update")
        if isinstance(update, dict):
            for v in update.values():
                if isinstance(v, str) and v.strip():
                    texts.setdefault(seat, []).append(v.strip()[:_CLIP])
    for seat, n in counts.items():
        texts.setdefault(seat, []).append(f"({n} tool calls)")
    return texts


def summarize_agents(
    events: list[dict[str, Any]], invoke: Callable[[str], str]
) -> dict[str, str] | None:
    """One model call → {seat: one-sentence plain-English summary}. None on any fault."""
    material = _digest(events)
    if not material:
        return None
    parts = [
        "You are narrating a software delivery run for a non-technical operator.",
        "For each agent below, write ONE short plain-English sentence saying what it",
        "actually did this run — concrete, past tense, no jargon, no code identifiers.",
        "Claim ONLY what the material under each heading shows: never invent packaging,",
        "releases, or steps that are not there. Refer to each agent as 'it' — never by",
        "the internal key (quincy/forge/proctor are keys, not names).",
        "Reply with ONLY a JSON object mapping the agent keys to their sentence.",
        "",
    ]
    for seat in _SEATS:
        if seat in material:
            parts.append(f"### {seat}\n" + "\n".join(material[seat][:6]))
    try:
        raw = invoke("\n".join(parts))
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        parsed = json.loads(match.group(0))
        out = {
            k: str(v).strip()
            for k, v in parsed.items()
            if k in _SEATS and isinstance(v, str) and v.strip()
        }
        return out or None
    except Exception:
        return None  # display-only artifact: silence over breakage


def persist_agent_summaries(session: Any) -> None:
    """Generate + durably record the summaries for ``session`` (best-effort)."""
    if session._memory is None:
        return
    # Only narrate runs that actually used a model: a model-free run (offline tests,
    # deterministic-only paths) must not trigger a NEW model call just for narration.
    try:
        if int(session.cost_meter.rollup().get("calls", 0)) <= 0:
            return
    except Exception:
        return
    try:
        from mosaera_core.config import Settings
        from mosaera_core.models import get_chat_model

        model = get_chat_model("pm", Settings.from_env())

        def invoke(prompt: str) -> str:
            reply = model.invoke(prompt)
            return str(getattr(reply, "content", reply))

        summaries = summarize_agents(list(session._history), invoke)
        if summaries:
            logging.getLogger(__name__).info(
                "agent summaries written for %s (%d seats)", session.run_id, len(summaries)
            )
            memory = session._memory
            session._safe(
                lambda: memory.add_decision(
                    session.run_id, "agent_summaries", json.dumps(summaries)
                )
            )
    except Exception:
        # Never break a run for narration — but say so once in the log.
        logging.getLogger(__name__).warning("agent-summary generation failed", exc_info=True)
