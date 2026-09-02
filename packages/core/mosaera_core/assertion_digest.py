"""A compact, durable record of what the authored suite actually ASSERTS.

**Why this exists.** `overstrict_vs_ref` proves that over-strict authoring is the dominant
over-park driver (44% over-park against 10%, n=163), and that the production detector catches 7%
of it. Improving that recall needs the assertions the detector **missed** — and the corpus does not
have them. Of the labelled runs whose patch survives, six positives retain the authored test text.
The scorecard keeps three authoring fields and all three are scalars: it can say a run *was*
over-strict and never *which assertion* made it so.

So this records the assertions themselves, once, at authoring time.

**Why snippets rather than counts.** `assertion_profile` already gives assertions-per-function, and
it is the wrong shape for this question: over-strictness is about *what* is asserted, not how much.
An exact-output equality and a behavioural range check are both "1".

**Why not the whole file.** A scorecard is written per run and read in bulk; storing suites verbatim
would bloat every future analysis to answer one question. The digest is capped on both axes and
carries the one line each assertion is about.

**Untrusted by construction.** Test source is repo content, which `AGENTS.md` classifies as data,
never instructions. Nothing reads this back into a prompt; it exists to be analysed offline.
"""

from __future__ import annotations

import ast

_MAX_ASSERTIONS = 200
_MAX_CHARS = 240


def _qualname(stack: list[str]) -> str:
    return "::".join(stack)


def assertion_snippets(source: str) -> list[str] | None:
    """``qualname :: <assert source>`` for every assertion inside a test function.

    ``None`` when the source does not parse — the same contract `assertion_profile` holds, and for
    the same reason: unparseable is *unknown*, never "asserts nothing". A caller that collapses
    those two turns a syntax error into evidence.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    out: list[str] = []

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, [*stack, child.name])
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                # Only test functions: a real assert in an uncalled helper is not the suite
                # asserting anything, which is the rule `authored_suite_asserts_behaviour` applies.
                if child.name.startswith("test"):
                    walk(child, [*stack, child.name])
            elif isinstance(child, ast.Assert):
                if len(out) >= _MAX_ASSERTIONS:
                    return
                text = ast.get_source_segment(source, child) or ast.dump(child.test)
                flat = " ".join(text.split())[:_MAX_CHARS]
                out.append(f"{_qualname(stack)} :: {flat}")
            else:
                walk(child, stack)

    walk(tree, [])
    return out


def suite_assertion_digest(workspace: object, authored: list[str]) -> list[str]:
    """The digest across every authored file. Best-effort: an unreadable or unparseable file
    contributes a MARKER rather than silence, because "we could not look" and "there was nothing"
    are different facts and collapsing them is the defect this repo keeps re-measuring."""
    digest: list[str] = []
    root = getattr(workspace, "root", None)
    if root is None:
        return digest
    for rel in authored:
        if len(digest) >= _MAX_ASSERTIONS:
            break
        try:
            src = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            digest.append(f"{rel} :: <unreadable>")
            continue
        snippets = assertion_snippets(src)
        if snippets is None:
            digest.append(f"{rel} :: <unparseable>")
            continue
        digest.extend(f"{rel}::{s}" for s in snippets[: _MAX_ASSERTIONS - len(digest)])
    return digest
