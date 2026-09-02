"""Deterministic detection of OVER-STRICT / unfaithful acceptance-test assertions (#57, ADR-0062).

The Proctor persona forbids pinning incidental detail the spec leaves open ("do not pin an exact
whitespace/format the task left open ... a FALSE NEGATIVE that fails a correct implementation"), but
a weak local model does not always obey it. Instrumented MCB runs showed authored suites pinning
exact stdout whitespace (``assert lines[0] == "1 [ ] Buy milk"``), a rendering literal
(``assert stdout.count("#important") == 1``), or a private helper name (``"_validate_user" in
source``), and even a mutually-contradictory pair no impl can pass (a name asserted in the
source AND ``module._name`` asserted to raise ``AttributeError``). This module MEASURES that
deterministically (AST, no LLM) so the run can hand the Proctor NAMED repair targets (#57 MR-B),
which it loosens with spec-reading judgment.

DETECTION ONLY -- it never rewrites a test. A deterministic auto-rewriter (MR-C) was built and
RED-TEAMED (ADR-0062): two independent adversarial passes CONFIRMED it reopened false-ship (bare
``.split()`` erases semantic whitespace -- newlines, column alignment, empty fields -- and the
exit-code rewrite gutted behavioural ``.status``/``.rc`` checks), so it was REVERTED. Distinguishing
incidental from semantic whitespace is not deterministically decidable, so loosening needs judgment
(the Proctor here; a held-out critic later), never a mechanical rewrite.

One-sided by construction, mirroring ``oraclecheck.py``: it only ever FLAGS strictness it can PROVE
is incidental -- a rendered literal the spec does not quote, an exit code the spec left as
"non-zero". When unsure it stays SILENT. A missed over-strict test is a latent thrash (today's
behaviour) -- the safe direction -- so the asymmetry is deliberate.

Both assertion styles are understood. Until F37 this module walked ``ast.Assert`` ALONE, so a suite
written with ``self.assertEqual(...)`` was completely invisible to it -- and LedgerCLI's charter
mandates ``unittest``, so the guard found nothing on every suite the product actually authored. The
blindness survived its own justification measurements because all 42 test files in the MCB bench
corpus are bare-``assert``. A ``unittest`` assertion is now NORMALISED into the equivalent
``assert`` (``assertEqual`` -> ``==``, ``assertIn`` -> ``in``, ``assertTrue(expr)`` -> ``expr``) and
the checks below are unchanged, so the two styles cannot drift to different verdicts. Absence forms
(``assertFalse`` / ``assertNotIn`` / ``assertNotEqual``) are deliberately NOT normalised: flagging
one would invert its meaning, matching the existing ``assert not hasattr(...)`` skip.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mosaera_core.assertions import (
    assert_views,
    assign_targets,
    dotted,
    expr_names,
    int_const,
    is_skipped,
    snippet,
    str_const,
    test_functions,
)

if TYPE_CHECKING:
    from mosaera_core.tools.repo import Workspace

# Names that mark an expression as CAPTURED PROGRAM OUTPUT (a CLI's stdout/stderr, a subprocess
# result, split lines). Only a comparison against such an expression can be an output-format
# over-strictness; a value assertion on a domain object (``entry.text``) never does.
_OUTPUT_HINTS = frozenset(
    {
        "stdout", "stderr", "output", "out", "result", "res", "proc", "completed",
        "lines", "listed", "found", "printed", "combined", "captured", "cp",
    }
)  # fmt: skip

# Names that mark an expression as the SOURCE TEXT of a module/function (an ``inspect.getsource``
# result), so ``<ident> in <source>`` is a structural (implementation-shape) assertion.
_SOURCE_HINTS = frozenset({"source", "src", "getsource", "code", "body"})

# Attributes that UNAMBIGUOUSLY carry a process exit status. Deliberately narrow: ``status``/``rc``
# were dropped (red-team ADR-0062) -- they are far more often a domain value (``response.status``,
# ``order.status``, ``job.rc``) than a process exit code, and misreading one gives a bogus finding.
_EXIT_ATTRS = frozenset({"returncode", "exit_code", "exitcode"})

_IDENT = re.compile(
    r"^_[A-Za-z_]\w*$"
)  # a PRIVATE identifier (leading underscore) -- the pinned kind


@dataclass(frozen=True)
class OverstrictFinding:
    """One over-strict / unfaithful assertion. ``auto_loosenable`` marks the class a JUDGMENT-based
    loosener (the Proctor's repair turn; a future held-out critic) can act on most safely -- exact
    output equality / an over-strict exit code. It is a hint, NOT a licence to auto-rewrite: the
    deterministic MR-C rewriter was red-teamed and reverted (it reopened false-ship, ADR-0062).
    """

    file: str
    line: int
    # exact_output_equality|exit_code_pin|output_count_pin|source_introspection|contradiction
    # |source_formatting_pin|vacuous_test
    kind: str
    snippet: str
    suggestion: str
    auto_loosenable: bool


def authored_suite_overstrict_findings(
    workspace: Workspace, authored: list[str], spec_text: str
) -> list[OverstrictFinding]:
    """Deterministic AST findings of over-strict / unfaithful assertions across ``authored``.

    ``spec_text`` is the trusted task/plan text: a string literal quoted verbatim in it is a value
    the spec PINNED (faithful) and is never flagged. Returns [] when there is nothing to assess.
    """
    # Imported here, not at module scope: `bar_integrity` imports `OverstrictFinding` from this
    # module, so a top-level import would be circular.
    from mosaera_core.bar_integrity import (
        check_case_impossible,
        check_exception_message_pin,
        check_source_text_pin,
        check_type_name_string,
        check_vacuous,
        source_text_vars,
    )

    findings: list[OverstrictFinding] = []
    late: list[OverstrictFinding] = []
    spec = spec_text or ""
    present: dict[str, tuple[str, int]] = {}  # ident asserted present in source -> (file, line)
    absent: dict[
        str, tuple[str, int]
    ] = {}  # ident asserted to raise AttributeError -> (file, line)
    for rel in authored:
        try:
            tree = ast.parse((workspace.root / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for fn in test_functions(tree):
            if is_skipped(fn):
                continue
            # Intra-function dataflow: a captured value is usually bound to a local first
            # (``lines = result.stdout.split()``; ``src = inspect.getsource(...)``) and the
            # assertion is on that local, so seed the OUTPUT / SOURCE name sets with those locals.
            out_names, src_names, count_vars = _derived_vars(fn)
            # Bare `assert` AND `unittest` assertions (F37): the module used to walk `ast.Assert`
            # alone, so a suite written with `self.assertEqual(...)` was entirely invisible to it.
            text_vars = source_text_vars(fn)
            for node in assert_views(fn):
                findings.extend(_check_assert(node, rel, spec, out_names, count_vars))
                findings.extend(_check_source_introspection(node, rel, spec))
                _collect_source_membership(node, rel, present, src_names)
                # APPENDED LAST (below), never here: it keeps the positional `findings[0]`
                # contracts intact, and makes the critic's truncation to 12 drop the NEW
                # findings rather than the established ones.
                late.extend(check_source_text_pin(node, rel, spec, text_vars))
                # Same APPENDED-LAST discipline (#129 slice 3): added from a labelled corpus
                # where the detector scored 0/10, so they must not disturb the positional
                # contracts the established findings hold.
                late.extend(check_exception_message_pin(node, rel, spec))
                late.extend(check_type_name_string(node, rel, spec))
                # UNSATISFIABLE, not merely strict: no implementation can pass it.
                late.extend(check_case_impossible(node, rel, spec))
            late.extend(check_vacuous(fn, rel))
            _collect_absent_in_raises(fn, rel, absent)
    contradictions = set(present) & set(absent)
    for name in sorted(contradictions):
        file, line = present[name]
        findings.append(
            OverstrictFinding(
                file,
                line,
                "contradiction",
                f"'{name}' asserted present in source AND asserted to raise AttributeError",
                f"unsatisfiable: no impl can both define and not-expose '{name}'; drop one",
                auto_loosenable=False,
            )
        )
    # source-introspection over-strictness (#60, ADR-0066): a private helper NAME pinned in the
    # module source (``assert "_helper" in inspect.getsource(mod)``) the task did NOT name — the
    # exact MCB-05 over-pin that fails a correct, differently-named refactor. Emitted for present
    # names that are NOT part of a contradiction (that stronger finding already covers them) and
    # not quoted in the spec (a spec-named helper is faithful).
    for name in sorted(set(present) - contradictions):
        if name in spec:
            continue
        file, line = present[name]
        findings.append(
            OverstrictFinding(
                file,
                line,
                "source_introspection",
                f'"{name}" in <module source>',
                f"'{name}' pins a specific private symbol NAME the task did not name; assert the "
                "LOOSE structural property (a short orchestrator + >= N helpers), "
                "not this exact name",
                auto_loosenable=False,
            )
        )
    return findings + late


def _check_source_introspection(node: ast.Assert, rel: str, spec: str) -> list[OverstrictFinding]:
    """``assert hasattr(mod, "_private")`` / ``assert getattr(mod, "_private")`` -- pins a specific
    PRIVATE symbol NAME the task did not name (an implementation-shape pin, #60/ADR-0066). The
    ``"_x" in source`` form rides the present-set path in the caller. Skips a NEGATED test (an
    ABSENCE assertion) and a spec-quoted name."""
    t = node.test
    if not (isinstance(t, ast.Call) and isinstance(t.func, ast.Name)):
        return []  # a bare `hasattr(...)`; `assert not hasattr(...)` is a UnaryOp -> skipped
    if t.func.id not in ("hasattr", "getattr") or len(t.args) < 2:
        return []
    lit = str_const(t.args[1])
    if lit and _IDENT.match(lit) and lit not in spec:
        return [
            OverstrictFinding(
                rel,
                node.lineno,
                "source_introspection",
                snippet(node),
                f"'{lit}' pins a specific private symbol NAME the task did not name; assert the "
                "LOOSE structural property (a short orchestrator + >= N helpers), "
                "not this exact name",
                auto_loosenable=False,
            )
        ]
    return []


def _is_output_derived(
    node: ast.expr, out_names: frozenset[str] | set[str] = _OUTPUT_HINTS
) -> bool:
    return bool(expr_names(node) & out_names)


def _is_source_derived(
    node: ast.expr, src_names: frozenset[str] | set[str] = _SOURCE_HINTS
) -> bool:
    if expr_names(node) & src_names:
        return True
    return any(isinstance(n, ast.Call) and "getsource" in dotted(n.func) for n in ast.walk(node))


def _derived_vars(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[set[str], set[str], dict[str, str]]:
    """Forward pass over a test's straight-line assignments, seeding three maps used to see through
    variable indirection: locals bound from captured OUTPUT, locals bound from module SOURCE text,
    and locals bound from ``<output>.count("literal")`` (mapped to that literal). One ordered pass
    resolves chains (``result`` -> ``lines`` -> ``first``); tuple/loop bindings are skipped."""
    out_names: set[str] = set(_OUTPUT_HINTS)
    src_names: set[str] = set(_SOURCE_HINTS)
    count_vars: dict[str, str] = {}
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None:
            continue
        names = assign_targets(node)
        if not names:
            continue
        lit = _count_literal(value, out_names)
        if lit is not None:
            for n in names:
                count_vars[n] = lit
        if _is_output_derived(value, out_names):
            out_names.update(names)
        if _is_source_derived(value, src_names):
            src_names.update(names)
    return out_names, src_names, count_vars


def _looks_rendered(s: str) -> bool:
    """A multi-token string with letters: a RENDERED line (``"1 [ ] Buy milk"``), not an id,
    an empty string, or a single word. Incidental whitespace/layout lives in exactly these."""
    return len(s.split()) >= 2 and any(c.isalpha() for c in s)


def _spec_says_nonzero(spec: str) -> bool:
    low = spec.lower()
    return "non-zero" in low or "nonzero" in low or "non zero" in low


def _is_exit_attr(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in _EXIT_ATTRS


def _count_literal(
    node: ast.expr, out_names: frozenset[str] | set[str] = _OUTPUT_HINTS
) -> str | None:
    """The literal in an output ``X.count("lit")`` call, else None."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "count"
        and node.args
        and _is_output_derived(node.func.value, out_names)
    ):
        return str_const(node.args[0])
    return None


def _has_render_prefix(s: str) -> bool:
    """The literal starts with a rendering artefact (``#tag``, ``[x]``, ``- item``): a display form
    the spec leaves open, not a plain word the task named."""
    t = s.strip()
    return bool(t) and not (t[0].isalnum() or t[0] in "\"'")


def _check_assert(
    node: ast.Assert,
    rel: str,
    spec: str,
    out_names: set[str],
    count_vars: dict[str, str],
) -> list[OverstrictFinding]:
    """Findings for a single ``assert`` -- at most one, most-specific first."""
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1):
        return []
    op, left, right, line = t.ops[0], t.left, t.comparators[0], node.lineno
    if not isinstance(op, ast.Eq):
        return []
    # exact output equality (either operand order)
    for a, b in ((left, right), (right, left)):
        lit = str_const(b)
        if (
            lit is not None
            and _is_output_derived(a, out_names)
            and _looks_rendered(lit)
            and lit.strip() not in spec
        ):
            return [
                OverstrictFinding(
                    rel,
                    line,
                    "exact_output_equality",
                    snippet(node),
                    "the spec does not pin this exact text/spacing; use a substring (`in`) or "
                    "whitespace-normalised (`.split()`) compare, not `==`",
                    auto_loosenable=True,
                )
            ]
    # exit-code pin -- flag only when the spec says "non-zero" AND does not pin this exact code
    # (a spec that pins the code, e.g. "exit 2", makes == 2 faithful; red-team ADR-0062).
    for a, b in ((left, right), (right, left)):
        code = int_const(b)
        if (
            code is not None
            and code != 0
            and _is_exit_attr(a)
            and _spec_says_nonzero(spec)
            and str(code) not in spec
        ):
            return [
                OverstrictFinding(
                    rel,
                    line,
                    "exit_code_pin",
                    snippet(node),
                    "the spec says a NON-ZERO exit, not this exact code; assert `!= 0`",
                    auto_loosenable=True,
                )
            ]
    # rendering-literal count pin (advisory: the count may be behavioural, the literal is not).
    # Inline ``out.count("lit") == n`` OR a local bound from it (``c = out.count("lit"); c == n``).
    cnt = _count_literal(left, out_names) or _count_literal(right, out_names)
    if cnt is None:
        for operand in (left, right):
            if isinstance(operand, ast.Name) and operand.id in count_vars:
                cnt = count_vars[operand.id]
                break
    if cnt is not None and cnt.strip() not in spec and _has_render_prefix(cnt):
        return [
            OverstrictFinding(
                rel,
                line,
                "output_count_pin",
                snippet(node),
                f"'{cnt}' pins a rendering the spec leaves open; count the spec-named token, not "
                "its display form",
                auto_loosenable=False,
            )
        ]
    return []


def _collect_source_membership(
    node: ast.Assert, rel: str, present: dict[str, tuple[str, int]], src_names: set[str]
) -> None:
    """Record ``assert "_name" in <source>`` -- a private identifier asserted in the module
    source (a structural pin, and one half of the contradiction pattern)."""
    t = node.test
    if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.In):
        lit = str_const(t.left)
        if lit and _IDENT.match(lit) and _is_source_derived(t.comparators[0], src_names):
            present.setdefault(lit, (rel, node.lineno))


def _collect_absent_in_raises(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, rel: str, absent: dict[str, tuple[str, int]]
) -> None:
    """Record a private attribute accessed in ``with pytest.raises(AttributeError):`` -- asserted
    NOT to exist on the module (the other half of the contradiction pattern)."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.With):
            continue
        # Case-INSENSITIVE: `pytest.raises` and `unittest`'s `self.assertRaises` must both match,
        # and the capital R in the latter silently missed it before F37.
        raises_attr_err = any(
            isinstance(item.context_expr, ast.Call)
            and "raises" in dotted(item.context_expr.func).lower()
            and any(
                isinstance(arg, ast.Name) and arg.id == "AttributeError"
                for arg in item.context_expr.args
            )
            for item in node.items
        )
        if not raises_attr_err:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Attribute) and _IDENT.match(inner.attr):
                absent.setdefault(inner.attr, (rel, getattr(inner, "lineno", node.lineno)))
