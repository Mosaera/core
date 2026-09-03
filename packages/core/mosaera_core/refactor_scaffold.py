"""Deterministic golden-master oracle for a behaviour-preserving refactor (ADR-0066 follow-up).

The ENGINE authors the differential oracle — a verbatim FROZEN copy of each target module plus a
generated test that (1) asserts the changed module's public functions return the SAME thing as the
frozen original across many inputs, and (2) asserts the change actually DECOMPOSED (more top-level
functions than the frozen original). Correctness does NOT depend on the weak model authoring it —
the prompt-led form (behavior_preservation_guard) reopened false-ship because the weak Proctor
wrote a tautological differential.

GENERAL, not case-specific: the target module is found by import, inputs are lifted from the
existing tests + mutated with generic numeric boundaries + the signature's optional params, and the
decomposition check is name-agnostic. Deny-by-default: authors NOTHING unless it can confidently
identify a target module (a root-level source module an existing test imports) AND extract LITERAL
inputs — otherwise it falls back SAFELY to the Proctor's authoring, never a broken or empty oracle.
"""

from __future__ import annotations

import ast
from typing import Any

from mosaera_core.behavior_preservation import is_behavior_preserving, requests_restructuring
from mosaera_core.input_mining import (
    _MAX_MINED_LITERALS,  # noqa: F401  (re-export)
    _NUM_BOUNDARIES,
    mined_boundaries,
)

if False:  # TYPE_CHECKING without the import cost
    from mosaera_core.tools.repo import Workspace


def scaffold_if_refactor(
    workspace: Workspace,
    *,
    enabled: bool,
    task: str,
    plan: str,
    design: str,
    existing_tests: list[str],
) -> list[str]:
    """Author the deterministic differential oracle IFF the scaffold is ``enabled`` AND the task is
    a detected behaviour-preserving refactor; ``[]`` otherwise. Best-effort — any fault yields
    ``[]`` so a scaffold bug can NEVER break a run (it falls back to the Proctor's authoring).

    Arming reads the TRUSTED TASK ONLY — never the PM's ``plan``/``design`` paraphrase. The
    detector's contract (ADR-0066: "fires only on an EXPLICIT preservation clause in the trusted
    spec") was violated by scanning the paraphrase: on a live feature run (MCB-11) the brief's
    symbol-scoped "keep the existing ``+``/``-`` behaviour unchanged" constraint did NOT match the
    patterns, but the PM's lossy restatement ("keep the existing behaviour unchanged") DID — arming
    the scaffold on a feature task and planting an unmeetable protected decomposition bar (the
    ADR-0072 live-drive false-positive class, closed here at the arming seam). ``plan``/``design``
    stay in the signature for call-site stability; they are deliberately NOT consulted."""
    del plan, design  # trusted-task-only arming — the PM paraphrase must never arm the scaffold
    if not enabled or not is_behavior_preserving(task):
        return []
    # A behaviour-preserving task is not necessarily a DECOMPOSITION, and this scaffold's only red
    # phase asserts that decomposition happened. Measured on the 0.6.3 sweep: a comment fix (MCB-30)
    # and a version bump (MCB-32) both promise "No behaviour changes", both armed here, and both got
    # `assert 2 > 2` from `test_decomposition_happened` against trees the hidden grader passed 100%
    # — 4 runs, 15% of every over-park where an authored assertion refused correct code.
    #
    # Declining is the right refusal rather than emitting the differential test alone: without a red
    # phase the golden-master is GREEN on an empty diff, which would trade a false park for a false
    # ship. `[]` hands authoring back to the Proctor, exactly as every other uncertainty here does.
    if not requests_restructuring(task):
        return []
    try:
        return scaffold_refactor_oracle(workspace, existing_tests)
    except Exception:
        return []


# Generic numeric boundaries a leaf is swapped to, to exercise the threshold/branch conditions a
# refactor must preserve (off-by-one, zero, sign). Deterministic; no RNG; not domain-specific.
_MAX_CASES = 48  # cap the parametrized differential inputs so a big example can't explode the file
# #62: how many distinct source literals become boundary triples (a constant-heavy module
# would otherwise dominate the case list). The measured need is small — MCB-14 has two.


def scaffold_refactor_oracle(workspace: Workspace, existing_tests: list[str]) -> list[str]:
    """Author the differential golden-master oracle for a refactor. Returns the list of files it
    wrote under ``tests/`` (frozen copies + the generated test), or ``[]`` when it could not
    confidently scaffold (deny-by-default → the Proctor authors as usual)."""
    root = workspace.root
    test_srcs = _read_all(workspace, existing_tests)
    if not test_srcs:
        return []
    imported = _imported_local_modules(test_srcs, root)
    written: list[str] = []
    for module in sorted(imported):
        src = _read(workspace, f"{module}.py")
        if not src:
            continue
        sigs = _public_function_sigs(src)
        if not sigs:
            continue
        cases = _cases_for(module, sigs, test_srcs, mined_boundaries(src))
        if not cases:
            continue  # no literal example inputs → cannot build a real differential; skip safely
        frozen_rel = f"tests/_frozen_{module}.py"
        test_rel = f"tests/test_refactor_golden_{module}.py"
        if not _write(workspace, frozen_rel, src):
            continue
        if not _write(workspace, test_rel, _render_test(module, cases)):
            continue
        written.extend([frozen_rel, test_rel])
    return written


# --- target + signature detection --------------------------------------------------------------


def _imported_local_modules(test_srcs: list[str], root: Any) -> set[str]:
    """Module names imported by the existing tests that correspond to a root-level source ``.py``
    (a local module, not a stdlib/third-party import and not a test)."""
    names: set[str] = set()
    for src in test_srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return {
        n
        for n in names
        if not n.startswith("test_")
        and (root / f"{n}.py").is_file()
        and not n.startswith("_frozen_")
    }


def _public_function_sigs(src: str) -> dict[str, list[tuple[str, Any]]]:
    """{public top-level function name -> [(param_name, default_or_MISSING)]}. Only module-level
    ``def``s whose name does not start with ``_`` (the public API a refactor must preserve)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    out: dict[str, list[tuple[str, Any]]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
            "_"
        ):
            out[node.name] = _params(node.args)
    return out


_MISSING = object()


def _params(args: ast.arguments) -> list[tuple[str, Any]]:
    """(name, default) for each positional/kw param; default is ``_MISSING`` when required, else the
    literal default value (or ``_MISSING`` when the default is not a literal we can evaluate)."""
    pos = list(args.posonlyargs) + list(args.args)
    defaults: list[Any] = [_MISSING] * (len(pos) - len(args.defaults))
    for d in args.defaults:
        defaults.append(_literal(d))
    return [(a.arg, defaults[i]) for i, a in enumerate(pos)]


# --- example inputs + mutations ----------------------------------------------------------------


def _type_confusions(args: list[Any]) -> list[list[Any]]:
    """One wrong-typed variant per positional arg (#62), by the arg's observed literal type.

    The validation-branch family a same-typed matrix structurally cannot reach: a bool where an
    int is expected (bool IS an int in Python — the classic guard), an empty string where a
    non-empty one is expected, a stringified number, and None. One variant per arg per family;
    never a cross-product (the cap is precious).
    """
    out: list[list[Any]] = []
    for i, a in enumerate(args):
        swaps: list[Any] = []
        if isinstance(a, bool):
            pass  # a bool arg is already exercised by the flip variant
        elif isinstance(a, int):
            swaps = [True, str(a), None]
        elif isinstance(a, str):
            swaps = ["", None] if a else [None]
        elif isinstance(a, (list, tuple, dict)):
            swaps = [None]
        for swap in swaps:
            v = list(args)
            v[i] = swap
            out.append(v)
    return out


def _cases_for(
    module: str,
    sigs: dict[str, list[tuple[str, Any]]],
    test_srcs: list[str],
    mined: tuple[int, ...] = (),
) -> list[tuple[str, list[Any], dict[str, Any]]]:
    """(fn, args, kwargs) differential cases: each existing-test LITERAL call to a public function,
    plus deterministic boundary/optional-param mutations of it."""
    cases: list[tuple[str, list[Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for fn, examples in _literal_calls(test_srcs, set(sigs)).items():
        params = sigs[fn]
        for args in examples:
            for margs, mkwargs in _mutations(args, params, mined):
                key = f"{fn}|{margs!r}|{mkwargs!r}"
                if key not in seen:
                    seen.add(key)
                    cases.append((fn, margs, mkwargs))
    return cases


def _literal_calls(test_srcs: list[str], fn_names: set[str]) -> dict[str, list[list[Any]]]:
    """{fn -> [ [positional literal args], ... ]} for every call in the existing tests to one of
    ``fn_names`` whose positional args are ALL literals (list/dict/num/str/bool/None). Keyword and
    non-literal-arg calls are skipped (we can only replay what we can evaluate)."""
    out: dict[str, list[list[Any]]] = {}
    for src in test_srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.keywords:
                continue
            name = _called_name(node.func)
            if name not in fn_names:
                continue
            args = [_literal(a) for a in node.args]
            if any(a is _MISSING for a in args):
                continue
            out.setdefault(name, []).append(args)
    return out


def _mutations(
    args: list[Any], params: list[tuple[str, Any]], mined: tuple[int, ...] = ()
) -> list[tuple[list[Any], dict[str, Any]]]:
    """Deterministic structure-preserving variants of one example call: the original, single numeric
    leaves swapped to boundary values, bool flips, empty top-level lists, and optional params
    (from the signature) not given in the example set to boundary/bool values. Capped."""
    # DIVERSE variants FIRST (few, high-signal) so they survive the cap; numeric-leaf boundary
    # swaps last (many — a big structure can generate hundreds and would otherwise crowd out the
    # optional-param/bool/empty cases that exercise the other branches).
    out: list[tuple[list[Any], dict[str, Any]]] = [(list(args), {})]
    for name, default in params[len(args) :]:  # optional params not given (e.g. member=True/False)
        if isinstance(default, bool):
            out.extend((list(args), {name: b}) for b in (True, False))
        elif isinstance(default, (int, float)):
            out.extend((list(args), {name: b}) for b in (0, 1, 10))
    # #62 targeted families, BEFORE the generic flood (the cap below evicts tail cases — see
    # the ordering argument above): source-mined boundaries reach the module's own thresholds,
    # type-confusions reach its type guards. Both are what the measured MCB-14 survivor needed.
    for path in _numeric_paths(args):
        for b in mined:
            out.append((_replace(args, path, b), {}))
    out.extend((v, {}) for v in _type_confusions(args))
    for path in _bool_paths(args):
        out.append((_replace(args, path, not _get(args, path)), {}))
    for i, a in enumerate(args):
        if isinstance(a, list) and a:
            v = list(args)
            v[i] = []
            out.append((v, {}))  # empty top-level collection
    for path in _numeric_paths(args):
        for b in _NUM_BOUNDARIES:
            out.append((_replace(args, path, b), {}))
    # dedup preserving order, cap
    seen: set[str] = set()
    uniq: list[tuple[list[Any], dict[str, Any]]] = []
    for a, k in out:
        key = f"{a!r}|{k!r}"
        if key not in seen:
            seen.add(key)
            uniq.append((a, k))
    return uniq[:_MAX_CASES]


# --- literal + path helpers ---------------------------------------------------------------------


def _literal(node: ast.expr) -> Any:
    """The Python value of a literal AST node, or ``_MISSING`` when it is not a literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return _MISSING


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _numeric_paths(value: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    # bool is a subclass of int — exclude it here (handled by _bool_paths).
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [prefix]
    return _walk_paths(value, prefix, _numeric_paths)


def _bool_paths(value: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    if isinstance(value, bool):
        return [prefix]
    return _walk_paths(value, prefix, _bool_paths)


def _walk_paths(value: Any, prefix: tuple[Any, ...], recur: Any) -> list[tuple[Any, ...]]:
    paths: list[tuple[Any, ...]] = []
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            paths.extend(recur(v, (*prefix, i)))
    elif isinstance(value, dict):
        for k, v in value.items():
            paths.extend(recur(v, (*prefix, k)))
    return paths


def _get(root: Any, path: tuple[Any, ...]) -> Any:
    cur = root
    for step in path:
        cur = cur[step]
    return cur


def _replace(root: Any, path: tuple[Any, ...], value: Any) -> Any:
    """A deep copy of ``root`` (lists/dicts) with ``path`` set to ``value``."""
    if not path:
        return value
    step, rest = path[0], path[1:]
    if isinstance(root, list):
        lst = list(root)
        lst[step] = _replace(lst[step], rest, value)
        return lst
    if isinstance(root, dict):
        dct = dict(root)
        dct[step] = _replace(dct[step], rest, value)
        return dct
    return root


# --- rendering ----------------------------------------------------------------------------------


def _render_test(module: str, cases: list[tuple[str, list[Any], dict[str, Any]]]) -> str:
    """The generated differential test file. Loads the frozen copy by PATH (importlib) so it does
    not depend on ``tests/`` being importable, imports the real (post-refactor) module by name, and
    compares outcome-for-outcome (value or raised exception type) across every case. Plus a
    decomposition check: the real module must define MORE module-level functions than the frozen
    original — the red phase (fails on the un-refactored seed), name-agnostic."""
    rows = ",\n".join(f"    ({fn!r}, {args!r}, {kwargs!r})" for fn, args, kwargs in cases)
    return f'''\
"""Auto-generated differential golden-master oracle for the `{module}` refactor (ADR-0066).

Behaviour must be PRESERVED (same output as the frozen original for every input) and the module must
be DECOMPOSED (more module-level functions than the original). Do not edit — the engine authored it.
"""

import importlib.util as _u
from pathlib import Path

import pytest

import {module} as _real

_frozen_path = Path(__file__).parent / "_frozen_{module}.py"
_spec = _u.spec_from_file_location("_frozen_{module}", _frozen_path)
_frozen = _u.module_from_spec(_spec)
_spec.loader.exec_module(_frozen)


def _outcome(mod, fn, args, kwargs):
    try:
        return ("value", getattr(mod, fn)(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - a raised error IS observable behaviour to preserve
        return ("raises", type(exc).__name__)


_CASES = [
{rows},
]


@pytest.mark.parametrize("fn,args,kwargs", _CASES)
def test_behaviour_is_preserved(fn, args, kwargs):
    assert _outcome(_real, fn, args, kwargs) == _outcome(_frozen, fn, args, kwargs)


def _module_level_functions(mod) -> int:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(mod))
    return sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in tree.body)


def test_decomposition_happened():
    # Name-agnostic structural red phase: a real refactor adds module-level helpers, so the changed
    # module has MORE top-level functions than the original. Fails on the un-refactored seed.
    assert _module_level_functions(_real) > _module_level_functions(_frozen), (
        "the function must be decomposed into more module-level helpers"
    )
'''


# --- workspace I/O (best-effort) ----------------------------------------------------------------


def _read(workspace: Workspace, rel: str) -> str:
    try:
        return (workspace.root / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_all(workspace: Workspace, rels: list[str]) -> list[str]:
    return [s for s in (_read(workspace, r) for r in rels) if s]


def _write(workspace: Workspace, rel: str, content: str) -> bool:
    # OVERWRITE, never skip-if-exists (ADR-0068 red-team, FN1). The oracle's paths are seed-
    # PREDICTABLE (`tests/test_refactor_golden_{module}.py`), and repo content is UNTRUSTED — a
    # skip-if-exists would let a pre-planted WEAK file at that path become the engine's oracle
    # (a reproduced HIGH). Overwriting clobbers any plant so the strong differential always wins.
    # The re-freeze this idempotency was meant to prevent is already handled by author_tests's
    # run-once guard (the scaffold never re-runs after the first authoring), so overwrite loses
    # nothing in the honest flow while closing the pre-plant hole.
    try:
        path = workspace.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False
