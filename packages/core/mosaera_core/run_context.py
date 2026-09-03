"""Shared, persistent run-time context for a project item run (#26).

An item run used to start cold — it saw only its own task + the project brief, so
the agents had no idea what sibling items exist or what earlier items already
built. This assembles a budgeted, DETERMINISTIC digest from what the memory store
already persists (backlog + delivered-run summaries + changed files) and hands it
to planning as extra grounding.

Deterministic-first by construction: pure read-back + string assembly, no model
calls, computed once at run start (siblings/history are static within a run) and
hard-capped so it can never blow the planner's context window.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from mosaera_core.clauses import clauses_prompt_block, load_clauses

# Newest deliveries and the current item matter most; cap the rest.
_MAX_HISTORY = 8
_MAX_SIBLINGS = 40
_MAX_FILES_PER_ITEM = 12
_DEFAULT_BUDGET = 6_000
_MAX_DOCTRINE = 1_500  # per-project reference material, budgeted like the global block
_MAX_DOCTRINE_CHUNK = 600


class _HistoryStore(Protocol):
    def list_backlog_items(self, project_id: str) -> list[dict[str, Any]]: ...
    def project_history(self, project_id: str, limit: int = ...) -> list[dict[str, Any]]: ...
    def load_doctrine(
        self, scope: str, project_id: str | None = ..., kind: str | None = ...
    ) -> list[dict[str, Any]]: ...


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_run_context(
    memory: _HistoryStore | None,
    project_id: str | None,
    current_item_id: int | None,
    brief: str,
    *,
    budget: int = _DEFAULT_BUDGET,
    clauses_enabled: bool = False,
) -> str:
    """Assemble the shared project context for an item run, or ``""`` for an ad-hoc
    run (no project / no memory). Three blocks — brief, the backlog (siblings +
    status, the current item marked), and what's already been built — each and the
    whole capped so planning gets awareness without a context blow-up."""
    if not project_id or memory is None:
        return _brief_block(brief, budget) if brief else ""

    sections: list[str] = []
    if brief.strip():
        sections.append(_brief_block(brief, budget // 3))

    # --- Standing decisions (ADR-0082 tier 2): what the operator already settled, so the team
    # does not re-derive it (or guess). This is the block that carries the MEASURED effect —
    # 0/6 -> 5/6 grader-clean came from the number reaching the coder, not from storing it. ---
    # Duck-typed on purpose: `_HistoryStore` describes what this module REQUIRES, and clauses are
    # optional — a store without them simply has none (`load_clauses` degrades to empty on any
    # store failure, including a missing method), so widening the protocol would force every
    # caller and test fake to grow a method they do not need.
    decisions = clauses_prompt_block(
        load_clauses(cast(Any, memory), project_id, enabled=clauses_enabled)
    )
    if decisions:
        sections.append(decisions)

    # --- Project doctrine: trusted reference material the PM should FOLLOW (distinct
    # from the untrusted repo/attachment data) — academic/research/house standards
    # seeded for this project. Empty when there's none or no DB. ---
    try:
        chunks = memory.load_doctrine("project", project_id)
    except Exception:
        chunks = []
    if chunks:
        parts = [
            f"### {_clip(str(c.get('source') or 'reference'), 80)}\n"
            f"{_fit(str(c.get('content', '')).strip(), _MAX_DOCTRINE_CHUNK)}"
            for c in chunks
        ]
        sections.append(
            "## Project doctrine (trusted reference — follow it)\n"
            + _fit("\n\n".join(parts), _MAX_DOCTRINE)
        )

    # --- Backlog: siblings + status, so the team sees the whole board ---
    try:
        items = memory.list_backlog_items(project_id)
    except Exception:
        items = []
    if items:
        lines: list[str] = []
        for it in items[:_MAX_SIBLINGS]:
            mark = " ← THIS ITEM" if it.get("id") == current_item_id else ""
            status = it.get("status", "todo")
            line = f"- [{status}] {_clip(str(it.get('title', '')), 120)}{mark}"
            # Acceptance is useful for work still open; done items stay compact.
            if status in ("todo", "in_progress") and it.get("acceptance"):
                line += f"\n    acceptance: {_clip(str(it['acceptance']), 200)}"
            lines.append(line)
        sections.append("## Backlog (this project)\n" + "\n".join(lines))

    # --- Already built: delivered items → what they did + files touched ---
    try:
        history = memory.project_history(project_id, limit=_MAX_HISTORY)
    except Exception:
        history = []
    history = [h for h in history if h.get("item_id") != current_item_id]
    if history:
        blocks: list[str] = []
        for h in history:
            title = _clip(str(h.get("title", "")), 120)
            entry = f"- {title}"
            summary = str(h.get("summary", "")).removeprefix("SUMMARY:").strip()
            if summary:
                entry += f"\n    did: {_clip(summary, 240)}"
            files = list(h.get("files", []))[:_MAX_FILES_PER_ITEM]
            if files:
                entry += f"\n    files: {', '.join(files)}"
            blocks.append(entry)
        sections.append(
            "## Already built in this project (reuse it; don't duplicate)\n" + "\n".join(blocks)
        )

    return _fit("\n\n".join(s for s in sections if s), budget)


def _brief_block(brief: str, budget: int) -> str:
    return "## Project brief\n" + _fit(brief.strip(), budget)


def _fit(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    return text[: budget - 40].rstrip() + "\n… (project context truncated)"
