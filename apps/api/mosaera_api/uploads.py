"""Attachment upload validation + storage (MR 4A: text/code only).

Server-side validation is authoritative — every check here runs regardless of
what the client claimed (guardrails 1-2): extension allowlist, size limits, and
a content sniff that rejects binary-looking or non-UTF-8 files. The browser MIME
type is never trusted. Binaries live on disk under the uploads root, never in
Postgres; the DB stores a relative path only.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

# 4A allowlist: text/code only. Images/PDF/audio arrive with the processing MR;
# anything else fails honestly as unsupported (guardrail 10).
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".csv": "text/csv",
    ".ts": "text/x-typescript",
    ".tsx": "text/x-typescript",
    ".js": "text/javascript",
    ".jsx": "text/javascript",
    ".py": "text/x-python",
    ".go": "text/x-go",
    ".rs": "text/x-rust",
    ".html": "text/html",
    ".css": "text/css",
}

# 4B: PDFs and images join with per-type limits and magic-byte validation
# (the NUL sniff only applies to text — these are legitimately binary).
PDF_EXTENSIONS: dict[str, str] = {".pdf": "application/pdf"}
IMAGE_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2 MB per text/code file
MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS_PER_MESSAGE = 5

_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),  # + WEBP at offset 8, checked below
}


class UploadRejected(Exception):
    """Validation failure with a user-facing reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class ValidatedUpload:
    filename: str  # sanitized
    mime_type: str  # derived from the allowlist, never from the client
    size_bytes: int
    sha256: str
    kind: str  # text | pdf | image
    text: str  # decoded content (text kind only; others extract in processing)
    token_estimate: int  # chars//4 approximation (text kind only at upload)


def sanitize_filename(name: str) -> str:
    """Display-safe name: no separators, no leading dots, sane length."""
    base = Path(name).name  # strips any path components
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[^\w.\-+ ]", "_", base).strip().lstrip(".")
    return (base or "upload")[:120]


def validate_upload(filename: str, data: bytes) -> ValidatedUpload:
    """Authoritative server-side validation (extension, size, content checks)."""
    clean = sanitize_filename(filename)
    ext = Path(clean).suffix.lower()
    sha = hashlib.sha256(data).hexdigest()

    if ext in ALLOWED_EXTENSIONS:
        if len(data) > MAX_TEXT_BYTES:
            raise UploadRejected("File too large (limit 2 MB for text/code)")
        if b"\x00" in data:
            raise UploadRejected("File looks binary; only readable text is supported")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadRejected("Could not extract text (file is not valid UTF-8)") from None
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return ValidatedUpload(
            filename=clean,
            mime_type=ALLOWED_EXTENSIONS[ext],
            size_bytes=len(data),
            sha256=sha,
            kind="text",
            text=text,
            token_estimate=len(text) // 4,
        )

    if ext in PDF_EXTENSIONS:
        if len(data) > MAX_PDF_BYTES:
            raise UploadRejected("File too large (limit 20 MB for PDF)")
        if not data.startswith(b"%PDF-"):
            raise UploadRejected("Not a valid PDF file")
        return ValidatedUpload(
            filename=clean,
            mime_type="application/pdf",
            size_bytes=len(data),
            sha256=sha,
            kind="pdf",
            text="",
            token_estimate=0,
        )

    if ext in IMAGE_EXTENSIONS:
        if len(data) > MAX_IMAGE_BYTES:
            raise UploadRejected("File too large (limit 10 MB for images)")
        mime = IMAGE_EXTENSIONS[ext]
        magics = _IMAGE_MAGIC[mime]
        if not any(data.startswith(m) for m in magics) or (
            mime == "image/webp" and data[8:12] != b"WEBP"
        ):
            raise UploadRejected(f"File content does not match a {ext} image")
        return ValidatedUpload(
            filename=clean,
            mime_type=mime,
            size_bytes=len(data),
            sha256=sha,
            kind="image",
            text="",
            token_estimate=0,
        )

    raise UploadRejected(f"Unsupported file type '{ext or 'none'}'")


def new_attachment_id() -> str:
    return f"att-{uuid.uuid4().hex[:12]}"


def store_upload(
    uploads_root: Path, project_id: str, attachment_id: str, filename: str, data: bytes
) -> str:
    """Write the original under the uploads root; returns the RELATIVE path.

    Layout: projects/{project_id}/{attachment_id}/original/{filename}. The
    resolved target must stay inside the root (path-traversal guard), files are
    never executable, and this directory is never served as static content.
    """
    rel = Path("projects") / project_id / attachment_id / "original" / filename
    root = uploads_root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise UploadRejected("Invalid storage path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(rel).replace("\\", "/")


def read_stored_text(uploads_root: Path, storage_path: str) -> str | None:
    """Load a stored attachment's text for prompt building; None if missing."""
    root = uploads_root.resolve()
    target = (root / storage_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
