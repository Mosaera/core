"""PM planning & design: per-item plan/design + the tool-using PM agent."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, NamedTuple

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool

from mosaera_agents.messages import fallback_evidence, message_text, reasoning_of
from mosaera_agents.prompts import DESIGN_SYSTEM, PM_SYSTEM
from mosaera_agents.retry import is_transient_model_error, robust_invoke

# A plan's real start: a markdown/bold header mentioning "plan", or the first
# numbered list item. Reasoning models (e.g. gpt-oss) sometimes emit a paragraph
# of deliberation before this; strip_preamble trims it.
_PLAN_HEADER = re.compile(r"^\s*(#{1,6}\s+.*plan|\*\*.*plan.*\*\*)\s*$", re.IGNORECASE)
_NUMBERED_START = re.compile(r"^\s*1[.)]\s+\S")

# Fallback when a reasoning model routes everything to its thinking channel and
# returns empty content — the Coder must still get an actionable instruction.
_FALLBACK_PLAN = (
    "1. Inspect the relevant files.\n"
    "2. Make the smallest change that satisfies the task.\n"
    "3. Run the tests and iterate until they pass."
)


class PlanOutcome(NamedTuple):
    """What a planning turn produced, and — when it produced nothing — the evidence why.

    `plan` is always usable (the fallback when all else failed). `reason` and `evidence` are set
    ONLY on a fallback; `rescued` says the plan came out of the model's reasoning channel rather
    than its content, which is a fact about the ENGINE worth seeing separately from a clean run.
    """

    plan: str
    reason: str
    evidence: str
    rescued: bool


def strip_preamble(text: str) -> str:
    """Drop leading deliberation before the plan's first header or numbered step.

    Conservative: if a recognizable plan start is found at the very top (or not at
    all), the text is returned unchanged; only genuine leading preamble is removed.
    """
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if _PLAN_HEADER.match(line) or _NUMBERED_START.match(line):
            return "\n".join(lines[idx:]).strip() if idx > 0 else text.strip()
    return text.strip()


def plan_task(
    model: BaseChatModel,
    task: str,
    repo_overview: str,
    feedback: Sequence[str] = (),
) -> str:
    """Produce a short numbered plan for ``task`` over the given repository."""
    sections = [f"## Task\n{task}", f"## Repository files\n{repo_overview}"]
    if feedback:
        joined = "\n".join(f"- {f}" for f in feedback if f)
        sections.append(f"## Feedback on the previous attempt (must be addressed)\n{joined}")
    response = robust_invoke(
        model, [SystemMessage(content=PM_SYSTEM), HumanMessage(content="\n\n".join(sections))]
    )
    raw = message_text(response)
    plan = strip_preamble(raw)
    return plan or raw.strip() or _FALLBACK_PLAN


# Fallback design when a reasoning model returns empty content — the Coder must
# still get an actionable architecture to build against.
_FALLBACK_DESIGN = (
    "## Approach\nImplement the plan directly, keeping the change minimal and "
    "consistent with the surrounding code.\n\n"
    "## Files to touch\nThe files named in the plan.\n\n"
    "## Risks & mitigations\n- RISK: breaking existing behaviour → MITIGATION: keep the "
    "change minimal → CHECK: all existing tests still pass."
)

# The '## Risks & mitigations' pre-mortem section of a design — actuated foresight the
# coder must implement and the reviewer verifies (RISK → MITIGATION → CHECK lines).
_FORESIGHT_HEADER = re.compile(r"^\s*#{1,6}\s*Risks\s*&\s*mitigations\s*$", re.IGNORECASE | re.M)


def extract_foresight(design: str) -> str:
    """Slice the '## Risks & mitigations' section out of a design — from its header to
    the next heading or end. "" when the design has no such section."""
    header = _FORESIGHT_HEADER.search(design)
    if not header:
        return ""
    rest = design[header.end() :]
    nxt = re.search(r"^\s*#{1,6}\s+\S", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def design_item(
    model: BaseChatModel,
    task: str,
    plan: str,
    repo_overview: str,
    feedback: Sequence[str] = (),
) -> str:
    """Elaborate ``plan`` into a concrete design/architecture for ``task`` — the
    layer above file-level steps (approach, interfaces, files, risks) the Coder
    builds against and the Reviewer checks the code conforms to."""
    sections = [
        f"## Task\n{task}",
        f"## Plan\n{plan}",
        f"## Repository files\n{repo_overview}",
    ]
    if feedback:
        joined = "\n".join(f"- {f}" for f in feedback if f)
        sections.append(f"## Feedback on the previous attempt (must be addressed)\n{joined}")
    response = robust_invoke(
        model, [SystemMessage(content=DESIGN_SYSTEM), HumanMessage(content="\n\n".join(sections))]
    )
    # Not strip_preamble: a design uses ## headers and may contain numbered lists,
    # which strip_preamble (tuned for plans) would wrongly treat as the start.
    design = message_text(response).strip()
    return design or _FALLBACK_DESIGN


# --- Tool-using PM (EYES): the planner reads the repo before it writes -------------
#
# build_pm_agent mirrors build_reviewer_agent: a compiled agent with the read-only
# repo tools, so plan/design can ground themselves in the ACTUAL code (not just a
# filename listing) before producing text. plan_with_agent / design_with_agent are
# the tool-using counterparts of plan_task / design_item — same prompt body, but the
# system prompt is baked into the agent, so they send only the HumanMessage. The
# plain plan_task / design_item above remain as a no-tool fallback (and are what the
# offline unit tests exercise).


def build_pm_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str,
    step_limit: int = 12,
) -> Runnable:
    """Build the PM planner as a compiled agent graph (read-only tools).

    ``tools`` must already be scoped to the read-only allowlist (list_files,
    read_file, search) — this factory does not widen permissions. ``system_prompt``
    selects the behaviour: ``PM_SYSTEM`` for planning, ``DESIGN_SYSTEM`` for design.

    Reliability middleware (like the reviewer): ``ModelCallLimitMiddleware`` bounds
    the read-tool loop so a degenerate planner STOPS and returns instead of exploring
    the whole tree / hitting the recursion limit; ``ModelRetryMiddleware`` retries a
    transient Ollama error and, on persistent failure, ends with partial output (→ ""
    → the fallback plan/design) rather than hard-erroring the run.
    """
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(
            max_retries=2, retry_on=is_transient_model_error, on_failure="continue"
        ),
        ModelCallLimitMiddleware(run_limit=step_limit, exit_behavior="end"),
    ]
    return create_agent(
        model=model, tools=list(tools), system_prompt=system_prompt, middleware=middleware
    )


# The sentinel ModelCallLimitMiddleware(exit_behavior="end") injects as the final AI
# message when the planner exhausts its step budget. It is NOT a plan — returning it
# verbatim once produced "Model call limits exceeded: run limit (12/12)" as the plan
# text. Skipped so a real earlier partial plan wins, else we fall to the fallback.
_BUDGET_SENTINEL = "Model call limits exceeded"


# `ModelRetryMiddleware(on_failure="continue")` leaves the transport error in the message list
# rather than raising, so the run degrades instead of crashing. The text it leaves behind is the
# ONLY surviving evidence that the model was never reached — measured live as
# "Model call failed after 3 attempts with ResponseError: <html>… 502 Bad Gateway … openresty".
_TRANSPORT_SENTINEL = "Model call failed after"


def _last_ai_text(result: dict[str, Any]) -> str:
    """The last non-empty, non-sentinel AI message from a compiled-agent result
    (mirrors the reviewer's extraction) — the agent's final answer after any tool use.

    BOTH middleware sentinels are skipped so neither can masquerade as output. The transport one
    was missing until 2026-08-24: `ModelRetryMiddleware(on_failure="continue")` leaves its failure
    text in the message list as an ordinary AI message, so it came back as the answer — and since
    `plan_is_fallback` compares against `_FALLBACK_PLAN`, the turn did not register as a fallback
    either, so no reason was recorded and the coder was handed "Model call failed after 3 attempts
    with ResponseError: <html>… 502 …" as its instructions.

    The predicates match the ones `_rescued_from_reasoning` and `fallback_reason` already use —
    `startswith` for budget, `in` for transport, because the transport text is embedded. Those two
    tested for both; this was the only one of the three that did not."""
    for message in reversed(result.get("messages", [])):
        text = message_text(message).strip()
        if message.type != "ai" or not text:
            continue
        if text.startswith(_BUDGET_SENTINEL) or _TRANSPORT_SENTINEL in text:
            continue
        return text
    return ""


def _looks_like_a_plan(text: str) -> bool:
    """Whether text has a recognizable plan SHAPE — a plan header or a numbered first step.

    The gate that makes the reasoning-channel rescue below one-sided. The reviewer's equivalent
    rescue can look for a parseable ``VERDICT:`` line; a plan has no such marker, so its shape
    stands in. Anything shapeless stays unrescued and the fallback wins.
    """
    for line in text.splitlines():
        if _PLAN_HEADER.match(line) or _NUMBERED_START.match(line):
            return True
    return False


def _rescued_from_reasoning(result: dict[str, Any]) -> str:
    """A plan the model wrote into its REASONING channel, or "" (#71, F39).

    Reasoning models (gpt-oss:20b) frequently leave ``content`` EMPTY and put the whole answer in
    the reasoning channel. ``reviewer.py`` already learned this the expensive way — a content-only
    read there false-parked ~75% of MCB-21 runs *whose code was delivered correctly* — and switched
    to ``reasoning_of``. The PM planner was the last content-only consumer in the engine, so it kept
    throwing away plans the model had actually written.

    NARROWER than the reviewer's version on purpose. The reviewer accepts any text carrying a
    verdict; here we accept only text that is plan-SHAPED, because the alternative failure — handing
    the coder a stream of deliberation as its marching orders — is worse than falling back. Rescue a
    plan that looks like a plan, or rescue nothing.
    """
    for message in reversed(result.get("messages", [])):
        if getattr(message, "type", "") != "ai":
            continue
        full = reasoning_of(message).strip()
        if not full or full.startswith(_BUDGET_SENTINEL) or _TRANSPORT_SENTINEL in full:
            continue
        candidate = strip_preamble(full)
        if _looks_like_a_plan(candidate):
            return candidate
    return ""


def fallback_reason(result: dict[str, Any]) -> str:
    """WHY this agent produced nothing usable: ``budget_exhausted`` | ``model_failed`` | ``empty``.

    Three very different failures collapse into the same silent ``_FALLBACK_PLAN``, and by the time
    the graph recovers the fact (by comparing the plan text to the constant) the cause is gone. They
    demand opposite responses from a human — raise a budget, restart a server, or clarify an item —
    so conflating them is its own kind of dressing-up (F39, issue #71).

    Measured 2026-08-07: the planner spent all 12 of its model calls reading the repo and had none
    left to write with. The run then told the operator the ITEM "needs clarification", and the gate
    told them validation was "unavailable". Neither was true, and the truth was in this message list
    the whole time.

    Reads only what is already there — no new state, no inference. ``empty`` is the honest
    *unknown*: no marker and nothing to show, which is the ONLY case where blaming the item is fair.
    """
    for message in reversed(result.get("messages", [])):
        text = message_text(message).strip()
        if text.startswith(_BUDGET_SENTINEL):
            return "budget_exhausted"
        if _TRANSPORT_SENTINEL in text:
            return "model_failed"
    return "empty"


def plan_with_agent_detailed(
    agent: Runnable,
    task: str,
    repo_overview: str,
    feedback: Sequence[str] = (),
    config: RunnableConfig | None = None,
) -> PlanOutcome:
    """``plan_with_agent`` plus WHY it fell back and WHAT the model actually returned.

    Split out rather than changing ``plan_with_agent``'s return type because that signature is the
    AgentTeam contract and several callers only want the string (compatibility is the default).
    """
    sections = [f"## Task\n{task}", f"## Repository files\n{repo_overview}"]
    if feedback:
        joined = "\n".join(f"- {f}" for f in feedback if f)
        sections.append(f"## Feedback on the previous attempt (must be addressed)\n{joined}")
    result: dict[str, Any] = agent.invoke(
        {"messages": [HumanMessage(content="\n\n".join(sections))]}, config
    )
    raw = _last_ai_text(result)
    plan = strip_preamble(raw) or raw.strip()
    rescued = ""
    if not plan:
        # The model said nothing in `content`. Before giving up, look in the reasoning channel —
        # it may have written the plan there and had it discarded (#71, F39).
        rescued = _rescued_from_reasoning(result)
        plan = rescued
    if plan:
        return PlanOutcome(plan, "", "", bool(rescued))
    # Genuinely nothing usable: record the cause AND the raw output, so the next person does not
    # have to reconstruct the request from the outside the way 2026-08-07 did.
    return PlanOutcome(_FALLBACK_PLAN, fallback_reason(result), fallback_evidence(result), False)


def plan_with_agent(
    agent: Runnable,
    task: str,
    repo_overview: str,
    feedback: Sequence[str] = (),
    config: RunnableConfig | None = None,
) -> str:
    """Tool-using counterpart of ``plan_task``: the agent may read the repo to ground
    the plan before writing it. ``config`` threads the run's stream writer so read
    tools surface as activity milestones. Same output contract as ``plan_task``."""
    return plan_with_agent_detailed(agent, task, repo_overview, feedback, config).plan


def design_with_agent(
    agent: Runnable,
    task: str,
    plan: str,
    repo_overview: str,
    feedback: Sequence[str] = (),
    config: RunnableConfig | None = None,
) -> str:
    """Tool-using counterpart of ``design_item``: the agent may read the plan-named
    files to ground signatures before elaborating the design. Same contract as
    ``design_item`` (no ``strip_preamble`` — a design leads with ## headers)."""
    sections = [
        f"## Task\n{task}",
        f"## Plan\n{plan}",
        f"## Repository files\n{repo_overview}",
    ]
    if feedback:
        joined = "\n".join(f"- {f}" for f in feedback if f)
        sections.append(f"## Feedback on the previous attempt (must be addressed)\n{joined}")
    result: dict[str, Any] = agent.invoke(
        {"messages": [HumanMessage(content="\n\n".join(sections))]}, config
    )
    return _last_ai_text(result) or _FALLBACK_DESIGN
