"""Graph wiring: build_graph assembles the LangGraph StateGraph bound to one workspace
clone, plus the reason_diagnose shim kept here for unit-test import."""

from __future__ import annotations

import functools
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from mosaera_memory import MemoryStore

from mosaera_core.agents_bridge import ModelFactory, build_default_team
from mosaera_core.config import RoleModel, Settings
from mosaera_core.graph.context import RunContext, TeamFactory
from mosaera_core.graph.nodes_critic import critic_node
from mosaera_core.graph.nodes_deliver import deliver_node
from mosaera_core.graph.nodes_impl import (
    fix_node,
    hygiene_fix_node,
    hygiene_node,
    route_after_hygiene,
    route_after_test,
    test_node,
)
from mosaera_core.graph.nodes_plan import (
    author_tests_node,
    capture_node,
    design_node,
    plan_node,
    route_after_capture,
    route_after_plan,
    route_after_supervise,
    supervise_node,
)
from mosaera_core.graph.nodes_reason import reason_node
from mosaera_core.graph.nodes_review import (
    gate_node,
    quality_revise_node,
    review_fix_node,
    review_node,
    route_after_gate,
    route_after_review,
    scan_node,
)
from mosaera_core.graph.state import RunState
from mosaera_core.models import get_chat_model
from mosaera_core.sandbox import SandboxWorker
from mosaera_core.tools.repo import Workspace, build_repo_tools
from mosaera_core.tools.scan import Scanner


def reason_diagnose(
    settings: Settings,
    state: Mapping[str, Any],
    kind: str,
    text: str,
    tier: RoleModel,
    config: RunnableConfig | None = None,
    *,
    model_factory: ModelFactory = get_chat_model,
) -> str:
    """Thin shim over `AgentTeam.diagnose` — the reasoner diagnosis (ADR-0018) now lives in
    `mosaera_core.agents_bridge`. Kept here so unit tests can import it from this module
    with an injected `model_factory`; diagnose needs no tools, so we build a toolless team."""
    return build_default_team(settings, [], None, model_factory).diagnose(
        settings, state, kind, text, tier, config
    )


def apply_reliability_sensitivity(settings: Settings) -> Settings:
    """Scale the self-stop budgets by the user-declared ``reliability_sensitivity`` (#51,
    ADR-0056), tuning the thrash↔delivery balance to model strength: ``cautious`` self-stops
    early (a weak model → cheap honest park), ``persistent`` grants more rope (a strong model →
    more delivery attempts). ``balanced`` (and any unknown value) is IDENTITY — today's budgets,
    zero regression.

    Scales WITHIN ``max_iterations_ceiling`` (ADR-0046 ``min(configured, ceiling)``) so a future
    posture composes, and derives from the CURRENT values via ``min``/``max`` so user config still
    shows through at the bound. IDEMPOTENT (every target is a min/max floor/ceiling, not a
    relative step) — safe to apply in both build_graph and recursion_limit_for on raw settings."""
    level = settings.reliability_sensitivity
    if level == "cautious":
        return replace(
            settings,
            max_iterations=max(1, min(settings.max_iterations, 2)),
            max_escalations=0,
            stall_limit=min(settings.stall_limit, 2),
            tester_step_limit=min(settings.tester_step_limit, 8),
            plan_stall_limit=1,
            gate_stall_limit=1,
        )
    if level == "persistent":
        return replace(
            settings,
            max_iterations=min(settings.max_iterations_ceiling, max(settings.max_iterations, 6)),
            max_escalations=max(settings.max_escalations, 2),
            stall_limit=max(settings.stall_limit, 4),
            tester_step_limit=max(settings.tester_step_limit, 20),
            plan_stall_limit=3,
            gate_stall_limit=3,
        )
    return settings


# LangGraph's ``recursion_limit`` caps total super-steps (node executions) in one invoke.
# A run does at most ``max_iterations_ceiling`` self-heal iterations, each traversing roughly
# NODES_PER_ITER graph nodes, atop a fixed plan/design/deliver spine and reason-pass slack — so
# the limit must scale with the CEILING. A fixed constant (the old ``150``) meant raising the
# ceiling knob turned an honest park at the cap into a ``GraphRecursionError`` crash (the M6
# audit finding). Sized off the ceiling, not the per-run cap, so a raised ceiling raises the limit
# with it. The default is 160: ADR-0043 widened the budget to cover the ESCALATION allowance too
# (``ceiling + max_escalations``), so ceiling 12 + 1 escalation = 13 iterations = 160. This comment
# read "the default (ceiling 12) is exactly the previous 150 — no behavior change" until 2026-08-20;
# that was true of the pre-ADR-0043 formula only, and `recursion_limit_for` below is authoritative
# (`docs/audits/adr-corpus-review-2026-08-18.md`).
NODES_PER_ITER = 10
RECURSION_HEADROOM = 30


def recursion_limit_for(settings: Settings) -> int:
    """The LangGraph ``recursion_limit`` sized to the run's WORST-CASE super-steps, so a run
    parks honestly at its caps instead of crashing with a ``GraphRecursionError``. Every
    graph-invoking caller (API, CLI, bench) resolves the limit through here.

    Two budgets drive the step count, and the limit must cover BOTH:
    - the self-heal iteration ceiling (each iteration ≈ ``NODES_PER_ITER`` nodes), and
    - the supervisor escalation budget (``max_escalations``): each re-scope loops back through
      ``plan → … → capture`` — another ``NODES_PER_ITER`` nodes — WITHOUT re-checking the
      iteration cap (that check lives on the test/review path, not the supervise path). Sizing
      the limit off the ceiling ALONE (the earlier M6 fix) still crashed on a high
      ``max_escalations``; folding it in here converts that crash into an honest park."""
    # Size the limit off the SCALED budgets — persistent raises max_escalations, so a limit
    # computed from the raw value would overflow inside build_graph (#51, ADR-0056). Idempotent.
    settings = apply_reliability_sensitivity(settings)
    iters = settings.max_iterations_ceiling + max(0, settings.max_escalations)
    return iters * NODES_PER_ITER + RECURSION_HEADROOM


def build_graph(
    settings: Settings,
    workspace: Workspace,
    sandbox: SandboxWorker,
    run_id: str,
    source: str,
    test_cmd: Sequence[str] | None = None,
    approve_writes: bool = True,
    max_iterations: int | None = None,
    checkpointer: Any = None,
    memory: MemoryStore | None = None,
    scanners: Sequence[Scanner] | None = None,
    scan_sandbox: SandboxWorker | None = None,
    project_brief: str = "",
    project_context: str = "",
    item_id: int | None = None,
    project_id: str | None = None,
    model_factory: ModelFactory = get_chat_model,
    team_factory: TeamFactory = build_default_team,
):
    """Assemble the run graph bound to one workspace clone."""
    # Scale every self-stop budget by the reliability-sensitivity dial (#51, ADR-0056) BEFORE
    # anything reads settings — the tester step-limit is baked into the agents at team_factory
    # below, and stall_limit is read live off ctx.settings. Idempotent; balanced = no-op.
    settings = apply_reliability_sensitivity(settings)
    tester_enabled = settings.tester_enabled

    # The tester (when enabled) authors protected acceptance tests; the coder is refused
    # on those files (deterministic, ADR-0013). A LIVE set the author_tests node fills at
    # runtime — the coder's tools close over it, so the protection applies once the tester
    # has written. Empty (no effect) when the tester is off. build_graph is the SOLE owner
    # of protected_tests and the SOLE caller of build_repo_tools.
    protected_tests: set[str] = set()
    # The operator's write-gate approvals, as facts the ADR-0036 tamper guard can read (F63, #65):
    # path -> the integrity hash of content a HUMAN approved. Same shared-mutable ownership as
    # protected_tests — the coder's tools write into this exact object and nodes_impl reads it.
    operator_sanctioned: dict[str, str] = {}
    # The coder's last engine-resolved validation, so a hand-raise escalation can name the tests
    # blocking it (F70, #75). Same shared-mutable ownership as the two above. Deliberately given
    # ONLY to the coder's toolset: the Proctor's own run must never become the evidence that
    # authorizes amending the Proctor's own test.
    coder_validation: dict[str, str] = {}
    # Slice 2.1: the probe's degradation counts, owned here for the whole run (same shared-mutable
    # ownership as the maps above) so they accumulate across iterations and reach the stored card.
    exec_degradations: dict[str, int] = {}
    exec_usage: dict[str, int] = {}
    all_tools = build_repo_tools(
        workspace,
        sandbox,
        test_cmd=test_cmd,
        approval_gate=approve_writes,
        install=settings.sandbox_install,
        install_timeout=settings.sandbox_install_timeout,
        allow_delete=settings.delete_tool_enabled,
        test_repeat_limit=settings.coder_test_repeat_limit,
        protected_paths=protected_tests,
        enable_exec=settings.coder_repl_enabled,
        enable_scratch=settings.coder_scratch_enabled,
        operator_sanctioned=operator_sanctioned,
        coder_validation=coder_validation,
        exec_degradations=exec_degradations,
        exec_usage=exec_usage,
    )
    # The tester gets its OWN toolset: write_file confined to tests/ (write_prefix), no
    # protected_paths (it must be able to write the tests). Built only when enabled; None
    # otherwise (the team factory then builds no tester agent).
    tester_tools = None
    if tester_enabled:
        tester_tools = build_repo_tools(
            workspace,
            sandbox,
            test_cmd=test_cmd,
            approval_gate=approve_writes,
            install=settings.sandbox_install,
            install_timeout=settings.sandbox_install_timeout,
            write_prefix="tests/",
            # Name the Proctor at its own gates (ADR-0013): "Coder wants to write" on a
            # test-file approval misattributes the separation the gate is there to protect.
            actor="Proctor",
            # Deliberately NOT given the sanction sink (red-team round 2): the tester authoring at
            # a path that COLLIDES with a pre-existing baselined test is the manufacture-a-green-
            # suite move the guard exists to stop, and a human rubber-stamp must not reopen it.
            # The Proctor's sanctioned route is proctor_edits (ADR-0058), which is coder-blind and
            # gated on the assertion floor + a proven mutation catch.
        )
    # All agent construction/invocation lives behind the injected team (agents_bridge, the
    # ONE core→agents seam). It receives the ALREADY-BUILT tools and scopes them per role —
    # it never builds tools, so protected_tests stays a single shared set owned here.
    agents = team_factory(settings, all_tools, tester_tools, model_factory)
    max_iter = settings.max_iterations if max_iterations is None else max_iterations
    # Clamp regardless of caller/UI input: an over-large value (the UI's old 999 for
    # "Unlimited") exceeds the LangGraph recursion_limit and crashes the run instead of
    # parking. This is the single chokepoint every caller (API, CLI, tests) resolves through.
    max_iter = max(1, min(max_iter, settings.max_iterations_ceiling))
    # Cap supervisor round-trips so an autonomous re-scope↔re-block can't run away;
    # once exceeded, the supervisor gives up and the run finalizes honestly.
    max_escalations = max(0, settings.max_escalations)
    # Reason-pass budget (ADR-0017/0018): at least max_reason_attempts, but never fewer than
    # 1 + the reasoning-ladder depth, so every configured reason_escalation tier is reachable
    # (pass 0 = own-model, passes 1..N = the N ladder tiers) without also raising the knob.
    max_reason = max(settings.max_reason_attempts, 1 + len(settings.reason_escalation))

    # Within-run cached evidence (#23 / ADR-0003): the repo overview (plan loop)
    # and the validation plan (test loop) are recomputed every iteration though
    # they only change when the working tree does. Memoize each by the tree hash
    # and reuse on an unchanged tree; recompute on change. build_graph is per-run,
    # so this dict is run/process-scoped — no cross-run staleness. This is the
    # "cached evidence" tier of the ADR-0002 escalation ladder, done deterministically.
    evidence_memo: dict[tuple[str, ...], Any] = {}

    # One explicit context object replaces the pile of captured closures: every node/
    # router/helper is a module-scope function taking `ctx` first, bound below via partial.
    ctx = RunContext(
        settings=settings,
        workspace=workspace,
        sandbox=sandbox,
        run_id=run_id,
        source=source,
        memory=memory,
        scanners=scanners,
        scan_sandbox=scan_sandbox,
        project_brief=project_brief,
        project_context=project_context,
        item_id=item_id,
        project_id=project_id,
        test_cmd=test_cmd,
        approve_writes=approve_writes,
        protected_tests=protected_tests,
        operator_sanctioned=operator_sanctioned,
        coder_validation=coder_validation,
        exec_degradations=exec_degradations,
        exec_usage=exec_usage,
        evidence_memo=evidence_memo,
        agents=agents,
        max_iter=max_iter,
        max_escalations=max_escalations,
        max_reason=max_reason,
    )
    # Bind ctx as the first arg so LangGraph still calls each node/router with (state[, config]).
    bind = functools.partial

    builder: StateGraph = StateGraph(RunState)
    builder.add_node("plan", bind(plan_node, ctx))
    builder.add_node("design", bind(design_node, ctx))
    builder.add_node("implement", ctx.agents.coder)
    builder.add_node("capture", bind(capture_node, ctx))
    builder.add_node("supervise", bind(supervise_node, ctx))
    builder.add_node("test", bind(test_node, ctx))
    builder.add_node("fix", bind(fix_node, ctx))
    builder.add_node("hygiene", bind(hygiene_node, ctx))
    builder.add_node("hygiene_fix", bind(hygiene_fix_node, ctx))
    builder.add_node("scan", bind(scan_node, ctx))
    builder.add_node("review", bind(review_node, ctx))
    builder.add_node("review_fix", bind(review_fix_node, ctx))
    builder.add_node("quality_revise", bind(quality_revise_node, ctx))
    builder.add_node("gate", bind(gate_node, ctx))
    builder.add_node("deliver", bind(deliver_node, ctx))

    builder.add_edge(START, "plan")
    # plan → design → implement: the PM elaborates the plan into an architecture
    # (#3) before the coder builds. The fix loop (fix→implement) skips re-design.
    # Plan-level breaker (#51, ADR-0056): a fallback/repeated plan at plan_stall_limit routes
    # straight to the gate (honest EARLY park) instead of design, saving the whole coder cycle.
    builder.add_conditional_edges(
        "plan",
        bind(route_after_plan, ctx),
        # "implement" is the reduced lane (#118 Approach A) -- plan straight to the coder, skipping
        # design and author_tests. Mapped unconditionally: route_after_plan only returns it when
        # the lane was certified, and an unmapped label is a LangGraph hard error.
        {"design": "design", "gate": "gate", "implement": "implement"},
    )
    if ctx.agents.tester_enabled:
        # Test-first (ADR-0013): Proctor authors the acceptance tests between design and
        # implement, and hands them to the coder as a must-pass contract. Authored once —
        # the fix/revise loops re-enter at implement, so the protected tests stay fixed.
        builder.add_node("author_tests", bind(author_tests_node, ctx))
        builder.add_edge("design", "author_tests")
        builder.add_edge("author_tests", "implement")
    else:
        builder.add_edge("design", "implement")
    builder.add_edge("implement", "capture")
    # An agent hand-raise (SUMMARY: blocked/escalate) diverts to the mode-gated
    # supervisor (ADR-0012); otherwise the normal test path. The supervisor either
    # re-scopes (→ plan with feedback) or gives up (→ gate → honest incomplete).
    builder.add_conditional_edges(
        "capture", bind(route_after_capture, ctx), {"supervise": "supervise", "test": "test"}
    )
    builder.add_conditional_edges(
        "supervise", bind(route_after_supervise, ctx), {"plan": "plan", "gate": "gate"}
    )
    # Reason-before-park (ADR-0017): the reason node + its edge exist ONLY when enabled;
    # the three route fns then may return "reason", so splice it into their mappings
    # (LangGraph requires every returned label to be mapped).
    reason_route: dict[str, str] = {}
    if settings.reason_on_stall_enabled:
        builder.add_node("reason", bind(reason_node, ctx))
        builder.add_edge("reason", "implement")
        reason_route = {"reason": "reason"}

    def _routes(base: dict[str, str]) -> dict[Hashable, str]:
        # Merge the reason branch (when enabled) into a route map; typed dict[Hashable, str]
        # for add_conditional_edges (dict is key-invariant, so build via update()).
        merged: dict[Hashable, str] = {}
        merged.update(base)
        merged.update(reason_route)
        return merged

    # A failing suite self-heals through fix→implement (bounded by max_iter); working
    # code runs the in-loop hygiene gate (or straight to scan when the gate is off).
    # The honest-stop (#56, ADR-0060): a tripped progress breaker routes test→supervise
    # for a decision (re-scope once vs give up honestly) instead of grinding to a park.
    builder.add_conditional_edges(
        "test",
        bind(route_after_test, ctx),
        _routes({"fix": "fix", "hygiene": "hygiene", "scan": "scan", "supervise": "supervise"}),
    )
    builder.add_edge("fix", "implement")
    # Residual lint/type issues self-heal through hygiene_fix→implement (default-on,
    # bounded by max_iter + hygiene_max_fixes); otherwise proceed to scan.
    builder.add_conditional_edges(
        "hygiene",
        bind(route_after_hygiene, ctx),
        # "test" closes the window where autofix rewrote the tree after it was validated: the
        # run re-validates through the normal spine rather than shipping an unmeasured tree.
        _routes({"hygiene_fix": "hygiene_fix", "scan": "scan", "test": "test"}),
    )
    builder.add_edge("hygiene_fix", "implement")
    builder.add_edge("scan", "review")
    # The held-out critic (#60, ADR-0065): when enabled, a veto-only judge of the delivered
    # OUTCOME sits on the review->gate edge — route_after_review's "gate" label targets the critic
    # node, which then flows unconditionally into the gate. It runs only on the delivery path (a
    # plan early-park / supervise give-up route straight to the gate, bypassing it: deny-by-default,
    # no delivered-passing code to judge). The node itself no-ops on a non-green/non-held-out run.
    gate_target = "gate"
    if ctx.agents.critic_enabled:
        builder.add_node("critic", bind(critic_node, ctx))
        builder.add_edge("critic", "gate")
        gate_target = "critic"
    # After review: a reviewer REQUEST_CHANGES self-heals through review_fix→implement
    # (default-on, bounded by max_iter); else a below-bar change may quality_revise
    # (opt-in); else proceed to the gate (via the critic when enabled).
    builder.add_conditional_edges(
        "review",
        bind(route_after_review, ctx),
        _routes(
            {
                "review_fix": "review_fix",
                "quality_revise": "quality_revise",
                "gate": gate_target,
            }
        ),
    )
    builder.add_edge("review_fix", "implement")
    builder.add_edge("quality_revise", "implement")
    builder.add_conditional_edges(
        "gate", bind(route_after_gate, ctx), {"deliver": "deliver", "plan": "plan"}
    )
    builder.add_edge("deliver", END)

    return builder.compile(checkpointer=checkpointer)
