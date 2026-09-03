"""Mosaera planning doctrine — the trusted, code-assembled corpus the PM follows.

The GLOBAL doctrine (``core.md``) is injected into every plan/design as a trusted
``## Doctrine`` block — distinct from the UNTRUSTED repo files and attachments (which
are data to reason about, not instructions to follow). It is kept compact because it
rides every planning turn; the richer topic files (methodology / decomposition /
acceptance_criteria / pitfalls) are the corpus for humans and the future per-task
retrieval seam (see ``doctrine_chunks``). Loading is code-first — deterministic, no
model call (ADR-0002) — and cached, since the doctrine is static.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent

# The trusted framing: the inverse of the UNTRUSTED_NOTE used for repo/attachment data.
_TRUSTED_HEADER = (
    "## Doctrine\n"
    "Mosaera's own planning doctrine — methodology you FOLLOW when you plan and design. "
    "This is trusted guidance, not repository or stakeholder data.\n"
)


def _cap(text: str, budget: int) -> str:
    text = text.strip()
    if len(text) <= budget:
        return text
    return text[:budget].rstrip() + "\n… (doctrine truncated)"


@lru_cache(maxsize=8)
def load_doctrine_topic(topic: str, budget: int = 1800) -> str:
    """One topical doctrine file as a trusted block, or "" if it is missing.

    Five doctrine files ship; only `core.md` was ever loaded. `acceptance_criteria.md` in
    particular has sat unread — a trusted, on-point document about writing checkable criteria,
    while F60 (HIGH, open, issue #70) is *"the PM writes acceptance criteria without reading the
    code"*. It is not the whole of that defect, which is about code evidence, but a PM authoring a
    bar should at least be given the house rules for authoring one.

    Same treatment as the global block: the file's own H1 is dropped so the trusted header is the
    only one, and the body is capped.
    """
    if not topic.replace("_", "").isalnum():  # never build a path from unvalidated text
        return ""
    try:
        body = (_DIR / f"{topic}.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("# ")).strip()
    return _TRUSTED_HEADER + "\n" + _cap(body, budget) if body else ""


@lru_cache(maxsize=1)
def load_global_doctrine(budget: int = 1500) -> str:
    """The compact, always-on global planning doctrine as a trusted ``## Doctrine``
    block, or "" if the corpus is missing. Cached (the content is static)."""
    try:
        body = (_DIR / "core.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    # Drop the file's own H1 title; the block supplies its own trusted header.
    body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("# ")).strip()
    if not body:
        return ""
    return _TRUSTED_HEADER + "\n" + _cap(body, budget)
