"""The non-use oracle — mechanical proof that nothing references a removed thing (slice 1.2).

A SUBTRACT item ("remove the deprecated `legacy_export` helper") has no behavioural signature to
test: the *absence* of code cannot be exercised by an acceptance test, and a green suite proves only
that whatever remains still works — not that the thing is gone, and certainly not that nothing still
calls it. That gap is why a removal item deadlocked: it minted a material claim with **no oracle**
(`claims.classify_sentence` matched no pattern, so it fell through to `("none", True)`), which by
construction can never be satisfied.

This is the missing oracle. It is the load-bearing piece of the slice, and it is deliberately
**deterministic** — mechanical reference enumeration, no model call, no sandbox.

**Tri-state, and the third state is the important one** (the shape `structural_spec` established):

- ``True``  — the symbol is defined nowhere and referenced nowhere. The removal is proven.
- ``False`` — something still references it. A real objection: shipping would break that caller.
- ``None``  — the question could not be asked (no target named, nothing parseable). **No effect.**

``None`` never vouches. An empty complaint list cannot tell "nothing references it" from "no file
could be read", and treating those alike is how a removal that breaks every caller would ship.
Like `structural_spec`, this can only ever DOWNGRADE — it turns a would-be ship into a park, and
never the reverse.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from mosaera_core.testintegrity import is_test_file

# Directories that are never part of the delivered work. `.mosaera` is the agent scratch space
# (ADR-0064) and a reference there is not a live caller; the rest are build/VCS noise.
_SKIP_DIRS = frozenset(
    {".git", ".mosaera", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
)

# A dotted target ("pkg.mod.helper") is proven by its LAST segment: `from pkg.mod import helper`
# binds the bare name, so searching only the full path would miss every real caller.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# What the claim says was removed. A removal sentence names its target in a code span
# ("Remove the deprecated `legacy_export` helper"), which is both the convention in every MCB brief
# and the only part of the sentence precise enough to search for. Prose without a code span names
# no target, and that resolves to `None` — unprovable, therefore unshippable.
_CODE_SPAN = re.compile(r"`([^`]+)`")


def removal_target(text: str) -> str:
    """The symbol a removal claim is about, or ``""`` when the sentence names none."""
    for span in _CODE_SPAN.findall(text):
        candidate = span.strip()
        # Skip spans that are obviously not a symbol: flags, paths with no identifier, prose.
        if _IDENTIFIER.search(candidate):
            return candidate
    return ""


def _symbol_of(target: str) -> str:
    """The bare identifier a reference would use. ``pkg.mod.helper`` -> ``helper``."""
    parts = [p for p in _IDENTIFIER.findall(target)]
    return parts[-1] if parts else ""


def _py_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        out.append(p)
    return out


def _split_by_kind(root: Path, files: list[Path]) -> tuple[list[Path], list[Path]]:
    """``(production, tests)`` — the partition `non_use_proven` judges against.

    MEASURED DEFECT (2026-08-10, MCB-27 over-parked 2/2 with the hidden grader PASSING). The oracle
    counted a *test asserting the symbol is gone* as a live caller: `from pkg import gone` inside a
    `pytest.raises(ImportError)` block is an `ast.ImportFrom` like any other, and `_SKIP_DIRS` never
    excluded `tests/`. **The test that proves a removal was the thing that refuted it** — this
    slice's own hidden grader contains that exact assertion, so the oracle would have refused its
    own proof.

    Splitting is not a weakening, because the two ways a test can name a removed symbol are already
    covered — by a *different, independent* control:

    - it **calls** the symbol      → the suite goes red → `validation_failed` parks the run;
    - it **asserts the absence**   → the suite stays green, and it is not a caller in any sense.

    So the only test-side reference that matters is one that breaks the suite, and the suite is
    judged elsewhere. The question this oracle owns is narrower and stays intact: *does anything in
    the delivered PRODUCTION tree still reach for this?*
    """
    production: list[Path] = []
    tests: list[Path] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        (tests if is_test_file(rel) else production).append(path)
    return production, tests


def _references_in(tree: ast.AST, symbol: str) -> bool:
    """Whether this module references ``symbol`` as a NAME, an attribute, or an import.

    AST rather than text: a bare `grep` counts the word inside strings, comments and unrelated
    docstrings, and a false reference here reports a removal as unsafe when it is fine — noise that
    would make the oracle useless rather than merely conservative.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == symbol:
            return True
        if isinstance(node, ast.Attribute) and node.attr == symbol:
            return True
        if isinstance(node, ast.ImportFrom):
            if any(a.name == symbol or a.asname == symbol for a in node.names):
                return True
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[-1] == symbol or a.asname == symbol for a in node.names):
                return True
        # A definition that still exists is not a "reference", but it means the thing was NOT
        # removed — which is the same answer to the question the caller is asking.
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node.name == symbol:
                return True
    return False


def _dynamic_mentions(tree: ast.AST, symbol: str) -> bool:
    """Whether the symbol appears as a whole STRING literal — a possible dynamic reference.

    RED TEAM R3 (found and fixed during slice 1). `getattr(mod, "legacy_export")` and
    `importlib.import_module` name their target as a *string*, so the AST pass above sees no
    `Name`, no `Attribute` and no import, and happily vouched for a removal that a live caller
    still used. A false vouch is the ONLY unsafe direction this oracle has: every other error makes
    it refuse a fine removal, which is waste, while this one ships breakage.

    EXACT match on the constant, not a substring: `"call legacy_export() someday"` in a docstring
    is prose, not a reference, and treating prose as a caller would make the oracle refuse almost
    everything. `getattr(m, "legacy_export")` produces the bare string and is caught.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == symbol:
                return True
    return False


def consumers_of(root: Path, target: str) -> tuple[list[str], list[str]] | None:
    """``(referencing_files, defining_files)`` for ``target``, or ``None`` when unaskable.

    Verb-arc slice 4 — the mirror of `non_use_proven`. SUBTRACT asks *"is this referenced
    anywhere?"* and demands the answer be empty; MODIFY asks *"who references this?"* and needs the
    list, because a behaviour change lands on everyone in it (Hyrum's Law).

    Shares `_references_in` and `_py_files` with `non_use_proven` deliberately: a second definition
    of "what counts as a reference" would drift from the one that judges removals, and the two
    slices would disagree about the same tree.
    """
    symbol = _symbol_of(target)
    if not symbol or not root.is_dir():
        return None
    files = _py_files(root)
    if not files:
        return None
    referencing: list[str] = []
    defining: list[str] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        defines = any(
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and n.name == symbol
            for n in ast.walk(tree)
        )
        if defines:
            defining.append(rel)
        elif _references_in(tree, symbol):
            # A file that DEFINES the symbol is not one of its consumers — counting it would make
            # "someone depends on this" true for every symbol that exists.
            referencing.append(rel)
    return sorted(referencing), sorted(defining)


def non_use_proven(root: Path, target: str) -> tuple[bool | None, str]:
    """``(verdict, evidence)`` — is ``target`` absent from the tree under ``root``?

    ``evidence`` always names what was actually examined, so a park can say *why* rather than
    leaving the operator to re-derive it (the `vouch` treatment: a control whose non-firing is
    invisible costs a day of archaeology).
    """
    symbol = _symbol_of(target)
    if not symbol:
        return None, "no removable symbol named in the claim"
    if not root.is_dir():
        return None, f"no tree to examine at {root}"

    files = _py_files(root)
    if not files:
        return None, "no Python sources to examine"

    # Only the PRODUCTION tree can refute a removal — see `_split_by_kind` for why, and for the
    # measured defect that made this necessary. Test-side references are still walked, because a
    # verdict that silently ignored them would be the invisible-control defect this repo has
    # measured four times: they are named in the evidence instead.
    production, test_files = _split_by_kind(root, files)
    if not production:
        # A tree of nothing but tests proves nothing. "Zero production callers" and "zero
        # production files examined" are the same sentence with opposite meanings, and vouching on
        # an empty walk is the green-by-vacancy shape this repo keeps measuring.
        return None, "no production sources to examine (every file is a test)"

    unparseable: list[str] = []
    hits: list[str] = []
    dynamic: list[str] = []
    for path in production:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            unparseable.append(rel)
            continue
        if _references_in(tree, symbol):
            hits.append(rel)
        elif _dynamic_mentions(tree, symbol):
            dynamic.append(rel)

    test_mentions: list[str] = []
    for path in test_files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue  # an unreadable TEST cannot refute a removal; the suite judges it
        if _references_in(tree, symbol) or _dynamic_mentions(tree, symbol):
            test_mentions.append(rel)
    seen_in_tests = (
        f"; named in {', '.join(sorted(test_mentions)[:3])} (tests — the suite judges those)"
        if test_mentions
        else ""
    )

    if hits:
        return False, f"`{symbol}` is still referenced by: {', '.join(sorted(hits)[:5])}"
    if dynamic:
        # Not proven referenced, but not proven ABSENT either — `None`, which blocks. Saying
        # "still referenced" would overstate; saying "proven gone" would be the false vouch.
        return None, (
            f"`{symbol}` appears as a string literal in {', '.join(sorted(dynamic)[:3])} — a "
            "dynamic reference (getattr / import_module) cannot be ruled out"
        )
    if unparseable:
        # Deny-by-default: a file we could not read might hold the one live caller. "We did not
        # look" is never "it is not there" — the same rule ADR-0076 applies to security evidence.
        return None, f"could not parse {len(unparseable)} file(s): {', '.join(unparseable[:3])}"
    return True, (
        f"`{symbol}` is defined and referenced nowhere across "
        f"{len(production)} production file(s){seen_in_tests}"
    )
