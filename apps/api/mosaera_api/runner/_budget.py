"""Budget concern: soft/hard spend-ceiling detection, the hard-cap cancel, the
soft-ceiling human park, and mid-run agent-escalation resolution by run mode.
"""

from __future__ import annotations

import time
from typing import Any

from mosaera_api.runner._base import _CANCELLED, RunCancelled, RunSessionBase, json_safe

# The resume verbs `_supervise` routes on (ADR-0082 `GateOutcome.effect`). A verb outside this
# set is not forwarded: supervise treats any truthy effect as "the operator chose deliberately"
# and skips its legacy inference, so an unknown string would continue a run rather than stop it.
_RESUME_EFFECTS = frozenset({"approve", "send_back", "end_run"})


class BudgetMixin(RunSessionBase):
    def _budget_breach(self) -> tuple[str, float, float] | None:
        """First crossed spend ceiling as ``(dimension, spent, cap)``, else None.
        Dimensions read the live CostMeter rollup: usd, tokens (total_tokens),
        tool_calls (calls). Cheap — a dict compare — so it's fine per chunk."""
        if not self._budget:
            return None
        roll = self.cost_meter.rollup()
        spent_by = {
            "usd": float(roll["usd"]),
            "tokens": float(roll["total_tokens"]),
            "tool_calls": float(roll["calls"]),
        }
        for dim, spent in spent_by.items():
            cap = self._budget.get(dim)
            if cap is not None and spent >= cap:
                return dim, spent, cap
        return None

    def _hard_breach(self) -> tuple[str, float, float] | None:
        """First crossed ABSOLUTE hard ceiling (usd/tokens), else None."""
        if not self._hard_budget:
            return None
        roll = self.cost_meter.rollup()
        spent_by = {"usd": float(roll["usd"]), "tokens": float(roll["total_tokens"])}
        for dim, spent in spent_by.items():
            cap = self._hard_budget.get(dim)
            if cap is not None and spent >= cap:
                return dim, spent, cap
        return None

    def _cancel_hard(self, breach: tuple[str, float, float]) -> None:
        """A hard ceiling was crossed: cancel the run outright (not re-askable) and
        write the durable terminal record before raising."""
        dim, spent, cap = breach
        self._audit("budget-hard-cap", f"{dim}: {spent:g} >= hard {cap:g} — cancelling run")
        if self._memory is not None:
            self._safe(lambda: self._memory.cancel_run(self.run_id))  # durable CANCELLED
            # Distinguish this automatic stop from a user cancel: the existing
            # CapabilityLimitNote surfaces a persisted capability_limit reason.
            reason = f"Stopped — hard {dim} budget ceiling reached: {spent:g} >= {cap:g}."
            self._safe(lambda: self._memory.add_decision(self.run_id, "capability_limit", reason))
        raise RunCancelled

    def _park_budget(self, breach: tuple[str, float, float]) -> None:
        """Park at a crossed SOFT spend ceiling until a human decides. Approve → grant
        another budget's worth on that dimension and continue; deny → stop with
        partial work and a durable terminal record. Runner-side park (no graph
        interrupt): the stream generator stays open, we just pause consuming it."""
        dim, spent, cap = breach
        self._audit("budget-park", f"{dim}: {spent:g}/{cap:g}")
        if self._on_park is not None:
            self._safe(self._on_park)
        roll = self.cost_meter.rollup()
        elapsed = int(time.time() - self.started_at) if self.started_at else 0
        self._enter_awaiting(
            {
                "id": f"budget-{dim}-{int(spent)}",
                "value": {
                    "action": "budget",
                    "breach": dim,
                    "spent": round(spent, 6),
                    "cap": cap,
                    "budget": dict(self._budget),
                    "cost": roll,
                    # Honest context so the human isn't asked to blindly fund a loop:
                    # how many times this was already raised, wall-clock, and calls.
                    "raised_before": self._budget_approvals,
                    "elapsed_s": elapsed,
                    "calls": int(roll["calls"]),
                    "phase": self.phase,
                },
            }
        )
        if self._memory is not None:
            self._safe(lambda: self._memory.mark_run_awaiting(self.run_id))
        self._audit("interrupt", "budget")
        self._emit("interrupt", self.pending_interrupt)
        parked_at = time.time()
        decision = self._resume.get()
        self._parked_seconds += time.time() - parked_at
        if decision is _CANCELLED:
            raise RunCancelled
        approved = bool(decision.get("approve")) if isinstance(decision, dict) else False
        if not approved:
            # A denial is terminal: write the durable CANCELLED record here (the
            # cancel endpoint isn't involved), so the run row never stays RUNNING.
            self._audit("budget-denied", f"{dim}: {spent:g}/{cap:g}")
            if self._memory is not None:
                self._safe(lambda: self._memory.cancel_run(self.run_id))
            raise RunCancelled
        # Approved → resume: grant another budget's worth on the breached dimension
        # so the run proceeds to the next ceiling instead of re-parking on this chunk.
        self.pending_interrupt = None
        self.status = "running"
        if self._memory is not None:
            self._safe(lambda: self._memory.mark_run_running(self.run_id))
        self._budget[dim] = spent + cap
        self._budget_approvals += 1
        self._audit(
            "budget-approved", f"{dim} -> {self._budget[dim]:g} (raised {self._budget_approvals}x)"
        )

    def _resolve_escalation(self, intr: Any, value: dict[str, Any]) -> dict[str, Any]:
        """Resolve a mid-run agent escalation by RUN MODE (ADR-0012), mirroring the
        delivery gate's mode split. Autonomous → Quincy re-scopes, recorded and
        NON-BLOCKING (the run keeps moving). Guided/High-Assurance → park for a human,
        reusing the gate's park/resume path. Every path emits a durable `escalation`
        transcript event so the decision is auditable. Returns the resume value the
        supervise node reads to route (re-scope → plan, or give up → honest incomplete)."""
        kind = str(value.get("kind", "blocked"))
        reason = str(value.get("reason", ""))
        # Autonomous = auto-approve WITHOUT high-assurance (HA always defers to a human,
        # same test the delivery gate uses).
        if self._auto_approve and not self._high_assurance:
            self._audit("escalation-auto", f"{kind}: {reason}"[:200])
            self._emit(
                "escalation",
                {
                    "node": "supervise",
                    "kind": kind,
                    "reason": reason,
                    "resolution": "rescope",
                    "mode": self.mode,
                },
            )
            return {
                "resolution": "rescope",
                "feedback": f"autonomous re-scope after coder {kind}: {reason}",
            }
        # Guided / High-Assurance: park for a human (same machinery as the delivery gate).
        self._enter_awaiting({"id": intr.id, "value": json_safe(intr.value)})
        if self._memory is not None:
            self._safe(lambda: self._memory.mark_run_awaiting(self.run_id))
        self._audit("interrupt", "escalation")
        self._emit(
            "escalation",
            {
                "node": "supervise",
                "kind": kind,
                "reason": reason,
                "resolution": "human_park",
                "mode": self.mode,
            },
        )
        self._emit("interrupt", self.pending_interrupt)
        if self._on_park is not None:
            self._safe(self._on_park)
        parked_at = time.time()
        decision = self._resume.get()
        self._parked_seconds += time.time() - parked_at
        if decision is _CANCELLED:
            raise RunCancelled
        self.pending_interrupt = None
        self.status = "running"
        if self._memory is not None:
            self._safe(lambda: self._memory.mark_run_running(self.run_id))
        d = decision if isinstance(decision, dict) else {}
        return {
            "resolution": "human",
            "approve": bool(d.get("approve")),
            "feedback": str(d.get("feedback", "")),
            # The amendment authorization (ADR-0087, #65) exists ONLY on this branch. The
            # autonomous branch above returns `rescope` and never constructs this key, so an
            # unattended run cannot authorize amending its own acceptance tests — the mirror of
            # `_sanction`'s `actor == "human"` rule, which is the constraint the #65 red team
            # pinned. The engine re-checks `resolution == "human"` rather than trusting this.
            "authorize_tests": [str(x) for x in (d.get("authorize_tests") or [])],
            # The gate's computed verb for the option the operator clicked (ADR-0082/0107).
            # THIS DICT IS THE SEAM: it is rebuilt from scratch rather than forwarded, so a field
            # added to the resume queue in `_lifecycle.approve` and not named here is silently
            # dropped — which is exactly what happened to `effect` on 2026-08-21, leaving
            # "Stop and record it honestly" inert in production while three tests stayed green
            # (they injected the resume BELOW this line). Red-team R1, two agents independently.
            #
            # Narrowed to the verbs supervise actually routes on: an unknown verb resolves to ""
            # (legacy inference) rather than being passed through, because `not effect` suppresses
            # the legacy give-up clause — so an unrecognised string would fail OPEN and continue a
            # run the operator asked to stop. Deny-by-default belongs on this side of the seam.
            "effect": (str(d.get("effect", "")) if d.get("effect") in _RESUME_EFFECTS else ""),
        }
