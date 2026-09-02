"""Stream agent reasoning-per-turn to the run's SSE.

A ``BaseCallbackHandler`` sibling to ``cost.UsageCallback``: it sees every nested
model message (PM / coder / reviewer), attributes it to the owning graph node (the
same ``_node_from_metadata`` cost accounting uses), and emits the model's THINKING
for that turn — its narration plus any reasoning/CoT blocks. One block per model
turn (message-granularity), never a token firehose. Best-effort: a malformed result
never breaks a run.

Lives in the API layer because it bridges ``mosaera_agents`` (message parsing) and the
runner's ``_emit`` — the same reason the runner, not ``core``, owns the SSE.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from mosaera_agents.messages import reasoning_of
from mosaera_core.cost import _node_from_metadata


class ReasoningCallback(BaseCallbackHandler):
    """Emit each model turn's reasoning via ``emit(node, text)``.

    ``emit`` is the runner's thought sink (``_emit_thought``); ``node`` is the owning
    graph node (implement / review / plan) or None. Attach alongside the usage
    callback on the run's LangGraph config so LangGraph propagates it to every nested
    model call — including the reviewer, whose ``review_change`` threads that config."""

    def __init__(self, emit: Callable[[str | None, str], None]) -> None:
        self._emit = emit
        self._node: dict[Any, str] = {}
        self._lock = threading.Lock()

    def _remember(self, run_id: Any, metadata: Any) -> None:
        node = _node_from_metadata(metadata)
        if node and run_id is not None:
            with self._lock:
                self._node[run_id] = node

    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self._remember(kwargs.get("run_id"), kwargs.get("metadata"))

    def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        self._remember(kwargs.get("run_id"), kwargs.get("metadata"))

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            with self._lock:
                node = self._node.pop(kwargs.get("run_id"), None)
            for batch in response.generations:
                for gen in batch:
                    message = getattr(gen, "message", None)
                    if message is None:
                        continue
                    text = reasoning_of(message)
                    if text:
                        self._emit(node, text)
        except Exception:  # noqa: S110 — telemetry must never break a run
            pass
