"""Transient model/transport error handling shared across the agents.

Ollama surfaces a truncated tool-call or a network hiccup as a
``ResponseError(status_code=-1)`` / ``httpx`` transport error. We classify these
by exception NAME and message markers so this package needs no dependency on
``ollama``/``httpx``. Agents built with ``create_agent`` use
``ModelRetryMiddleware(retry_on=is_transient_model_error)``; the PM's raw
``model.invoke`` calls (plan/chat/decompose/synthesize) use ``robust_invoke``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from mosaera_agents.messages import message_text

_TRANSIENT_EXC_NAMES = frozenset(
    {"ResponseError", "ConnectError", "ReadTimeout", "ReadError", "RemoteProtocolError"}
)
_TRANSIENT_MARKERS = ("unexpected eof", "status code: -1", "connection reset")


def _is_empty_response(response: Any) -> bool:
    """A "successful" model reply that carries nothing — no text content AND no tool
    calls. Local models (measured: gpt-oss:20b on the second consecutive long call,
    #53/#54 validation drive) intermittently return exactly this; to a raw text
    caller it is as useless as a transport error, so it retries the same way. The
    ``tool_calls`` guard keeps a legit tool-call-only reply from ever being retried."""
    if message_text(response).strip():
        return False
    return not getattr(response, "tool_calls", None)


def is_transient_model_error(exc: Exception) -> bool:
    """Whether a model-call failure is a transient hiccup worth retrying
    (vs. a real bug, which should surface)."""
    if type(exc).__name__ in _TRANSIENT_EXC_NAMES:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def robust_invoke(
    model: BaseChatModel,
    messages: Sequence[BaseMessage],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    config: RunnableConfig | None = None,
) -> Any:
    """``model.invoke`` with bounded exponential-backoff retry on transient errors.

    For raw invokes that aren't wrapped by an agent's ``ModelRetryMiddleware`` —
    a transient Ollama blip during planning/decomposition/PM chat should not
    hard-fail the whole run. Non-transient exceptions (real bugs) re-raise
    immediately; a persistent transient re-raises after ``attempts``.

    ``config`` (optional) is passed straight to ``model.invoke`` — thread the graph's
    RunnableConfig for a call made INSIDE a node so its tokens are metered by the run's
    ``UsageCallback`` and attributed to that node (``config=None`` is the same no-op as
    before, so existing callers are unaffected).

    An EMPTY successful reply (no text, no tool calls) retries on the same backoff
    schedule: local models intermittently return nothing at all (the #53/#54 live-drive
    finding — decompose silently collapsed to its single-item fallback). A persistent
    empty is RETURNED after ``attempts``, never raised — every caller's existing
    empty-handling fallback keeps working; it just gets the empty after real tries.
    """
    response: Any = None
    for i in range(attempts):
        try:
            response = model.invoke(list(messages), config=config)
        except Exception as exc:
            if i == attempts - 1 or not is_transient_model_error(exc):
                raise
            sleep(base_delay * (2**i))
            continue
        if i == attempts - 1 or not _is_empty_response(response):
            return response
        sleep(base_delay * (2**i))
    return response
