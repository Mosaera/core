"""PM agent: task intake and planning.

Facade over the two concerns this package separates:

- ``_planning`` — per-item PLANNING/DESIGN (the agent-driven plan/design +
  ``build_pm_agent`` and its tool-using counterparts).
- ``_backlog`` — BACKLOG/CHAT operations (understanding, decompose, curate,
  chat, summarize).

Everything the rest of the codebase references as ``pm.X`` (including the
underscore-prefixed prompt constants and helpers) is re-exported here so the
public surface is unchanged by the split.
"""

from __future__ import annotations

from mosaera_agents.pm._backlog import (
    _CHANGESET_OPS,
    _CHAT_CAPABILITY_CLAUSE,
    _CHAT_SYSTEM,
    _CURATE_SYSTEM,
    _DECOMPOSE_CAPABILITY_CLAUSE,
    _DECOMPOSE_SYSTEM,
    _FALLBACK_BRIEF,
    _JSON_BLOCK,
    _SUMMARIZE_SYSTEM,
    _UNDERSTANDING_CAPABILITY_CLAUSE,
    _UNDERSTANDING_SYSTEM,
    _augment_system,
    _extract_json_array,
    chat,
    chat_system_prompt,
    curate_backlog,
    decompose_brief,
    summarize_file,
    synthesize_understanding,
)
from mosaera_agents.pm._chat_agent import (
    CHAT_STEP_LIMIT,
    ChatOutcome,
    chat_with_agent,
)
from mosaera_agents.pm._planning import (
    _BUDGET_SENTINEL,
    _FALLBACK_DESIGN,
    _FALLBACK_PLAN,
    _FORESIGHT_HEADER,
    _NUMBERED_START,
    _PLAN_HEADER,
    PlanOutcome,
    _last_ai_text,
    build_pm_agent,
    design_item,
    design_with_agent,
    extract_foresight,
    fallback_reason,
    plan_task,
    plan_with_agent,
    plan_with_agent_detailed,
    strip_preamble,
)

__all__ = [
    "CHAT_STEP_LIMIT",
    "_BUDGET_SENTINEL",
    "_CHANGESET_OPS",
    "_CHAT_CAPABILITY_CLAUSE",
    "_CHAT_SYSTEM",
    "_CURATE_SYSTEM",
    "_DECOMPOSE_CAPABILITY_CLAUSE",
    "_DECOMPOSE_SYSTEM",
    "_FALLBACK_BRIEF",
    "_FALLBACK_DESIGN",
    "_FALLBACK_PLAN",
    "_FORESIGHT_HEADER",
    "_JSON_BLOCK",
    "_NUMBERED_START",
    "_PLAN_HEADER",
    "_SUMMARIZE_SYSTEM",
    "_UNDERSTANDING_CAPABILITY_CLAUSE",
    "_UNDERSTANDING_SYSTEM",
    "ChatOutcome",
    "PlanOutcome",
    "_augment_system",
    "_extract_json_array",
    "_last_ai_text",
    "build_pm_agent",
    "chat",
    "chat_system_prompt",
    "chat_with_agent",
    "curate_backlog",
    "decompose_brief",
    "design_item",
    "design_with_agent",
    "extract_foresight",
    "fallback_reason",
    "plan_task",
    "plan_with_agent",
    "plan_with_agent_detailed",
    "strip_preamble",
    "summarize_file",
    "synthesize_understanding",
    # --- backlog / chat ---,
    # --- planning / design ---,
]
