"""Backlog routes: list/add/patch items, (re)generate the backlog, and run an
item on the project clone.

Extracted from ``create_app`` verbatim (Phase 2 router split). Shared run state
and lifecycle helpers come through the injected ``AppContext`` (``ctx``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from mosaera_core.claims import claims_as_dicts, claims_from_acceptance
from mosaera_core.clauses import Clause, clause_for, load_clauses
from mosaera_core.config import Settings
from mosaera_core.reachability import reachability
from mosaera_core.sandbox import SandboxUnavailable
from mosaera_core.spec_lint import (
    checkability,
    decidability,
    decidability_findings,
    diagnose_backlog,
    diagnose_item,
)

from mosaera_api.projects import apply_backlog_changeset, curate_backlog, start_decompose
from mosaera_api.routes.context import AppContext
from mosaera_api.routes.preflight import guard_can_run
from mosaera_api.schemas import (
    ApplyChangesetBody,
    BacklogItemBody,
    BacklogItemPatch,
    BacklogReorderBody,
    ClarificationResolveBody,
    CurateBody,
    ItemBlocked,
    ItemDependenciesBody,
    ItemLockBody,
    ItemLocked,
    ItemNeedsClarification,
    ProjectBusy,
    RunItemBody,
)


def _settled_clause(item: dict[str, Any], clauses: tuple[Clause, ...]) -> Clause | None:
    """The ratified clause that answers THIS item's undecidability, or None.

    Derived per finding rather than assumed: a finding whose `param` is empty (a semantic
    ambiguity like "how is the score composed") can never be settled by a clause, whatever is
    ratified — only an operator ask reaches it.
    """
    if not clauses:
        return None
    for finding in decidability_findings([item]):
        if finding.param:
            settled = clause_for(clauses, finding.param)
            if settled is not None:
                return settled
    return None


def _with_checkability(
    items: list[dict[str, Any]], clauses: tuple[Clause, ...] = ()
) -> list[dict[str, Any]]:
    """Attach the per-item Checkability + Decidability verdicts and derived claims.

    THREE orthogonal axes: checkability asks whether a claim BINDS to an oracle (ADR-0079/0080);
    decidability asks whether the text determines ONE answer; reachability asks whether the work it
    demands is something the engine can BUILD (F76). A claim can bind and still leave its value
    unstated — the combination that produced two different scoring models from one brief — and it
    can satisfy both and still be impossible, which cost item 88 five runs. All three ride the row.

    Pure + in-request (same derivation the launch path uses); non-`todo` items get no verdict
    (both skip them — settled work isn't re-judged). Additive fields only, so every existing
    consumer of the item shape is untouched.
    """
    verdicts = checkability(items)
    decidable = decidability(items)
    buildable = reachability(items)
    out = []
    for item in items:
        row = dict(item)
        row["checkability"] = verdicts.get(int(item["id"]))
        row["decidability"] = decidable.get(int(item["id"]))
        # The third axis (F76, #78): can the engine's toolset actually DO this work? Derived and
        # displayed even while `intake_ask_unreachable` is off, so the signal is visible before it
        # is binding — the posture `decidability` shipped with.
        row["reachability"] = buildable.get(int(item["id"]))
        # Status-blind, so work authored before these checks existed is visible at all: the
        # two verdicts above go None once an item leaves `todo`, which is correct for the run
        # path and is exactly why a backfill needs its own derivation.
        diag = diagnose_item(item)
        row["compliant"] = diag.compliant
        row["compliance_reasons"] = diag.reasons
        # A ratified standing decision (ADR-0082) answers the undecidability it settles — but
        # ONLY the one it settles. The parameter is derived from this item's own finding, never
        # assumed: a statement-count clause must not mark a SCORING ambiguity decided, because
        # no number settles "how is the score composed" (greenfield). Named, never silent — a
        # verdict that just vanished is indistinguishable from the check breaking.
        settled = (
            _settled_clause(item, clauses) if row.get("decidability") == "UNDECIDABLE" else None
        )
        row["decided_by"] = settled.id if settled else None
        if settled is not None:
            row["decidability"] = "DECIDABLE"
            row["compliant"] = diag.compliant or not [
                r for r in diag.reasons if "never states a rule" in r
            ]
        claims = claims_from_acceptance(int(item["id"]), str(item.get("acceptance") or ""))
        row["claims"] = claims_as_dicts(claims)
        out.append(row)
    return out


def make_backlog_router(ctx: AppContext) -> APIRouter:
    api = APIRouter()

    @api.get("/projects/{project_id}/backlog")
    def get_backlog(project_id: str) -> dict[str, Any]:
        items = ctx.history.list_backlog_items(project_id) if ctx.history is not None else []
        clauses = load_clauses(ctx.history, project_id, enabled=Settings.from_env().clauses_enabled)
        return {"backlog": _with_checkability(items, clauses)}

    @api.get("/projects/{project_id}/compliance")
    def project_compliance(project_id: str) -> dict[str, Any]:
        """The backfill: how the WHOLE backlog stands against today's intake bar.

        Read-only and derived — nothing is stored and nothing is marked on the item. A stored
        verdict would freeze today's detectors into a column and silently go stale the moment
        they improve; recomputing keeps the answer honest and makes the pass repeatable.

        The `note` travels with the payload on purpose: a non-compliant SETTLED item says the
        acceptance text could not have gated the work, NOT that the delivered code is wrong.
        """
        items = ctx.history.list_backlog_items(project_id) if ctx.history is not None else []
        by_id = {int(i["id"]): i for i in items}
        rows: list[dict[str, Any]] = []
        by_status: dict[str, dict[str, int]] = {}
        for diag in diagnose_backlog(items):
            bucket = by_status.setdefault(diag.status, {"total": 0, "non_compliant": 0})
            bucket["total"] += 1
            if not diag.compliant:
                bucket["non_compliant"] += 1
            source = by_id.get(diag.item_id, {})
            rows.append(
                {
                    "id": diag.item_id,
                    "title": source.get("title", ""),
                    "status": diag.status,
                    "created_at": source.get("created_at"),
                    "checkability": diag.checkability,
                    "decidability": diag.decidability,
                    "compliant": diag.compliant,
                    "reasons": diag.reasons,
                }
            )
        non_compliant = [r for r in rows if not r["compliant"]]
        return {
            "total": len(rows),
            "compliant": len(rows) - len(non_compliant),
            "non_compliant": len(non_compliant),
            "by_status": by_status,
            "items": rows,
            "note": (
                "A non-compliant item means its ACCEPTANCE TEXT would not pass today's intake "
                "bar — every material claim bound, and one answer determined. For settled work "
                "that is a statement about the evidence it was gated on, not a claim that the "
                "delivered code is wrong."
            ),
        }

    @api.post("/projects/{project_id}/backlog", status_code=201)
    def add_backlog_item(project_id: str, body: BacklogItemBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        items = mem.list_backlog_items(project_id)
        position = max((i["position"] for i in items), default=-1) + 1
        item_id = mem.add_backlog_item(
            project_id, body.title, body.description, body.acceptance, position
        )
        return mem.get_backlog_item(item_id)  # type: ignore[return-value]

    @api.patch("/projects/{project_id}/backlog/{item_id}")
    def patch_backlog_item(project_id: str, item_id: int, body: BacklogItemPatch) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.get_backlog_item(item_id) is None:
            raise HTTPException(status_code=404, detail="unknown item")
        mem.update_backlog_item(item_id, **body.model_dump(exclude_none=True))
        return mem.get_backlog_item(item_id)  # type: ignore[return-value]

    @api.put("/projects/{project_id}/backlog/{item_id}/dependencies")
    def set_item_dependencies(
        project_id: str, item_id: int, body: ItemDependenciesBody
    ) -> dict[str, Any]:
        mem = ctx.require_memory()
        item = mem.get_backlog_item(item_id)
        if item is None or item["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="unknown item")
        try:
            mem.set_item_dependencies(item_id, body.depends_on)
        except ValueError as exc:  # self-dep / cycle / cross-project / unknown dep
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return mem.get_backlog_item(item_id)  # type: ignore[return-value]

    @api.put("/projects/{project_id}/backlog/reorder")
    def reorder_backlog(project_id: str, body: BacklogReorderBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        try:
            mem.reorder_backlog(project_id, body.ordered_ids)
        except ValueError as exc:  # not exactly the project's item ids
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"backlog": mem.list_backlog_items(project_id)}

    @api.put("/projects/{project_id}/backlog/{item_id}/lock")
    def set_item_lock(project_id: str, item_id: int, body: ItemLockBody) -> dict[str, Any]:
        mem = ctx.require_memory()
        item = mem.get_backlog_item(item_id)
        if item is None or item["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="unknown item")
        mem.set_item_lock(item_id, body.locked, body.reason)
        return mem.get_backlog_item(item_id)  # type: ignore[return-value]

    @api.post("/projects/{project_id}/backlog/{item_id}/clarification/resolve")
    def resolve_clarification(
        project_id: str, item_id: int, body: ClarificationResolveBody
    ) -> dict[str, Any]:
        """Resolve the item's open clarification (ADR-0080 §1, ADR-0091).

        Accepting (by proposal index, or with edited text) rewrites the acceptance through
        the SAME validated changeset path every backlog edit uses (one `enhance` op) — the
        operator's acceptance is what mints ENTAILED. Rejecting just clears the ask.

        A proposal index is honoured ONLY for a `proposal_kind == "acceptance"` ask. The ESCALATE
        arm writes DIRECTIONS ("amend the criteria so tests/x.py can pass"), and accepting one by
        index used to make that sentence the item's bar. **A row with no `proposal_kind` — every
        row written before ADR-0091 — is treated as `direction` and refused.** Defaulting legacy
        rows the other way would reproduce the defect for every row already in the database, which
        is the tempting and wrong migration."""
        mem = ctx.require_memory()
        item = mem.get_backlog_item(item_id)
        if item is None or item["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="unknown item")
        open_req = mem.item_clarification(item_id)
        if open_req is None:
            raise HTTPException(status_code=409, detail="no open clarification on this item")
        if body.disposition == "bar_stands_retry":
            # The bar is right and the CODE is wrong. Acceptance untouched; the affirmation is
            # RECORDED so the arm does not re-ask the identical question on the next sweep.
            mem.resolve_item_clarification(item_id, status="affirmed", resolution="")
            return _with_checkability([mem.get_backlog_item(item_id)])[0]  # type: ignore[list-item]
        if not body.rejected:
            if body.edited_text and body.edited_text.strip():
                new_acceptance = body.edited_text.strip()
            elif body.accepted_proposal_index is not None:
                if open_req.get("proposal_kind") != "acceptance":
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "this ask's proposals are DIRECTIONS, not acceptance text — write the "
                            "acceptance you want in edited_text, or answer bar_stands_retry"
                        ),
                    )
                proposals = list(open_req.get("proposals") or [])
                if not (0 <= body.accepted_proposal_index < len(proposals)):
                    raise HTTPException(status_code=400, detail="proposal index out of range")
                new_acceptance = proposals[body.accepted_proposal_index]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="accept a proposal index, provide edited_text, or set rejected",
                )
            try:
                apply_backlog_changeset(
                    mem,
                    project_id,
                    [
                        {
                            "op": "enhance",
                            "id": item_id,
                            "acceptance": new_acceptance,
                            "why": "operator resolved the intake clarification",
                        }
                    ],
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Retain the exchange (#63 ledger): a dismissal records status only; an accept
        # records the operator's answer (the same text the enhance op just applied).
        mem.resolve_item_clarification(
            item_id,
            status="dismissed" if body.rejected else "resolved",
            resolution="" if body.rejected else new_acceptance,
        )
        return _with_checkability([mem.get_backlog_item(item_id)])[0]  # type: ignore[list-item]

    @api.post("/projects/{project_id}/backlog/curate")
    def curate_backlog_route(project_id: str, body: CurateBody | None = None) -> dict[str, Any]:
        """Quincy PROPOSES a backlog changeset (reorder/enhance/lock/set-deps). Review-only
        — nothing is applied until the changeset is approved via curate/apply."""
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return {"changeset": curate_backlog(mem, project_id, body.instruction if body else "")}

    @api.post("/projects/{project_id}/backlog/curate/apply")
    def apply_changeset_route(project_id: str, body: ApplyChangesetBody) -> dict[str, Any]:
        """Apply an approved changeset atomically (validated; whole set rejected on any bad op)."""
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        try:
            backlog = apply_backlog_changeset(
                mem, project_id, body.changeset, allow_delivered=body.allow_delivered
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"backlog": backlog}

    @api.post("/projects/{project_id}/backlog/generate", status_code=202)
    def generate_backlog(project_id: str) -> dict[str, str]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        # Clear stale todo items so a regenerate replaces (not duplicates) them.
        mem.clear_todo_backlog(project_id)
        start_decompose(mem, project_id)
        return {"status": "generating"}

    @api.post("/projects/{project_id}/backlog/{item_id}/run", status_code=201)
    def run_backlog_item(
        project_id: str, item_id: int, body: RunItemBody | None = None
    ) -> dict[str, Any]:
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        item = mem.get_backlog_item(item_id)
        if item is None or item["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="unknown item")
        # Refuse before resolving anything else: an instance with no model backend cannot serve
        # this run, and saying so here beats failing downstream (#119).
        guard_can_run()
        # An explicit per-run mode always wins; otherwise the project's onboarding default (#121),
        # which itself defaults to `guided`.
        mode = (body.mode if body else None) or str(detail.get("default_run_mode") or "guided")
        # _launch_item reserves the project atomically and releases on failure;
        # no manual pre-check/discard here (that pattern was the launch race).
        # A per-run mode never chains — chaining stays the project Autonomous flag.
        try:
            session = ctx.launch_item(
                project_id,
                item,
                mode=mode,
                chain=False,
                max_iterations=body.max_iterations if body else None,
                budget_tokens=body.budget_tokens if body else None,
                budget_usd=body.budget_usd if body else None,
                cost_mode=body.cost_mode if body else None,
                override=body.override if body else False,
            )
        except ProjectBusy as exc:
            raise HTTPException(
                status_code=409, detail="another item is already running on this project's clone"
            ) from exc
        except ItemBlocked as exc:
            raise HTTPException(
                status_code=409,
                detail=f"blocked by unfinished dependencies: {exc.blocking}",
            ) from exc
        except ItemLocked as exc:
            raise HTTPException(
                status_code=409,
                detail=f"soft-locked: {exc.reason or 'unlock or run with override'}",
            ) from exc
        except ItemNeedsClarification as exc:
            raise HTTPException(
                status_code=409,
                # The PREFIX is byte-stable — tests and the UI read it. Only the tail differs,
                # because the decidability case is counter-intuitive: the item looks fine and the
                # tests would pass, against a value nobody specified.
                detail=(
                    "open clarification: "
                    f"{exc.claim_text[:120] or 'a material claim needs clarifying'} — "
                    + (
                        "a check binds to this, but the text doesn't fix the answer; "
                        "answer it (or run with override)"
                        if exc.axis == "decidability"
                        else "resolve it (or run with override)"
                    )
                ),
            ) from exc
        except SandboxUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"could not start run: {exc}") from exc
        return session.snapshot()

    return api
