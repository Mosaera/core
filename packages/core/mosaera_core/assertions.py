"""AST extraction of test functions and their assertions — shared by the acceptance-test detectors.

`faithfulness.py` (over-strict formatting) and `roundtrip.py` (a value the test never supplied) ask
different questions of the same input: the functions a runner will RUN, and the assertions inside
them. Both used to carry their own copy of that extraction, which is how they drifted — `roundtrip`
understood `unittest` assertions while `faithfulness` walked `ast.Assert` alone and was blind to
every suite this product authors (F37). One definition, imported by both, is what keeps the two
detectors agreeing on what an assertion IS; what to make of one stays with each detector.

Nothing here decides anything. It has no notion of over-strictness, and it never rewrites a test.
"""

from __future__ import annotations

import ast

# `unittest` assertion methods carrying the same meaning as a comparison, mapped to the operator
# they normalise to. ONLY positive forms: `assertNotEqual` / `assertNotIn` / `assertFalse` are
# ABSENCE assertions and are deliberately absent, mirroring the `assert not hasattr(...)` skip the
# detectors already apply — flagging an absence assertion would invert its meaning.
_UNITTEST_COMPARE: dict[str, type[ast.cmpop]] = {
    "assertEqual": ast.Eq,
    "assertEquals": ast.Eq,  # the pre-3.2 alias, still emitted by small models
    "assertIn": ast.In,
}
# Carries a single expression whose TRUTH is asserted — normalises to that expression, so
# `assertTrue(hasattr(m, "_x"))` reads exactly as `assert hasattr(m, "_x")`.
_UNITTEST_TRUTHY = frozenset({"assertTrue"})


class AssertView(ast.Assert):
    """A `unittest` assertion normalised into the bare-`assert` shape the checks understand (F37).

    Subclassing `ast.Assert` is what lets the detectors' checks stay untouched: they read `.test` /
    `.lineno` and neither know nor care that this one was synthesised. `source` keeps the ORIGINAL
    call text so an operator is shown the line that is actually in their file, never a synthesised
    `a == b` they cannot grep for.
    """

    source: str


def dotted(node: ast.expr) -> str:
    """`a.b.c` for an Attribute/Name chain, else ""."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def is_assertion(node: ast.AST) -> bool:
    """Whether ``node`` asserts something — a bare ``assert`` or any ``assert*`` call.

    Deliberately name-based and permissive: it CLASSIFIES, and every caller gates on stronger
    evidence afterwards.
    """
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return str(name).startswith("assert")
    return False


def _call_text(call: ast.Call) -> str:
    try:
        text = ast.unparse(call)
    except (ValueError, AttributeError):  # pragma: no cover - unparse is stable on parsed trees
        return "<assert>"
    return text if len(text) <= 160 else text[:157] + "..."


def _unittest_view(call: ast.Call) -> AssertView | None:
    """A ``unittest`` assertion call as an equivalent ``assert``, or None when it carries no
    comparable meaning (an absence assertion, or a form with no positional operands)."""
    func = call.func
    name = str(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    op = _UNITTEST_COMPARE.get(name)
    if op is not None and len(call.args) >= 2:
        test: ast.expr = ast.Compare(left=call.args[0], ops=[op()], comparators=[call.args[1]])
    elif name in _UNITTEST_TRUTHY and len(call.args) >= 1:
        test = call.args[0]
    else:
        return None
    view = AssertView(test=test, msg=None)
    view.lineno = call.lineno
    view.col_offset = call.col_offset
    view.source = _call_text(call)
    # The operands come from the parsed tree and carry positions; the synthesised Compare and
    # operator nodes do not, and `ast.unparse` on an unlocated tree can raise.
    ast.fix_missing_locations(view)
    return view


def assert_views(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Assert]:
    """Every assertion in ``fn`` as an ``ast.Assert``: real ones as-is, ``unittest`` calls
    normalised. Walk order, so a file's findings keep their source order."""
    views: list[ast.Assert] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            views.append(node)
        elif isinstance(node, ast.Call):
            view = _unittest_view(node)
            if view is not None:
                views.append(view)
    return views


def is_test_class(node: ast.ClassDef) -> bool:
    """Whether a runner would collect this class's ``test_*`` methods.

    TWO conventions, because the product uses one and the bench uses the other:

    - `unittest` collects any **TestCase subclass** and never looks at the class name. A rule keyed
      on the name misses `StorageTests` / `StorageTestCase` entirely — measured on
      `regex/tests/test_regex.py` (class `RegexTests`, 4540 lines), where a `Test*`-prefix rule
      collected ONE function for the whole file. LedgerCLI only escaped this because its Proctor
      happened to write `TestStorage`.
    - pytest collects `Test*`-prefixed classes regardless of base.

    Deliberately NOT "any class with test_ methods": the only non-`Test*` class in all 42 MCB bench
    files is `_Page(HTMLParser)`, a parsing helper. Reading non-test code would change the corpus
    findings and start flagging things no runner executes.
    """
    if any(dotted(base).split(".")[-1].endswith("TestCase") for base in node.bases):
        return True
    name = node.name
    return name.startswith("Test") or name.endswith(("Tests", "TestCase"))


def test_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Top-level ``test_*`` functions plus the ``test_*`` methods of every collected test class —
    the functions a runner RUNS."""
    out: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            out.append(node)
        elif isinstance(node, ast.ClassDef) and is_test_class(node):
            out += [
                m
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                and m.name.startswith("test")
            ]
    return out


def is_skipped(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A ``skip`` / ``skipif`` / ``xfail`` decorated test never runs, so its assertions cannot trap
    the coder — don't flag them (no repair noise on a dead test). Covers `pytest.mark.skip` and
    `unittest.skip` alike."""
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if str(name).lower() in ("skip", "skipif", "xfail"):
            return True
    return False


def expr_names(node: ast.AST) -> set[str]:
    """Every ``Name`` id and ``Attribute`` leaf attr in an expression -- used to classify what an
    operand is derived from (captured output vs. source text vs. a domain value)."""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return names


def assign_targets(node: ast.stmt) -> list[str]:
    """The plain ``Name`` targets a statement binds -- ``a = b = e`` -> [a, b]; ``x: T = e`` ->
    [x]. Tuple/attribute/subscript targets are ignored (we only track simple locals)."""
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets = [node.target]
    return [t.id for t in targets if isinstance(t, ast.Name)]


def str_const(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def int_const(node: ast.expr) -> int | None:
    # bool is a subclass of int -- exclude, or ``== True`` would read as an exit code.
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return node.value
    return None


def snippet(node: ast.Assert) -> str:
    # A normalised `unittest` assertion reports its ORIGINAL call text: the operator must be able to
    # find the line in their file, and `self.assertEqual(a, b)` is not greppable as `a == b`.
    if isinstance(node, AssertView):
        return node.source
    try:
        text = ast.unparse(node.test)
    except (ValueError, AttributeError):  # pragma: no cover - unparse is stable on parsed trees
        return "<assert>"
    return text if len(text) <= 160 else text[:157] + "..."
