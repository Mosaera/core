"""Standing standards and ratified clauses (ADR-0082 tiers 1-2).

Its own router rather than an addition to ``routes/projects.py`` (489/500 lines) — and the split
is the honest one anyway: standards are repository facts, clauses are operator decisions, and
neither is a project CRUD concern.

`GET /standards` exists so the vocabulary is inspectable. A deny-by-default surface that will not
say what it accepts is indistinguishable from a broken one, and an operator who cannot see which
parameters a standard leaves open cannot tell a refusal from a bug.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_core.clauses import load_clauses, ratify_clause
from mosaera_core.config import Settings
from mosaera_policies.standards import PARAMS, STANDARDS

from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import ClauseBody


def make_standards_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    @api.get("/standards")
    def list_standards() -> dict[str, Any]:
        """The tier-1 registry and the parameters a clause may bind.

        ``open_params`` is the interesting field: it is what a clause citing this standard may
        set, and everything a standard fixes is simply absent from ``parameters`` — so "waive the
        500-line ceiling" has no name here rather than being denied by a rule someone could amend.
        """
        return {
            "standards": [
                {
                    "id": s.id,
                    "title": s.title,
                    "scope": s.scope,
                    "enforced_by": s.enforced_by,
                    "open_params": list(s.open_params),
                }
                for s in STANDARDS.values()
            ],
            "parameters": [
                {"name": p.name, "kind": p.kind, "min": p.minimum, "max": p.maximum}
                for p in PARAMS.values()
            ],
        }

    @api.get("/projects/{project_id}/clauses")
    def list_clauses(project_id: str) -> dict[str, Any]:
        """Live clauses for this project, READ THROUGH the same validation the engine uses.

        Deliberately not the raw rows: a clause the engine has stopped honouring (its standard was
        retired, its parameter became proof-bearing) must not still be displayed as if in force.
        """
        clauses = load_clauses(ctx.history, project_id, enabled=True)
        return {
            "clauses": [
                {
                    "id": c.id,
                    "project_id": c.project_id,
                    "standard_id": c.standard_id,
                    "binds": c.binds,
                    "value_kind": c.value_kind,
                    "value_num": c.value_num,
                    "when": (
                        {"param": c.when_param, "op": c.when_op, "value": c.when_num}
                        if c.when_param
                        else None
                    ),
                    "because": c.because,
                    "author": c.author,
                }
                for c in clauses
            ],
            "enabled": Settings.from_env().clauses_enabled,
        }

    @api.post("/projects/{project_id}/clauses", status_code=201)
    def ratify(project_id: str, body: ClauseBody, request: Request) -> dict[str, Any]:
        """Ratify one clause. Admin-gated: this is a governance write, not a preference.

        There is no ``scope`` in the body BY DESIGN — scope is inherited from the cited standard
        (ADR-0082 §3). A refusal returns 400 with the reason, because "your clause was rejected"
        without saying which limit it hit teaches an operator nothing.
        """
        require_admin(request)
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        try:
            clause = ratify_clause(
                mem,
                standard_id=body.standard_id,
                binds=body.binds,
                value_kind=body.value_kind,
                value_num=body.value_num,
                project_id=project_id,
                author=body.author,
                because=body.because,
                provenance=body.provenance or {},
                when=(
                    (body.when_param, body.when_op, body.when_num)
                    if body.when_param and body.when_op and body.when_num is not None
                    else None
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": clause.id, "standard_id": clause.standard_id, "binds": clause.binds}

    return api
