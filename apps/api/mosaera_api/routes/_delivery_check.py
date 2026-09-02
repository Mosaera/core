"""Does the delivered artifact work for someone who clones it? — the endpoint (#104).

The delivery gate proves the code works under the SANDBOX's conditions; this answers the other
question, which the gate was never asked. See `mosaera_core.cleanroom` for what it inspects and why
every gate passed on a repository that did not run.

**Read-only and offline.** It parses the manifest, reads the README as data, and walks the tree's
imports. Nothing is executed, no network is touched, and the project clone is never written to — so
it needs neither the sandbox nor a lock, and it cannot disturb a run in flight.

**It informs; it never gates.** No gate reason, no `packages/policies` change. The operator reads
the verdict and decides, which is what keeps a false positive on an unusual layout from ever
refusing correct work.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from mosaera_core.cleanroom import inspect_tree
from mosaera_core.config import Settings
from mosaera_core.tools.repo.clone import open_project_workspace

from mosaera_api.app_context import AppContext


def register_delivery_check_routes(api: APIRouter, ctx: AppContext) -> None:
    @api.get("/projects/{project_id}/clean-check")
    def clean_check(project_id: str) -> dict[str, Any]:
        """Inspect the project's delivered tree as a consumer would meet it.

        Synchronous on purpose: this reads files, so it returns in well under a second. The
        `recon.py` daemon-thread pattern exists for work that installs packages, and nothing here
        does — which is also why it is safe to call while a run is in flight.
        """
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        settings = Settings.from_env()
        try:
            workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        report = inspect_tree(workspace.root)
        return {
            "status": report.status,
            "findings": report.findings,
            "steps": report.steps,
            "not_checked_reason": report.not_checked_reason,
        }
