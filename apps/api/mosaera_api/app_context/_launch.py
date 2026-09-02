"""Run launch, item launch, restart rehydration, and the autonomous orchestrator.

The core lifecycle: build a graph + start a background ``RunSession`` (ad-hoc or
backlog-item), reconstruct a parked run after a restart, and drive the autonomous
project sweep item-to-item.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Callable
from typing import Any

from mosaera_core.clauses import load_clauses
from mosaera_core.config import Settings
from mosaera_core.spec_lint import undecidable_reason
from mosaera_core.task_spec import build_run_task

from mosaera_api.app_context._base import AppContextBase
from mosaera_api.factory import resolve_run_settings
from mosaera_api.runner import RunSession
from mosaera_api.schemas import (
    CloudEgressBlocked,
    ItemBlocked,
    ItemLocked,
    ItemNeedsClarification,
    ProjectBusy,
    RunSubmit,
)


def _run_budget(settings: Settings) -> dict[str, float]:
    """Per-run spend ceilings from settings, as the {dim: cap} map RunSession
    enforces (omitting unset dimensions). Empty = no budget (feature off)."""
    caps: dict[str, float] = {}
    if settings.run_max_usd is not None:
        caps["usd"] = settings.run_max_usd
    if settings.run_max_tokens is not None:
        caps["tokens"] = float(settings.run_max_tokens)
    if settings.run_max_tool_calls is not None:
        caps["tool_calls"] = float(settings.run_max_tool_calls)
    return caps


def _run_hard_budget(settings: Settings) -> dict[str, float]:
    """Absolute HARD ceilings ({dim: cap}) that CANCEL the run (not re-askable).
    Empty = no hard cap."""
    caps: dict[str, float] = {}
    if settings.run_hard_max_usd is not None:
        caps["usd"] = settings.run_hard_max_usd
    if settings.run_hard_max_tokens is not None:
        caps["tokens"] = float(settings.run_hard_max_tokens)
    return caps


def _new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class LaunchMixin(AppContextBase):
    def launch(self, req: RunSubmit) -> RunSession:
        """Build the graph and start a background run session. Raises on setup error.

        A run targeting a project's persistent clone must hold the project
        reservation like any item run — the mutex is what makes the run-start
        clone reset safe and keeps the clone single-writer. Released only by
        the worker's own on_done.
        """
        if req.project_id:
            self.reserve_project(req.project_id)
        try:
            run_id = _new_run_id()
            graph, config, initial, memory = self.factory()(req, run_id)
            on_done: Callable[[], None] | None = None
            if req.project_id:
                pid = req.project_id
                on_done = lambda: self.release_project(pid)  # noqa: E731
            session = RunSession(
                run_id,
                graph,
                config,
                initial,
                memory=memory,
                project_id=req.project_id,
                item_id=req.item_id,
                on_done=on_done,
                max_iterations=req.max_iterations,
                max_seconds=Settings.from_env().run_max_seconds,
                budget=_run_budget(Settings.from_env()),
                hard_budget=_run_hard_budget(Settings.from_env()),
            )
            self.register_session(run_id, session)
            session.start()
            return session
        except Exception:
            if req.project_id:
                self.release_project(req.project_id)
            raise

    def launch_item(
        self,
        project_id: str,
        item: dict[str, Any],
        *,
        mode: str = "guided",
        chain: bool = False,
        max_iterations: int | None = None,
        budget_tokens: int | None = None,
        budget_usd: float | None = None,
        cost_mode: str | None = None,
        override: bool = False,
        escalation_settings: Settings | None = None,
        escalation_attempt: int = 0,
        escalation_role: str = "",
    ) -> RunSession:
        """Start a backlog item's run on the project clone (serialized).

        ``mode`` is the per-run approval posture (decoupled from chaining):
        guided = human approves every gate; autonomous = auto-approve writes and
        auto-resolve delivery (park on blocking evidence); high_assurance =
        auto-approve writes but always park delivery for a human. ``chain`` (the
        project Autonomous flag) is what queues the next item on clean delivery —
        a per-run mode never chains.

        The project reservation is taken FIRST — before the slow clone-open and
        graph build — and released only by the worker's own on_done (or here on
        a launch failure). That closes the launch race and guarantees the
        run-start clone reset never touches another run's working tree.
        """
        mem = self.history
        if mem is None:
            raise RuntimeError("durable memory required for project runs")
        # Dependency + soft-lock gate: an item can't start until every item it depends on
        # is delivered, and not while the PM has soft-locked it — both checked here (the
        # single choke point for manual + autonomous + rehydrate) BEFORE reserving the
        # clone. ``override`` is the user's manual, per-run escape hatch (they've read the
        # caveat and chosen to run early); the autonomous sweep passes override=False and
        # additionally pre-filters blocked/locked items, so it NEVER runs one.
        if not override:
            blocking = mem.blocking_dependencies(item["id"])
            if blocking:
                raise ItemBlocked(blocking)
            locked, reason = mem.is_item_locked(item["id"])
            if locked:
                raise ItemLocked(reason)
            # Intake clarification (ADR-0080 §1): an OPEN ask means a material claim has no
            # binding — running now burns tokens toward an uncheckable "done". Same posture
            # as the soft-lock: deny at the single choke point; override stays the operator's
            # explicit escape hatch.
            open_clar = mem.item_clarification(item["id"])
            if open_clar is not None:
                claim_text = str(open_clar.get("claim_text", ""))
                # Best-effort axis for the message only — never stored (a stored verdict goes
                # stale as the detectors improve). A derivation failure must not break a deny.
                axis = ""
                with contextlib.suppress(Exception):
                    if undecidable_reason(claim_text, str(item.get("acceptance") or "")):
                        axis = "decidability"
                raise ItemNeedsClarification(claim_text, axis)
        auto_approve = mode in ("autonomous", "high_assurance")
        high_assurance = mode == "high_assurance"
        self.reserve_project(project_id)
        try:
            detail = mem.project_detail(project_id)
            if detail is None:
                raise RuntimeError("unknown project")
            # ONE definition of the task a run is given (task_spec.build_run_task) — the weave of
            # standing decisions into the acceptance criteria and the minting of claims from the
            # WOVEN text both live there, so an instrument cannot grade a different contract.
            task, claims = build_run_task(
                item, load_clauses(mem, project_id, enabled=Settings.from_env().clauses_enabled)
            )
            req = RunSubmit(
                repo=str(detail["source_repo"]),
                task=task,
                project_id=project_id,
                item_id=item["id"],
                max_iterations=max_iterations,
                cost_mode=cost_mode,
                claims=claims,
                # Autonomous runs get the verify+recover overlay (ADR-0020) in the factory.
                autonomous=(mode == "autonomous"),
                # The operator's own validation command (#121). One of the four independence legs
                # `evaluate_oracle` accepts, and until now reachable only from the CLI's
                # `--test-cmd` — so a project whose suite the planner cannot detect parked on
                # `oracle_unverified` with no way to say what "validated" means here. `resolve_plan`
                # treats the operator's judgement as `strength="suite"` (ADR-0034).
                test_cmd=str(detail.get("test_cmd") or "") or None,
            )
            # Off-box egress gate (ADR-0024): an AUTONOMOUS run (no human at the gate) may not
            # bind an active role to a cloud model unless egress is consented AND the model is
            # priced. Guided/HA runs are the operator's watched, consented choice — not gated.
            if mode == "autonomous":
                resolved = resolve_run_settings(req, escalation_settings)
                # Only roles that ACTUALLY run this autonomous config are gated: the tester and the
                # held-out critic (#60) each send repo content (spec/diff/test output) to their
                # model, so a CLOUD binding for either must clear egress consent + pricing like the
                # always-on roles — else a cloud critic would exfiltrate off-box unconsented.
                roles = (
                    ["pm", "coder", "reviewer"]
                    + (["tester"] if resolved.tester_enabled else [])
                    + (["critic"] if resolved.critic_enabled else [])
                )
                blocked = resolved.disallowed_cloud_roles(roles)  # type: ignore[arg-type]
                if blocked:
                    role, _prov, model = blocked[0]
                    raise CloudEgressBlocked(
                        f"role '{role}' uses cloud model '{model}' — enable cloud egress and set "
                        "its price, or bind a local model"
                    )
            run_id = _new_run_id()
            # A live model-escalation re-run (ADR-0022) injects the bumped Settings; a first
            # run passes none (the factory resolves from_env + overlays). Only forward the arg
            # when set, so a test factory that doesn't accept `settings` still works normally.
            factory_kwargs = (
                {"settings": escalation_settings} if escalation_settings is not None else {}
            )
            graph, config, initial, memory = self.factory()(req, run_id, **factory_kwargs)
            # The exact Settings this run executes under — for the escalation diagnosis below
            # (byte-identical to what the factory built, both via resolve_run_settings).
            used_settings = resolve_run_settings(req, escalation_settings)

            def _after() -> None:
                self.release_project(project_id)
                if not chain:
                    # #68, measured live 2026-08-21 on run `20260821-180202-7865c0`: the ESCALATE
                    # arm sat BELOW this return, so a manually launched item run — the "Run guided"
                    # button, which is how an operator drives a single item — parked `incomplete`
                    # on a real oracle conflict and the item carried no clarification. That is F62
                    # verbatim: the stop worked and the ask never fired, this time because the
                    # arm's CALL SITE was unreachable rather than its predicate wrong.
                    #
                    # Only the arm is hoisted. The three siblings below stay chain-only on purpose:
                    # model-escalation launches another run, close-named-gap ships a diff, and
                    # recurate/defer moves the item out of the picker — all sweep autonomy a
                    # human-driven run must not get for free. Raising a QUESTION on the item is
                    # the opposite: it takes no autonomy, it hands the decision back.
                    if session.status == "incomplete":
                        self._try_escalate_arm(item, run_id, session, used_settings)
                    return
                # Did the escalated producer actually SPEAK? (#119, ADR-0016 Amendment 1)
                #
                # Measured 2026-08-10: 45 of 61 recorded escalations produced ZERO calls from the
                # escalated role — every one binding an unfunded cloud key — with `error` left None
                # and `escalation_path` still naming the model, so a failed escalation read exactly
                # like "a stronger model tried and could not". The bench got this detector; the
                # live path was recorded as OWED. This is that debt.
                #
                # `cloud_tier_allowed` cannot close it: it checks the model is PRICED, and priced is
                # not funded. Reachability is only knowable after a call, so the check is post-hoc.
                if escalation_role:
                    self._note_escalation_outcome(
                        project_id, run_id, session, escalation_role, escalation_attempt
                    )

                # Chain to the next item only if this one delivered cleanly; else pause.
                if session.status == "completed" and bool((session.final or {}).get("approved")):
                    # Clear any gate-park pause note before resuming the chain.
                    mem.update_project(project_id, error="")
                    # Per-item stacked MR (ADR-0021): open THIS item's MR now, before moving
                    # on — so delivery is one reviewable MR per item, not one at the end.
                    self._maybe_open_item_mr(project_id, item["id"], run_id)
                    self.advance_project(project_id)
                elif session.status == "cancelled":
                    # A human stopped it; that's a decision, not a failure.
                    mem.update_project(project_id, error="")
                elif session.status == "incomplete" and self._try_model_escalation(
                    project_id,
                    item,
                    chain,
                    mode,
                    run_id,
                    session,
                    used_settings,
                    escalation_attempt,
                ):
                    return  # a stronger-model re-run was launched in place of parking
                elif session.status == "incomplete" and self._try_close_named_gap(
                    project_id, item, mode, run_id, session, used_settings
                ):
                    return  # Layer-2 (#76): the parked diff was VERIFIED + shipped in place
                elif session.status == "incomplete" and self._try_escalate_arm(
                    item, run_id, session, used_settings
                ):
                    # F49: the bar itself is unreachable — the ITEM now carries a question for the
                    # operator. Placed BEFORE recurate/defer on purpose: a deferred item drops out
                    # of the picker, which would bury the question we just raised.
                    return
                elif session.status == "incomplete" and self._try_recurate_or_defer(
                    project_id, item, mode, run_id, session
                ):
                    return  # resilient sweep: item deferred/re-curated, the sweep advanced
                elif mem is not None:
                    mem.update_project(
                        project_id,
                        error=f"autonomous paused: item '{item['title']}' needs attention",
                    )

            def _on_park() -> None:
                # The gate policy found blocking evidence — the run waits for a
                # human at the approval gate; surface why the chain paused.
                mem.update_project(
                    project_id,
                    error=f"autonomous paused: item '{item['title']}' awaiting gate approval",
                )

            session = RunSession(
                run_id,
                graph,
                config,
                initial,
                memory=memory,
                project_id=project_id,
                item_id=item["id"],
                on_done=_after,
                auto_approve=auto_approve,
                high_assurance=high_assurance,
                mode=mode,
                on_park=_on_park if chain else None,
                max_iterations=max_iterations,
                max_seconds=Settings.from_env().run_max_seconds,
                # Resilient sweep (ADR-0023): a chained autonomous run gives up honestly at a
                # blocking delivery gate instead of parking-and-holding the clone, so the sweep
                # can defer the item and keep going.
                resilient=(chain and mode == "autonomous" and Settings.from_env().resilient_sweep),
                budget={
                    **_run_budget(Settings.from_env()),
                    **({"tokens": float(budget_tokens)} if budget_tokens else {}),
                    **({"usd": budget_usd} if budget_usd else {}),
                },
            )
            self.register_session(run_id, session)
            # Mark in_progress before starting so a fast run can't set in_review first.
            mem.update_backlog_item(item["id"], status="in_progress")
            session.start()
            return session
        except Exception:
            self.release_project(project_id)
            raise

    def advance_project(self, project_id: str) -> None:
        """Autonomous orchestrator: launch the next todo item (position order), or stop
        when the backlog is done (leaving everything ready for human validation)."""
        if self.history is None:
            return
        detail = self.history.project_detail(project_id)
        if detail is None or not detail.get("autonomous"):
            return
        budget = self.project_budget_status(project_id)
        if budget["over"]:
            # Monthly budget reached — stop the sweep BEFORE spending more.
            self.history.update_project(
                project_id,
                error=f"autonomous paused: monthly budget reached ({budget['reason']})",
            )
            runs = detail.get("runs") or []
            if runs:  # attribute the event to the run that pushed spend over
                try:
                    self.history.add_audit_event(runs[0]["id"], "budget.exceeded", budget["reason"])
                except Exception:  # noqa: S110 — audit is best-effort
                    pass
            return
        # The next runnable item: a todo whose dependencies are all delivered
        # (blocked_by empty) AND not soft-locked by the PM, in position order. The sweep
        # never overrides a lock — that's a human-only, per-run action. If the rest are all
        # blocked/locked, idle.
        todo = sorted(
            (
                i
                for i in detail["backlog"]
                if i["status"] == "todo"
                and not i.get("blocked_by")
                and not i.get("locked")
                # ADR-0080: an open clarification is a question awaiting the operator —
                # the autonomous sweep never runs past an unanswered material ask.
                and not i.get("clarification")
            ),
            key=lambda i: (i["position"], i["id"]),
        )
        if not todo:
            # Nothing left to run. If the WHOLE backlog is delivered, the autonomous
            # last-mile (ADR-0019) may open the project MR; otherwise stop at review.
            # Honest partial completion (ADR-0023): if the resilient sweep DEFERRED items (or
            # left dependents blocked behind them), say so plainly rather than silently
            # stopping — the delivered items already opened their per-item MRs (ADR-0021).
            backlog = detail.get("backlog") or []
            deferred = [i for i in backlog if i["status"] == "deferred"]
            if deferred:
                delivered = sum(1 for i in backlog if i["status"] in ("in_review", "done"))
                titles = ", ".join(str(i["title"]) for i in deferred[:5])
                more = "…" if len(deferred) > 5 else ""
                self.history.update_project(
                    project_id,
                    error=(
                        f"sweep complete: delivered {delivered}, deferred {len(deferred)} "
                        f"(need attention): {titles}{more}"
                    ),
                )
            self._maybe_open_project_mr(project_id, detail)
            return
        try:
            self.launch_item(project_id, todo[0], mode="autonomous", chain=True)
        except ProjectBusy:
            return  # another run already owns the clone — its on_done will chain
        except (ItemBlocked, ItemLocked, ItemNeedsClarification):
            return  # became blocked/locked between filter and launch — idle
        except CloudEgressBlocked as exc:
            # A config gate, not a crash: the same bindings would block every item, so halt the
            # sweep with a clear, actionable note (ADR-0024) rather than defer-spamming.
            self.history.update_project(project_id, error=f"autonomous run blocked: {exc.reason}")
        except Exception as exc:
            self.history.update_project(project_id, error=f"autonomous failed to start: {exc}")
