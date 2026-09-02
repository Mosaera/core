"""Attachment processing pipeline tests (fake memory, tmp uploads root)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from mosaera_api.processing import (
    SCANNED_PDF_NOTE,
    SUMMARY_UNAVAILABLE_NOTE,
    chunk_text,
    run_processing,
    sync_context_item,
)
from mosaera_api.uploads import store_upload
from test_api import _FakeProjectMemory


def _add(
    mem: Any,  # duck-typed fake standing in for MemoryStore
    uploads: Path,
    att_id: str,
    filename: str,
    data: bytes,
    mime: str,
    scope: str = "message_only",
) -> None:
    path = store_upload(uploads, "p1", att_id, filename, data)
    mem.add_attachment(
        att_id,
        "p1",
        filename=filename,
        mime_type=mime,
        size_bytes=len(data),
        sha256=att_id,
        storage_path=path,
        status="processing",
        token_estimate=0,
        scope=scope,
    )


def _mem() -> Any:  # duck-typed fake standing in for MemoryStore
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    return mem


def test_large_text_gets_extract_summary_and_chunks(tmp_path: Any) -> None:
    mem, uploads = _mem(), tmp_path / "uploads"
    body = ("alpha line\n" * 400) + "the buried code is OMEGA-7\n" + ("omega line\n" * 400)
    _add(mem, uploads, "att-big", "big.md", body.encode(), "text/markdown", "project_context")
    run_processing(mem, "att-big", uploads, lambda n, t: "A big alpha/omega file.")
    att = mem.get_attachment("att-big")
    assert att is not None and att["status"] == "ready" and att["error_message"] == ""
    kinds = {d["kind"] for d in mem.list_derivatives("att-big")}
    assert kinds == {"text_extract", "summary_short", "chunk"}
    chunks = mem.list_derivatives("att-big", kind="chunk")
    assert len(chunks) >= 2 and any("OMEGA-7" in c["content"] for c in chunks)
    # project_context + ready ⇒ context item registered with the summary.
    items = mem.list_project_context_items("p1")
    assert items[0]["summary"] == "A big alpha/omega file."


def test_summary_failure_does_not_fail_attachment(tmp_path: Any) -> None:
    mem, uploads = _mem(), tmp_path / "uploads"
    body = "important text\n" * 500
    _add(mem, uploads, "att-x", "x.md", body.encode(), "text/markdown")

    def boom(name: str, text: str) -> str:
        raise RuntimeError("model down")

    run_processing(mem, "att-x", uploads, boom)
    att = mem.get_attachment("att-x")
    # Guardrail 3: extraction succeeded ⇒ ready with the honest fallback note.
    assert att is not None and att["status"] == "ready"
    assert att["error_message"] == SUMMARY_UNAVAILABLE_NOTE
    kinds = {d["kind"] for d in mem.list_derivatives("att-x")}
    assert "text_extract" in kinds and "chunk" in kinds and "summary_short" not in kinds


def test_scanned_pdf_is_honest(tmp_path: Any) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    mem, uploads = _mem(), tmp_path / "uploads"
    _add(mem, uploads, "att-pdf", "scan.pdf", buf.getvalue(), "application/pdf")
    run_processing(mem, "att-pdf", uploads, lambda n, t: "should not be called")
    att = mem.get_attachment("att-pdf")
    # Guardrail 5: ready, honest note, and NO invented text derivatives.
    assert att is not None and att["status"] == "ready"
    assert att["error_message"] == SCANNED_PDF_NOTE
    assert mem.list_derivatives("att-pdf") == []


def test_image_gets_thumbnail_only(tmp_path: Any) -> None:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (255, 176, 28)).save(buf, "PNG")
    mem, uploads = _mem(), tmp_path / "uploads"
    _add(mem, uploads, "att-img", "shot.png", buf.getvalue(), "image/png")
    run_processing(mem, "att-img", uploads, lambda n, t: "should not be called")
    att = mem.get_attachment("att-img")
    assert att is not None and att["status"] == "ready"
    derivs = mem.list_derivatives("att-img")
    # Guardrail 4: thumbnail only — no text, no caption, no OCR.
    assert [d["kind"] for d in derivs] == ["thumbnail"]
    thumb = uploads / derivs[0]["storage_path"]
    assert thumb.is_file()
    with Image.open(thumb) as t:
        assert max(t.size) <= 128


def test_corrupt_image_fails_only_that_attachment(tmp_path: Any) -> None:
    mem, uploads = _mem(), tmp_path / "uploads"
    _add(mem, uploads, "att-bad", "bad.png", b"\x89PNG\r\n\x1a\nGARBAGE", "image/png")
    run_processing(mem, "att-bad", uploads, lambda n, t: "")
    att = mem.get_attachment("att-bad")
    # Guardrail 2: this attachment fails cleanly; nothing else is touched.
    assert att is not None and att["status"] == "failed"
    assert "Processing failed" in att["error_message"]


def test_sync_context_item_follows_scope_and_delete(tmp_path: Any) -> None:
    mem, uploads = _mem(), tmp_path / "uploads"
    _add(mem, uploads, "att-s", "s.md", b"tiny note", "text/markdown")
    run_processing(mem, "att-s", uploads, lambda n, t: "Tiny note.")
    assert mem.list_project_context_items("p1") == []  # message_only
    mem.update_attachment("att-s", scope="project_context")
    sync_context_item(mem, "att-s")
    assert mem.list_project_context_items("p1")[0]["title"] == "s.md"
    mem.update_attachment("att-s", scope="message_only")
    sync_context_item(mem, "att-s")
    assert mem.list_project_context_items("p1") == []  # guardrail 8: no stale ctx
    mem.update_attachment("att-s", scope="project_context")
    sync_context_item(mem, "att-s")
    mem.soft_delete_attachment("att-s")
    sync_context_item(mem, "att-s")
    assert mem.list_project_context_items("p1") == []  # delete disables too


def test_chunker_is_deterministic() -> None:
    text = "line one\n" * 1000
    chunks = chunk_text(text, chunk_tokens=100)
    assert len(chunks) > 1
    assert "".join(chunks) == text  # lossless
    assert chunks == chunk_text(text, chunk_tokens=100)  # deterministic
