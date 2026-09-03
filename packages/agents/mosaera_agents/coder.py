"""Coder agent: implements the plan via allowlisted repo tools."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from operator import add
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain.agents.middleware.context_editing import ClearToolUsesEdit
from langchain.agents.middleware.types import AgentState, ModelRequest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from mosaera_agents.prompts import CODER_SYSTEM
from mosaera_agents.retry import is_transient_model_error

# An operator send-back arrives as this tool result (tools/repo/factory.py). It is the ONLY
# place the correction goes today — a ToolMessage, which ClearToolUsesEdit deletes.
_DENIAL_PREFIX = "DENIED by human reviewer:"
_NO_REASON = "no reason given"
# The block rides EVERY model call, and the coder's profile is ~98% input, so it is bounded on
# both axes. Newest wins: a later correction supersedes an earlier one on the same subject.
_MAX_CORRECTIONS = 10
_MAX_CORRECTION_CHARS = 1_500
_CORRECTIONS_HEADER = (
    "STANDING OPERATOR CORRECTIONS — given at earlier approval gates in THIS run.\n"
    "They remain in force for every file you write from now on, not just the file they were\n"
    "about. If one conflicts with the plan or the design, the correction wins and you should\n"
    "say so rather than silently reverting to the earlier instruction."
)


def _correction_from(text: str) -> str | None:
    """The operator's words from a denial tool result, or None if there is nothing to carry."""
    if not text.startswith(_DENIAL_PREFIX):
        return None
    note = text[len(_DENIAL_PREFIX) :].strip()
    # A denial with no stated reason carries no constraint — recording it would spend budget on
    # every later model call to say nothing.
    return note if note and note != _NO_REASON else None


def _corrections_block(notes: Sequence[str]) -> str:
    """Render the standing corrections, newest-first-wins, within both budgets."""
    seen: set[str] = set()
    kept: list[str] = []
    for note in reversed(notes):  # newest first, so the cap drops the STALEST
        if note in seen:
            continue
        seen.add(note)
        kept.append(note)
        if len(kept) >= _MAX_CORRECTIONS:
            break
    kept.reverse()  # render oldest → newest: the order the operator gave them
    lines: list[str] = []
    budget = _MAX_CORRECTION_CHARS
    for note in kept:
        entry = f"- {note}"
        if len(entry) > budget:
            break
        lines.append(entry)
        budget -= len(entry)
    return f"{_CORRECTIONS_HEADER}\n" + "\n".join(lines) if lines else ""


class CoderState(AgentState):
    """The coder's agent state, extended with the run's standing operator corrections.

    DECLARED here or the key never leaves the agent subgraph: verified experimentally — without
    this schema the ``Command`` update below is silently discarded and never reaches the parent
    run graph (so it would also never be checkpointed). Mirrors the ADR-0026 rule that already
    governs ``RunState``.
    """

    corrections: Annotated[list[str], add]


class StandingCorrections(AgentMiddleware):
    """Make an operator send-back a standing constraint instead of a one-shot hint.

    F27's sibling defect, and the mechanism is deletion rather than disobedience. A send-back
    becomes ``DENIED by human reviewer: …`` — a ToolMessage, and nothing else. ``ClearToolUsesEdit``
    keeps only the last 3 tool results, so a correction given six gates ago is provably gone from
    the model's context by the time it matters. Observed live: the coder was told to use exactly
    one package, complied in that file, then six gates later proposed the exact import it had been
    told not to use, and the same ambiguity took five corrections to settle.

    So the correction is lifted out of the transcript and into the SYSTEM MESSAGE, which is rebuilt
    on every model call and is not a ToolMessage — structurally immune to the trimming that erased
    it. It is stored in graph state rather than on this instance so it survives a park and
    rehydrate; a correction lost on restart is the same defect in a smaller window.

    Producer-side only. Corrections never reach the reviewer, the critic or the gate: an operator
    instruction is guidance to whoever is writing, never evidence that something was verified.
    """

    state_schema = CoderState

    def wrap_tool_call(
        self, request: Any, handler: Callable[[Any], Any]
    ) -> ToolMessage | Command[Any]:
        result = handler(request)
        if not isinstance(result, ToolMessage):
            return result  # a Command from another middleware — pass through untouched
        note = _correction_from(str(result.content))
        if note is None:
            return result
        # The ToolMessage must be carried in the update too: returning a Command REPLACES the
        # default append, so omitting it would drop the tool result the model is waiting on.
        return Command(update={"messages": [result], "corrections": [note]})

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[Any], Any]) -> Any:
        raw = (request.state or {}).get("corrections") or []
        notes = [str(n) for n in raw] if isinstance(raw, list) else []
        block = _corrections_block(notes)
        if block:
            base = request.system_message.content if request.system_message else ""
            request = request.override(system_message=SystemMessage(content=f"{base}\n\n{block}"))
        return handler(request)


def build_coder_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    step_limit: int = 25,
    context_token_trigger: int = 10_000,
    system_prompt: str = CODER_SYSTEM,
):
    """Build the Coder as a compiled agent graph (usable as a LangGraph node).

    ``tools`` must already be scoped by the policy allowlist — this factory does
    not widen or narrow permissions. ``system_prompt`` defaults to ``CODER_SYSTEM``;
    the graph passes ``coder_system(allow_delete)`` so the prompt names delete_file
    only when that tool is actually built.

    Reliability middleware (all reset/scoped per implement invocation):
    - ``ModelCallLimitMiddleware`` (``step_limit``): caps model calls so a runaway
      ReAct loop STOPS and returns partial work instead of hitting the graph's
      recursion limit and hard-erroring the run.
    - ``ContextEditingMiddleware`` (``context_token_trigger``): once the transcript
      exceeds the trigger, clears OLD tool outputs (big file reads) keeping the
      last few — so accumulated reads across fix/revise loops don't fill num_ctx
      and truncate the next tool call.
    - ``StandingCorrections``: an operator send-back at a write gate becomes a standing
      constraint in the system message for the rest of the run, instead of a ToolMessage the
      trimming below deletes three tool calls later.
    - ``ModelRetryMiddleware``: a transient model/transport error (notably a
      truncated tool-call → Ollama ResponseError) is retried; if it keeps failing,
      ``on_failure="continue"`` ends the agent with partial work (never raises), so
      validation fails and the gate PARKS for a human rather than the run erroring.
    """
    # Each middleware subclass parametrizes AgentMiddleware differently, so the
    # heterogeneous list needs a widened element type.
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        # FIRST, and it must stay ahead of ContextEditingMiddleware: that one is what deletes the
        # tool result the correction arrived in, so the standing copy has to be lifted out before
        # trimming can reach it.
        StandingCorrections(),
        ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=context_token_trigger, keep=3)]),
        ModelRetryMiddleware(
            max_retries=2, retry_on=is_transient_model_error, on_failure="continue"
        ),
        ModelCallLimitMiddleware(run_limit=step_limit, exit_behavior="end"),
    ]
    return create_agent(
        model=model, tools=list(tools), system_prompt=system_prompt, middleware=middleware
    )
