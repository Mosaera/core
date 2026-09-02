"""Critic agent (the Judge): a held-out, veto-only judge of the delivered OUTCOME.

Built exactly like the reviewer (a bounded read-only tool loop) — but it is a DIFFERENT
role with its own held-out model binding, it runs ONCE per delivery (not per-iteration), and
its verdict is VETO-only: it can only DOWNGRADE a ship to a park at the gate, never create a
delivery. It judges whether the delivered code meets the spec, INDEPENDENT of whether the
tests are green (a suite can pass for the wrong reason). See docs/adr/ADR-0065.
"""

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

from mosaera_agents.messages import reasoning_of
from mosaera_agents.personas import load_persona
from mosaera_agents.retry import is_transient_model_error

_MAX_DIFF_CHARS = 12_000
_MAX_TEST_CHARS = 4_000
_MAX_OVERSTRICT_CHARS = 2_000

# Authoritative verdict parse: VERDICT-anchored (start of a line) so a "veto"/"ship" word
# buried in the notes can never be read as the verdict. A confident VETO is the ONLY thing
# that downgrades — anything else (SHIP, unparseable, empty) leaves the run alone.
_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(SHIP|VETO)\b", re.IGNORECASE | re.MULTILINE)

# Fenced code blocks are where a reasoning model most often ECHOES untrusted input (the diff,
# quoted source, test output) into its answer — and an echoed ``VERDICT:`` line there would be
# read as authoritative (red-team #60, MED). Strip fences before scanning so a planted verdict
# token inside a quoted block can neither force a park (DoS) nor suppress a genuine veto.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


# Claims-protocol line parse (#61): line-anchored like _VERDICT_RE, scanned AFTER fence
# stripping — the same echo-injection defenses. Quotes are captured verbatim; the DETERMINISTIC
# verification of those quotes (do they literally occur in the requirements / the diff?) lives
# in core (`mosaera_core.critic_policy`) — the agent package only ever parses, never disposes.
_CLAIM_LINE_RE = re.compile(
    r"^\s*CLAIM\s+([A-Za-z0-9_.-]+)\s*:\s*"
    r"(REFUTED|SUPPORTED|INSUFFICIENT_EVIDENCE)\s*\|\s*"
    r'REQUIREMENT:\s*"([^"]*)"\s*\|\s*EVIDENCE:\s*"([^"]*)"',
    re.IGNORECASE | re.MULTILINE,
)


def build_critic_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    step_limit: int = 12,
    persona: str = "critic",
) -> Runnable:
    """Build the Critic as a compiled agent graph (read-only tools).

    ``tools`` must already be scoped to the critic's read-only allowlist (list_files,
    read_file, search) — this factory does not widen permissions. Mirrors
    ``build_reviewer_agent`` so the Judge can verify the delivered code against the actual
    repository, not just the diff. Reliability middleware is identical: a bounded read loop
    (``ModelCallLimitMiddleware``) so a degenerate Judge STOPS and returns, and a transient-
    error retry (``ModelRetryMiddleware``) that ends with partial output rather than crashing
    the run — a fault yields "" → no verdict → never a veto (deny-by-default: it can only
    ever REMOVE a ship, so a blank critic simply doesn't act)."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(
            max_retries=2, retry_on=is_transient_model_error, on_failure="continue"
        ),
        ModelCallLimitMiddleware(run_limit=step_limit, exit_behavior="end"),
    ]
    return create_agent(
        model=model, tools=list(tools), system_prompt=load_persona(persona), middleware=middleware
    )


def critic_verdict(text: str) -> dict[str, Any] | None:
    """Parse the Judge's reply into ``{"vetoed": bool, "reason": str}`` — or None when there
    is no confident verdict.

    Hardened against ECHO-INJECTION (red-team #60, MED): a reasoning model restates untrusted
    input (the diff, quoted source, test output) in its answer, so a ``VERDICT:`` line planted in
    that input could be misread as the model's verdict. Two defenses, mirroring the reviewer's
    ``parse_reviewer_verdict`` (which solved the same class, ADR-0034): (1) STRIP fenced code
    blocks — the most common echo vector — before scanning; (2) collect ALL distinct anchored
    verdicts and only act on an UNAMBIGUOUS one. A conflict (both SHIP and VETO present — a genuine
    verdict next to an echoed/injected opposite) or no verdict at all → None, i.e. NO veto:
    deny-by-default in the SAFE direction (uncertainty never vetoes, per the persona's "when
    unsure, SHIP"). This kills the false-VETO DoS (a planted VETO can't force a park) and bounds
    the suppression direction to the pre-critic baseline (a planted SHIP that masks a real veto is
    no worse than having no critic — the veto-only + downgrade-only design guarantees no new ship).

    The gate parks ONLY on ``vetoed is True``, so SHIP / None / conflict can never create OR block
    a delivery beyond what the rest of the evidence already decided."""
    if not text or not text.strip():
        return None
    scanned = _FENCE_RE.sub("", text)
    matches = list(_VERDICT_RE.finditer(scanned))
    verdicts = {m.group(1).upper() for m in matches}
    if verdicts == {"VETO"}:
        # Reason = the notes after the (first) verdict line (what the human at the park reads).
        reason = scanned[matches[0].end() :].strip()[:500] or scanned.strip()[:500]
        return {"vetoed": True, "reason": reason}
    if verdicts == {"SHIP"}:
        return {"vetoed": False, "reason": scanned.strip()[:500]}
    # {} (no verdict) or {SHIP, VETO} (conflict) → no confident verdict → no veto.
    return None


def critic_claim_rows(text: str) -> list[dict[str, Any]]:
    """Parse per-claim protocol lines into rows — parse only, never dispose (#61).

    Fence-stripped first (the echo vector); duplicate claim ids keep the LAST line (a model
    that revises itself is judged on its final word, matching critic_verdict's reversed scan).
    """
    if not text or not text.strip():
        return []
    scanned = _FENCE_RE.sub("", text)
    rows: dict[str, dict[str, Any]] = {}
    for m in _CLAIM_LINE_RE.finditer(scanned):
        rows[m.group(1)] = {
            "claim_id": m.group(1),
            "verdict": m.group(2).upper(),
            "requirement_quote": m.group(3).strip()[:500],
            "evidence_quote": m.group(4).strip()[:500],
        }
    return list(rows.values())


def judge_outcome(
    agent: Runnable,
    task: str,
    plan: str,
    diff: str,
    test_output: str,
    overstrict: str = "",
    config: RunnableConfig | None = None,
) -> dict[str, Any] | None:
    """Judge the delivered change against the spec; returns the parsed verdict or None.

    ``agent`` is a compiled critic agent (``build_critic_agent``), invoked with a FRESH
    message context — never a shared transcript — so the Judge reasons only about this
    delivery. ``overstrict`` is the deterministic #57 over-strictness findings (context for
    the Judge's read of the code, not a defect in it). An unparseable/empty judgement yields
    None → no verdict → no veto (the run ships or parks on its other evidence unchanged)."""
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + "\n... (diff truncated)"
    if len(test_output) > _MAX_TEST_CHARS:
        test_output = test_output[:_MAX_TEST_CHARS] + "\n... (test output truncated)"
    if len(overstrict) > _MAX_OVERSTRICT_CHARS:
        overstrict = overstrict[:_MAX_OVERSTRICT_CHARS] + "\n... (truncated)"
    overstrict_section = (
        f"## Authored-test assertions a detector flagged as possibly over-strict\n"
        f"(context for judging the code — NOT a defect in the code)\n{overstrict}\n\n"
        if overstrict.strip()
        else ""
    )
    body = (
        f"## Task\n{task}\n\n## Plan\n{plan}\n\n"
        f"## Diff (what was delivered)\n```diff\n{diff or '(empty diff)'}\n```\n\n"
        f"## Test output\n```\n{test_output or '(no test output)'}\n```\n\n"
        f"{overstrict_section}"
        "Judge the delivered code against the Task. VETO only with a specific unmet "
        "requirement; when unsure, SHIP."
    )
    result: dict[str, Any] = agent.invoke({"messages": [HumanMessage(content=body)]}, config)
    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    # Read BOTH channels (reasoning models like gpt-oss:20b often leave `content` empty and put
    # the whole judgement — verdict line included — in the reasoning channel). Prefer the last
    # message that carries a parseable verdict; else return None (no verdict → no veto).
    for message in reversed(ai_messages):
        full = reasoning_of(message).strip()
        verdict = critic_verdict(full)
        if verdict is not None:
            return verdict
    return None


def judge_outcome_claims(
    agent: Runnable,
    task: str,
    plan: str,
    diff: str,
    test_output: str,
    claims: list[dict[str, Any]],
    overstrict: str = "",
    config: RunnableConfig | None = None,
) -> dict[str, Any] | None:
    """The claims-protocol judgement (#61): per-claim rows, agent-parsed but NEVER disposed
    here — `mosaera_core.critic_policy` verifies the quotes deterministically and decides the
    veto. Returns ``{"rows": [...], "fallback": <legacy verdict or None>}``; the legacy
    fallback fires only when the model ignored the claim format entirely, so a
    format-noncompliant model degrades to today's behaviour, never to silence."""
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + "\n... (diff truncated)"
    if len(test_output) > _MAX_TEST_CHARS:
        test_output = test_output[:_MAX_TEST_CHARS] + "\n... (test output truncated)"
    if len(overstrict) > _MAX_OVERSTRICT_CHARS:
        overstrict = overstrict[:_MAX_OVERSTRICT_CHARS] + "\n... (truncated)"
    material = [c for c in claims if isinstance(c, dict) and c.get("material", True)]
    claim_lines = (
        "\n".join(f"- CLAIM {c.get('id', '?')}: {str(c.get('text', ''))[:300]}" for c in material)
        or "- CLAIM task: the delivered code meets every concrete requirement in the Task."
    )
    overstrict_section = (
        f"## Authored-test assertions a detector flagged as possibly over-strict\n"
        f"(context for judging the code — NOT a defect in the code)\n{overstrict}\n\n"
        if overstrict.strip()
        else ""
    )
    body = (
        f"## Task\n{task}\n\n## Plan\n{plan}\n\n"
        f"## Diff (what was delivered)\n```diff\n{diff or '(empty diff)'}\n```\n\n"
        f"## Test output\n```\n{test_output or '(no test output)'}\n```\n\n"
        f"{overstrict_section}"
        f"## Acceptance claims to judge\n{claim_lines}\n\n"
        "Output one CLAIM line per claim above, exactly in the required format. "
        "REFUTED requires verbatim quotes; INSUFFICIENT_EVIDENCE is the honest default."
    )
    result: dict[str, Any] = agent.invoke({"messages": [HumanMessage(content=body)]}, config)
    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    for message in reversed(ai_messages):
        full = reasoning_of(message).strip()
        rows = critic_claim_rows(full)
        if rows:
            return {"rows": rows, "fallback": None}
        legacy = critic_verdict(full)
        if legacy is not None:
            return {"rows": [], "fallback": legacy}
    return None
