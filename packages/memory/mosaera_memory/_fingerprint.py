"""Pure content fingerprints for coverage-ledger regions (issue #32, #29 P2).

A *region* is a ``(file, function)`` unit of the coverage map. Two hashes describe one, both
derived from the region's OWN source text — never its line numbers — so they survive **line
churn** (edits elsewhere in the file that shift where the region sits):

- ``region_key`` — the region's stable IDENTITY (``file::qualname``). Independent of content, so
  coverage re-attaches to the same region across versions.
- ``region_fingerprint`` — a NORMALIZED hash (dedented; blank lines, comment-only lines, and
  trailing whitespace dropped). Stable across cosmetic edits and reindentation, so a purely
  cosmetic change keeps the same fingerprint. This is the content identity that survives churn.
- ``source_hash`` — the RAW hash of the exact source. Any change at all flips it; it is the rot
  signal (stored ``source_hash`` != current ⇒ the region changed and its coverage is unverified).

No I/O, no AST, no ``core`` imports. The region's source lines are extracted upstream (the graph
integration wiring ``test_node`` → ledger, out of scope for #32) and passed in — keeping the
``memory`` layer a leaf and this module trivially unit-testable."""

from __future__ import annotations

import hashlib
import textwrap


def region_key(file: str, qualname: str) -> str:
    """Stable identity for a region: POSIX file path + fully-qualified function name, e.g.
    ``pkg/mod.py::Cls.method``. Survives line churn AND body edits — it names WHICH region,
    independent of content, so coverage can be re-attached across versions."""
    return f"{file.replace(chr(92), '/')}::{qualname}"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_hash(source: str) -> str:
    """Exact hash of a region's source — the rot signal (any change, even a comment, flips it)."""
    return _sha(source)


def region_fingerprint(source: str) -> str:
    """Line-churn- and cosmetic-stable hash of a region's source.

    Drops blank lines and comment-only lines, strips trailing whitespace, and dedents (removes
    common leading indentation) — so a region that merely moved, was reindented, or had blanks/
    comments edited keeps its fingerprint; only a real change to the code flips it. Conservative
    by design: a trailing inline comment is left in (stripping it safely would need to parse
    strings), so at worst a cosmetic edit is treated as a change — the safe direction (re-verify),
    never the unsafe one (skip a real change)."""
    kept: list[str] = []
    for raw in source.splitlines():
        stripped = raw.rstrip()
        body = stripped.strip()
        if not body or body.startswith("#"):
            continue  # blank or comment-only line — cosmetic, excluded from the fingerprint
        kept.append(stripped)
    normalized = textwrap.dedent("\n".join(kept))
    return _sha(normalized)
