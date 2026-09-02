"""The PM chat as a bounded, tool-using agent — the ON half of ADR-0111's knob.

`_backlog.chat` stays exactly as it was: one model call, no tools. That is the OFF path, and it
stays byte-identical because it is a different branch, not a carefully-edited one.

What is new here is the loop. It reuses `build_pm_agent` rather than assembling its own
middleware, so the chat inherits the same retry-and-bound behaviour the planner already has and
there is only one place `ModelCallLimitMiddleware` is configured.

The failure vocabulary is the planner's too: `fallback_reason` returns budget_exhausted /
model_failed / empty, which is exactly what the API already knows how to record and the web
already has words for. That is why a budget exhaustion arrives here as an honest note in the
transcript rather than as a mystery.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import Any, NamedTuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import Runnable, RunnableConfig

from mosaera_agents.messages import message_text
from mosaera_agents.pm._planning import (
    _BUDGET_SENTINEL,
    _TRANSPORT_SENTINEL,
    _last_ai_text,
    fallback_reason,
)
from mosaera_agents.pm._proposals import (
    _CHARTER_BLOCK,
    _CLARIFY_BLOCK,
    _extract_changeset,
    _extract_charter,
    _extract_clarify,
)

#: Steps one conversational turn may spend. Not `pm_step_limit` (20): that is the PLANNER's read
#: budget, sized for plan-plus-design work with nobody waiting. A chat turn has a human watching,
#: and every step is another full decode on the default local deployment.
CHAT_STEP_LIMIT = 6

_log = logging.getLogger(__name__)


class ChatOutcome(NamedTuple):
    """What a chat turn produced, and — when it produced nothing — why.

    Mirrors `PlanOutcome`: `failure` is set ONLY when the turn produced nothing usable, and is
    the empty string on a turn that answered. One shape, so "did it work" and "why not" cannot
    drift apart into two fields that disagree.
    """

    reply: str
    changeset: list[dict[str, Any]]
    charter: dict[str, str] | None
    clarification: dict[str, Any] | None
    failure: str


def replay(history: Sequence[dict[str, str]]) -> list[BaseMessage]:
    """The conversation as messages — only what somebody actually SAID.

    Deny-by-default on the role, and it is a control rather than tidiness: an engine `note` row
    records that a turn did not complete, and the old `else` branch turned every unrecognised
    role into a HUMAN message, so such a note would replay as if the operator had said it.

    Shared by both chat paths so the single-call turn and the loop cannot disagree about what the
    model is shown. Agents never imports memory, hence the literals.
    """
    out: list[BaseMessage] = []
    for turn in history:
        role = turn.get("role")
        if role not in ("pm", "user"):
            continue
        text = turn.get("content", "")
        out.append(AIMessage(content=text) if role == "pm" else HumanMessage(content=text))
    return out


#: What a listener is told, in the order it happens. Deliberately tiny — a name and some plain
#: words — because everything richer belongs to the caller that knows the surface it is drawing.
#: `step` is a lookup starting; `text` is Quincy saying something mid-turn.
StepListener = Callable[[str, dict[str, Any]], None]


def _notify(on_event: StepListener | None, kind: str, payload: dict[str, Any]) -> None:
    """Tell the listener, and never let it break the turn. Same posture as `emit_activity`:
    watching the work is telemetry, and telemetry that can fail the thing it observes is worse
    than no telemetry."""
    if on_event is None:
        return
    try:
        on_event(kind, payload)
    except Exception:
        _log.warning("chat step listener failed on %s", kind, exc_info=True)


def _run(
    agent: Runnable,
    messages: list[BaseMessage],
    config: RunnableConfig | None,
    on_event: StepListener | None,
    available: frozenset[str],
) -> dict[str, Any]:
    """Drive the agent, announcing what happens, and return what `invoke` would have returned.

    With no listener this IS `agent.invoke`. With one, the same work runs through `stream` with
    two modes:

    - `values` yields the whole state after each superstep, so keeping the last one gives the
      exact dict `invoke` returns — sentinels included. That is the trick that lets the parsing
      below `chat_with_agent` stay untouched: watching does not reconstruct the result, it
      observes one that was going to exist anyway.
    - `updates` yields each node's delta, which is where the steps are read from.

    The pair is the same idiom the run loop drives (`runner/_loop.py`), minus `subgraphs` — there
    is no subgraph here.

    Prose is BUFFERED rather than announced immediately. The last thing Quincy says is the reply,
    and the transcript renders that; announcing it live too would show it twice. So a buffered
    line is only released once a further update proves it was not the last — which in a real loop
    is however long the model takes to ask for the next lookup, i.e. imperceptible.
    """
    if on_event is None:
        return agent.invoke({"messages": messages}, config)

    state: dict[str, Any] = {"messages": list(messages)}
    pending: str | None = None
    for mode, data in agent.stream(
        {"messages": messages}, config, stream_mode=["updates", "values"]
    ):
        if mode == "values":
            if isinstance(data, dict):
                state = data
            continue
        if not isinstance(data, dict):
            continue
        for node_state in data.values():
            if not isinstance(node_state, dict):
                continue
            for message in node_state.get("messages", []):
                # Anything new proves the buffered line was not the final word.
                if pending is not None:
                    _notify(on_event, "text", {"text": pending})
                    pending = None
                pending = _announce(on_event, message, available)
    return state


def _announce(on_event: StepListener | None, message: Any, available: frozenset[str]) -> str | None:
    """Report the lookups a message makes, and hand back any prose for buffering.

    Only tools the agent ACTUALLY HAS are reported. A model can ask for anything — and on the
    live instance one asked for `search` and `list_files`, which the chat does not have and never
    ran. Reporting the request produced "checked 2 things" under a reply where nothing had been
    checked: a record claiming work that did not happen, which is the one kind of wrong this
    system is built to refuse. A request is not a read.

    Sentinels are dropped for the same reason `_last_ai_text` drops them: a middleware notice is
    not Quincy speaking, and putting "Model call failed after 3 attempts" on screen in his voice
    is exactly what slice 2 removed. A new surface is a new chance to reintroduce it.
    """
    if getattr(message, "type", "") != "ai":
        return None
    for call in getattr(message, "tool_calls", None) or []:
        if str(call.get("name", "")) not in available:
            continue
        args = call.get("args") or {}
        _notify(
            on_event,
            "step",
            {
                "id": str(call.get("id", "")),
                "kind": str(call.get("name", "")),
                "detail": str(next(iter(args.values()), "")) if args else "",
            },
        )
    text = message_text(message).strip()
    if not text or text.startswith(_BUDGET_SENTINEL) or _TRANSPORT_SENTINEL in text:
        return None
    return text


def chat_with_agent(
    agent: Runnable,
    context: str,
    history: Sequence[dict[str, str]],
    user_message: str,
    config: RunnableConfig | None = None,
    on_event: StepListener | None = None,
    available: Iterable[str] = (),
) -> ChatOutcome:
    """One conversational turn, with the agent free to look things up before it answers.

    Proposals are parsed from the FINAL message only. `_last_ai_text` skips both middleware
    sentinels and returns the last real AI message, so a tool step can never be read as a
    proposal — and a tool RESULT that happens to contain a fenced array is not an AI message at
    all, so it is never a candidate either.

    When nothing usable comes back, `fallback_reason` says which of the three causes it was. The
    budget case is the one this loop makes reachable for the first time: the middleware ends the
    turn at the bound and leaves a sentinel, `_last_ai_text` refuses to return it, and the caller
    gets `budget_exhausted` instead of a confident answer built on half an investigation.

    ``available`` is the names of the tools this agent actually holds; only those are announced.
    A model can request anything, and a request that reaches no tool is not a lookup.

    ``on_event`` watches the turn happen. It changes WHEN the caller learns things, never WHAT is
    parsed: the proposal still comes from the final message alone, after the loop has finished.
    A listener that raises is a listener's problem — watching must never break the turn.
    """
    messages: list[BaseMessage] = [HumanMessage(content=context)]
    messages.extend(replay(history))
    messages.append(HumanMessage(content=user_message))

    result = _run(agent, messages, config, on_event, frozenset(available or ()))
    raw = _last_ai_text(result).strip()
    if not raw:
        return ChatOutcome("", [], None, None, fallback_reason(result))

    changeset, visible = _extract_changeset(raw)
    charter = _extract_charter(raw)
    clarification = _extract_clarify(raw)
    reply = _CLARIFY_BLOCK.sub("", _CHARTER_BLOCK.sub("", visible)).strip()
    if not reply:
        # Same rule as the single-call path: a turn carrying only a proposal is an ANSWER, and the
        # card holds the content. A turn carrying nothing at all is not.
        reply = "Here's what I'd suggest." if (changeset or charter or clarification) else ""
    if not reply and not changeset and not charter and not clarification:
        return ChatOutcome("", [], None, None, fallback_reason(result))
    return ChatOutcome(reply, changeset, charter, clarification, "")
