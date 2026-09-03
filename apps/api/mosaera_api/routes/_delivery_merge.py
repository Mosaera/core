"""The merge routes — the only endpoints that change a real repository's target branch.

Split out of ``project_delivery.py`` for the god-file ratchet, and the split is not incidental:
everything here is governed by one rule that does not apply to the openers beside it. Opening a
merge request PROPOSES; merging DELIVERS, and cannot be undone from this UI.

**Admin-gated, on this codebase's own stated principle.** ``_branch_ops_allowed`` says it about
branch deletion: *"Installing the project token is admin-gated (ADR-0004, secret write); spending
it irreversibly on the real repository is the same class of authority."* Merging spends it
irreversibly. The admin gate also excludes the bare service token (ADR-0004 — the token is not
admin), which is what keeps ADR-0102's *"a human still merges"* a property rather than a word:
automation holds the service token and therefore cannot reach these.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mosaera_core.config import Settings

from mosaera_api.app_context import AppContext
from mosaera_api.merge_mr import item_mr_readiness, merge_item_mr
from mosaera_api.schemas import MergeBody

# Merge refusals, named. A merge is refused for reasons the operator can act on, and "it didn't
# work" is the failure mode: a button that reports success on a refused merge is strictly worse
# than no button at all. Mirrors `_SKIP_HTTP` so a refused merge reads like every other delivery
# refusal instead of a bare 502.
_MERGE_SKIP_HTTP: dict[str, tuple[int, str]] = {
    "unknown_project": (404, "unknown project"),
    "not_gitlab": (400, "project source is not on the configured GitLab"),
    "no_item": (404, "unknown backlog item"),
    "no_mr": (409, "this item has no merge request to merge"),
    "no_api_token": (
        400,
        "merging needs an api-scoped token for this project; the write_repository push token "
        "cannot merge (add one under Manage GitLab)",
    ),
    "not_open": (409, "this merge request is not open"),
}


def register_merge_routes(
    api: APIRouter,
    ctx: AppContext,
    require_admin: Callable[[Request], None],
    _actor: Callable[[AppContext, Request], str],
    _audit_mr: Callable[..., None],
) -> None:
    @api.get("/projects/{project_id}/items/{item_id}/merge-readiness")
    def item_merge_readiness(project_id: str, item_id: int, request: Request) -> dict[str, Any]:
        """GitLab's live verdict, read at the moment the operator is asked.

        A readiness computed at the last poll describes the MR as it WAS; the operator is about to
        act on it as it IS. Same rule ADR-0108 applies to gate evidence, on the one action here
        that cannot be undone. Admin-gated like the merge itself: this exists only to answer the
        confirmation, and it spends the api token.
        """
        require_admin(request)
        r = item_mr_readiness(ctx.require_memory(), Settings.from_env(), project_id, item_id)
        if r.skip is not None and r.skip != "not_open":
            code, msg = _MERGE_SKIP_HTTP[r.skip]
            raise HTTPException(status_code=code, detail=msg)
        return {
            "status": r.status,
            "sha": r.sha,
            "source_branch": r.source_branch,
            "target_branch": r.target_branch,
            "web_url": r.web_url,
            "error": r.error,
        }

    @api.post("/projects/{project_id}/items/{item_id}/merge")
    def merge_item_merge_request(
        project_id: str, item_id: int, request: Request, body: MergeBody | None = None
    ) -> dict[str, Any]:
        """Merge this item's MR — the only endpoint that changes a real repository's target branch.

        ADMIN-GATED, and deliberately so. `_branch_ops_allowed` states the principle this reuses:
        *"Installing the project token is admin-gated (ADR-0004, secret write); spending it
        irreversibly on the real repository is the same class of authority."* Merging spends it
        irreversibly. The admin gate also excludes the bare service token (ADR-0004 — the token is
        not admin), which is what keeps "a human still merges" (ADR-0102) a property rather than a
        word: automation holds the service token and therefore cannot reach this.
        """
        require_admin(request)
        payload = body or MergeBody()
        outcome = merge_item_mr(
            ctx.require_memory(),
            Settings.from_env(),
            project_id,
            item_id,
            when_pipeline_succeeds=payload.when_pipeline_succeeds,
            sha=payload.sha,
        )
        if outcome.skip is not None:
            code, msg = _MERGE_SKIP_HTTP[outcome.skip]
            raise HTTPException(status_code=code, detail=msg)
        if outcome.error:
            # Recorded even when refused: an attempted merge on a real repository is worth a line
            # whether or not it landed.
            _audit_mr(
                ctx,
                project_id,
                f"actor={_actor(ctx, request)}; item {item_id} merge REFUSED; {outcome.error}",
                event="mr.merge_refused",
            )
            raise HTTPException(status_code=502, detail=outcome.error)
        _audit_mr(
            ctx,
            project_id,
            f"actor={_actor(ctx, request)}; item {item_id} "
            + ("queued behind the pipeline" if outcome.queued else "MERGED"),
            event="mr.merged",
        )
        return {"merged": outcome.merged, "queued": outcome.queued}
