"""Can an authored test serve as a BAR at all? -- the two checks ADR-0085's amendment admitted.

`faithfulness.py` asks whether an assertion is over-strict RELATIVE TO THE SPEC. These two ask a
prior, spec-independent question, which is why they live apart from the five classes ADR-0085 §1
froze: a test can fail that question with no spec at all.

- **It can never pass.** `assert "action='store_true'" in cli_content` pins the SPELLING of source
  code, and `hygiene` runs `ruff format` over delivered source AFTER the tests are authored. The
  bar is unsatisfiable against this engine's own pipeline -- a mechanical fact about Mosaera, not a
  judgement about what the task meant. Live: item 107 reported 67 passed, delivered `completed`,
  and shipped a tree failing its own suite (ADR-0106).
- **It can never fail.** A running test that computes a value and asserts nothing passes whatever
  the coder writes. `authored_suite_asserts_behaviour` (`oraclecheck.py`) already asks this per
  SUITE -- true if ANY test asserts -- so a vacuous test carried by its siblings is invisible
  there. This is the same rule at function scope. Live twice in one day, caught both times only by
  a human reading the test.

Both are STRUCTURAL and ONE-SIDED in the ADR-0085 sense: decidable from the shape of the code, and
silent when unsure. Like everything in this family they are DETECTION ONLY (ADR-0062) -- they name
a target for the Proctor's coder-blind repair turn and never rewrite a test or gate anything.

Kept out of `faithfulness.py` for two reasons that agree: that module and `oraclecheck.py` are both
at the god-file ceiling, and the split puts the boundary exactly where the ADR draws it -- the
frozen five there, the amendment's pair here. No measured code moved to make room.
"""

from __future__ import annotations

import ast

from mosaera_core.assertions import (
    assign_targets,
    dotted,
    expr_names,
    is_assertion,
    snippet,
    str_const,
)
from mosaera_core.faithfulness import OverstrictFinding

# File-read calls: paired with a `.py` path these identify SOURCE TEXT without hint words.
_READ_CALLS = frozenset({"read_text", "read", "read_bytes"})

# Context managers that CHECK something without an `assert*` name, so a test using one is not
# vacuous. `assertRaises` needs no entry -- `is_assertion` already classifies it.
_CHECK_CTX = frozenset({"raises", "warns", "deprecated_call"})

# Path CONSTRUCTORS -- the only names allowed in a path the detector will call literal. Any other
# name means the path was composed from a value the AST cannot resolve (a fixture, a temp dir).
_PATH_CTORS = frozenset({"Path", "PurePath", "pathlib", "open", "os"})


def _reads_text(node: ast.expr) -> bool:
    """Whether the expression READS a file (``.read_text()`` / ``.read()`` / ``.read_bytes()``)."""
    return any(
        isinstance(n, ast.Call) and dotted(n.func).rsplit(".", 1)[-1] in _READ_CALLS
        for n in ast.walk(node)
    )


def _names_a_py_file(node: ast.expr, path_vars: set[str]) -> bool:
    """Whether the expression names a `.py` file at a path written LITERALLY in the test.

    The literal requirement is the one-sidedness, not fussiness. A path COMPOSED at runtime
    (``tmp_path / "golden.py"``, ``workspace.root / "hello.py"``) is usually a file the code under
    test just WROTE -- asserting on its contents is behaviour, and legitimate -- and nothing in the
    AST distinguishes that from the module under test. So when the path is not literal this stays
    SILENT, at the cost of missing a real pin behind a computed path. Measured: this is what takes
    the product's own suites from 5 findings to 1.

    A path already known to be literal may flow through a local (``p = Path("cli.py")`` then
    ``p.read_text()``), so ``path_vars`` widens what counts as literal -- but it never WAIVES the
    rule: one unresolvable name anywhere in the receiver (``tmp_path / p``) and the check is silent.
    ``_PATH_CTORS`` is a constructor allowlist, not a hint-word list.
    """
    allowed = _PATH_CTORS | path_vars
    if any(isinstance(n, ast.Name) and n.id not in allowed for n in ast.walk(node)):
        return False
    if expr_names(node) & path_vars:
        return True
    return any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith(".py")
        for n in ast.walk(node)
    )


def source_text_vars(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Locals bound to the TEXT of a `.py` file the test read (``Path("a/cli.py").read_text()``).

    Deliberately NOT folded into ``_derived_vars``' ``src_names``: that set feeds ``present`` and
    therefore the ``contradiction`` / ``source_introspection`` counts, which this check has no
    business moving (measured: it does not).
    """
    paths: set[str] = set()
    text: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None or not (names := assign_targets(node)):
            continue
        if _names_a_py_file(value, paths):
            paths.update(names)
            if _reads_text(value):
                text.update(names)
    return text


def check_source_text_pin(
    node: ast.Assert, rel: str, spec: str, text_vars: set[str]
) -> list[OverstrictFinding]:
    """``assert "action='store_true'" in cli_content`` -- pins the SPELLING of source code.

    Unsatisfiable against the engine's OWN pipeline, not merely strict: ``hygiene`` runs
    ``ruff format`` over delivered source AFTER the tests are authored, so quotes and whitespace
    are rewritten out from under the assertion and it fails a CORRECT implementation (live, item
    107 -- it shipped a tree failing its own suite). One-sided: fires only when the literal carries
    a QUOTE character (what a formatter provably rewrites) and the haystack is provably a `.py`
    file's text. A spec-quoted literal is faithful; an absence assertion never reaches here
    (``assertNotIn`` carries no view, and ``not in`` is not ``ast.In``).
    """
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.In)):
        return []
    lit = str_const(t.left)
    if not lit or not any(q in lit for q in ("'", '"')) or lit in spec:
        return []
    hay = t.comparators[0]
    if not (expr_names(hay) & text_vars or (_reads_text(hay) and _names_a_py_file(hay, set()))):
        return []
    return [
        OverstrictFinding(
            rel,
            node.lineno,
            "source_formatting_pin",
            snippet(node),
            "this asserts the SPELLING of source code, which `ruff format` rewrites after you "
            "author -- it fails a correct implementation; assert the BEHAVIOUR (run it and check "
            "what it does) or the STRUCTURE via `ast`/`inspect`, never the source text",
            auto_loosenable=False,
        )
    ]


def check_vacuous(fn: ast.FunctionDef | ast.AsyncFunctionDef, rel: str) -> list[OverstrictFinding]:
    """A running test that COMPUTES a value and asserts nothing -- it passes whatever the coder
    writes, so it is not a bar. Live twice in one day, caught both times only by a human reading it.

    NOT every assertion-free test is vacuous: a bare call statement is a real "does not raise" bar.
    Only a test that computes and DISCARDS is flagged.

    ``authored_suite_asserts_behaviour`` asks this per SUITE (true if ANY test asserts), so a
    vacuous test carried by its siblings is invisible there; this is that rule at function scope.
    One-sided three ways: ``is_assertion`` is the permissive classifier (an ABSENCE assertion
    counts, unlike ``assert_views``), a ``raises``/``warns`` context counts, and the test must BIND
    a local -- a pure delegation test (``test_x(): _check_all(d)``) is never flagged.
    """
    binds = False
    for node in ast.walk(fn):
        if is_assertion(node):
            return []
        if isinstance(node, ast.Call) and dotted(node.func).rsplit(".", 1)[-1] in _CHECK_CTX:
            return []
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            binds = True
    # A statement that is just a CALL is a "does it run / does it raise" bar -- weak, but it DOES
    # fail when the code raises, so it is not vacuous. This is the `persist(ctx, m)  # no raise`
    # idiom, and it was 3 of 3 findings on the product's own suites before this guard.
    if not binds or any(
        isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) for st in fn.body
    ):
        return []
    return [
        OverstrictFinding(
            rel,
            fn.lineno,
            "vacuous_test",
            f"def {fn.name}(...): computes a value, asserts nothing",
            f"'{fn.name}' passes no matter what the implementation does, so it is not a bar at "
            "all; assert on the value it computes",
            auto_loosenable=False,
        )
    ]


# --- Exception-surface pins (#129 slice 3) ------------------------------------------------------
# Added from a LABELLED corpus, not from intuition: `overstrict_vs_ref` marks how much stricter the
# authored suite is than the reference solution, and on 10 labelled positives the production
# detector fired ZERO times. These two shapes recur across MCB-06/17/18 and are the most defensible
# of the candidates scored -- together they catch 3 of the 10 at 75% precision, against 0 of 10.
#
# Both are one-sided and inherit the same faithfulness guard every check here uses: a literal the
# SPEC quotes verbatim is a value the spec pinned, and is never flagged.

_EXC_NAMES = {"e", "ex", "exc", "err", "error", "exception"}


def _is_exception_text(node: ast.expr) -> bool:
    """``str(e)`` / ``str(exc_info.value)`` / ``error_message`` — a rendering of an exception."""
    if isinstance(node, ast.Name) and "message" in node.id.lower():
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
        if not node.args:
            return False
        arg = node.args[0]
        if isinstance(arg, ast.Name):
            base = arg.id.lower()
            return base in _EXC_NAMES or "exc" in base or "err" in base
        if isinstance(arg, ast.Attribute):
            # pytest's `exc_info.value` / unittest's `cm.exception`
            return arg.attr in {"value", "exception"} or "exc" in arg.attr.lower()
    return False


def check_exception_message_pin(node: ast.Assert, rel: str, spec: str) -> list[OverstrictFinding]:
    """``assert "not found" in str(exc)`` -- pins the WORDING of an error message.

    The spec almost always says an error is RAISED, not what it says. Pinning the prose makes a
    correct implementation fail for rephrasing a message, and it is the single most common
    over-strict shape in the labelled corpus (MCB-06, MCB-17, MCB-18). A literal the spec quotes
    verbatim IS the contract and is never flagged.
    """
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.In)):
        return []
    lit = str_const(t.left)
    if not lit or lit in spec:
        return []
    if not _is_exception_text(t.comparators[0]):
        return []
    return [
        OverstrictFinding(
            file=rel,
            line=node.lineno,
            kind="exception_message_pin",
            snippet=f"{lit!r} in <exception text>",
            suggestion=(
                "assert the exception TYPE (pytest.raises(X)) rather than its wording, unless the "
                "task states the message text"
            ),
            # A rewrite would have to invent what the message SHOULD say: judgment, not
            # mechanism -- the line ADR-0062 was reverted for. The Proctor decides, coder-blind.
            auto_loosenable=False,
        )
    ]


def check_type_name_string(node: ast.Assert, rel: str, spec: str) -> list[OverstrictFinding]:
    """``assert "OperationError" in str(type(e))`` -- pins a class NAME through a string.

    Any rename, subclass or wrapper breaks it while the behaviour is unchanged, and the check is
    weaker than the `isinstance` it is standing in for. Seen on MCB-18; 100% precision on the
    labelled corpus (it fired on no negative).
    """
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.In)):
        return []
    lit = str_const(t.left)
    if not lit or lit in spec:
        return []
    hay = t.comparators[0]
    if not (
        isinstance(hay, ast.Call)
        and isinstance(hay.func, ast.Name)
        and hay.func.id == "str"
        and hay.args
        and isinstance(hay.args[0], ast.Call)
        and isinstance(hay.args[0].func, ast.Name)
        and hay.args[0].func.id == "type"
    ):
        return []
    return [
        OverstrictFinding(
            file=rel,
            line=node.lineno,
            kind="type_name_string",
            snippet=f"{lit!r} in str(type(...))",
            suggestion="use isinstance(...) -- it survives a rename and is a stronger check",
            # Mechanically rewriting this to isinstance needs the TYPE, which the string does not
            # carry. Judgment again, so the hint stays False.
            auto_loosenable=False,
        )
    ]


# Case-folding methods whose OUTPUT can never contain a differently-cased literal.
_CASE_FOLDS: dict[str, str] = {"lower": "upper", "upper": "lower", "casefold": "upper"}


def _case_folded_call(node: ast.expr) -> str | None:
    """The fold applied by ``<expr>.lower()`` / ``.upper()`` / ``.casefold()``, else ``None``."""
    if (
        isinstance(node, ast.Call)
        and not node.args
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CASE_FOLDS
    ):
        return node.func.attr
    return None


def _impossible_against(fold: str, lit: str) -> bool:
    """Can ``lit`` ever appear in / equal a string that has been through ``fold``?

    A theorem, not a heuristic: ``s.lower()`` contains no uppercase character, so a literal holding
    one can never be found in it. Letters are the only carriers of case, so a literal with no cased
    characters at all (digits, punctuation) is unconstrained and is never flagged.
    """
    if fold in ("lower", "casefold"):
        return any(c.isupper() for c in lit)
    return any(c.islower() for c in lit)


def check_case_impossible(node: ast.Assert, rel: str, spec: str) -> list[OverstrictFinding]:
    """``assert "<!DOCTYPE html>" in content.lower()`` -- UNSATISFIABLE by construction.

    Measured on the 0.6.3 sweep: the Proctor lower-cased a page's source and then searched it for a
    literal containing capitals, so no implementation could ever pass. It refused a tree the hidden
    grader passed 100% (MCB-02, ``docs/engineering-history/over-park-anatomy-2026-08-30.md``).

    The rare check that cannot produce a false positive: ``s.lower()`` provably contains no
    uppercase character. It is therefore not a judgement about strictness at all -- the assertion is
    not *strict*, it is *impossible*, and no correct implementation satisfies it.

    Still ``auto_loosenable=False``. Knowing an assertion is unsatisfiable does not reveal what it
    was MEANT to say: folding both sides and dropping the fold are different contracts, and only the
    author knows which was intended. That judgement is the Proctor's, made coder-blind before any
    implementation exists (ADR-0058); mechanically rewriting the oracle is the line ADR-0062 was
    reverted for.
    """
    del spec  # a task quoting the literal cannot make an impossible comparison possible
    t = node.test
    if not isinstance(t, ast.Compare) or len(t.ops) != 1:
        return []
    if not isinstance(t.ops[0], (ast.In, ast.Eq)):
        return []
    # Either orientation: `lit in x.lower()` or `x.lower() == lit`.
    for lit_side, fold_side in ((t.left, t.comparators[0]), (t.comparators[0], t.left)):
        lit = str_const(lit_side)
        fold = _case_folded_call(fold_side)
        if lit is None or fold is None:
            continue
        if not _impossible_against(fold, lit):
            continue
        return [
            OverstrictFinding(
                file=rel,
                line=node.lineno,
                kind="case_impossible",
                snippet=f"{lit!r} vs .{fold}()",
                suggestion=(
                    f"this can never hold: .{fold}() output cannot contain {lit!r}. Fold BOTH "
                    "sides, or drop the fold -- whichever matches what the task requires"
                ),
                auto_loosenable=False,
            )
        ]
    return []
