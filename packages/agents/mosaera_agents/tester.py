"""Tester agent: authors the acceptance tests from the spec (test-first, strict).

Built like the reviewer (a bounded read-tool loop) but with a write_file scoped to
``tests/`` (see mosaera_core.tools.repo build_repo_tools write_prefix) so it can only
create test files — never source. The Coder must pass these tests and may not edit them
(protected_paths). This is the separation of duties that removes the coder's ability to
author its own success bar (ADR-0013).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from mosaera_agents.coder import StandingCorrections
from mosaera_agents.personas import load_persona
from mosaera_agents.retry import is_transient_model_error


def build_tester_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    step_limit: int = 15,
    test_file_cap: int = 0,
) -> Runnable:
    """Build the Tester as a compiled agent graph.

    ``tools`` must already be scoped to the ``tester`` allowlist AND built with
    ``write_prefix='tests/'`` — this factory does not widen permissions. Reliability
    middleware mirrors the reviewer: ``ModelCallLimitMiddleware`` bounds the loop so a
    degenerate tester STOPS with partial work; ``ModelRetryMiddleware`` retries a
    transient error and, on persistent failure, ends with partial output.

    ``test_file_cap`` (>0) bounds the RED-HUNT (#51, ADR-0056): on an already-satisfied task the
    tester otherwise writes ~a dozen files chasing a red it can never obtain.
    ``ToolCallLimitMiddleware`` on ``write_file`` blocks further writes past the cap with
    ``exit_behavior='continue'`` (NOT ``'end'``, which raises on a parallel/batched tool call) so
    the model then winds the loop down normally.
    """
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        # The Proctor needs standing corrections MORE than the coder does, not less: every
        # `author_tests` / `validate_and_repair_tests` call starts a FRESH conversation
        # (agents_bridge builds `{"messages": [HumanMessage(...)]}` each time), so a correction
        # given during authoring is discarded wholesale at the invocation boundary — it cannot
        # survive by any amount of context budget. Observed live 2026-08-06: told at one gate
        # never to turn an assertion into a vacuous pass, it deleted three real tests for
        # `assertTrue(True)` in the next invocation. This is the agent that owns the acceptance
        # oracle, so a lost correction here is how an oracle stops being able to fail.
        # The caller MUST thread `corrections` in and the delta back out (see agents_bridge).
        StandingCorrections(),
        ModelRetryMiddleware(
            max_retries=2, retry_on=is_transient_model_error, on_failure="continue"
        ),
        ModelCallLimitMiddleware(run_limit=step_limit, exit_behavior="end"),
    ]
    if test_file_cap > 0:
        middleware.insert(
            0,
            ToolCallLimitMiddleware(
                tool_name="write_file", run_limit=test_file_cap, exit_behavior="continue"
            ),
        )
    return create_agent(
        model=model, tools=list(tools), system_prompt=load_persona("tester"), middleware=middleware
    )
