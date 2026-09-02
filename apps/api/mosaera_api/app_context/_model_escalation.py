"""Live model escalation, and the rule that an escalation must have HAPPENED (ADR-0022, ADR-0016).

Split out of ``_escalation.py`` at the 500-line god-file ceiling — and cohesive on its own terms,
exactly as ``bench/_escalation_run.py`` is on the benchmark side: it owns one question the rest of
that file does not ask, *did the escalated producer actually speak?*, and the answer decides whether
the run is evidence about that model at all.
"""

from __future__ import annotations

import contextlib
from typing import Any

from mosaera_core.bench.escalation import diagnose_bottleneck, escalate_role
from mosaera_core.config import Settings
from mosaera_core.models import cloud_tier_allowed

from mosaera_api.app_context._base import AppContextBase
from mosaera_api.runner import RunSession
from mosaera_api.schemas import ItemBlocked, ItemLocked, ItemNeedsClarification, ProjectBusy

# What became of a live escalation, on the run record. Mirrors the bench's vocabulary
# (`bench/_escalation_run.py`) so a live escalation and a benchmarked one are describable in the
# same words — the reason `run_diagnosis` exists as one definition rather than two.
ESCALATION_APPLIED = "applied"
ESCALATION_NO_CALLS = "no_calls_discarded"


class ModelEscalationMixin(AppContextBase):
    def _try_model_escalation(
        self,
        project_id: str,
        item: dict[str, Any],
        chain: bool,
        mode: str,
        run_id: str,
        session: RunSession,
        used_settings: Settings,
        escalation_attempt: int,
    ) -> bool:
        """Live model escalation (ADR-0022). An autonomous item run ended honestly
        ``incomplete`` (too-weak model, not a crash/park) — before parking, diagnose the one
        bottleneck role and, if it has a next tier on its ``role_escalation`` ladder, RE-RUN
        the same item with that stronger model. Bounded (``max_model_escalations``), gated
        (``model_escalation_enabled``, a separate opt-in), autonomous-sweep-only. Returns True
        when a re-run was launched (so ``_after`` skips the pause note), False to fall through
        to the pause. Reuses ADR-0016's pure diagnose/escalate funcs verbatim."""
        if self.history is None or mode != "autonomous":
            return False
        if not used_settings.model_escalation_enabled:
            return False
        if escalation_attempt >= used_settings.max_model_escalations:
            return False
        # No live grader → diagnose from the terminal signals only (acceptance_failed=False).
        role = diagnose_bottleneck(session.final or {}, used_settings)
        esc = escalate_role(used_settings, role) if role else None
        if esc is None:
            return False  # nothing attributable / ladder exhausted → park honestly
        # Off-box egress gate (ADR-0024): a CLOUD escalation tier may only fire when the operator
        # consented to egress AND the model is priced (so the USD cap can bound it). Otherwise
        # refuse the escalation — don't silently send repo content off-box on an unattended run.
        bump = esc.settings.role_model(esc.role)
        if not cloud_tier_allowed(used_settings, bump.provider, bump.model):
            self._safe_audit(
                run_id,
                "escalation.blocked",
                f"{esc.role}: cloud egress not permitted ({bump.model})",
            )
            return False
        self._safe_audit(run_id, f"escalation.{role}", esc.label)
        self.history.update_project(project_id, error="")  # the re-run's outcome sets the next note
        try:
            self.launch_item(
                project_id,
                item,
                mode="autonomous",
                chain=chain,
                escalation_settings=esc.settings,
                escalation_attempt=escalation_attempt + 1,
                # The role that was bumped, carried into the re-run so `_after` can ask whether it
                # actually SPOKE (ADR-0016 Amendment 1's owed live detector).
                escalation_role=esc.role,
            )
        except (ProjectBusy, ItemBlocked, ItemLocked, ItemNeedsClarification):
            return False  # raced / became blocked between release and re-reserve → pause
        except Exception as exc:  # a build/setup failure must never leave the item silently todo
            self.history.update_project(project_id, error=f"escalation retry failed: {exc}")
            return True  # handled (with its own note) — don't also write the generic pause
        return True

    def _note_escalation_outcome(
        self,
        project_id: str,
        run_id: str,
        session: RunSession,
        role: str,
        attempt: int,
    ) -> None:
        """Record whether the escalated role actually made a model call — and say so loudly if not.

        **The defect this closes.** Across the stored corpus, 45 of 61 recorded escalations produced
        ZERO calls from the escalated role, every one binding an unfunded cloud key. `error` stayed
        `None` and `escalation_path` still named the model, so a failed escalation was
        indistinguishable from *"a stronger model tried and could not"* — and read the second way it
        inverted the conclusions drawn from six runs. ADR-0016 Amendment 1 fixed the bench and
        recorded the live path as owed; this is that.

        **Why post-hoc.** `cloud_tier_allowed` requires the model be PRICED, which is what lets the
        USD cap bound the spend — but priced is not funded. An exhausted key, a revoked key and a
        typo'd model name all clear it identically, and reachability is only knowable after a call.
        So the honest signal is `role_calls(...) == 0`, which already exists because a role with no
        successful calls contributes no `by_agent` row at all.

        Unlike the bench, nothing is DISCARDED here: the live path re-launches the item as its own
        run with its own record, so no earlier result is overwritten. What was missing was the
        record itself — an operator reading the history could not tell the two apart. Best-effort:
        a bookkeeping failure must never break the sweep.
        """
        from mosaera_core.cost import role_calls

        try:
            rollup = session.cost_meter.rollup()
            spoke = role_calls(rollup, role) > 0
        except Exception as exc:
            self._safe_audit(run_id, "escalation.outcome-unknown", f"{type(exc).__name__}: {exc}")
            return
        if spoke:
            self._safe_audit(run_id, "escalation.outcome", f"{ESCALATION_APPLIED}: {role}")
            return
        detail = (
            f"{role} made ZERO model calls on escalation attempt {attempt} — the stronger model "
            "was never reached (an unfunded, revoked or misspelled binding looks exactly like "
            "this). This run is not evidence about that model."
        )
        self._safe_audit(run_id, "escalation.outcome", f"{ESCALATION_NO_CALLS}: {detail}")
        if self.history is not None:
            # Visible where an operator actually looks, not only in the audit trail.
            with contextlib.suppress(Exception):
                self.history.update_project(project_id, error=detail)
