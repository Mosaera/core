"""Reason-before-park (ADR-0017) + the reasoning-escalation ladder (ADR-0018).

Extracted from ``nodes_impl`` (the implement-loop nodes) so that module stays under the god-file
ceiling. A no-progress trip diverts here instead of parking: pass 0 has the coder's own model
rethink; a later configured tier has a one-off, tool-less stronger reasoner diagnose the stuck
point and hand the cheap coder a plan.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from mosaera_core.config import RoleModel
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState
from mosaera_core.models import cloud_tier_allowed


def _reason_tier(ctx: RunContext, attempts: int) -> RoleModel | None:
    # The reasoning-ladder tier for this reason pass (ADR-0018). Pass 0 (attempts==0 on
    # entry) is the own-model pass (ADR-0017) → None. Passes 1..N map to reason_escalation
    # [attempts-1]. A CLOUD tier is used only when off-box egress is consented AND the model
    # is priced (ADR-0024); otherwise it's dropped (returns None) and the own-model pass
    # covers it — so nothing auto-egresses off-box without consent + a USD-cap-able price.
    idx = attempts - 1
    ladder = ctx.settings.reason_escalation
    if idx < 0 or idx >= len(ladder):
        return None
    tier = ladder[idx]
    return tier if cloud_tier_allowed(ctx.settings, tier.provider, tier.model) else None


def reason_node(ctx: RunContext, state: RunState, config: RunnableConfig) -> dict[str, Any]:
    # Reason-before-park (ADR-0017) + reasoning-escalation ladder (ADR-0018). A no-progress
    # trip diverts here instead of parking. Pass 0 = the coder's OWN model rethinks (ADR-0017).
    # Pass k≥1 (a configured local reason_escalation tier) = a one-off, tool-less STRONGER
    # reasoner diagnoses the stuck point and its plan is injected for the cheap coder to
    # execute. RESET the tripped kind's streak (fresh start); bump reason_attempts (bounds
    # the climb via max_reason); clear needs_reason; increment `iteration` (shares max_iter).
    # Re-enters implement; a 'SUMMARY: escalate' the coder emits still routes to the supervisor.
    signal = state.get("needs_reason") or {}
    kind = str(signal.get("kind", "test"))
    text = str(signal.get("text", ""))
    attempts = state.get("reason_attempts", 0)  # tier index on entry
    by_kind = dict(state.get("stall_by_kind") or {})
    by_kind[kind] = ["", 0]  # forget this loop's history → a different attempt gets a fair run

    tier = _reason_tier(ctx, attempts)
    plan_text = ctx.agents.diagnose(ctx.settings, state, kind, text, tier, config) if tier else ""
    reason = signal.get("reason", "")
    if tier is not None and plan_text:  # a reasoner tier produced a plan → hand it down
        packet = ctx.agents.reasoned_plan_instruction(plan_text, kind, text)
        note = f"reason-escalation ({kind}) via {tier.provider}/{tier.model}: {reason}"
    else:  # pass 0, exhausted/non-local ladder, or an empty/failed reasoner → own-model
        packet = ctx.agents.reason_instruction(kind, text)
        summary = state.get("coder_summary", "").strip()
        if summary:
            packet += f"\n\nYour last report:\n{summary}"
        via = f" ({tier.provider}/{tier.model} returned nothing)" if tier is not None else ""
        note = f"reason-and-change-approach ({kind}){via}: {reason}"
    # Honest-stop (#56): a reason pass earns a fresh non-improving STREAK, but the best-so-far
    # count survives — a "different approach" must still beat the best ever seen this episode
    # (it can't change the test population, so the bar stands).
    track = dict(state.get("progress_track") or {})
    track["streak"] = 0
    return {
        "iteration": state.get("iteration", 0) + 1,
        "reason_attempts": attempts + 1,
        "stall_by_kind": by_kind,
        "progress_track": track,
        "needs_reason": {},  # consumed
        "feedback": [note],  # reducer-append trail for the evidence log
        "messages": [HumanMessage(content=packet)],
    }
