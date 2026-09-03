"""Which seed-failing authored tests are provably over-strict — no hidden grader needed.

**The split (P2 Stage B).** A test the Proctor authored that FAILS against the pre-implementation
seed is one of two things:

- **legitimately red** — it exercises the NEW behaviour the task asks for, which does not exist
  yet (the ADR-0013 test-first contract working as designed); or
- **over-pinned EXISTING behaviour** — it asserts something the task does not change, against code
  that already works. For that test the current code IS the reference, and its seed failure is
  proof of over-strictness: the ADR-0062 class (`assert lines[0] == "1 [ ] Buy milk"` pinning
  whitespace an already-working `list` never promised), measured at 13/23 reference-failing
  authored tests on MCB-21.

**The discriminator is deterministic and one-sided.** NEW-behaviour tokens are the identifiers in
the material claims' backtick code-spans (ENTAILED text the operator approved — `tag`, `find`, a
changed symbol). A seed-failing test whose reachable source mentions **none** of them cannot be
exercising the new behaviour, so it is flagged. Reachable = the test function's own segment plus
same-file module-level helpers it calls (one hop), so a test delegating to `make_tagged_entry()`
is not falsely flagged. Every undecidable case — no tokens, unparseable file, an id that cannot be
resolved — flags NOTHING. A missed flag costs a diagnostic; a false flag would point the Proctor's
repair at a legitimate bar, which is the unsafe direction.

Detection only: this module names tests, it never edits one (ADR-0062 reverted mechanical
loosening and that revert stands).
"""

from __future__ import annotations

import ast
import re

_CODE_SPAN = re.compile(r"`([^`]+)`")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Identifiers too generic to indicate NEW behaviour — flooding the token set with these would
# un-flag everything (safe direction, but it would kill the diagnostic). Python keywords/builtins
# that routinely appear in code-spans.
_STOP = frozenset(
    "def class return import from print str int float list dict set bool None True False "
    "self args kwargs main test tests py python json".split()
)


def new_behaviour_tokens(claims: list[dict[str, object]]) -> frozenset[str]:
    """Identifiers from the MATERIAL claims' code-spans — the vocabulary of the asked-for change.

    Material only: premise sentences (``material=False``) describe the PRE-change state, and their
    spans would mark old-behaviour tests as new-behaviour (the exact confusion this module splits).
    """
    out: set[str] = set()
    for c in claims:
        if not isinstance(c, dict) or not c.get("material", True):
            continue
        for span in _CODE_SPAN.findall(str(c.get("text") or "")):
            for ident in _IDENTIFIER.findall(span):
                if len(ident) >= 3 and ident.lower() not in _STOP:
                    out.add(ident)
    return frozenset(out)


def _test_functions(src: str) -> list[str]:
    """Names of the module-level test functions in ``src`` (empty on a parse fault)."""
    try:
        mod = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    return [
        n.name
        for n in mod.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test")
    ]


def _reachable_source(src: str, test_name: str) -> str | None:
    """The test function's segment plus same-file module-level functions it calls (one hop)."""
    try:
        mod = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    fns = {n.name: n for n in mod.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    fn = fns.get(test_name)
    if fn is None:
        return None
    pieces = [ast.get_source_segment(src, fn) or ""]
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            helper = fns.get(node.func.id)
            if helper is not None and helper.name != test_name:
                pieces.append(ast.get_source_segment(src, helper) or "")
    return "\n".join(pieces)


def runtime_overstrict(
    authored_sources: dict[str, str],
    seed_failures: list[str] | None,
    claims: list[dict[str, object]],
) -> list[str]:
    """Seed-failing authored test ids that provably assert PRE-EXISTING behaviour.

    ``authored_sources`` maps authored test paths to their source. Only ids that resolve to a
    known file and function are considered; everything undecidable is silently not flagged.
    """
    if not seed_failures:
        return []
    tokens = new_behaviour_tokens(claims)
    if not tokens:
        return []  # deny-by-default: no vocabulary of the new behaviour, no claim about any test
    # UBIQUITY FILTER (found by the first fixture, not by foresight): a shared runner helper
    # carries harness vocabulary — `python -m journal …` puts `journal` into EVERY CLI test's
    # reachable source via the one-hop rule, un-flagging everything. A token present in every
    # authored test discriminates nothing, so it is dropped; only tokens that at least one test
    # LACKS can separate new-behaviour tests from old. If that empties the set, flag nothing.
    reaches: list[str] = []
    for src in authored_sources.values():
        for fn_name in _test_functions(src):
            reach = _reachable_source(src, fn_name)
            if reach is not None:
                reaches.append(reach)
    if reaches:
        tokens = frozenset(
            t
            for t in tokens
            if not all(re.search(rf"\b{re.escape(t)}\b", r, re.IGNORECASE) for r in reaches)
        )
    if not tokens:
        return []
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in sorted(tokens)) + r")\b", re.IGNORECASE
    )
    flagged: list[str] = []
    for node_id in seed_failures:
        path, _, name = node_id.partition("::")
        file_src = authored_sources.get(path)
        if file_src is None or not name:
            continue
        reach = _reachable_source(file_src, name.split("[")[0])
        if reach is None:
            continue
        if not pattern.search(reach):
            flagged.append(node_id)
    return sorted(flagged)
