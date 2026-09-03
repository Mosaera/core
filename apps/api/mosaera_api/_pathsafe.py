"""Path-safety for URL ids that become filesystem path segments.

A run/project id arrives from the URL (``run_id``, ``project_id``) and is joined onto a
base dir to locate that run's workspace or report (``workspaces_dir / run_id``). Trusted
blindly, a ``..`` segment — reachable as the percent-encoded ``%2e%2e``, which proxies do
NOT normalise and uvicorn decodes back to ``..`` in a single ``[^/]+`` path param —
escapes the base dir. That let ``DELETE /runs/%2e%2e`` ``rmtree`` the whole ``.mosaera/``
tree (``settings.json`` secrets included) and ``GET /runs/%2e%2e/files/settings.json``
stream the unmasked PAT + provider keys, since the containment root was built FROM the
id before it was checked (ADR-0038 / TM-0002).

Two layers, deny-by-default:
- ``safe_segment`` rejects anything that is not a single, benign path segment (the boundary
  guard — a clean 400 before the id ever touches the filesystem or the DB).
- ``contained_path`` additionally resolves the join and proves it stays under the base, so
  even a missed boundary guard cannot reach a path outside the base dir (defence in depth).

Ids are server-minted single segments — run ``YYYYMMDD-HHMMSS-<6hex>`` (cli/_launch),
project ``proj-<slug>-<6hex>`` (projects) — so the benign charset below never rejects a
legitimate id; it only refuses the separators and dot-runs that enable traversal.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def is_safe_id(value: str) -> bool:
    """True iff ``value`` is a single, non-traversing path segment.

    Forbids the empty string, a leading dot (``.``/``..``/dotfiles), any ``..`` run, and
    every path separator — ``/`` and ``\\`` are simply outside the allowed charset.
    """
    return bool(_SAFE_ID.fullmatch(value)) and ".." not in value


def safe_segment(value: str, *, kind: str = "id") -> str:
    """Return ``value`` if it is a safe path segment, else raise ``400``. Boundary guard."""
    if not is_safe_id(value):
        raise HTTPException(status_code=400, detail=f"invalid {kind}")
    return value


def contained_path(base: Path, segment: str, *, kind: str = "id") -> Path:
    """``base / segment`` resolved and PROVEN to stay under ``base`` — else ``400``.

    ``segment`` is first validated as a single safe segment, then the fully-resolved join
    is re-checked against the resolved base. Belt-and-suspenders: the returned path is safe
    to ``rmtree``/serve even if a caller forgot the boundary guard. Use this at every sink
    that turns a URL id into a filesystem path.
    """
    safe_segment(segment, kind=kind)
    root = base.resolve()
    target = (root / segment).resolve()
    if target != root and not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail=f"invalid {kind}")
    return target
