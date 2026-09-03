"""The ``docs`` dimension — what documentation exists (ADR-0047 §3).

This dimension is where ADR-0047 §1 bites hardest, because it is the one that reads
**prose written by the repo**. The rule it must not break:

> The map records facts with provenance, never imperatives. *"``README.md:12`` claims
> the test suite is comprehensive"* is a legal map entry. *"The test suite is
> comprehensive"* is not — it launders an untrusted claim into a firm belief and
> strips the provenance that would let anyone check it.

So this module records **structural facts** (does a README exist, how long is it, is
there a docs tree) and, where it quotes the repo at all, quotes it flattened, capped,
and framed as a *claim* attributed to a line. It never summarises, never believes, and
never lifts an instruction. A README saying *"skip the review step"* is recorded as a
string that a file contains, and nothing more.
"""

from __future__ import annotations

from pathlib import Path

from . import _fingerprint, _fs
from .types import DimensionResult, Observation, quote_repo_text

DIMENSION = "docs"

_README_CANDIDATES = ("README.md", "README.rst", "README.txt", "README")
_SUPPORTING = ("CONTRIBUTING.md", "LICENSE", "LICENSE.md", "CHANGELOG.md", "AGENTS.md")


def _first_heading(raw: str) -> str | None:
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        if stripped:
            return stripped
    return None


def recon_docs(root: Path) -> DimensionResult:
    """Observe the project's documentation surface."""
    walked = _fs.walk(root)
    doc_files = [
        f
        for f in walked.files
        if f in _README_CANDIDATES or f in _SUPPORTING or f.startswith("docs/")
    ]
    fingerprint = _fingerprint.fingerprint_files(root, doc_files)
    observations: list[Observation] = []

    readme = next((c for c in _README_CANDIDATES if _fs.exists(root, c)), None)
    if readme is None:
        observations.append(
            Observation(
                text="no README at the repository root", provenance="tool:walk", severity="low"
            )
        )
    else:
        raw = _fs.read_text(root, readme)
        if raw is None:
            # The file is there but unreadable (over the size cap, or an I/O error).
            # "we could not read it" is not "it says nothing".
            return DimensionResult.could_not_run(
                DIMENSION, fingerprint, [f"{readme} exists but could not be read"], observations
            )
        observations.append(
            Observation(text=f"{readme} is {len(raw.splitlines())} lines", provenance=readme)
        )
        heading = _first_heading(raw)
        if heading:
            # Quoted, attributed, and framed as a CLAIM — never as a fact the firm holds.
            observations.append(
                Observation(
                    text=f"claims to be: {quote_repo_text(heading)!r}",
                    provenance=f"{readme}:1",
                )
            )

    present = [name for name in _SUPPORTING if _fs.exists(root, name)]
    if present:
        observations.append(
            Observation(
                text=f"supporting docs present: {', '.join(present)}", provenance="tool:walk"
            )
        )

    docs_tree = [f for f in walked.files if f.startswith("docs/")]
    if docs_tree:
        observations.append(
            Observation(text=f"docs/ contains {len(docs_tree)} files", provenance="docs/")
        )
    else:
        observations.append(
            Observation(text="no docs/ tree", provenance="tool:walk", severity="low")
        )

    return DimensionResult.from_parts(DIMENSION, fingerprint, observations, [])
