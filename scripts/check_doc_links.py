#!/usr/bin/env python3
"""Doc-link guard: fail if a Markdown file has a broken *relative* link.

The docs are a governed system (see ``docs/README.md`` — the authority map): every
canonical doc points at the others, and moves/renames silently rot those pointers. This
guard makes a broken relative link a CI failure, so the doc set stays navigable as files
move. It is deliberately small and deterministic (no network, no anchor resolution).

What it checks: every ``[text](target)`` and ``![alt](target)`` link whose target is a
*local relative path* (optionally with an ``#anchor`` fragment) resolves to a file that
exists on disk. What it SKIPS by design: external links (``http(s)://``, ``mailto:``),
bare in-page anchors (``#section``), and links inside fenced or inline code. Anchor
*fragments* are stripped before the file check — we verify the file exists, not the
heading.

Run: ``python scripts/check_doc_links.py`` (wired into ``make lint``, which CI runs).
Exit 0 = all links resolve; exit 1 = at least one broken link (listed with file:line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Scan the docs tree plus the root-level governance/onboarding Markdown. These are the
# cross-linked canonical set; a broken pointer between them is what this guard catches.
SCAN_DIRS = ("docs",)
ROOT_DOCS = (
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "coding-standards.md",
    "project-brief.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
)

# A Markdown link/image: capture the target inside the parens. `!?` covers images too.
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
# Fenced code blocks (```...```) and inline code spans (`...`) — stripped before matching
# so a bracketed example inside code isn't treated as a link.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _is_external_or_anchor(target: str) -> bool:
    """True for links this guard intentionally does not resolve on disk."""
    t = target.strip()
    if not t or t.startswith("#"):
        return True  # bare in-page anchor
    lower = t.lower()
    return lower.startswith(("http://", "https://", "mailto:", "tel:", "//"))


def _target_path(md_file: Path, target: str) -> Path:
    """Resolve a relative link target (fragment + query stripped) against md_file's dir."""
    clean = target.strip().split("#", 1)[0].split("?", 1)[0].strip()
    # A link may be wrapped in <angle brackets> for paths with spaces.
    clean = clean.strip("<>").strip()
    return (md_file.parent / clean).resolve()


def unbalanced_backtick(text: str) -> int | None:
    """Line of the backtick that leaves inline-code stripping unreliable, or None (F64).

    `_INLINE_CODE_RE` pairs backticks. An ODD number of them outside fenced blocks means the
    pairing runs past the intended span and blanks arbitrary prose — so links inside that region
    are never examined and the guard prints success over content it did not read.

    Found 2026-08-06: prose reading *"Quincy's ```clarify fence"* shifted parity in
    `docs/roadmap.md`, hiding a genuinely broken ADR link for an unknown period. The repo's own
    rule applies to guards too — "zero executed checks is never a pass"
    (docs/architecture/control-register.md).

    This FAILS rather than warns on purpose: a check that can be skipped will be.
    """

    def _blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    outside_fences = _FENCE_RE.sub(_blank, text)
    if outside_fences.count("`") % 2 == 0:
        return None
    # Report the LAST backtick: everything after it is the unexamined region.
    for lineno, line in reversed(list(enumerate(outside_fences.splitlines(), start=1))):
        if "`" in line:
            return lineno
    return 1


def _links_in(text: str):
    """Yield (line_number, target) for every on-disk link candidate, code stripped."""

    # Blank out code so bracketed content inside it can't masquerade as a link, while
    # preserving line numbers (replace each code span with same-length newlines/spaces).
    def _blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    stripped = _FENCE_RE.sub(_blank, text)
    stripped = _INLINE_CODE_RE.sub(_blank, stripped)
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        for m in _LINK_RE.finditer(line):
            yield lineno, m.group(1)


def _iter_md_files():
    seen: set[Path] = set()
    for name in ROOT_DOCS:
        p = ROOT / name
        if p.exists():
            seen.add(p)
            yield p
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.md")):
            if p not in seen:
                seen.add(p)
                yield p


def main() -> int:
    broken: list[str] = []
    unreadable: list[str] = []
    for md_file in _iter_md_files():
        text = md_file.read_text(encoding="utf-8")
        rel = md_file.relative_to(ROOT).as_posix()
        # Coverage FIRST: if stripping is unreliable here, a clean link result means nothing.
        bad_line = unbalanced_backtick(text)
        if bad_line is not None:
            unreadable.append(f"{rel}:{bad_line}")
        for lineno, target in _links_in(text):
            if _is_external_or_anchor(target):
                continue
            resolved = _target_path(md_file, target)
            if not resolved.exists():
                broken.append(f"{rel}:{lineno}  ->  {target.strip()}")

    if unreadable:
        print("Unbalanced backticks — link coverage in these files is UNKNOWN (F64):\n")
        for u in unreadable:
            print(f"  {u}")
        print(
            "\nAn odd backtick count makes inline-code stripping pair across unrelated prose,\n"
            "so links after it are never checked. Escape the stray backtick or fence the block.\n"
            f"{len(unreadable)} file(s) with unknown coverage."
        )
    if broken:
        print("Broken relative doc links (target does not exist):\n")
        for b in broken:
            print(f"  {b}")
        print(f"\n{len(broken)} broken link(s). Fix the path or the moved target.")
    if unreadable or broken:
        return 1

    print("check_doc_links: all relative Markdown links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
