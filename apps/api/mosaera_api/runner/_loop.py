"""The worker loop: drive the compiled graph's stream, surface milestones/updates,
resolve gate/escalation interrupts, and record the honest terminal outcome.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.types import Command
from mosaera_core.run_diagnosis import build_diagnosis, diagnosis_summary
from mosaera_policies import autonomous_resolution

from mosaera_api.runner._base import (
    _CANCELLED,
    RunCancelled,
    RunSessionBase,
    RunTimeout,
    _activity,
    _revision_feedback,
    json_safe,
)
from mosaera_api.runner._mode import get_mode, writes_auto
from mosaera_api.runner._summaries import persist_agent_summaries
from mosaera_api.runner._terminal import _termination_reason


class LoopMixin(RunSessionBase):
    def _record_pause_diagnosis(self) -> None:
        """Record WHY the run is asking, at the moment it asks (F78, 2026-08-23).

        ``build_diagnosis`` ran on TERMINAL paths only — here after the stream completes, and
        ``_record_terminal_diagnosis`` for cancel/timeout/crash. A run parked at an interrupt is
        neither, so ``diagnosis`` was ``null`` exactly when a human is being asked to decide, and
        the run page fell back to listing what the gate could not find.

        Measured live: three LedgerCLI runs went ``plan -> gate`` instantly and the page said "no
        checks were attempted / the reviewer's verdict couldn't be read / the run ended before the
        security scan could run" — none of which name the cause. State held the answer the whole
        time (``plan_unworkable_reason: under_specified: no material acceptance claim is checkable
        as written``), and reading the API was the only way to reach it. The vocabulary to render
        it already existed on both sides; nothing was writing the record at this moment.

        Stamped ``provisional`` so a reader can tell "this is why it is asking" from "this is how
        it ended"; the terminal diagnosis overwrites it when the run settles. Best-effort, exactly
        like the terminal path — a diagnosis must never break the pause it describes.
        """
        if self._memory is None:
            return
        try:
            final = dict(self._graph.get_state(self._config).values)
            diagnosis = build_diagnosis(
                final,
                max_iterations=self._max_iterations,
                evidence_home=self.evidence_home,
            )
        except Exception:  # never let diagnosis-building break the park
            return
        diagnosis["provisional"] = True
        self.diagnosis = diagnosis
        self._audit("diagnosis", f"parked: {diagnosis_summary(diagnosis)}")
        self._safe(lambda: self._memory.record_run_diagnosis(self.run_id, diagnosis))

    def _run(self) -> None:
        payload: Any = self._initial
        try:
            while True:
                interrupts: list[Any] = []
                # Manual iteration so the stop checkpoint runs BEFORE pulling
                # each chunk: a cancelled run can never start its next node.
                # "updates" = per-node deltas; "custom" = milestone activity the
                # coder's tools emit via get_stream_writer, so the implement node
                # is no longer an opaque box. subgraphs=True is required for the
                # custom events (and interrupts) raised INSIDE the coder subgraph
                # to reach us; with a list stream_mode + subgraphs each item is a
                # (namespace, mode, data) tuple.
                stream = self._graph.stream(
                    payload,
                    self._config,
                    stream_mode=["updates", "custom"],
                    subgraphs=True,
                )
                while True:
                    self._checkpoint()
                    hard = self._hard_breach()
                    if hard is not None:
                        self._cancel_hard(hard)  # absolute ceiling → cancel, no re-ask
                    breach = self._budget_breach()
                    if breach is not None:
                        self._park_budget(breach)  # blocks; raises on deny/cancel
                    try:
                        namespace, mode, data = next(stream)
                    except StopIteration:
                        break
                    if mode == "custom":
                        act = _activity(data)
                        if act is not None:
                            # Each milestone is one deterministic tool op (#22).
                            self._det_ops += 1
                            # Attribute the milestone to the node that emitted it.
                            # The namespace names the owning subgraph node
                            # ("implement:<uuid>" → implement, "review:<uuid>" →
                            # review) in real time; self.phase lags (it's set on
                            # node COMPLETION), so prefer the namespace.
                            act["node"] = (
                                namespace[0].split(":")[0]
                                if namespace
                                else (self.phase or "implement")
                            )
                            self._emit("activity", act)
                        continue
                    # updates: interrupts can bubble up from the coder subgraph,
                    # so accept __interrupt__ at any namespace; only surface
                    # top-level (root) node deltas as phase updates.
                    for node, update in data.items():
                        if node == "__interrupt__":
                            interrupts.extend(update)
                        elif not namespace:
                            self.phase = node
                            self._record_corrections(update)
                            self._emit("update", {"node": node, "update": json_safe(update)})
                            self._audit("node", node)
                if not interrupts:
                    break
                intr = interrupts[0]
                value = intr.value if isinstance(intr.value, dict) else {}
                action = str(value.get("action", ""))

                # A mid-run agent escalation (ADR-0012) is resolved by RUN MODE, not the
                # delivery-gate evidence policy: autonomous → Quincy re-scopes (recorded,
                # non-blocking); guided/high-assurance → park for a human. Resolve, resume
                # the graph with the decision, and re-stream.
                if action == "escalation":
                    payload = Command(resume={intr.id: self._resolve_escalation(intr, value)})
                    continue

                gate = value.get("gate_decision")

                # Delivery-gate policy (mosaera_policies.gate): autonomous mode
                # may approve ONLY on all-clear evidence. Non-deliver gates
                # (write_file) keep legacy auto-approve — otherwise autonomous
                # runs would deadlock on every file write.
                resolution = "approve"
                if action == "deliver":
                    # Deny-by-default at the delivery gate: a malformed/absent
                    # gate_decision must PARK for a human, never silently
                    # auto-approve a ship. (Non-deliver write gates keep the
                    # legacy auto-approve above so autonomous doesn't deadlock.)
                    resolution = autonomous_resolution(gate) if isinstance(gate, dict) else "park"
                    # High Assurance always routes delivery to a human, even
                    # on all-clear evidence (writes still auto-approve above).
                    if self._high_assurance:
                        resolution = "park"
                    # An autonomous approve must correspond to a real change. An
                    # empty committed diff means the coder shipped nothing — a silent
                    # failure (budget/retry exhaustion, or an unsatisfiable task) or
                    # an already-satisfied item. Neither should auto-ship and chain
                    # the sweep as "delivered": park for a human to confirm the no-op.
                    if resolution == "approve" and not str(value.get("diff", "")).strip():
                        resolution = "park"
                        self._audit("empty-delivery", "autonomous approve withheld — no change")
                reasons = (
                    [str(r) for r in gate.get("reasons", [])] if isinstance(gate, dict) else []
                )

                # ADR-0101: a WRITE gate consults the LIVE interaction mode — accept/auto
                # auto-approve it (recorded), ask parks it. Delivery keeps launch semantics.
                is_write_gate = action in ("write_file", "edit_file", "delete_file")
                if is_write_gate and not self._auto_approve and writes_auto(self):
                    mode = get_mode(self)
                    self._audit("auto-accepted", f"{action} (mode: {mode})")
                    if self._memory is not None:
                        self._safe(
                            lambda a=action, m=mode: self._memory.add_approval(
                                self.run_id, a, True, f"auto-accepted (mode: {m})"
                            )
                        )
                    # actor stays "autonomous": actor == "human" is the SANCTION authority
                    # (tools/repo factory) — an auto-accept must never mint a human sanction.
                    payload = Command(
                        resume={intr.id: {"approve": True, "feedback": "", "actor": "autonomous"}}
                    )
                    continue
                if self._auto_approve and resolution == "approve":
                    self._audit("auto-approved", action)
                    if self._memory is not None:
                        self._safe(
                            lambda a=action: self._memory.add_approval(self.run_id, a, True, "auto")
                        )
                    decision: Any = {"approve": True, "feedback": "", "actor": "autonomous"}
                elif self._auto_approve and resolution == "deny_with_feedback":
                    # Reviewer-only complaint: bounded revise loop with the
                    # reviewer's notes as feedback.
                    fb = _revision_feedback(value, reasons)
                    self._audit("auto-denied", f"{action}: {', '.join(reasons)}")
                    if self._memory is not None:
                        self._safe(
                            lambda a=action, f=fb: self._memory.add_approval(
                                self.run_id, a, False, f
                            )
                        )
                    decision = {"approve": False, "feedback": fb, "actor": "autonomous"}
                elif self._auto_approve and self._resilient and action == "deliver":
                    # Resilient sweep (ADR-0023): don't park-and-HOLD the clone on blocking
                    # delivery evidence — break to the terminal block, which sees approved=False
                    # (the gate interrupt precedes deliver_node) and ends the run honestly
                    # `incomplete` with the gate reasons. The sweep's _after then defers this
                    # item and keeps delivering the rest. The run row goes INCOMPLETE (not
                    # AWAITING_APPROVAL), so it can never be rehydrated into the gate.
                    self._audit(
                        "resilient-giveup", ", ".join(reasons) or "blocked at delivery gate"
                    )
                    # The break happens AT the gate interrupt, before the gate node returns
                    # `gate_decision` into the state — so `get_state().values` below won't carry
                    # it. Stash it from the interrupt value so `diagnose_bottleneck` (ADR-0022,
                    # keyed on gate_decision.reasons) can still attribute the bottleneck role and
                    # ESCALATE before the sweep defers. Without this, escalation silently no-ops
                    # on every gate-blocked item (found live, ADR-0023↔0022 interaction).
                    # Widened stash (ADR-0078): the payload's gate dict lacks the receipt
                    # fields the gate node only merges into COMMITTED state (which this break
                    # forfeits) — fold in the vouch diagnosis + priced residual, and keep the
                    # claims/dispositions so _persist_receipt can write the ledger.
                    self._resilient_gate = (
                        {
                            **gate,
                            "oracle_vouched_by": str(value.get("oracle_vouched_by", "")),
                            "oracle_residual": str(value.get("oracle_residual", "")),
                        }
                        if isinstance(gate, dict)
                        else None
                    )
                    self._resilient_claims = (
                        list(value.get("claims") or []),
                        list(value.get("claim_dispositions") or []),
                    )
                    break
                else:
                    if self._auto_approve:
                        # Blocking evidence: park for a human. No approval row —
                        # the eventual human decision writes it via approve().
                        self._audit("auto-park", ", ".join(reasons) or action)
                        if self._on_park is not None:
                            self._safe(self._on_park)
                    self._enter_awaiting({"id": intr.id, "value": json_safe(intr.value)})
                    self._record_pause_diagnosis()
                    # Durable marker so the park survives an API restart: the run
                    # row goes AWAITING_APPROVAL (finalize_orphans only sweeps
                    # RUNNING), keeping the checkpointed state resumable.
                    if self._memory is not None:
                        self._safe(lambda: self._memory.mark_run_awaiting(self.run_id))
                    self._audit("interrupt", action)
                    self._emit("interrupt", self.pending_interrupt)
                    parked_at = time.time()
                    decision = self._resume.get()
                    self._parked_seconds += time.time() - parked_at
                    if decision is _CANCELLED:
                        raise RunCancelled
                    # This branch is reached ONLY by a person answering the parked gate over
                    # the API. Stamp it, so the gate node can tell a real human override apart
                    # from the autonomous auto-approve above — which it previously could not,
                    # and so branded every autonomous silence-ship as "a human approved this".
                    if isinstance(decision, dict):
                        decision = {**decision, "actor": "human"}
                    self.pending_interrupt = None
                    self.status = "running"
                    if self._memory is not None:
                        self._safe(lambda: self._memory.mark_run_running(self.run_id))
                payload = Command(resume={intr.id: decision})
            # Deliberately NO checkpoint here: if the stream ran to completion,
            # deliver already executed — the commit and record_run happened.
            # Recording "completed" even when a cancel raced the last chunk is
            # the honest outcome; the cancel simply arrived too late.
            self.final = self._graph.get_state(self._config).values
            # A resilient gate-giveup broke before the gate node committed its decision to
            # state; restore it so the terminal reason + escalation diagnosis see the evidence.
            if self._resilient_gate and not self.final.get("gate_decision"):
                self.final = {**self.final, "gate_decision": self._resilient_gate}
            # Honest terminal state: the graph always ends via deliver_node, but it
            # only DELIVERS when the gate approved. A run that reached the end because
            # it hit the iteration cap / no-progress breaker / couldn't satisfy the
            # reviewer did NOT complete — call it "incomplete" (+ the reason) rather
            # than dressing a give-up as success.
            # The structured record, computed for EVERY terminal run — a delivery too, because
            # "it concluded honestly" is a claim about deliveries as much as parks. `_termination
            # _reason` below stays as the durable 80-char column; this is the evidence behind it.
            self.diagnosis = build_diagnosis(
                self.final,
                max_iterations=self._max_iterations,
                evidence_home=self.evidence_home,
            )
            self._audit("diagnosis", diagnosis_summary(self.diagnosis))
            if self._memory is not None:
                # ONE call site for both terminal paths (delivery → record_run, give-up →
                # mark_run_incomplete). Threading it through each of those is how a record gets
                # written on one path and forgotten on the other — and the forgotten path is
                # always the failure path, which is the only one anybody needs later.
                diag = self.diagnosis
                self._safe(lambda: self._memory.record_run_diagnosis(self.run_id, diag))
            approved = bool(self.final.get("approved"))
            if approved:
                self.status = "completed"
            else:
                self.status = "incomplete"
                self.termination_reason = _termination_reason(self.final)
                if self._memory is not None:
                    reason = self.termination_reason or ""
                    self._safe(lambda: self._memory.mark_run_incomplete(self.run_id, reason))
                # ADR-0078: a resilient giveup never resumed the graph, so deliver_node's
                # persist never ran — capture the receipt + claim ledger here or lose them.
                self._persist_receipt()
            # Approved → in_review; otherwise back to todo (never stuck in_progress).
            if self._item_id and self._memory is not None:
                new_status = "in_review" if approved else "todo"
                self._safe(
                    lambda: self._memory.update_backlog_item(self._item_id, status=new_status)
                )
            self._audit(
                "run.completed" if approved else "run.incomplete", self.termination_reason or ""
            )
            self._emit("done", self.snapshot())
        except RunCancelled:
            # No persist/record_run/mark_run_error: the cancel endpoint's
            # history.cancel_run owns the durable CANCELLED row.
            self.status = "cancelled"
            self.pending_interrupt = None
            if self._item_id and self._memory is not None:
                self._safe(lambda: self._memory.update_backlog_item(self._item_id, status="todo"))
            self._record_terminal_diagnosis("cancelled")
            self._audit("run.cancelled")
            self._emit("done", self.snapshot())
        except RunTimeout as exc:
            self.status = "error"
            if self._item_id and self._memory is not None:
                self._safe(lambda: self._memory.update_backlog_item(self._item_id, status="todo"))
            if self._memory is not None:
                self._safe(lambda: self._memory.mark_run_error(self.run_id))
            self._record_terminal_diagnosis("timeout", errored=True)
            self._audit("run.timeout", str(exc))
            self._emit("error", {"message": str(exc)})
        except Exception as exc:
            self.status = "error"
            # A crashed item run must not leave the item stuck in_progress,
            # nor the DB row stuck RUNNING until a restart sweep.
            if self._item_id and self._memory is not None:
                self._safe(lambda: self._memory.update_backlog_item(self._item_id, status="todo"))
            if self._memory is not None:
                self._safe(lambda: self._memory.mark_run_error(self.run_id))
            self._record_terminal_diagnosis("error", errored=True)
            self._audit("run.error", str(exc))
            self._emit("error", {"message": str(exc)})
        finally:
            # Persist the run's final token/cost rollup durably (survives eviction and
            # restart) as a structured `cost` decision row — same pattern as
            # gate_decision/validation_plan, no schema migration. Also written at each
            # park (see _enter_awaiting); the terminal write supersedes those.
            self._persist_cost()
            persist_agent_summaries(self)
            if self._on_done is not None:
                self._safe(self._on_done)
            self._emit("_end", {})
