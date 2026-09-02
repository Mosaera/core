"""Per-dimension fingerprints — the thing that makes the map cheap to keep true.

ADR-0047 §4: each dimension is keyed by a fingerprint over **just its own inputs**.
A lockfile edit must re-recon ``deps`` and must NOT invalidate the security scan.
That is the entire economic argument for the map — one monolithic key means any
change invalidates everything and the cache stops paying.

**Why this does not reuse ``Workspace.tree_hash``.** That hash is stat-based
(``size`` + ``mtime_ns``, never content) and caps at 300 files, and its own docstring
scopes it to "within-run … run/process-scoped, so no cross-run staleness". Both
shortcuts are sound for a within-run memo and wrong here:

- The map is **durable and cross-run**. ``mtime`` does not survive a fresh clone —
  every file gets a new mtime, so a stat-based key would miss every cache on a repo
  that did not change at all. Content-hashing is what makes the fingerprint mean
  "these inputs", not "this checkout".
- The **300-file cap** means a change to file 301 does not move the hash. For a
  within-run diff memo that is a bounded approximation; for a project map it is a
  fingerprint that silently stops noticing edits.

So: sha256 over sorted ``(path, sha256(content))`` pairs. Content in, path included
so a rename registers, sorted so the walk order cannot change the key.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from . import _fs

# A dimension whose inputs are entirely absent — no lockfile, no CI config — still
# needs a stable key, and it must not collide with "one empty file".
EMPTY_FINGERPRINT = "0" * 64


def fingerprint_files(root: Path, rels: Iterable[str]) -> str:
    """Fingerprint the CONTENT of the given repo-relative files.

    Unreadable/missing/symlinked paths (anything :func:`_fs.read_text` refuses) are
    folded in as a distinct ``absent`` marker rather than skipped — otherwise
    "the lockfile was deleted" and "the lockfile never existed" would share a key.
    """
    paths = sorted(set(rels))
    if not paths:
        return EMPTY_FINGERPRINT
    h = hashlib.sha256()
    for rel in paths:
        content = _fs.read_text(root, rel)
        if content is None:
            h.update(f"{rel}\0absent\n".encode())
            continue
        digest = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
        h.update(f"{rel}\0{digest}\n".encode())
    return h.hexdigest()


def fingerprint_listing(rels: Iterable[str]) -> str:
    """Fingerprint a set of paths WITHOUT reading them — for dimensions whose input
    is the shape of the tree (``structure``) rather than file contents."""
    paths = sorted(set(rels))
    if not paths:
        return EMPTY_FINGERPRINT
    h = hashlib.sha256()
    for rel in paths:
        h.update(f"{rel}\n".encode())
    return h.hexdigest()
