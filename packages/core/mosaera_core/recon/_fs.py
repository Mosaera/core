"""Filesystem reads against an UNTRUSTED clone.

Recon walks and reads a repo it does not trust, on the host. Two guards apply to
every read here, and they are why dimensions never touch ``Path`` directly:

1. **Never follow a symlink out of the clone.** A hostile repo can commit a symlink
   (or a symlinked *directory*) pointing at a host file — ``~/.gitconfig``, the
   GitLab PAT, ``/etc/passwd`` — and recon would happily fingerprint it, read it, and
   record its contents as an "observation about the project". This mirrors the guard
   :meth:`Workspace.file_listing` already applies for the same reason.
2. **Bound every read.** Repo content is attacker-controlled, so file size is
   attacker-controlled. An unbounded ``read_text`` on a 4GB file (or a parser fed one)
   is a host-side DoS in a process that holds the PAT and provider keys.

:func:`walk` deliberately does **not** reuse ``Workspace.file_listing``: that caps at
300 files, which is right for a within-run memo and wrong for reconning a real
project. The cap here is far higher and, when hit, is reported so the caller can say
so rather than silently reconning a prefix of the repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Recon reads whole projects, not a diff — ``Workspace._MAX_LISTING`` (300) would
# truncate any real repo. This bound exists only to stop a pathological tree from
# hanging the host; hitting it is reported, never silent (see WalkResult.truncated).
MAX_FILES = 20_000

# Per-file read ceiling. Bigger than any hand-written source/config file, small enough
# that a hostile 4GB blob cannot exhaust host memory. A file over this is skipped and
# named — recon reports what it could not read rather than pretending it read it.
MAX_READ_BYTES = 2_000_000

_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mosaera",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".tox",
    }
)


@dataclass(frozen=True)
class WalkResult:
    """The files recon may safely read, plus what it refused to.

    ``truncated`` is the honesty bit: True means :data:`MAX_FILES` was hit and this
    listing is a *prefix* of the repo, so any dimension built on it is partial.
    """

    files: tuple[str, ...] = ()
    truncated: bool = False


def walk(root: Path, *, limit: int = MAX_FILES) -> WalkResult:
    """List repo-relative file paths under ``root``, symlink-safe and bounded.

    Skips VCS/build/venv noise, skips symlinks entirely, and skips anything that
    resolves outside ``root`` — so a committed symlink cannot pull a host file into
    the map.
    """
    root_resolved = root.resolve()
    out: list[str] = []
    truncated = False
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        # The escape guard: a symlink (file OR dir) is never read, and neither is
        # anything whose real location is outside the clone.
        if path.is_symlink():
            continue
        try:
            if not path.resolve().is_relative_to(root_resolved):
                continue
            if not path.is_file():
                continue
        except OSError:
            continue
        out.append(rel.as_posix())
        if len(out) >= limit:
            truncated = True
            break
    return WalkResult(files=tuple(out), truncated=truncated)


def read_text(root: Path, rel: str, *, max_bytes: int = MAX_READ_BYTES) -> str | None:
    """Read one repo file as text, or ``None`` if it cannot be safely read.

    ``None`` means *"no content"* — missing, a symlink, outside the clone, over the
    size ceiling, or unreadable. Callers must map that to ``unavailable`` where the
    file was expected, never to "the file is empty" (ADR-0047 §5).
    """
    root_resolved = root.resolve()
    path = root / rel
    try:
        if path.is_symlink():
            return None
        resolved = path.resolve()
        if not resolved.is_relative_to(root_resolved) or not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def exists(root: Path, rel: str) -> bool:
    """True if ``rel`` is a real, non-symlink path inside the clone."""
    root_resolved = root.resolve()
    path = root / rel
    try:
        if path.is_symlink():
            return False
        return path.exists() and path.resolve().is_relative_to(root_resolved)
    except OSError:
        return False
