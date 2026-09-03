"""Read-only project reporting: audit trail, cost rollups, discipline metrics, cost projection.

Split out of ``routes/projects.py`` when that module reached the 500-line god-file ceiling. These
four share one shape and nothing else in the file has it: they are pure reads off ``ctx.history``,
they mutate nothing, and every one of them degrades to an empty rollup rather than an error when
there is no durable store — so a memory-only instance renders zeros instead of failing.

Registered by ``make_projects_router`` via ``include_router``, so the routes and their paths are
unchanged from the caller's point of view.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from mosaera_core.config import Settings
from mosaera_core.models import COST_MODES

from mosaera_api.routes.context import AppContext


def make_project_reporting_router(ctx: AppContext) -> APIRouter:
    api = APIRouter()

    @api.get("/projects/{project_id}/activity")
    def project_activity(project_id: str, limit: int = 200) -> dict[str, Any]:
        """The project's persisted audit trail (run lifecycle + governance)."""
        if ctx.history is None:
            return {"events": []}
        return {"events": ctx.history.project_activity(project_id, limit=limit)}

    @api.get("/projects/{project_id}/cost")
    def project_cost(project_id: str) -> dict[str, Any]:
        """Aggregated token/$ spend across the project's runs (durable rollups)."""
        empty = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
            "usd": 0.0,
            "runs_metered": 0,
            "runs_total": 0,
            "by_agent": [],
            "by_model": [],
        }
        return ctx.history.project_cost(project_id) if ctx.history is not None else empty

    @api.get("/projects/{project_id}/metrics")
    def project_metrics(project_id: str) -> dict[str, Any]:
        """Deterministic-first discipline metrics (#22): calls-per-delivered-item
        and the deterministic:LLM ratio, from durable run rollups."""
        empty: dict[str, Any] = {
            "runs_metered": 0,
            "delivered_items": 0,
            "total_calls": 0,
            "total_det_ops": 0,
            "delivered_calls": 0,
            "calls_per_delivered_item": None,
            "det_llm_ratio": None,
            "latency_samples": 0,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "by_agent": [],
        }
        return ctx.history.project_metrics(project_id) if ctx.history is not None else empty

    @api.get("/projects/{project_id}/estimate")
    def project_estimate(project_id: str, cost_mode: str | None = None) -> dict[str, Any]:
        """Conditioned per-run cost projection for a cost-mode (#7, the return of #5).

        Deterministic and honest: prices this project's *historical* average
        per-role token load (from durable rollups) at the SELECTED mode's models.
        Conditioned on the tier — not a misleading blended average. Returns
        ``available: false`` until there's run history to project from."""
        from mosaera_core.cost import TokenUsage, price_usd

        settings = Settings.from_env()
        mode = cost_mode or settings.default_cost_mode
        if mode not in COST_MODES:
            raise HTTPException(status_code=422, detail=f"unknown cost mode '{mode}'")
        base = {"cost_mode": mode, "available": False, "runs_metered": 0}
        if ctx.history is None:
            return base
        agg = ctx.history.project_cost(project_id)
        runs = int(agg.get("runs_metered") or 0)
        if runs == 0:
            return base
        prices = settings.model_prices
        agent_to_role = {"PM": "pm", "Coder": "coder", "Reviewer": "reviewer"}
        per_role: list[dict[str, Any]] = []
        projected = 0.0
        for row in agg.get("by_agent", []):
            role = agent_to_role.get(str(row.get("agent")))
            if role is None:
                continue
            avg_in = float(row.get("input_tokens") or 0) / runs
            avg_out = float(row.get("output_tokens") or 0) / runs
            binding = settings.role_model_for(mode, role)  # type: ignore[arg-type]
            usd = price_usd(binding.model, TokenUsage(round(avg_in), round(avg_out)), prices)
            projected += usd
            per_role.append(
                {
                    "role": role,
                    "provider": binding.provider,
                    "model": binding.model,
                    "avg_input_tokens": round(avg_in),
                    "avg_output_tokens": round(avg_out),
                    "usd": round(usd, 6),
                }
            )
        return {
            "cost_mode": mode,
            "available": True,
            "runs_metered": runs,
            "projected_usd": round(projected, 6),
            "per_role": per_role,
        }

    return api
