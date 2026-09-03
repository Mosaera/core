"""Background attachment processing (MR 4B).

Upload returns immediately with status=``processing``; a daemon thread (same
pattern as intake/decompose) extracts text, generates the summary, chunks
oversized content, thumbnails images, then flips the attachment to ``ready``
or ``failed``. Failures isolate to the one attachment (guardrail 2); a failed
summary never fails an attachment whose extraction succeeded (guardrail 3);
images and scanned PDFs are handled honestly — no OCR, no vision, no invented
content (guardrails 4-5). Reprocessing replaces derivatives (guardrail 9).
"""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mosaera_core.config import Settings
from mosaera_core.models import get_chat_model
from mosaera_memory import MemoryStore

from mosaera_api.pm_context_builder import estimate_tokens
from mosaera_api.uploads import read_stored_text

# Files above this raw size get chunk derivatives; each chunk targets ~1000
# tokens so keyword selection can fill budgets precisely.
CHUNK_TOKEN_SIZE = 1000
CHUNK_THRESHOLD_TOKENS = 1500
THUMBNAIL_MAX_PX = 128

# Honest copy (guardrails 3-5) — also asserted by tests.
SUMMARY_UNAVAILABLE_NOTE = (
    "Summary unavailable. Text was extracted and can still be used in chunks."
)
SCANNED_PDF_NOTE = "No readable text found. This may be a scanned PDF. OCR is not enabled yet."


def chunk_text(text: str, chunk_tokens: int = CHUNK_TOKEN_SIZE) -> list[str]:
    """Split on line boundaries into ~chunk_tokens pieces (deterministic)."""
    max_chars = chunk_tokens * 4
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > max_chars and current:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _make_thumbnail(original: Path, dest: Path) -> bool:
    from PIL import Image

    with Image.open(original) as img:
        img.thumbnail((THUMBNAIL_MAX_PX, THUMBNAIL_MAX_PX))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(dest, "PNG")
    return True


def run_processing(
    memory: MemoryStore,
    attachment_id: str,
    uploads_root: Path,
    summarize: Callable[[str, str], str],
) -> None:
    """The pipeline body — synchronous, seam-injected summarizer for tests."""
    att = memory.get_attachment(attachment_id)
    if att is None:
        return
    try:
        derivatives: list[dict[str, Any]] = []
        text = ""
        error_note = ""
        mime = att["mime_type"]

        if mime.startswith("image/"):
            # Guardrail 4: thumbnail + metadata only; never fake understanding.
            original = (uploads_root / att["storage_path"]).resolve()
            thumb_rel = str(Path(att["storage_path"]).parent.parent / "derivatives" / "thumb.png")
            thumb_rel = thumb_rel.replace("\\", "/")
            _make_thumbnail(original, (uploads_root / thumb_rel).resolve())
            derivatives.append({"kind": "thumbnail", "storage_path": thumb_rel})
        elif mime == "application/pdf":
            original = (uploads_root / att["storage_path"]).resolve()
            text = _extract_pdf_text(original.read_bytes())
            if not text.strip():
                # Guardrail 5: honest scanned-PDF note; never invent OCR text.
                text = ""
                error_note = SCANNED_PDF_NOTE
        else:
            text = read_stored_text(uploads_root, att["storage_path"]) or ""

        token_estimate = estimate_tokens(text) if text else 0
        if text:
            derivatives.append(
                {"kind": "text_extract", "content": text, "token_count": token_estimate}
            )
            # Guardrail 3: a failed summary never fails a usable attachment.
            try:
                summary = summarize(att["filename"], text).strip()
            except Exception:
                summary = ""
            if summary:
                derivatives.append(
                    {
                        "kind": "summary_short",
                        "content": summary,
                        "token_count": estimate_tokens(summary),
                    }
                )
            else:
                error_note = error_note or SUMMARY_UNAVAILABLE_NOTE
            if token_estimate > CHUNK_THRESHOLD_TOKENS:
                for idx, chunk in enumerate(chunk_text(text)):
                    derivatives.append(
                        {
                            "kind": "chunk",
                            "content": chunk,
                            "token_count": estimate_tokens(chunk),
                            "chunk_index": idx,
                        }
                    )

        memory.replace_derivatives(attachment_id, derivatives)
        memory.update_attachment(
            attachment_id,
            status="ready",
            token_estimate=token_estimate or att["token_estimate"],
            error_message=error_note,  # informational; status stays ready
        )
        # Guardrail 8: project-context files register a context item on ready.
        if att["scope"] == "project_context":
            sync_context_item(memory, attachment_id)
    except Exception as exc:  # guardrail 2: only THIS attachment fails
        memory.update_attachment(
            attachment_id,
            status="failed",
            error_message=f"Processing failed: {exc}"[:500],
        )


def sync_context_item(memory: MemoryStore, attachment_id: str) -> None:
    """Bring the ProjectContextItem in line with the attachment's current
    scope/status/deletion — the single sync point (guardrail 8)."""
    att = memory.get_attachment(attachment_id)
    if att is None:
        return
    active = (
        att["scope"] == "project_context" and att["status"] == "ready" and att["deleted_at"] is None
    )
    if active:
        summaries = memory.list_derivatives(attachment_id, kind="summary_short")
        summary = summaries[0]["content"] if summaries else (att["error_message"] or "")
        memory.upsert_project_context_item(
            att["project_id"],
            attachment_id,
            title=att["filename"],
            summary=summary,
            token_count=att["token_estimate"],
        )
    else:
        memory.disable_project_context_item(att["project_id"], attachment_id)


def start_processing(memory: MemoryStore, attachment_id: str) -> None:
    """Fire the pipeline on a daemon thread with the real local model."""
    settings = Settings.from_env()

    def summarize(filename: str, text: str) -> str:
        from mosaera_agents import pm

        return pm.summarize_file(get_chat_model("pm", settings), filename, text)

    threading.Thread(
        target=run_processing,
        args=(memory, attachment_id, settings.uploads_dir, summarize),
        daemon=True,
    ).start()
