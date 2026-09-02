"""The ONE core→agents seam.

`mosaera_core.graph` must import nothing from `mosaera_agents`; all agent
construction and invocation lives behind the injected `AgentTeam` bundle defined
here. This module is the single place that imports `mosaera_agents` — the graph
depends only on the `AgentTeam` Protocol and the `build_default_team` factory.

The dependency direction stays legal: this module (in `mosaera_core`) imports
`mosaera_agents` (which itself already depends on `mosaera_core`), exactly as the
graph did before this inversion, and imports `scoped_tools` from `mosaera_policies`
(core→policies). It receives ALREADY-BUILT tools and never constructs repo tools itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig
from mosaera_agents import pm, prompts, prompts_reason, reviewer
from mosaera_agents.coder import build_coder_agent
from mosaera_agents.critic import build_critic_agent, judge_outcome, judge_outcome_claims
from mosaera_agents.retry import robust_invoke
from mosaera_agents.reviewer import build_reviewer_agent
from mosaera_agents.tester import build_tester_agent
from mosaera_policies import scoped_tools

from mosaera_core.config import Role, RoleModel, Settings
from mosaera_core.messages import message_text
from mosaera_core.models import coder_num_ctx, get_chat_model

# The role→model construction seam, injectable so tests pass a fake factory instead of
# monkeypatching module-global get_chat_model (default is the real get_chat_model).
ModelFactory = Callable[[Role, Settings], BaseChatModel]


class AgentTeam(Protocol):
    """The exact surface the graph nodes need from the agents — mirrors today's call
    sites so `graph.py` imports nothing from `mosaera_agents`. `coder` is the compiled
    coder agent wired directly as the `implement` node; `tester_enabled` gates the
    author_tests node."""

    coder: Runnable
    tester_enabled: bool
    # Whether the held-out critic node is wired (#60, ADR-0065): the team builds the critic
    # agent iff critic_enabled, and build_graph splices the critic node on the same flag.
    critic_enabled: bool

    def plan(
        self, task: str, overview: str, feedback: Sequence[str], config: RunnableConfig | None
    ) -> str: ...

    def plan_is_fallback(self, plan: str) -> bool: ...

    def plan_fallback_reason(self) -> str: ...

    def plan_fallback_evidence(self) -> str: ...

    def design(
        self,
        task: str,
        plan: str,
        overview: str,
        feedback: Sequence[str],
        config: RunnableConfig | None,
    ) -> str: ...

    def extract_foresight(self, design: str) -> str: ...

    def author_tests(
        self,
        instruction: str,
        config: RunnableConfig | None,
        corrections: Sequence[str] = (),
    ) -> dict[str, Any] | None: ...

    def validate_and_repair_tests(
        self,
        instruction: str,
        config: RunnableConfig | None,
        corrections: Sequence[str] = (),
    ) -> dict[str, Any] | None: ...

    def review(
        self,
        task: str,
        plan: str,
        diff: str,
        test_output: str,
        findings: str,
        *,
        design: str,
        foresight: str,
        quality: str,
        config: RunnableConfig | None,
    ) -> str: ...

    def clarify(self, review: str, config: RunnableConfig | None) -> str: ...

    def critic(
        self,
        task: str,
        plan: str,
        diff: str,
        test_output: str,
        overstrict: str,
        config: RunnableConfig | None,
        claims: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None: ...

    def diagnose(
        self,
        settings: Settings,
        state: Mapping[str, Any],
        kind: str,
        text: str,
        tier: RoleModel,
        config: RunnableConfig | None,
    ) -> str: ...

    def reason_instruction(self, kind: str, text: str) -> str: ...

    def reasoned_plan_instruction(self, plan_text: str, kind: str, text: str) -> str: ...

    def hygiene_fix_instruction(self, findings: list[str]) -> str: ...

    def quality_revise_instruction(self, dim_name: str, score: int, findings: list[str]) -> str: ...

    def review_fix_instruction(self, review: str) -> str: ...


def _tester_input(instruction: str, corrections: Sequence[str]) -> dict[str, Any]:
    """The Proctor's invoke payload — a fresh conversation, plus the run's standing corrections.

    The `messages` list is deliberately new every call (that is the Proctor's design: authoring and
    validate/repair are separate, coder-blind turns). The consequence is that anything living only
    in the transcript dies here, which is exactly what happened to operator corrections. Carrying
    them in state instead is what makes them survive the boundary.
    """
    payload: dict[str, Any] = {"messages": [HumanMessage(content=instruction)]}
    if corrections:
        payload["corrections"] = [str(c) for c in corrections]
    return payload


def new_corrections(result: Any, carried: Sequence[str]) -> list[str]:
    """Corrections captured during ONE Proctor invocation that were not already carried in.

    Only the delta may be returned into `RunState`: `corrections` uses an `add` reducer, so
    returning the whole list would re-append everything that was passed in and the standing block
    would grow by its own length every turn.
    """
    got = (result or {}).get("corrections") or [] if isinstance(result, dict) else []
    seen = set(str(c) for c in carried)
    fresh: list[str] = []
    for item in got:
        text = str(item)
        if text and text not in seen:
            seen.add(text)
            fresh.append(text)
    return fresh


@dataclass
class LangGraphAgentTeam:
    """The concrete `AgentTeam`: holds the compiled agents + models and delegates each
    method to today's exact `mosaera_agents` call. Built by `build_default_team`."""

    coder: Runnable
    reviewer_agent: Any
    reviewer_model: Any
    pm_plan_agent: Any
    pm_design_agent: Any
    tester_agent: Any
    tester_enabled: bool
    critic_agent: Any
    critic_enabled: bool
    model_factory: ModelFactory
    settings: Settings

    # WHY the last plan() fell back (F39, #71) — "budget_exhausted" | "model_failed" | "empty".
    # Carried on the team rather than in plan()'s return type: that signature is the AgentTeam
    # contract, and widening it for a value only one caller reads is the wrong trade. Meaningful
    # only when plan_is_fallback() is True.
    _last_plan_fallback: str = "empty"
    # VERBATIM what the model returned on that fallback (#71, F39). "The planner returned nothing
    # usable" is a dead end: diagnosing one such run took three synthetic probes against the live
    # endpoint, none of which reproduced it, because nothing recorded the real response. Rides the
    # same rail for the same reason — the value is diagnostic, and only one caller wants it.
    _last_plan_evidence: str = ""

    def plan(
        self, task: str, overview: str, feedback: Sequence[str], config: RunnableConfig | None
    ) -> str:
        outcome = pm.plan_with_agent_detailed(self.pm_plan_agent, task, overview, feedback, config)
        self._last_plan_fallback = outcome.reason
        self._last_plan_evidence = outcome.evidence
        return outcome.plan

    def plan_is_fallback(self, plan: str) -> bool:
        return plan.strip() == pm._FALLBACK_PLAN.strip()

    def plan_fallback_reason(self) -> str:
        return self._last_plan_fallback

    def plan_fallback_evidence(self) -> str:
        return self._last_plan_evidence

    def design(
        self,
        task: str,
        plan: str,
        overview: str,
        feedback: Sequence[str],
        config: RunnableConfig | None,
    ) -> str:
        return pm.design_with_agent(self.pm_design_agent, task, plan, overview, feedback, config)

    def extract_foresight(self, design: str) -> str:
        return pm.extract_foresight(design)

    def author_tests(
        self,
        instruction: str,
        config: RunnableConfig | None = None,
        corrections: Sequence[str] = (),
    ) -> dict[str, Any] | None:
        # Replicates author_tests_node's tester_agent.invoke EXACTLY; None when off.
        # `corrections` MUST be threaded explicitly: the Proctor is invoked with a hand-built
        # payload, not wired as a graph node, so it never sees RunState. Omit it and
        # StandingCorrections reads an empty list and injects nothing (silently).
        if self.tester_agent is None:
            return None
        return self.tester_agent.invoke(_tester_input(instruction, corrections), config)

    def validate_and_repair_tests(
        self,
        instruction: str,
        config: RunnableConfig | None = None,
        corrections: Sequence[str] = (),
    ) -> dict[str, Any] | None:
        # The Proctor's up-front validate/repair turn (#54, ADR-0058): the SAME tester agent (it
        # now holds edit_file in its allowlist), invoked AFTER authoring and BEFORE the coder — so
        # it is structurally blind to the coder's diff and cannot relax a test to fit wrong code.
        # None when the tester is off. Distinct method (not author_tests) so the call site reads
        # its intent and a future prompt/tooling divergence has a seam.
        if self.tester_agent is None:
            return None
        return self.tester_agent.invoke(_tester_input(instruction, corrections), config)

    def review(
        self,
        task: str,
        plan: str,
        diff: str,
        test_output: str,
        findings: str,
        *,
        design: str,
        foresight: str,
        quality: str,
        config: RunnableConfig | None,
    ) -> str:
        return reviewer.review_change(
            self.reviewer_agent,
            task,
            plan,
            diff,
            test_output,
            findings,
            design=design,
            foresight=foresight,
            quality=quality,
            config=config,
        )

    def clarify(self, review: str, config: RunnableConfig | None) -> str:
        return reviewer.clarify_verdict(self.reviewer_model, review, config)

    def critic(
        self,
        task: str,
        plan: str,
        diff: str,
        test_output: str,
        overstrict: str,
        config: RunnableConfig | None = None,
        claims: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        # The held-out judge (#60, ADR-0065): None when the critic is off (no agent built), else
        # the parsed verdict (or None on an empty/unparseable/failed judgement → no veto). The
        # node guards on tests_passed + held-out + memoization before calling this.
        # claims is not None => the claims protocol (#61): per-claim rows the caller disposes via
        # mosaera_core.critic_policy — the agent proposes, core decides.
        if self.critic_agent is None:
            return None
        if claims is not None:
            return judge_outcome_claims(
                self.critic_agent, task, plan, diff, test_output, claims, overstrict, config
            )
        return judge_outcome(self.critic_agent, task, plan, diff, test_output, overstrict, config)

    def diagnose(
        self,
        settings: Settings,
        state: Mapping[str, Any],
        kind: str,
        text: str,
        tier: RoleModel,
        config: RunnableConfig | None = None,
    ) -> str:
        """One-off, TOOL-LESS reasoner call at `tier` (ADR-0018): diagnose the stuck point
        and return a concrete plan (clean text) for the cheap coder to execute. Returns ""
        on an empty OR failed reasoner so the caller falls back to the own-model reason pass
        — a reasoner blip must never crash the run. Metered via the threaded `config`. Moved
        here verbatim from graph.py's reason_diagnose."""
        try:
            # Bind a throwaway 'pm' role to the tier so get_chat_model resolves it (auto
            # reasoning-channel for deepseek-r1/gpt-oss); clear cost-modes so a 'pm' override
            # can't shadow the tier binding. No agent binding is mutated — this is one-off.
            tier_settings = replace(
                settings,
                role_providers={**settings.role_providers, "pm": tier.provider},
                pm_model=tier.model,
                cost_modes={},
                active_cost_mode=None,
            )
            model = self.model_factory("pm", tier_settings)
            packet = prompts_reason.diagnosis_packet(
                kind,
                text,
                str(state.get("task", "")),
                str(state.get("plan", "")),
                str(state.get("design", "")),
                str(state.get("coder_summary", "")).strip(),
            )
            resp = robust_invoke(
                model,
                [
                    SystemMessage(content=prompts_reason.DIAGNOSIS_SYSTEM),
                    HumanMessage(content=packet),
                ],
                config=config,
            )
            return message_text(resp).strip()
        except Exception:
            return ""

    def reason_instruction(self, kind: str, text: str) -> str:
        return prompts_reason.reason_instruction(kind, text)

    def reasoned_plan_instruction(self, plan_text: str, kind: str, text: str) -> str:
        return prompts_reason.reasoned_plan_instruction(plan_text, kind, text)

    def hygiene_fix_instruction(self, findings: list[str]) -> str:
        return prompts.hygiene_fix_instruction(findings)

    def quality_revise_instruction(self, dim_name: str, score: int, findings: list[str]) -> str:
        return prompts.quality_revise_instruction(dim_name, score, findings)

    def review_fix_instruction(self, review: str) -> str:
        return prompts.review_fix_instruction(review)


def build_default_team(
    settings: Settings,
    all_tools: list,
    tester_tools: list | None,
    model_factory: ModelFactory = get_chat_model,
) -> AgentTeam:
    """Construct the real agent team from ALREADY-BUILT tools (moved out of build_graph).

    `all_tools` are the coder/reviewer/pm repo tools (constructed by build_graph, closing over
    the shared protected_tests set); `tester_tools` are the tester's write-scoped tools (None
    when the tester is off). This factory scopes each toolset per role but NEVER constructs
    tools — build_graph remains the sole owner of protected_tests and the sole place tools are
    built.
    """
    pm_model = model_factory("pm", settings)
    reviewer_model = model_factory("reviewer", settings)
    coder_model = model_factory("coder", settings)

    # Trim old tool outputs once the coder transcript passes ~60% of its context,
    # leaving room for the next tool call (prevents truncated tool-call errors).
    coder = build_coder_agent(
        coder_model,
        scoped_tools("coder", all_tools),
        step_limit=settings.coder_step_limit,
        context_token_trigger=int(coder_num_ctx(settings) * 0.6),
        system_prompt=prompts.coder_system(
            settings.delete_tool_enabled,
            scratch_enabled=settings.coder_scratch_enabled,
            # ADR-0013: when the Proctor is on, its authored tests are protected and a write is
            # refused. The prompt used to claim ownership regardless, so the coder burned
            # iterations on writes the tools reject. Forced ON for autonomous runs, so this was
            # the delivery path.
            #
            # Derived from `tester_tools`, NOT `settings.tester_enabled` — the same expression
            # `tester_enabled` is set from below, and the one every other consumer reads. The two
            # agree only because `build_graph` happens to derive both from one flag; a team_factory
            # that passes tester_tools with the setting off (bench and tests inject one) would tell
            # the coder it owns tests while its writes were being refused.
            tester_owns_tests=tester_tools is not None,
        ),
    )
    reviewer_agent = build_reviewer_agent(
        reviewer_model,
        scoped_tools("reviewer", all_tools),
        step_limit=settings.reviewer_step_limit,
    )
    # The PM (EYES): plan and design run as read-only tool-using agents so they can
    # read the actual repo before writing, instead of guessing from a filename list.
    # Two agents differ only by system prompt (plan vs design); both share the PM
    # read-only allowlist (list_files/read_file/search) and the pm_step_limit budget.
    pm_plan_agent = pm.build_pm_agent(
        pm_model,
        scoped_tools("pm", all_tools),
        system_prompt=prompts.PM_SYSTEM,
        step_limit=settings.pm_step_limit,
    )
    pm_design_agent = pm.build_pm_agent(
        pm_model,
        scoped_tools("pm", all_tools),
        system_prompt=prompts.DESIGN_SYSTEM,
        step_limit=settings.pm_step_limit,
    )
    # The tester gets its OWN toolset: write_file confined to tests/ (built with
    # write_prefix by build_graph). Built only when the tester is enabled.
    tester_agent = None
    if tester_tools is not None:
        tester_agent = build_tester_agent(
            model_factory("tester", settings),
            scoped_tools("tester", tester_tools),
            step_limit=settings.tester_step_limit,
            test_file_cap=settings.tester_file_cap,
        )
    # The held-out critic (#60, ADR-0065): a read-only judge over the SAME read tools as the
    # reviewer (scoped to the critic allowlist). Its model is the held-out critic binding
    # (default a different model from the coder). Built only when enabled; None otherwise (the
    # graph then wires no critic node and the critic() method is inert).
    critic_agent = None
    if settings.critic_enabled:
        critic_agent = build_critic_agent(
            model_factory("critic", settings),
            scoped_tools("critic", all_tools),
            step_limit=settings.reviewer_step_limit,
            # #61: the claims-protocol persona when the knob is ON (A/B-measured before any
            # posture flip); the legacy persona is the OFF arm, byte-identical to today.
            persona="critic_claims" if settings.critic_claim_protocol else "critic",
        )
    return LangGraphAgentTeam(
        coder=coder,
        reviewer_agent=reviewer_agent,
        reviewer_model=reviewer_model,
        pm_plan_agent=pm_plan_agent,
        pm_design_agent=pm_design_agent,
        tester_agent=tester_agent,
        tester_enabled=tester_tools is not None,
        critic_agent=critic_agent,
        critic_enabled=settings.critic_enabled,
        model_factory=model_factory,
        settings=settings,
    )
