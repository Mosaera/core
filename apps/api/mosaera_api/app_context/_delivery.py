"""Merge-request last-mile + project budget accounting.

The autonomous MR openers (project- and item-granularity, ADR-0019/0021) and the
monthly budget snapshot that gates an autonomous sweep between items.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mosaera_core.config import Settings

from mosaera_api.app_context._base import AppContextBase
from mosaera_api.delivery import open_item_mr, open_project_mr


class DeliveryMixin(AppContextBase):
    def project_budget_status(self, project_id: str) -> dict[str, Any]:
        """Monthly budget snapshot: caps, spend this calendar month (UTC), and
        warn/over flags. The window auto-resets on the 1st. Enforcement uses
        recorded (finished-run) spend, so it halts an autonomous sweep BETWEEN
        items, not mid-run (the per-run cap handles mid-run)."""
        now = datetime.now(UTC)
        cycle_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        resets_at = (
            cycle_start.replace(year=now.year + 1, month=1)
            if now.month == 12
            else cycle_start.replace(month=now.month + 1)
        )
        caps_usd: float | None = None
        caps_tokens: int | None = None
        spent_usd = 0.0
        spent_tokens = 0
        if self.history is not None:
            detail = self.history.project_detail(project_id)
            if detail is not None:
                caps_usd = detail.get("budget_usd")
                caps_tokens = detail.get("budget_tokens")
                # Spend is reported even with no cap set: the Overview budgets card shows
                # the month's spend regardless, and enforcement below stays cap-gated.
                spent = self.history.project_cost(project_id, since=cycle_start)
                spent_usd = float(spent["usd"])
                spent_tokens = int(spent["total_tokens"])

        def frac(spent: float, cap: float | None) -> float:
            return spent / cap if cap else 0.0

        pct = max(frac(spent_usd, caps_usd), frac(spent_tokens, caps_tokens))
        over_usd = caps_usd is not None and spent_usd >= caps_usd
        over_tokens = caps_tokens is not None and spent_tokens >= caps_tokens
        reason = ""
        if over_usd:
            reason = f"${spent_usd:.2f} of ${caps_usd:g}"
        elif over_tokens:
            reason = f"{spent_tokens:,} of {caps_tokens:,} tokens"
        return {
            "budget_usd": caps_usd,
            "budget_tokens": caps_tokens,
            "spent_usd": round(spent_usd, 6),
            "spent_tokens": spent_tokens,
            "cycle_start": cycle_start.isoformat(),
            "resets_at": resets_at.isoformat(),
            "pct": round(pct, 3),
            "warn": pct >= 0.8,
            "over": over_usd or over_tokens,
            "reason": reason,
        }

    def _maybe_open_project_mr(self, project_id: str, detail: dict[str, Any]) -> None:
        """Autonomous MR last-mile (ADR-0019). When an autonomous sweep leaves nothing to
        run AND the whole backlog is delivered, OPEN the project MR (opt-in). It only opens —
        a human still merges. Best-effort: audited, never breaks the sweep. A backlog with
        blocked/locked items remaining is stuck, not complete → left at review, no MR."""
        if self.history is None:
            return
        settings = Settings.from_env()
        if not settings.auto_open_mr or settings.mr_granularity != "project":
            return  # item granularity opens per item as each delivers (ADR-0021)
        backlog = detail.get("backlog") or []
        if not backlog or not all(i["status"] in ("in_review", "done") for i in backlog):
            return  # not a complete delivery — don't open
        if detail.get("mr_url"):
            return  # idempotent: an MR is already open for this project
        try:
            outcome = open_project_mr(self.history, settings, project_id)
        except Exception as exc:  # the last-mile must never break the sweep
            self.history.update_project(project_id, error=f"autonomous MR open error: {exc}")
            return
        runs = detail.get("runs") or []
        rid = runs[0]["id"] if runs else None
        if outcome.opened:
            self.history.update_project(project_id, error="")  # clear any prior pause note
            if rid:
                self._safe_audit(rid, "mr.opened", outcome.url or "(opened; no url in banner)")
        elif outcome.error:  # the connector was called but the push/MR failed
            self.history.update_project(
                project_id, error=f"autonomous MR open failed: {outcome.error}"
            )
            if rid:
                self._safe_audit(rid, "mr.failed", outcome.error)
        # A benign skip (no token / not GitLab / empty diff) leaves the project at review silently.

    def _maybe_open_item_mr(self, project_id: str, item_id: int, run_id: str) -> None:
        """Per-item stacked MR (ADR-0021). On an item's clean delivery, OPEN its own MR —
        source ``mosaera/item-<id>``, targeting the stacked predecessor's branch — so the
        project delivers as one small, reviewable + revertable MR per item. Opt-in
        (``auto_open_mr``) and only in ``item`` granularity; ``project`` keeps the single
        whole-project MR at backlog completion. Best-effort: audited, never breaks the sweep."""
        if self.history is None:
            return
        settings = Settings.from_env()
        if not settings.auto_open_mr or settings.mr_granularity != "item":
            return
        try:
            outcome = open_item_mr(self.history, settings, project_id, item_id)
        except Exception as exc:  # the last-mile must never break the sweep
            self.history.update_project(project_id, error=f"autonomous MR open error: {exc}")
            return
        if outcome.opened:
            self._safe_audit(run_id, "mr.opened", outcome.url or "(opened; no url in banner)")
        elif outcome.error:  # the connector was called but the push/MR failed
            self._safe_audit(run_id, "mr.failed", outcome.error)
        # A benign skip (already open / empty diff / not GitLab / no token) is silent.
