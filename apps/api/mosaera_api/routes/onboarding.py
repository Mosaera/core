"""Project setup: the choices that decide whether a run can succeed (#121).

Its own router, not a section of ``routes/projects.py`` — that module sits one line under the
god-file ceiling, and this is a distinct concern anyway: onboarding READS a repo and WRITES across
three authorities, where projects.py is lifecycle.

**What this endpoint pair is for.** A newcomer's project is almost always greenfield, whose default
terminal state is a park: ``evaluate_oracle`` needs one of four independence legs and a fresh repo
supplies none of them, so a green self-authored suite still stops at ``oracle_unverified``. That
was operator folklore. ``GET`` states it from measured facts before the first run; ``PUT`` applies
the answers.

**Three authorities in one body, gated separately** — a partial save must never exercise one the
operator did not mean to use:

* ``posture`` — an ADR-0046 governance declaration. Admin, and only when it actually CHANGES (the
  ADR-0047 amendment's rule: re-sending the stored value is not a governance act).
* ``tester_enabled`` — deployment-GLOBAL config (``settings.json``). Admin, like every other write
  through ``/settings/general``. There is no per-project overlay and #121's scope forbids inventing
  one, so the UI says deployment-wide where it offers the toggle.
* ``run_mode`` / ``test_cmd`` / budgets — per-project operator intent. A member's job, like
  ``goal``/``constraints`` on the charter.

**Nothing here is a gate input.** The shape and the plan describe the repo and the configuration;
they inform what the operator CHOOSES. Delivery authority stays with the deterministic gate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_core.config import Settings, coerce_general_patch, general_settings_view
from mosaera_core.models import COST_MODES
from mosaera_core.reposhape import SHAPES, classify_repo_shape, oracle_plan
from mosaera_core.settings_store import write_settings
from mosaera_core.tools.repo import open_project_workspace
from mosaera_memory.models import DEFAULT_RUN_MODE, RUN_MODES
from mosaera_memory.models_charter import CHARTER_POSTURES, DEFAULT_POSTURE

from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import SetupBody

# The synthetic run id the read-only shape scan opens the clone under — the same convention recon
# uses. It never writes, never resets, and never checks out a branch (`open_project_workspace`'s
# read-path contract).
_SETUP_RUN_ID = "setup"


def _shape_payload(project_id: str, settings: Settings, test_cmd: str) -> dict[str, Any]:
    """The repo shape + oracle plan, or an honest ``unavailable`` with the reason.

    A clone that has not landed yet is the COMMON case here (intake clones in the background), so
    it must read as "not yet", never as a guess and never as a 500 (ADR-0035: a check that could
    not run says so).
    """
    try:
        workspace = open_project_workspace(settings.projects_dir, project_id, _SETUP_RUN_ID)
        shape = classify_repo_shape(workspace)
    except Exception:  # the clone is missing, mid-clone, or unreadable
        # The exception is NOT interpolated: `open_project_workspace` raises
        # `project clone not found at <absolute host path>`, which would hand the server's
        # filesystem layout to any authenticated caller for no operator benefit. The state is what
        # the reader needs, and it is the ordinary one — intake clones in the background.
        return {
            "available": False,
            "reason": "the repository has not finished cloning yet — this fills in once it has",
            "shapes": list(SHAPES),
        }
    plan = oracle_plan(shape, tester_enabled=settings.tester_enabled, test_cmd=test_cmd)
    return {
        "available": True,
        "shapes": list(SHAPES),
        "repo_shape": shape.as_dict(),
        "oracle_plan": plan.as_dict(),
    }


def make_onboarding_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    @api.get("/projects/{project_id}/setup")
    def get_setup(project_id: str) -> dict[str, Any]:
        """Everything the setup card renders, in one deterministic read. No model call — this is on
        the interactive path (Deterministic-First)."""
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        settings = Settings.from_env()
        knobs = general_settings_view()
        charter = mem.get_charter(project_id) or {}
        test_cmd = str(detail.get("test_cmd") or "")
        return {
            "completed_at": detail.get("setup_completed_at"),
            "current": {
                "run_mode": str(detail.get("default_run_mode") or DEFAULT_RUN_MODE),
                "posture": str(charter.get("posture") or DEFAULT_POSTURE),
                "test_cmd": test_cmd,
                "tester_enabled": bool(settings.tester_enabled),
                "budget_usd": detail.get("budget_usd"),
                "budget_tokens": detail.get("budget_tokens"),
            },
            # Choice sets come from the SERVER so the UI renders dropdowns from the same vocabulary
            # the write path validates against (ADR-0005) — never a hand-kept list in the SPA.
            "choices": {
                "run_mode": sorted(RUN_MODES),
                "posture": sorted(CHARTER_POSTURES),
                "cost_mode": list(COST_MODES),
            },
            # `source` says whether a knob is env-pinned (read-only in the UI), and `clamped_by`
            # names the knob that overrides it on some runs — the operator must not be shown a
            # toggle whose value does not govern the mode they are about to pick.
            "tester_knob": knobs.get("tester_enabled", {}),
            **_shape_payload(project_id, settings, test_cmd),
        }

    @api.put("/projects/{project_id}/setup")
    def put_setup(project_id: str, body: SetupBody, request: Request) -> dict[str, Any]:
        """Apply the onboarding answers. Every field is None-sentinelled: omitted = leave alone."""
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")

        # --- governance: the ADR-0046 posture, admin-gated only on a REAL change ---
        posture = body.posture.strip().lower() if body.posture is not None else None
        if posture is not None:
            # Compared against the EFFECTIVE posture: a project with no charter row is already
            # governed by DEFAULT_POSTURE, and the GET reports it as such. Comparing against None
            # would 403 an operator who simply accepts the pre-filled card unchanged — the same
            # dead-end the ADR-0047 amendment fixed for the charter, re-created here.
            current = (mem.get_charter(project_id) or {}).get("posture") or DEFAULT_POSTURE
            if posture != current:
                require_admin(request)
            try:
                mem.upsert_charter(project_id, posture=posture)
            except ValueError as exc:  # out-of-set — the ADR-0005 enum rule
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        # --- deployment-global config: the Proctor knob ---
        if body.tester_enabled is not None:
            # The same two lines `/settings/general` uses — one write path for the knob store, so
            # a knob set from here is validated and merged exactly as one set from Settings.
            require_admin(request)
            write_settings(
                Settings.from_env().home,
                coerce_general_patch({"tester_enabled": body.tester_enabled}),
            )

        # --- per-project operator intent ---
        try:
            mem.update_project(
                project_id,
                default_run_mode=(body.run_mode.strip().lower() if body.run_mode else None),
                # "" CLEARS the command — hence the `is not None` test rather than truthiness.
                test_cmd=(body.test_cmd.strip() if body.test_cmd is not None else None),
                setup_completed=body.completed,
            )
        except ValueError as exc:  # out-of-set run mode — deny-by-default in the store
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if body.budget_usd is not None or body.budget_tokens is not None:
            mem.set_project_budget(
                project_id, budget_usd=body.budget_usd, budget_tokens=body.budget_tokens
            )

        _audit_setup(ctx, project_id, body)
        return get_setup(project_id)

    return api


def _audit_setup(ctx: AppContext, project_id: str, body: SetupBody) -> None:
    """Record WHAT was set and by which authority.

    **Known gap, stated rather than implied (red-team 2026-08-24, finding 2).** `AuditEvent.run_id`
    is a NOT NULL foreign key to `runs` and `project_activity` reads through a join on it, so an
    event can only be anchored to a run that exists. Setup is normally answered BEFORE the first
    run — which is precisely the case that goes unrecorded here. This is inherited, not introduced:
    the charter's own `put_charter` audit has the same shape and the same hole. Closing it needs a
    project-anchorable audit row (a migration on a shared table), which is its own change; until
    then, a setup answered on a fresh project leaves no audit line, and neither this docstring nor
    the threat model may claim otherwise.

    The test command is recorded as PRESENT/CLEARED, never verbatim: it is operator-authored, not
    secret, but the activity feed is not the place to re-publish a command line.
    """
    if ctx.history is None:
        return
    parts = []
    if body.posture is not None:
        parts.append(f"posture={body.posture.strip().lower()}")
    if body.tester_enabled is not None:
        parts.append(f"tester_enabled={body.tester_enabled} (deployment-wide)")
    if body.run_mode is not None:
        parts.append(f"run_mode={body.run_mode.strip().lower()}")
    if body.test_cmd is not None:
        parts.append("test_cmd=" + ("set" if body.test_cmd.strip() else "cleared"))
    if not parts:
        return
    try:
        detail = ctx.history.project_detail(project_id)
        runs = (detail or {}).get("runs") or []
        if runs:
            ctx.history.add_audit_event(str(runs[0]["id"]), "project.setup", "; ".join(parts))
    except Exception:  # noqa: S110 — audit is best-effort, never blocks the operator
        pass
