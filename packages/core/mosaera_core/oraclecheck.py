"""Deterministic checks that MEASURE whether the tester's authored suite is a real oracle.

``oracle_verified`` — the signal that an INDEPENDENT oracle vouched for correctness this run —
must mean "a suite that can actually FAIL bad code passed", not "a non-empty test file exists".
Today it is the latter (``bool(tests_baseline)``), so a tautological suite counts. These checks
turn that from an ASSERTION into a MEASUREMENT (the oracle-make-real arc).

Phase 1a — the RED PHASE. A test-first acceptance suite must FAIL against the pre-implementation
tree: that is the whole point of authoring it before the coder writes anything. A suite that is
already GREEN with no implementation is tautological (``assert True``, or asserting something the
seed already satisfies) and cannot be the oracle — it would pass no matter what the coder does.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

# The mutation check moved to `mutation` (god-file ceiling); re-exported so the existing call site
# (nodes_impl) and tests keep resolving `oraclecheck.suite_catches_a_mutation` / `_mutate_source`.
from mosaera_core.mutation import _mutate_source, suite_catches_a_mutation  # noqa: F401

if TYPE_CHECKING:
    from mosaera_core.sandbox import SandboxWorker
    from mosaera_core.tools.repo import Workspace


def authored_suite_is_red(
    workspace: Workspace, sandbox: SandboxWorker, authored: list[str]
) -> bool | None:
    """Whether the authored tests FAIL against the pre-implementation tree. The original
    single-boolean face of `seedcheck.authored_seed_results` — see there for the contract."""
    from mosaera_core.seedcheck import authored_seed_results

    return authored_seed_results(workspace, sandbox, authored)[0]


def _callee_name(call: ast.Call) -> str:
    """Dotted name of a call target — ``pytest.raises`` → "pytest.raises",
    ``self.assertEqual`` → "self.assertEqual", ``assert_that`` → "assert_that"."""
    node: ast.expr = call.func
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _static_falsy(test: ast.expr) -> bool:
    """A branch whose condition is a compile-time falsy constant — its body never runs (``if
    False:``, ``while 0:``). Used so an assert hidden in a dead branch doesn't count (#54 R2)."""
    return isinstance(test, ast.Constant) and not bool(test.value)


def _reachable(node: ast.AST) -> Iterator[ast.AST]:
    """Yield ``node``'s descendants that could actually RUN when the enclosing test executes — an
    over-approximation that (a) does NOT descend into a nested function/lambda scope (an assert in
    an uncalled helper never runs), and (b) skips a statically-false branch body (``if False:``; the
    ``else`` still runs). Makes the assertion floor REACHABILITY-aware: a real assert the runtime
    never reaches no longer clears it (red-team #54 R2 — nested-uncalled / dead-branch guts)."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # a nested scope — its body is not part of THIS test's straight-line run
        if isinstance(child, (ast.If, ast.While)) and _static_falsy(child.test):
            for orelse in getattr(
                child, "orelse", []
            ):  # the dead body is skipped; else-branch runs
                yield orelse
                yield from _reachable(orelse)
            continue
        yield child
        yield from _reachable(child)


def _literal_only(node: ast.expr) -> bool:
    """Whether an expression is built ENTIRELY from literals — no runtime value anywhere in it.

    ``True`` / ``1 == 1`` / ``(1, 2)`` / ``"a" + "b"`` are literal-only; anything containing a
    ``Name``, ``Call``, ``Attribute``, ``Subscript``, comprehension or f-string interpolation is
    not. An assertion whose operands are all literal-only decides the same way on every run and
    therefore cannot fail — it asserts nothing about the code under test.
    """
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.Name,
                ast.Call,
                ast.Attribute,
                ast.Subscript,
                ast.Starred,
                ast.FormattedValue,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
                ast.Await,
                ast.Yield,
                ast.YieldFrom,
            ),
        ):
            return False
    return True


def _trivial_assert_call(call: ast.Call) -> bool:
    """Whether an ``assert*`` / ``*raises`` CALL is a tautology over literals —
    ``self.assertTrue(True)``, ``self.assertEqual(1, 1)``, ``self.assertIsNone(None)``.

    The bare-``assert`` branch below has always rejected exactly this (``assert True``,
    ``assert 1 == 1``); the call branch matched on the callee NAME alone and never looked at the
    arguments, so the identical tautology was rejected as a statement and accepted as a method call
    (F52). This closes that asymmetry — it is the SAME structural rule, not a new detector class
    (ADR-0085 keeps the deterministic layer to structural, one-sided facts).

    !! ACCEPTED RESIDUAL (issue #67, red-teamed 3 rounds): a tautology wrapped in a CALL still
    clears — ``assertTrue(bool(1))``, ``assertEqual(str(1), "1")``, f-strings, starred literals.
    Catching those needs constant propagation, which ADR-0085 freezes. Do not add a case-specific
    detector here; `oracle_mutation_check` is the behavioural backstop.

    One-sided, because the error to avoid is a FALSE PARK: only a call proven trivial is rejected.
    **Zero positional arguments counts as REAL** — it cannot be proven trivial. Keyword arguments
    (``msg=``) are ignored; they carry no claim. ``pytest.raises(ValueError)`` passes untouched, its
    argument being a ``Name``.
    """
    return bool(call.args) and all(_literal_only(a) for a in call.args)


def _real_assertions(fn: ast.AST) -> int:
    """How many NON-trivial assertions a test's REACHABLE body makes: an ``assert`` whose test is
    not a truthy/constant target and not a comparison of ONLY constants (``assert 1 == 1``), plus
    each ``*raises`` / ``assert*`` call (``pytest.raises``, ``self.assertEqual``, …) whose arguments
    are not ALL literals. Only asserts that could actually RUN count (``_reachable`` skips
    nested-function scopes + statically-false branches), so a gut hiding a real assert where it
    never executes does NOT count.

    The COUNT is what ``assertion_profile`` measures weakening with, and the same walk decides the
    assertion FLOOR (``_asserts_something_real`` is ``> 0`` over this). One rule, so the floor and
    the weakening measure can never disagree about what an assertion is."""
    count = 0
    for n in _reachable(fn):
        if isinstance(n, ast.Assert):
            t = n.test
            if isinstance(t, ast.Constant):  # assert True / 1 / "x"
                continue
            if isinstance(
                t, (ast.Lambda, ast.FunctionDef)
            ):  # assert <lambda> — the object is truthy
                continue
            if (
                isinstance(t, ast.Compare)
                and isinstance(t.left, ast.Constant)
                and all(isinstance(c, ast.Constant) for c in t.comparators)
            ):  # assert 1 == 1 / "a" == "a" — a tautology over literals
                continue
            count += 1
        elif isinstance(n, ast.Call):
            name = _callee_name(n).lower()
            if "raises" in name or "assert" in name:  # pytest.raises, unittest assert*, etc.
                if _trivial_assert_call(n):  # assertTrue(True) — the same tautology, as a call
                    continue
                count += 1
    return count


def _asserts_something_real(fn: ast.AST) -> bool:
    """Whether a test's reachable body makes at least one non-trivial assertion. See
    ``_real_assertions`` — this is that count being positive, and nothing else."""
    return _real_assertions(fn) > 0


def _dotted_name(node: ast.expr) -> str:
    """Dotted name of an attribute/name expression — ``pytest.mark.skip`` → "pytest.mark.skip"."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_skipped_test(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a test function is skipped/xfailed by a decorator — ``@pytest.mark.skip``,
    ``@pytest.mark.xfail``, ``@unittest.skip``, or a bare ``@skip`` (any dotted name whose leaf is
    ``skip``/``skipif``/``xfail``). Such a test COLLECTS but never RUNS, so pytest exits 0 (green)
    while asserting nothing at runtime — it must not count toward the assertion floor (red-team
    ADR-0052, the skip/xfail rubber-stamp). ``skipif`` is treated the same, deny-by-default: a
    conditionally skipped test can't be relied on to run. A real assertion inside is inert."""
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        leaf = _dotted_name(target).rsplit(".", 1)[-1].lower()
        if leaf in ("skip", "skipif", "xfail"):
            return True
        # An EMPTY parametrize set generates ZERO cases → the test never runs (pytest reports it
        # skipped), so its assertions never execute (red-team #54 R2). Treat it like a skip.
        if leaf == "parametrize" and isinstance(dec, ast.Call) and len(dec.args) >= 2:
            argvalues = dec.args[1]
            if isinstance(argvalues, (ast.List, ast.Tuple, ast.Set)) and not argvalues.elts:
                return True
    return False


def authored_suite_asserts_behaviour(workspace: Workspace, authored: list[str]) -> bool | None:
    """Whether the suite makes at least one REAL assertion about behaviour — INSIDE a test function
    that actually RUNS: not ``assert True`` / ``assert 1 == 1`` / a no-assert test / an uncalled
    helper / a skip-or-xfail-decorated test. A suite that asserts nothing meaningful (or never runs)
    passes no matter what the coder does, so it can't be the oracle.

    Static (AST) — complements the RED PHASE. The red phase rejects a suite green with no code, but
    a suite can red pre-impl ONLY because an import is missing and still assert nothing once the
    module exists; this catches that. Only ``test_*`` functions / ``Test*``-class methods
    count — a real assert in an UNCALLED helper isn't the suite testing anything — and a
    skip/xfail-decorated test is excluded (it collects green but never executes its assertions).

    - ``True``  — some RUNNING TEST function asserts a non-trivial property.
    - ``False`` — parseable, but no running test function asserts anything real.
    - ``None``  — nothing assessable (no files, or none parseable).
    """
    if not authored:
        return None
    assessed = False
    for rel in authored:
        try:
            tree = ast.parse((workspace.root / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        assessed = True
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test")
                and not _is_skipped_test(node)
                and _asserts_something_real(node)
            ):
                return True
    return False if assessed else None


# --- the assertion profile: measuring a WEAKENING, not a change (#66, ADR-0087 §6) -------------
#
# `tampered_integrity` answers *was this file touched?* — a different question from *was the bar
# lowered?*, and the two came apart in both directions on 2026-08-06: a run that DELETED
# `assert len(lines) == 2` from a delivered test shipped, and a run that RESTORED it was blocked.
#
# `authored_suite_asserts_behaviour` cannot stand in. It is `any()` over a whole suite, so one
# surviving assertion in a forty-test file reads as fine. Weakening has to be measured PER TEST
# FUNCTION and ONE-SIDED: we report only losses, never gains.


def _parametrize_factor(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """How many times a parametrized test's body actually RUNS — the product over
    ``@pytest.mark.parametrize`` decorators whose argvalues are a statically countable collection.

    Without this, replacing three inline asserts with a three-case ``parametrize`` — a
    STRENGTHENING, and a refactor any reviewer would ask for — reads as a 3→1 regression and
    false-parks the run (red-team round 2). Counting executions rather than statements makes the
    two forms agree, and it is the same rule ``_is_skipped_test`` already applies at the zero-case
    end (an empty set generates no runs), not a new detector class.

    Deny-by-default on the unknown side: argvalues that are not a literal list/tuple/set (a
    module-level constant, a generator, a fixture) count as 1 rather than a guess, so an
    uncountable set can never inflate a profile. Parametrizing from a named constant therefore
    still reads as a regression — accepted, and the failure direction is a refusal, not a ship.
    """
    factor = 1
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if _dotted_name(target).rsplit(".", 1)[-1].lower() != "parametrize":
            continue
        if not (isinstance(dec, ast.Call) and len(dec.args) >= 2):
            continue
        argvalues = dec.args[1]
        if isinstance(argvalues, (ast.List, ast.Tuple, ast.Set)):
            factor *= len(argvalues.elts)
    return factor


def _profile_tree(tree: ast.AST) -> dict[str, int]:
    """Walk with class context so a method reads as ``TestCase.test_x``, not ``test_x``."""
    out: dict[str, int] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name.startswith("test"):
                    # A skipped/xfailed test COLLECTS but never runs, so its assertions are inert
                    # (red-team ADR-0052). Profiling it as 0 is what makes ADDING a skip decorator
                    # to a surviving test read as the weakening it is.
                    out[f"{prefix}{child.name}"] = (
                        0
                        if _is_skipped_test(child)
                        else _real_assertions(child) * _parametrize_factor(child)
                    )
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def assertion_profile(source: str) -> dict[str, int] | None:
    """Non-trivial, reachable, non-skipped assertions per test function. ``None`` if unparseable.

    ``None`` is NOT "no assertions" — a caller must treat it as *unknown* and refuse to conclude
    anything, or a syntax error becomes a licence to gut a file."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    return _profile_tree(tree)


def profile_regression(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Test functions REMOVED, or whose assertion count DROPPED. One-sided by construction.

    A RENAME reads as one removal plus one addition, so it surfaces as a regression the operator
    must acknowledge rather than passing silently. That is deliberate: matching a renamed function
    by body similarity is exactly the case-specific detector ADR-0085 freezes. Annoying, never
    silent — and the failure direction is a refused amendment, not a shipped weakening.

    Returns qualnames with a short reason, sorted; empty means nothing was lost.
    """
    out: list[str] = []
    for name, n in before.items():
        if name not in after:
            out.append(f"{name} (removed)")
        elif after[name] < n:
            out.append(f"{name} ({n} -> {after[name]} assertions)")
    return sorted(out)


def _changed_module_paths(changed_source_files: list[str]) -> set[str]:
    """Each changed ``.py`` source file as a normalized module-PATH fragment (POSIX, no ``.py``,
    ``__init__`` collapsed to its package dir): ``pkg/parser.py`` → ``{"pkg/parser"}``;
    ``pkg/__init__.py`` → ``{"pkg"}``. We match imports against these PATHS (not bare leaf names) so
    a test importing an unrelated ``settings``/``utils`` from a DIFFERENT package can't be mistaken
    for touching this one (adversarial findings F-A / Finding-1)."""
    frags: set[str] = set()
    for rel in changed_source_files:
        if not rel.endswith(".py"):
            continue
        frag = rel[:-3]  # drop ".py"
        if frag.endswith("/__init__"):
            frag = frag[: -len("/__init__")]
        elif frag == "__init__":
            continue  # a top-level __init__ with no package dir — nothing importable to attribute
        if frag:
            frags.add(frag)
    return frags


def _import_candidates(node: ast.AST) -> list[str]:
    """The dotted module paths an import statement makes the test depend on. ``import a.b.c`` →
    ``["a.b.c"]``; ``from a.b import c, d`` → ``["a.b", "a.b.c", "a.b.d"]`` (the module imported
    FROM, plus each name as a possible submodule). Relative imports (``from . import x``) are
    skipped — resolving them needs the test's own package location."""
    out: list[str] = []
    if isinstance(node, ast.Import):
        out += [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom) and not node.level:
        mod = node.module or ""
        if mod:
            out.append(mod)
            out += [f"{mod}.{a.name}" for a in node.names]
    return out


def _frag_matches(cand: str, changed_frags: set[str]) -> bool:
    """Whether an import's reconstructed path ``cand`` refers to a changed file fragment.

    - MULTI-segment (``pkg/parser``): a component-suffix of a changed path counts, so it matches
      under a ``src/`` (or any) source root. A multi-component collision with an UNRELATED module is
      vanishingly rare, so suffix matching is safe here.
    - SINGLE-segment (``logging``): ONLY an exact match or a ``src/``-rooted one. A bare
      ``import logging`` / ``from types import X`` is almost always a STDLIB / third-party import,
      and matching it as a suffix of ``myapp/logging.py`` was a false-CREDIT (stdlib shadowing,
      near-universal in real suites). We can't tell a repo whose source root is ``myapp/`` from the
      stdlib case, so deny-by-default: only top-level and ``src/`` layouts credit a single-segment
      reference (a repo importing its own nested module by bare name parks — safe direction)."""
    for g in changed_frags:
        if g == cand:
            return True
        if "/" in cand:
            if g.endswith("/" + cand):
                return True
        elif g == "src/" + cand:
            return True
    return False


def _references_changed_module(test_src: str, changed_frags: set[str]) -> bool:
    """Whether the test IMPORTS a changed module — matching the reconstructed import PATH (not a
    bare name) against the changed file paths (see ``_frag_matches``). ``from django.conf import
    settings`` → ``django/conf/settings``, which does NOT match a changed ``myapp/settings.py`` —
    closing the namespace collision where an imported NAME coincides with a common repo filename
    (findings F-A / Finding-1). Residual coarseness: a same-package ``from pkg import name`` where
    ``pkg/name.py`` is changed but ``name`` is a symbol in ``pkg/__init__`` credits. Line coverage —
    not this — is the precise answer."""
    try:
        tree = ast.parse(test_src)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        for dotted in _import_candidates(node):
            if _frag_matches(dotted.replace(".", "/"), changed_frags):
                return True
    return False


# Provably-inert change surface: documentation/markup only, classified by EXTENSION (not path — a
# behavioural `service/docs/flags.json` must not read as inert just for living under a docs/ dir,
# finding F-C-bis). Everything else (config, data, code) is potentially BEHAVIORAL, so the
# skip-credit branch must not fire for it (finding F-B — a `flags.json` / `.sql` change yields no
# `.py` module paths but is not inert). `.txt` is excluded on purpose (`requirements.txt` is a
# dependency change, not documentation). Deny-by-default: anything not clearly docs is behavioural.
_DOC_SUFFIXES = (".md", ".rst", ".adoc", ".markdown")


def _is_docs(rel: str) -> bool:
    return rel.lower().endswith(_DOC_SUFFIXES)


def standing_suite_is_independent_oracle(
    workspace: Workspace,
    integrity_baseline: dict[str, str] | None,
    changed_files: list[str],
    covered: bool | None = None,
) -> bool:
    """Whether a PRE-EXISTING, tamper-guarded suite qualifies as an independent oracle for THIS
    change (Phase 2, HARDENED). ``changed_files`` is EVERY changed repo-relative path (any
    extension). Requires all of:

    1. actual test FILES in the baseline (a bare ``conftest`` / ``pyproject.toml`` / ``setup.cfg``
       / ``tox.ini`` is collection CONTROL, not a suite — plain ``bool(integrity_baseline)``
       credited any repo merely carrying a pyproject);
    2. those tests ASSERT something real (the same floor the tester path uses);
    3. **the suite REFERENCES the changed code** (module-reference heuristic, F1): some baselined
       test IMPORTS a changed ``.py`` module, matched by reconstructed module PATH (not bare name).
       A suite about UNRELATED modules is not an oracle for THIS change — without this a brownfield
       change no test touches auto-shipped on a green-but-irrelevant suite. Coarse by design
       (imports by path, not line coverage — 1b / a future coverage gate do the line-level half);
       it errs toward DENY, with only narrow residual over-credit (see the helper's own note).

    When NO ``.py`` source changed, requirement 3 has nothing to match, so the change must be
    provably INERT to credit: if any changed path is behavioural (a non-``.py`` config/data file —
    ``flags.json``, a SQL migration — that the suite can't be shown to cover), DENY (F-B). Only a
    docs/test-only (or empty) change credits on 1 + 2 alone.
    """
    from mosaera_core.testintegrity import is_collection_control, is_test_file

    # C = baseline MINUS collection controls (a bare conftest/pyproject is collection CONTROL, not
    # a suite — the distinction this function's docstring already turns on). `is_test_file` would
    # be pytest's DEFAULT naming and would empty this on any repo that sets `python_files`.
    test_files = [p for p in (integrity_baseline or {}) if not is_collection_control(p)]
    if not test_files:
        return False
    if authored_suite_asserts_behaviour(workspace, test_files) is not True:
        return False
    if covered is not None:
        # P1 change-coverage gate (#29): runtime line COVERAGE of the changed lines decides
        # relevance precisely — True = a test actually executes them, False = none does. Replaces
        # the coarse import heuristic below whenever coverage measured this run. Deny-by-default:
        # credit only a suite that both ASSERTS real (above) AND is shown to cover the change;
        # `None` (coverage off / unmeasurable) falls through to the heuristic.
        return covered
    source = [f for f in changed_files if not is_test_file(f)]
    module_frags = _changed_module_paths(source)
    if not module_frags:
        # No attributable .py source changed. Credit only if EVERY non-test change is inert docs —
        # a behavioural non-.py change (config/data) the suite can't be shown to cover must park.
        return not any(not _is_docs(f) for f in source)
    for rel in test_files:
        try:
            src = (workspace.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _references_changed_module(src, module_frags):
            return True
    return False
