"""PM chat + attachment routes: post/list messages, and the full attachment
lifecycle (upload, list, get, patch scope, previews, images, thumbnails, delete).

Extracted from ``create_app`` verbatim (Phase 2 router split). Shared memory
comes through the injected ``AppContext`` (``ctx``); the two attachment helpers
are inner functions here since they close over ``ctx.require_memory``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from mosaera_core.config import Settings

from mosaera_api.decisions import project_decisions
from mosaera_api.pm_context_builder import ContextBudgets
from mosaera_api.pm_stream import stream_turn
from mosaera_api.pm_turn import pm_chat
from mosaera_api.processing import start_processing, sync_context_item
from mosaera_api.proof import project_proof
from mosaera_api.routes.context import AppContext
from mosaera_api.schemas import AttachmentPatchBody, MessageBody
from mosaera_api.uploads import (
    MAX_ATTACHMENTS_PER_MESSAGE,
    UploadRejected,
    new_attachment_id,
    read_stored_text,
    store_upload,
    validate_upload,
)


def make_messages_router(ctx: AppContext) -> APIRouter:
    api = APIRouter()

    # --- PM chat ---

    @api.get("/projects/{project_id}/messages")
    def get_messages(project_id: str, session_id: str | None = None) -> dict[str, Any]:
        # ``session_id`` scopes the transcript to one thread; omitted → the whole project
        # (legacy behaviour). No session is created on a read — first send does that.
        if ctx.history is None:
            return {"messages": []}
        return {"messages": ctx.history.list_messages(project_id, session_id)}

    @api.post("/projects/{project_id}/messages/proposals/{proposal_id}/{status}")
    def resolve_proposal(project_id: str, proposal_id: int, status: str) -> dict[str, Any]:
        """Record that the operator accepted or dismissed a stored proposal (0031).

        This RECORDS an outcome; it applies nothing. A changeset still goes through
        `/backlog/curate/apply` with its validator and delivered-work guard, and a charter still
        needs the admin-gated PUT (ADR-0047 §1: propose is not write). Without it a card the
        operator already handled returns on every reload, which teaches them to ignore cards.
        """
        mem = ctx.require_memory()
        if not mem.set_proposal_status(proposal_id, status):
            raise HTTPException(status_code=400, detail="unknown proposal or status")
        return {"ok": True}

    @api.get("/projects/{project_id}/decisions")
    def get_decisions(project_id: str) -> dict[str, Any]:
        """What is waiting on a human for this project (ADR-0105).

        DERIVED on every call, so a decision disappears the moment its underlying control
        resolves — there is no stored copy to go stale, and none of these entries grants
        anything. Each action names an endpoint that keeps its own gate.
        """
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return {
            "decisions": project_decisions(
                mem, Settings.from_env(), project_id, sessions=ctx.sessions
            )
        }

    @api.get("/projects/{project_id}/proof")
    def get_proof(project_id: str) -> dict[str, Any]:
        """What this project's DELIVERED work stands on, aggregated from its sealed receipts.

        Read-only and DERIVED per call — there is no stored rollup that could drift from the
        receipts it summarizes. The response discloses the run ids it read and the ones it could
        not, so the summary can be reconciled against its own sources by hand; a receipt that is
        missing or unparseable counts as `unknown` on every axis and never as proof.
        """
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return project_proof(mem, project_id)

    def _admit(project_id: str, body: MessageBody) -> tuple[Any, list[str]]:
        """Everything that must be true before a message becomes a turn, in ONE place.

        Shared by the plain and the streaming endpoint. These are guards, not formatting: a
        session belonging to another project and an attachment belonging to another project are
        both cross-tenant reads, and a second copy of them is a second thing to forget to fix.
        """
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        # A named session must belong to THIS project (else one project could post into
        # another's thread). Omitted → pm_chat resolves the project's current session.
        if body.session_id is not None:
            sess = mem.get_pm_session(body.session_id)
            if sess is None or sess["project_id"] != project_id:
                raise HTTPException(status_code=404, detail="unknown session")
        # Guardrail 3: only ready, non-deleted attachments of THIS project link.
        att_ids: list[str] = []
        for ref in body.attachments[:MAX_ATTACHMENTS_PER_MESSAGE]:
            att = mem.get_attachment(ref.attachment_id)
            if (
                att is None
                or att["project_id"] != project_id
                or att["status"] != "ready"
                or att["deleted_at"] is not None
            ):
                raise HTTPException(
                    status_code=422, detail=f"attachment {ref.attachment_id} is not usable"
                )
            att_ids.append(ref.attachment_id)
        # A file alone is a valid message; a fully empty send is not.
        if not body.text.strip() and not att_ids:
            raise HTTPException(status_code=422, detail="message needs text or an attachment")
        return mem, att_ids

    @api.post("/projects/{project_id}/messages")
    def post_message(project_id: str, body: MessageBody) -> dict[str, Any]:
        mem, att_ids = _admit(project_id, body)
        return pm_chat(
            mem, project_id, body.text, attachment_ids=att_ids, session_id=body.session_id
        )

    @api.post("/projects/{project_id}/messages/stream")
    async def post_message_streaming(project_id: str, body: MessageBody) -> StreamingResponse:
        """The same turn, reported as it happens.

        A separate endpoint rather than a mode on the one above, for two reasons. The plain POST
        is the simple contract every non-browser caller wants, and it is what the browser falls
        back to if streaming fails — a fallback that shares an endpoint with the thing it is
        replacing is not a fallback. And the guards run HERE, synchronously, so a bad request is
        still a 4xx with a reason rather than an error frame inside a 200.
        """
        mem, att_ids = _admit(project_id, body)
        return StreamingResponse(
            stream_turn(
                mem,
                project_id,
                body.text,
                attachment_ids=att_ids,
                session_id=body.session_id,
            ),
            media_type="text/event-stream",
        )

    # --- attachments (storage ≠ context injection; processing is async) ---

    def _attachment_public(a: dict[str, Any]) -> dict[str, Any]:
        # storage_path/sha256 are server internals; the client gets metadata only.
        out = {
            k: a[k]
            for k in (
                "id",
                "filename",
                "mime_type",
                "size_bytes",
                "status",
                "error_message",
                "token_estimate",
                "scope",
                "created_at",
            )
        }
        # Honest large-file signal (guardrail 14): raw won't fit the budget.
        out["large"] = a["token_estimate"] > ContextBudgets.from_env().message_attachments
        summaries = (
            ctx.require_memory().list_derivatives(a["id"], kind="summary_short")
            if a["status"] == "ready"
            else []
        )
        out["summary"] = summaries[0]["content"] if summaries else ""
        return out

    @api.post("/projects/{project_id}/attachments", status_code=201)
    async def upload_attachment(
        project_id: str,
        file: UploadFile,
        scope: str = Form("message_only"),
    ) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if scope not in ("message_only", "project_context"):
            raise HTTPException(status_code=400, detail="invalid scope")
        data = await file.read()
        try:
            validated = validate_upload(file.filename or "upload", data)
        except UploadRejected as exc:
            raise HTTPException(status_code=422, detail=exc.reason) from exc
        att_id = new_attachment_id()
        # Dedup by content hash: reuse the stored binary, new metadata record.
        existing = mem.find_attachment_by_hash(project_id, validated.sha256)
        if existing is not None:
            storage_path = existing["storage_path"]
        else:
            storage_path = store_upload(
                Settings.from_env().uploads_dir, project_id, att_id, validated.filename, data
            )
        mem.add_attachment(
            att_id,
            project_id,
            filename=validated.filename,
            mime_type=validated.mime_type,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
            storage_path=storage_path,
            status="processing",  # guardrail 1: honest — the thread is running
            token_estimate=validated.token_estimate,
            scope=scope,
        )
        start_processing(mem, att_id)
        return _attachment_public(mem.get_attachment(att_id))  # type: ignore[arg-type]

    @api.get("/projects/{project_id}/attachments")
    def list_attachments(project_id: str) -> dict[str, Any]:
        mem = ctx.require_memory()
        if mem.project_detail(project_id) is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return {"attachments": [_attachment_public(a) for a in mem.list_attachments(project_id)]}

    @api.get("/projects/{project_id}/attachments/{attachment_id}")
    def get_attachment(project_id: str, attachment_id: str) -> dict[str, Any]:
        mem = ctx.require_memory()
        att = mem.get_attachment(attachment_id)
        if att is None or att["project_id"] != project_id or att["deleted_at"] is not None:
            raise HTTPException(status_code=404, detail="unknown attachment")
        return _attachment_public(att)

    @api.patch("/projects/{project_id}/attachments/{attachment_id}")
    def patch_attachment(
        project_id: str, attachment_id: str, body: AttachmentPatchBody
    ) -> dict[str, Any]:
        mem = ctx.require_memory()
        att = mem.get_attachment(attachment_id)
        if att is None or att["project_id"] != project_id or att["deleted_at"] is not None:
            raise HTTPException(status_code=404, detail="unknown attachment")
        if body.scope not in ("message_only", "project_context"):
            raise HTTPException(status_code=400, detail="invalid scope")
        mem.update_attachment(attachment_id, scope=body.scope)
        # Guardrail 8: the context registry follows scope immediately — no
        # stale context after a change.
        sync_context_item(mem, attachment_id)
        return _attachment_public(mem.get_attachment(attachment_id))  # type: ignore[arg-type]

    def _previewable_attachment(project_id: str, attachment_id: str) -> dict[str, Any]:
        mem = ctx.require_memory()
        att = mem.get_attachment(attachment_id)
        if (
            att is None
            or att["project_id"] != project_id
            or att["deleted_at"] is not None
            or att["status"] != "ready"
        ):
            raise HTTPException(status_code=404, detail="no preview")
        return att

    @api.get("/projects/{project_id}/attachments/{attachment_id}/file")
    def get_file(project_id: str, attachment_id: str) -> Response:
        # Original bytes for the preview overlay — PDFs and images ONLY.
        # Text kinds go through /content as JSON: serving uploaded .html/.js
        # inline from the API origin would be a stored-XSS vector.
        att = _previewable_attachment(project_id, attachment_id)
        if att["mime_type"] != "application/pdf" and not att["mime_type"].startswith("image/"):
            raise HTTPException(status_code=404, detail="no preview")
        root = Settings.from_env().uploads_dir.resolve()
        target = (root / att["storage_path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="no preview")
        return Response(
            content=target.read_bytes(),
            media_type=att["mime_type"],
            headers={"Content-Disposition": "inline"},
        )

    @api.get("/projects/{project_id}/attachments/{attachment_id}/content")
    def get_attachment_content(project_id: str, attachment_id: str) -> dict[str, str]:
        # Text preview for the overlay: the extracted text plus any honest
        # processing note (scanned PDF / summary fallback). Images have none.
        att = _previewable_attachment(project_id, attachment_id)
        if att["mime_type"].startswith("image/"):
            raise HTTPException(status_code=404, detail="no text preview")
        mem = ctx.require_memory()
        extracts = mem.list_derivatives(attachment_id, kind="text_extract")
        if extracts:
            return {"text": extracts[0]["content"], "note": att["error_message"]}
        if att["mime_type"] != "application/pdf":
            # Pre-derivative (4A-era) text uploads: read the stored original.
            root = Settings.from_env().uploads_dir
            text = read_stored_text(root, att["storage_path"])
            if text is not None:
                return {"text": text, "note": att["error_message"]}
        return {"text": "", "note": att["error_message"] or "No readable text available."}

    @api.get("/projects/{project_id}/attachments/{attachment_id}/image")
    def get_image(project_id: str, attachment_id: str) -> Response:
        # Full-size view for the lightbox. Same strictness as thumbnails
        # (guardrail 10): images only, ready + non-deleted, path-guarded,
        # inline disposition, no filesystem paths exposed.
        mem = ctx.require_memory()
        att = mem.get_attachment(attachment_id)
        if (
            att is None
            or att["project_id"] != project_id
            or att["deleted_at"] is not None
            or att["status"] != "ready"
            or not att["mime_type"].startswith("image/")
        ):
            raise HTTPException(status_code=404, detail="no image")
        root = Settings.from_env().uploads_dir.resolve()
        target = (root / att["storage_path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="no image")
        return Response(
            content=target.read_bytes(),
            media_type=att["mime_type"],
            headers={"Content-Disposition": "inline"},
        )

    @api.get("/projects/{project_id}/attachments/{attachment_id}/thumbnail")
    def get_thumbnail(project_id: str, attachment_id: str) -> Response:
        # Guardrail 10: only generated thumbnails, strict path guard, 404
        # for deleted/failed/non-image/no-thumbnail; no fs paths exposed.
        mem = ctx.require_memory()
        att = mem.get_attachment(attachment_id)
        if (
            att is None
            or att["project_id"] != project_id
            or att["deleted_at"] is not None
            or att["status"] != "ready"
            or not att["mime_type"].startswith("image/")
        ):
            raise HTTPException(status_code=404, detail="no thumbnail")
        thumbs = mem.list_derivatives(attachment_id, kind="thumbnail")
        if not thumbs or not thumbs[0]["storage_path"]:
            raise HTTPException(status_code=404, detail="no thumbnail")
        root = Settings.from_env().uploads_dir.resolve()
        target = (root / thumbs[0]["storage_path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="no thumbnail")
        return Response(
            content=target.read_bytes(),
            media_type="image/png",
            headers={"Content-Disposition": "inline"},
        )

    @api.delete("/projects/{project_id}/attachments/{attachment_id}")
    def delete_attachment(project_id: str, attachment_id: str) -> dict[str, str]:
        mem = ctx.require_memory()
        att = mem.get_attachment(attachment_id)
        if att is None or att["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="unknown attachment")
        mem.soft_delete_attachment(attachment_id)  # message links stay intact
        # Guardrail 8: deleted files leave the context registry immediately.
        sync_context_item(mem, attachment_id)
        return {"deleted": attachment_id}

    return api
