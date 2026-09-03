"""The held-out critic node (#60/#61, ADR-0065 + amendment) — split from nodes_review.py
when the god-file ratchet fired (501 lines): a cohesive unit — the Judge's evidence prep, the
claims-protocol vs legacy routing, and the deterministic disposal call. The gate seam is
unchanged (`outcome_verdict` → gate_node)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from mosaera_core.claim_oracles import evaluate_claims
from mosaera_core.critic_policy import dispose
from mosaera_core.faithfulness import authored_suite_overstrict_findings
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState


def _overstrict_evidence(ctx: RunContext, state: RunState) -> str:
    """The deterministic #57 over-strictness findings (if any), as compact context for the
    Judge — a hint about the authored tests, never a defect in the delivered code. Best-effort:
    absent tester / a parse fault yields "" (the Judge simply gets no hint)."""
    authored = list(state.get("authored_tests") or [])
    if not authored:
        return ""
    try:
        spec = f"{state.get('task', '')}\n{state.get('plan', '')}"
        findings = authored_suite_overstrict_findings(ctx.workspace, authored, spec)
    except Exception:
        return ""
    lines = [f"- {f.file}:{f.line} [{f.kind}] {f.snippet}" for f in findings[:12]]
    return "\n".join(lines)


def critic_node(ctx: RunContext, state: RunState, config: RunnableConfig) -> dict[str, Any]:
    """The held-out critic (#60, ADR-0065): a veto-only, once-per-delivery judge of the delivered
    OUTCOME, wired between review and the gate. Runs ONLY on a green run (deny-by-default: a
    failing/None run already parks and has no delivered-passing code to judge) and ONLY when the
    critic is genuinely HELD OUT (a different model from the coder — else it shares the coder's
    blind spots and is no independent check). Memoized by tree hash so it costs at most one model
    call per distinct delivered tree — off the iteration loop, exactly like the mutation/coverage
    checks (nodes_impl). Any fault degrades to None (no verdict → no veto), never a park: the
    critic can only ever REMOVE a ship, so a blank critic simply doesn't act. Its verdict rides
    `outcome_verdict` into gate_node, which turns a confident VETO into the `critic_vetoed` gate
    reason (a universal downgrade)."""
    if state.get("tests_passed") is not True or not ctx.settings.held_out_ok():
        return {}
    key = ("critic", ctx.workspace.tree_hash())
    if key in ctx.evidence_memo:
        return {"outcome_verdict": ctx.evidence_memo[key]}
    # Read the knob OUTSIDE the fault guard: a config fault is a bug, not a judge fault to
    # silently degrade on (the liveness lesson — a control that can't fire must fail loud).
    claim_protocol = bool(getattr(ctx.settings, "critic_claim_protocol", False))
    try:
        diff = ctx.workspace.diff_all()
        if claim_protocol:
            # #61 claims protocol: the agent proposes per-claim rows with verbatim quotes;
            # critic_policy verifies the quotes DETERMINISTICALLY and disposes — a REFUTED row
            # whose requirement/evidence quote doesn't literally occur in the requirements/the
            # delivered text convicts nobody (the measured over-veto source is persona drift,
            # and drifted vetoes can't quote real text). The gate seam is byte-identical:
            # only `vetoed` reaches evaluate_gate.
            claims = [c for c in (state.get("claims") or []) if isinstance(c, dict)]
            judged = ctx.agents.critic(
                state["task"],
                state.get("plan", ""),
                diff,
                state.get("test_output", ""),
                _overstrict_evidence(ctx, state),
                config,
                claims=claims,
            )
            # Jurisdiction input (#61 fix round): the same deterministic per-claim verdicts the
            # gate will use — computed here too (pure AST/flags, cheap) so the critic's
            # authority is confined to the residual determinism can't cover.
            dispositions = evaluate_claims(claims, ctx.workspace, dict(state))
            verdict = dispose(
                judged,
                claims,
                state["task"],
                diff,
                state.get("test_output", ""),
                dispositions=dispositions,
            )
        else:
            verdict = ctx.agents.critic(
                state["task"],
                state.get("plan", ""),
                diff,
                state.get("test_output", ""),
                _overstrict_evidence(ctx, state),
                config,
            )
    except Exception:
        # A judge FAULT (model error, malformed tree) is inconclusive → no veto this pass, never a
        # crash that discards a deliverable diff (mirrors the mutation-check's try/except, #52). But
        # do NOT memoize the fault (red-team #60): caching None would let a single transient blip
        # PERMANENTLY suppress a veto the recovered critic would raise on a re-delivery of the SAME
        # tree (a looping coder produces an identical tree_hash). Only a COMPLETED judgement is
        # cached; a fault leaves the memo empty so the next pass over this tree retries.
        return {"outcome_verdict": None}
    ctx.evidence_memo[key] = verdict
    return {"outcome_verdict": verdict}
