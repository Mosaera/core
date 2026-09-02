"""Reviewer agent: critiques the diff and test results."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool
from mosaera_core.verdict import ReviewerVerdict, parse_reviewer_verdict

from mosaera_agents.messages import reasoning_of
from mosaera_agents.prompts import REVIEWER_SYSTEM
from mosaera_agents.retry import is_transient_model_error

_MAX_DIFF_CHARS = 12_000
_MAX_TEST_CHARS = 4_000
_MAX_SCAN_CHARS = 4_000


# The re-ask reply is a single constrained verdict line, so a bare keyword scan (no
# required VERDICT prefix) is safe HERE — unlike the authoritative parser above, which
# stays VERDICT-anchored so it never catches a verdict word buried in review prose.
_LENIENT_VERDICT_RE = re.compile(
    r"\b(APPROVED?|REQUEST[\s_\-]*CHANGES|BLOCK(?:ED)?)\b", re.IGNORECASE
)

_CANON_VERDICT_LINE = {
    "APPROVE": "VERDICT: APPROVE",
    "REQUEST_CHANGES": "VERDICT: REQUEST CHANGES",
    "BLOCK": "VERDICT: BLOCK",
}

_VERDICT_REASK = (
    "Your review above did not end with a parseable verdict line. Based ONLY on the "
    "review you just wrote, reply with EXACTLY ONE line and nothing else — the single "
    "verdict that matches it:\n"
    "VERDICT: APPROVE\n"
    "VERDICT: REQUEST CHANGES\n"
    "VERDICT: BLOCK\n\n"
    "Review:\n{review}"
)


def _lenient_verdict(text: str) -> ReviewerVerdict:
    """Keyword-scan a short, constrained verdict reply (no VERDICT anchor needed)."""
    found: set[ReviewerVerdict] = set()
    for match in _LENIENT_VERDICT_RE.finditer(text):
        token = re.sub(r"[\s\-]+", "_", match.group(1).upper())
        if token.startswith("APPROVE"):
            found.add("APPROVE")
        elif token.startswith("REQUEST"):
            found.add("REQUEST_CHANGES")
        elif token.startswith("BLOCK"):
            found.add("BLOCK")
    return found.pop() if len(found) == 1 else "UNKNOWN"


def clarify_verdict(model: BaseChatModel, review: str, config: RunnableConfig | None = None) -> str:
    """Recover a verdict when a NON-EMPTY review lacked a parseable ``VERDICT:`` line.

    A common local-model flake: the reviewer reasons and concludes but drops or
    reformats the required verdict line, so ``parse_reviewer_verdict`` returns
    ``UNKNOWN`` and the run FALSE-PARKS correct, passing work. One bounded, direct
    model call (NOT the tool agent — cheap, no re-review) asks the model to commit to
    a single verdict based on its OWN review. Returns a canonical ``VERDICT: X`` line
    to append to the review, or "" when still unrecoverable.

    Never guesses APPROVE (a blank/ambiguous reply → ""), never overrides a review
    that already parsed (the caller only invokes this on UNKNOWN), and does not widen
    what can ship — the independent validation/tester gate still applies, so a
    recovered APPROVE cannot deliver failing code.
    """
    if not review.strip():
        return ""
    prompt = _VERDICT_REASK.format(review=review[:_MAX_DIFF_CHARS])
    try:
        response = model.invoke([HumanMessage(content=prompt)], config)
    except Exception:
        return ""
    # Read both channels — the re-ask answer, like the review itself, may land in the
    # reasoning channel with empty content on a reasoning model.
    return _CANON_VERDICT_LINE.get(_lenient_verdict(reasoning_of(response)), "")


def build_reviewer_agent(
    model: BaseChatModel, tools: Sequence[BaseTool], step_limit: int = 15
) -> Runnable:
    """Build the Reviewer as a compiled agent graph (read-only tools).

    ``tools`` must already be scoped to the read-only allowlist (list_files,
    read_file, search) — this factory does not widen permissions. Mirrors
    ``build_coder_agent`` so the reviewer can verify the change against the
    actual repository, not just the diff.

    Reliability middleware (like the coder): ``ModelCallLimitMiddleware`` bounds
    the read-tool loop so a degenerate reviewer STOPS and returns instead of
    burning to the graph recursion limit; ``ModelRetryMiddleware`` retries a
    transient Ollama error and, on persistent failure, ends with partial output
    (→ "" → UNKNOWN at the gate → parks) rather than hard-erroring the run.
    """
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(
            max_retries=2, retry_on=is_transient_model_error, on_failure="continue"
        ),
        ModelCallLimitMiddleware(run_limit=step_limit, exit_behavior="end"),
    ]
    return create_agent(
        model=model, tools=list(tools), system_prompt=REVIEWER_SYSTEM, middleware=middleware
    )


def review_change(
    agent: Runnable,
    task: str,
    plan: str,
    diff: str,
    test_output: str,
    scan_findings: str = "",
    design: str = "",
    foresight: str = "",
    quality: str = "",
    config: RunnableConfig | None = None,
) -> str:
    """Review a proposed change; returns 'VERDICT: ...' plus notes.

    ``agent`` is a compiled reviewer agent (``build_reviewer_agent``). It is
    invoked with a FRESH message context — never the coder's shared transcript —
    so the reviewer reasons only about this review. ``config`` threads the run's
    stream writer so the reviewer's read tools surface as activity milestones.
    An unparseable/empty review yields "" → UNKNOWN at the gate, never APPROVE.
    """
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + "\n... (diff truncated)"
    if len(test_output) > _MAX_TEST_CHARS:
        test_output = test_output[:_MAX_TEST_CHARS] + "\n... (test output truncated)"
    if len(scan_findings) > _MAX_SCAN_CHARS:
        scan_findings = scan_findings[:_MAX_SCAN_CHARS] + "\n... (findings truncated)"
    design_section = f"## Design\n{design}\n\n" if design.strip() else ""
    foresight_section = (
        f"## Anticipated risks — confirm each CHECK holds\n{foresight}\n\n"
        if foresight.strip()
        else ""
    )
    quality_section = (
        f"## Machine-computed code quality on the changed files (ground truth)\n{quality}\n\n"
        if quality.strip()
        else ""
    )
    body = (
        f"## Task\n{task}\n\n## Plan\n{plan}\n\n"
        f"{design_section}{foresight_section}{quality_section}"
        f"## Diff\n```diff\n{diff or '(empty diff)'}\n```\n\n"
        f"## Test output\n```\n{test_output or '(no test output)'}\n```\n\n"
        f"## Security scan findings\n{scan_findings or 'No security findings.'}"
    )
    result: dict[str, Any] = agent.invoke({"messages": [HumanMessage(content=body)]}, config)
    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    # Read BOTH channels. Reasoning models (gpt-oss:20b) frequently leave `content`
    # EMPTY and put the whole review — including its VERDICT line — in the reasoning
    # channel; the old content-only read returned "" for those, which parsed to UNKNOWN
    # and FALSE-PARKED correct work (~75% of MCB-21 runs, all with the code delivered
    # correctly). `reasoning_of` returns reasoning + narration, so it captures whichever
    # channel the model used. Prefer the last message that carries a parseable verdict;
    # otherwise return the last non-empty text so clarify_verdict has real analysis to
    # work from rather than "".
    for message in reversed(ai_messages):
        full = reasoning_of(message).strip()
        if full and parse_reviewer_verdict(full) != "UNKNOWN":
            return full
    for message in reversed(ai_messages):
        full = reasoning_of(message).strip()
        if full:
            return full
    return ""
