"""Deterministic detection of a test that pins a value it never supplied (F36).

`faithfulness.py` detects over-strict FORMATTING — exact stdout equality, an exit-code pin, source
introspection. This detects a different and stricter failure: an assertion that is *unsatisfiable*,
because it asserts a round-trip of the test's own inputs and slips in a component the test never
supplied and the spec never pinned.

Measured 2026-08-06 (run `20260806-074310-721ec9`). The Proctor wrote:

    result = subprocess.run([... 'add', '12.34', 'food', '--note=Lunch', '--file', temp_file])
    ...
    self.assertIn('2023-01-01,12.34,food,"Lunch"', content)

The command was never given `--date`, so it writes today's date and the test can never pass.
The coder correctly escalated — after ~256k tokens and eleven gates. This is decidable the
moment the file is authored.

DETECTION ONLY. It never rewrites a test: ADR-0062 built a deterministic rewriter for the sibling
module, red-teamed it twice, and reverted it for reopening false-ship. Findings are shown to the
operator; loosening needs judgment.

Two proof gates keep it one-sided, mirroring `faithfulness.py`'s "when unsure, stay silent":

* **Round-trip evidence.** A MAJORITY of the asserted components must be values the test itself
  supplied. Without that this is not a round-trip assertion and the detector says nothing. The
  majority (not "at least one") is load-bearing: in the very same file, `assertIn('date,amount,
  category,note', content)` has `note` as a substring of the supplied `--note=Lunch`, so a
  single-match rule would flag a perfectly good header assertion. One of four is not a round-trip;
  three of four is.
* **Spec-pinned values are faithful.** A component quoted verbatim in the task/plan/design was
  pinned by the spec, exactly as the sibling module treats it.

Both assertion styles are understood — `unittest` calls (`self.assertIn(...)`) and bare `assert`.
Test-function and assertion extraction lives in `assertions.py` and is imported by both detectors,
so they cannot drift on what an assertion IS. (`faithfulness.py` was itself blind to `unittest`
until F37 — exactly the drift that sharing prevents.)

KNOWN GAP, open and DELIBERATELY NOT CLOSED HERE (F44, ADR-0085): the round-trip proof needs >=
`_MIN_COMPONENTS` components, so a STANDALONE unsupplied pin — `self.assertIn("2023-01-01", body)`
with no `--date` supplied — splits to one component and this module stays silent. Measured live on
run `20260806-140201-44bb12`, where that exact assertion reached the coder and it tried to hardcode
the date into the product to satisfy it (F43).

Do not "fix" this by adding a seventh detection rule. ADR-0085 froze the deterministic layer to
STRUCTURAL, one-sided facts after both accretion strategies measured null: the sibling module's F37
fix was correct, properly measured, and reports zero on the product's real suites, while ADR-0070's
LLM spec-review converted nothing in 15 runs. Judging whether an assertion is faithful to the spec
is not structural, and each new class is a photograph of a defect already seen.

That freeze has been answered once, on the record: ADR-0085's 2026-08-20 amendment admitted the two
checks in `bar_integrity.py` — a bar that can never pass (it pins source SPELLING, which the
engine's own `ruff format` rewrites) and one that can never fail (it asserts nothing). Both are
structural in the §1 sense and neither is spec-relative. The rule here is unchanged: a proposal must
answer the freeze, and "it would have caught last week's defect" is not an answer.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from mosaera_core.assertions import is_assertion, is_skipped, test_functions
from mosaera_core.faithfulness import OverstrictFinding

if TYPE_CHECKING:
    from mosaera_core.tools.repo import Workspace

# Components of a rendered row/line. A CSV row splits on commas; a printed line on whitespace.
_SPLIT = re.compile(r"[,\t\s]+")
# Trim the quoting/padding a renderer adds, so `"Lunch"` matches the supplied `Lunch`.
_TRIM = " \t\r\n\"'"
# Below this many components it is a single value, not a round-trip of several inputs.
_MIN_COMPONENTS = 2


def unsupplied_roundtrip_findings(
    workspace: Workspace, authored: list[str], spec_text: str
) -> list[OverstrictFinding]:
    """Assertions that round-trip the test's own inputs but pin a component it never supplied."""
    findings: list[OverstrictFinding] = []
    spec = spec_text or ""
    for rel in authored:
        try:
            tree = ast.parse((workspace.root / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue  # unreadable/unparseable is not evidence of anything
        for fn in test_functions(tree):
            if is_skipped(fn):
                continue
            supplied = _supplied_values(fn)
            if not supplied:
                continue
            for node, literal in _asserted_literals(fn):
                findings += _check(node, literal, supplied, spec, rel)
    return findings


def _check(
    node: ast.AST, literal: str, supplied: set[str], spec: str, rel: str
) -> list[OverstrictFinding]:
    parts = [p.strip(_TRIM) for p in _SPLIT.split(literal) if p.strip(_TRIM)]
    if len(parts) < _MIN_COMPONENTS:
        return []
    matched = [p for p in parts if _is_supplied(p, supplied)]
    if len(matched) * 2 <= len(parts):  # not a majority → no round-trip proof → stay silent
        return []
    missing = [p for p in parts if p not in matched and p not in spec]
    if not missing:
        return []
    names = ", ".join(f"'{m}'" for m in missing[:3])
    return [
        OverstrictFinding(
            file=rel,
            line=getattr(node, "lineno", 0),
            kind="unsupplied_value",
            snippet=literal if len(literal) <= 160 else literal[:157] + "...",
            suggestion=(
                f"this asserts a round-trip of the test's own inputs but pins {names}, which the "
                "test never supplies and the spec does not fix — so it can never pass. Either pass "
                "the value in as an input, or assert only the parts the test controls."
            ),
            auto_loosenable=False,  # ADR-0062: judgment, never a mechanical rewrite
        )
    ]


def _is_supplied(part: str, supplied: set[str]) -> bool:
    # Substring, not equality: an argv item is often `--note=Lunch` while the rendered row carries
    # only `Lunch`. But a ONE-CHARACTER component substring-matches almost any supplied value, and
    # that is not evidence of a round-trip — it manufactures the majority. Measured on
    # `regex/tests/test_regex.py`: `pattern.sub('#', 'a\nb\n') == 'a\nb#\n#'` asserts a
    # TRANSFORMATION, and `'a'` + `'#'` matching carried it over the majority line, flagging the
    # transformed `'b#'` as unsupplied. An exact match still counts at any length.
    return any(part == s or (len(part) > 1 and part in s) for s in supplied)


def _value_args(call: ast.Call) -> list[ast.AST]:
    """A `unittest` assertion's VALUE arguments — its trailing message dropped (F46).

    `assertEqual(a, b, "the row must contain the amount")` puts prose last. Treating it as an
    asserted value is the same mistake as reading `assert cond, "msg"`'s message. Keyword `msg=` is
    already excluded (it is not in `.args`); this drops the positional form. Conservative: only a
    plain string constant in trailing position, and only when there is at least one other argument —
    so `assertIn("needle", haystack)` keeps its literal. It can drop the second literal of a
    literal-vs-literal assertion, which is a degenerate test, and dropping only makes this module
    quieter — the safe direction.
    """
    args = list(call.args)
    if len(args) >= 2:
        last = args[-1]
        if isinstance(last, ast.Constant) and isinstance(last.value, str):
            return list(args[:-1])
    return list(args)


def _literals_not_behind_a_call(node: ast.AST) -> list[str]:
    """String literals reachable in ``node`` WITHOUT passing through a nested call.

    A literal handed to a nested call is an INPUT, not an asserted value:

        self.assertEqual(regex.match(pat, 'c a ts').fuzzy_counts, (0, 2, 0))

    The asserted value is the tuple; `'c a ts'` is what the test fed the matcher. Walking blindly
    into it treats an input as an unsupplied pin — measured on `regex/tests/test_regex.py`, where it
    produced 19 findings, every one a false positive (short components like `'c'` and `'a'` also
    substring-match almost any supplied value, manufacturing the round-trip majority). Containers —
    a list/tuple of expected row values — are still descended, since those ARE the asserted value.
    """
    out: list[str] = []
    stack: list[ast.AST] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, ast.Constant):
            if isinstance(cur.value, str) and cur.value.strip():
                out.append(cur.value)
            continue
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, ast.Call):
                continue  # an input to something, not the thing being asserted
            stack.append(child)
    return out


def _asserted_literals(fn: ast.AST) -> list[tuple[ast.AST, str]]:
    """(node, literal) pairs an assertion compares against — `unittest` calls and bare asserts."""
    out: list[tuple[ast.AST, str]] = []
    for node in ast.walk(fn):
        if not is_assertion(node):
            continue
        # For a `unittest` call the assertion IS a Call, so start from its arguments; for a bare
        # `assert` start from the TEST expression only — `assert cond, "message"` puts prose in
        # `.msg`, and prose is not a value under test (F46). `unittest` puts the same prose in a
        # trailing argument, dropped by `_value_args`. Either way, never descend into nested calls.
        if isinstance(node, ast.Call):
            roots: list[ast.AST] = _value_args(node)
        elif isinstance(node, ast.Assert):
            roots = [node.test]
        else:  # pragma: no cover - is_assertion admits only Assert and Call
            continue
        for root in roots:
            if isinstance(root, ast.Call):
                continue
            out += [(node, lit) for lit in _literals_not_behind_a_call(root)]
    return out


def _supplied_values(fn: ast.AST) -> set[str]:
    """Literals the test hands to the system under test — argv items, call args, dict values.

    An assertion's own ASSERTED literals are excluded — they must not count as their own evidence,
    or every assertion would prove itself. But a literal handed to a NESTED call inside the
    assertion is an input the test supplied, and it counts:

        self.assertEqual(regex.search(pat, 'A B CYZ').group(), 'A B CYZ')

    The test plainly supplied `'A B CYZ'`; excluding the whole assertion hid that and made the
    round-trip read as unsupplied. Exactly the complement of `_literals_not_behind_a_call`: inside
    an assertion, behind a call is an INPUT, not behind a call is the ASSERTED value.

    DOCSTRINGS ARE NOT INPUTS (F46). A docstring is never handed to the system under test, but it is
    English about the same subject, so its words substring-match the assertion's components and
    manufacture the round-trip majority. Measured live: *"Test that pyproject.toml exists in the
    repo root…"* matched 5 of 6 components of the message beside it ("exist" inside "exists", "in",
    "repo", "root", the path), which cleared the majority and flagged the remaining word as an
    unsupplied pin. Prose on both sides of the comparison, evidence on neither.
    """
    docstrings: set[int] = set()
    for holder in ast.walk(fn):
        if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            first = holder.body[0] if holder.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    inside_assert: set[int] = set(docstrings)
    for node in ast.walk(fn):
        if is_assertion(node):
            roots: list[ast.AST] = list(node.args) if isinstance(node, ast.Call) else [node]
            for root in roots:
                if isinstance(root, ast.Call):
                    continue  # a nested call's arguments are inputs — leave them supplied
                stack: list[ast.AST] = [root]
                while stack:
                    cur = stack.pop()
                    inside_assert.add(id(cur))
                    for child in ast.iter_child_nodes(cur):
                        if not isinstance(child, ast.Call):
                            stack.append(child)
    supplied: set[str] = set()
    for node in ast.walk(fn):
        if id(node) in inside_assert or not isinstance(node, ast.Constant):
            continue
        if isinstance(node.value, bool) or node.value is None:
            continue
        if isinstance(node.value, (str, int, float)):
            text = str(node.value).strip()
            if text:
                supplied.add(text)
    return supplied
