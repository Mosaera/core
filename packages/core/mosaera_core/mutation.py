"""Deterministic mutation testing of the DELIVERED change (ADR-0049 / #39; comprehensive ADR-0071).

Extracted from ``oraclecheck`` to stay under the god-file ceiling; ``oraclecheck`` re-exports
``_mutate_source`` + ``suite_catches_a_mutation`` for the existing call sites and tests.

A mutation is a small, MUST-change-behaviour edit to the delivered code (a value-returning
``return X`` → ``return None``; the first comparison operator flipped; a bare side-effecting call
deleted → ``pass``). If the authored suite does not go RED on it, the suite EXECUTES that behaviour
but never ASSERTS it — a rubber stamp.

- The SINGLE check (``_mutate_source`` → one mutation per file, first catch wins) proves the suite
  can fail SOME bad code.
- The COMPREHENSIVE check (``_all_mutations`` → every eligible construct in the changed region,
  require ALL caught) closes the executed-but-unasserted gap: a SECOND unasserted region that a
  single mutation would miss now surfaces a survivor → the ship is downgraded (deny-by-default).

Judge-independent and deterministic; it verifies what the code DOES (a surviving mutant = an
unasserted delivered behaviour). It does NOT catch a dropped requirement whose code is simply absent
(nothing to mutate). Downgrade-only: a survivor can only turn a would-be ship into a park.
"""

from __future__ import annotations

import ast
import sys
from typing import TYPE_CHECKING, Any

from mosaera_core.validation import resolve_plan, run_plan

if TYPE_CHECKING:
    from pathlib import Path

    from mosaera_core.sandbox import SandboxWorker
    from mosaera_core.tools.repo import Workspace

# The maximum number of mutants run per comprehensive check (a cost bound; the test suite runs once
# per mutant). Most real changes have far fewer eligible constructs; a change that exceeds this has
# its first ``_MUTATION_CAP`` constructs checked (strictly more than the single-mutation baseline).
_MUTATION_CAP = 20

_OP_FLIP: dict[type, type] = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}  # fmt: skip


# Arithmetic: ONE substitution per operator, matching mutmut and PIT's `MATH` — deliberately not
# the 4-way AOR cross-product, whose measured cost is 31% duplicated mutants (Trivial Compiler
# Equivalence, ICSE 2015). AOR is one of Offutt's five sufficient operators (TOSEM 1996) and the
# second-cleanest of them for equivalence: 5% under manual analysis (Yao et al., ICSE 2014), 1%
# under TCE. `Sub` is listed last on purpose — the `-` -> {+,*,/,%} family generates about half of
# all AOR equivalent mutants, so keeping it to a single flip bounds the worst sub-operator.
_ARITH_SWAP: dict[type, type] = {
    ast.Add: ast.Sub, ast.Mult: ast.Div, ast.FloorDiv: ast.Div,
    ast.Mod: ast.Div, ast.Pow: ast.Mult, ast.Sub: ast.Add,
}  # fmt: skip

# Where a numeric literal is NOT worth mutating, because the mutant is equivalent or nonsensical
# rather than informative. Google's arid-node rules are the published source for this class, and it
# is the one that took their mutant productivity from 15% to 89% — skipping it turns constant
# mutation into a wrongful-decline generator. Matched on the CALLED NAME, so `sleep(100)` is arid
# and `total(100)` is not.
#
# Google flags their own equivalent of this as "unsound: they employ fuzzy name matching... and can
# suppress a productive mutant". True here too: the cost of a wrong suppression is a mutant we do
# not generate (a MISSED question), never a mutant we wrongly kill — it cannot cause a false ship.
_ARID_CALLS = frozenset(
    {
        "sleep", "wait", "timeout", "set_deadline", "deadline", "retry", "backoff",
        "range", "reserve", "resize", "shrink_to_fit", "seed", "exit", "getLogger",
    }
)  # fmt: skip


def _arid_literal(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Whether this numeric literal sits somewhere a mutation says nothing.

    A timeout of 101 instead of 100, a `range(11)` bound, a default argument value: changing these
    either cannot change observable behaviour or changes only speed. Mutating them manufactures a
    survivor that no test could reasonably kill, which in this gate is a refusal of correct work.
    """
    parent = parents.get(id(node))
    if isinstance(parent, ast.arguments):
        return True  # a default argument value
    if isinstance(parent, ast.Call):
        fn = parent.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        return name in _ARID_CALLS
    return False


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    """id(child) -> parent, so a literal can be judged by the context it sits in."""
    out: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _overlaps(node: ast.AST, changed: set[int] | None) -> bool:
    """Whether ``node`` touches a changed line — its ``lineno..end_lineno`` span intersects
    ``changed`` (range-intersection, so a multi-line construct whose interior line was edited still
    matches). ``changed is None`` means 'anywhere in the file' (first-in-file — the backward-compat
    default when no changed-line set is threaded through)."""
    if changed is None:
        return True
    start = getattr(node, "lineno", None)
    if start is None:
        return False
    end = getattr(node, "end_lineno", None) or start
    return bool(set(range(start, end + 1)) & changed)


def _is_noopable(node: ast.Expr) -> bool:
    """Whether a bare ``Expr`` statement is a side-effecting CALL safe to delete → ``pass``:
    ``foo()``, ``x.append(y)``, ``audit(...)``, ``await session.delete(x)``. Deleting one removes
    ONLY its (discarded) side effect. Everything else is excluded so the mutation isn't 'caught' by
    a SITE-LOCAL structural error that any suite would trip regardless of quality (a useless non-
    downgrade): assignments aren't ``Expr`` at all; a bare walrus binds a name (→ NameError) and a
    bare ``yield`` de-generators the fn (→ TypeError); a docstring/bare literal is a true no-op
    that always survives (→ false park). ``await <non-call>`` is excluded, conservatively. (Credit
    SOUNDNESS itself rests on the gate ANDing the result as a downgrade-only signal, not on this
    predicate — see ADR-0049 #39; a downstream data-dependency crash is a legitimate kill.)"""
    value = node.value
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return False
    # A walrus ANYWHERE in the call (``log(y := f())``) binds a name later code may reference —
    # deleting the statement would unbind it (→ NameError downstream), an error-as-caught posing
    # as a real catch. Exclude it exactly like a bare walrus (red-team Finding 2).
    return not any(isinstance(n, ast.NamedExpr) for n in ast.walk(value))


def _eligible_return(node: ast.Return, changed: set[int] | None) -> bool:
    v = node.value
    trivial_none = isinstance(v, ast.Constant) and v.value is None
    return v is not None and not trivial_none and _overlaps(node, changed)


def _eligible_compare(node: ast.Compare, changed: set[int] | None) -> bool:
    return bool(node.ops) and type(node.ops[0]) in _OP_FLIP and _overlaps(node, changed)


# Operand values that make a swap IDENTITY-PRESERVING, i.e. an equivalent mutant. Found by the
# F83 red team (R2), which is the failure the literature predicts: `-` -> {+,*,/,%} generates about
# half of all AOR equivalent mutants (Yao et al., ICSE 2014). `x - 0` -> `x + 0` and `x ** 1` ->
# `x * 1` compute the same answer, so NO test can kill them; in this gate an unkillable mutant is a
# survivor, and a survivor is a refusal of correct work.
#
# Note `x * 1` -> `x / 1` is deliberately NOT here: in Python that turns an int into a float, which
# is observable. Suppressing it would cost a real question for no benefit.
_ARITH_IDENTITY: dict[type, tuple[int, ...]] = {
    ast.Add: (0,), ast.Sub: (0,), ast.Pow: (1,), ast.Div: (1,), ast.FloorDiv: (1,), ast.Mod: (1,),
}  # fmt: skip


def _identity_swap(node: ast.BinOp) -> bool:
    """Whether swapping this operator leaves the value unchanged, making the mutant equivalent."""
    neutral = _ARITH_IDENTITY.get(type(node.op))
    if neutral is None:
        return False
    return any(
        isinstance(side, ast.Constant)
        and not isinstance(side.value, bool)
        and side.value in neutral
        for side in (node.left, node.right)
    )


def _eligible_arith(node: ast.BinOp, changed: set[int] | None) -> bool:
    return type(node.op) in _ARITH_SWAP and not _identity_swap(node) and _overlaps(node, changed)


def _eligible_const(
    node: ast.Constant, changed: set[int] | None, parents: dict[int, ast.AST]
) -> bool:
    """A numeric literal worth perturbing. `bool` is excluded — it is an `int` subclass in Python,
    and `True + 1` is a nonsense mutant, not a behavioural one."""
    if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
        return False
    return _overlaps(node, changed) and not _arid_literal(node, parents)


def _mutate_source(src: str, changed: set[int] | None = None) -> str | None:
    """``src`` with ONE deterministic behaviour-changing mutation, or None if none applies. Tries,
    in order: the first value-returning ``return X`` → ``return None``; else flip the first
    comparison operator (``==``↔``!=``, ``<``↔``>=``, …); else delete the first bare side-effecting
    call (``x.append(y)``, ``audit(...)``, ``await session.delete(x)``) → ``pass`` — the operator
    that catches a purely non-mutable change (ADR-0049 / #39). When ``changed`` is given, only a
    node touching one of those lines is eligible, so the mutation lands on the coder's actual change
    rather than the first well-tested construct elsewhere in the file; ``changed=None`` keeps
    first-in-file (the backward-compat default). Reserialized via ``ast.unparse`` — the caller MUST
    revert (formatting/comments are lost, which is fine for a throwaway mutation)."""
    for kind in ("return", "compare", "arith", "noop", "const"):
        out = _mutate_nth(src, changed, kind, 0)
        if out is not None:
            return out
    return None


def _mutate_nth(src: str, changed: set[int] | None, kind: str, index: int) -> str | None:
    """``src`` with the ``index``-th eligible ``kind`` construct (in traversal order, confined to
    ``changed``) mutated, or None when there is no such site / the tree won't parse. ``kind`` is
    ``return`` / ``compare`` / ``noop``. This is the per-site primitive both the single-mutation
    (``_mutate_source``, index 0 per kind) and the comprehensive (``_all_mutations``, every index)
    checks are built from — one construct changed per returned source, so a survivor names exactly
    which delivered behaviour the suite fails to assert."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    st = {"i": 0, "done": False}
    parents = _parents(tree)

    class _Mut(ast.NodeTransformer):
        # Every visitor ends with generic_visit so traversal DESCENDS into children — otherwise a
        # Compare nested in a Return value (``return n > 100``) or a bare call is unreachable, its
        # mutant never enumerated (red-team #74 HIGH: silent false vouch). ``st["done"]`` still
        # bounds it to exactly ONE mutation per call.
        def visit_Return(self, node: ast.Return) -> ast.AST:
            if kind == "return" and not st["done"] and _eligible_return(node, changed):
                if st["i"] == index:
                    st["done"] = True
                    return ast.copy_location(ast.Return(value=ast.Constant(value=None)), node)
                st["i"] += 1
            return self.generic_visit(node)

        def visit_Compare(self, node: ast.Compare) -> ast.AST:
            if kind == "compare" and not st["done"] and _eligible_compare(node, changed):
                if st["i"] == index:
                    st["done"] = True
                    node.ops[0] = _OP_FLIP[type(node.ops[0])]()
                    return node
                st["i"] += 1
            return self.generic_visit(node)

        def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
            if kind == "arith" and not st["done"] and _eligible_arith(node, changed):
                if st["i"] == index:
                    st["done"] = True
                    node.op = _ARITH_SWAP[type(node.op)]()
                    return self.generic_visit(node)
                st["i"] += 1
            return self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> ast.AST:
            if kind == "const" and not st["done"] and _eligible_const(node, changed, parents):
                if st["i"] == index:
                    st["done"] = True
                    assert isinstance(node.value, (int, float))  # noqa: S101 - narrowed by _eligible_const
                    return ast.copy_location(ast.Constant(value=node.value + 1), node)
                st["i"] += 1
            return node

        def visit_Expr(self, node: ast.Expr) -> ast.AST:
            eligible = _overlaps(node, changed) and _is_noopable(node)
            if kind == "noop" and not st["done"] and eligible:
                if st["i"] == index:
                    st["done"] = True
                    return ast.copy_location(ast.Pass(), node)
                st["i"] += 1
            return self.generic_visit(node)

    _Mut().visit(tree)
    if not st["done"]:
        return None
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _all_mutations(src: str, changed: set[int] | None, cap: int) -> list[str]:
    """Every distinct single-construct mutation of ``src`` in the changed region — one per eligible
    return / comparison / side-effecting call — capped at ``cap`` (a cost bound; the caller runs the
    suite once per mutant).

    INTERLEAVED by index across kinds (return[0], compare[0], noop[0], return[1], …) so the cap is
    CONSTRUCT-FAIR: a change with many returns can't starve the cap and leave every comparison
    unprobed (red-team #74 Finding 2 — comparisons are the boundary-logic constructs most likely to
    be the unasserted region). Each kind is enumerated up to ``cap`` so no kind runs unbounded."""
    by_kind: dict[str, list[str]] = {k: [] for k in ("return", "compare", "arith", "noop", "const")}
    for kind in by_kind:
        index = 0
        while len(by_kind[kind]) < cap:
            m = _mutate_nth(src, changed, kind, index)
            if m is None:
                break  # no index-th site of this kind
            if m != src:
                by_kind[kind].append(m)
            index += 1
    mutants: list[str] = []
    for i in range(max((len(v) for v in by_kind.values()), default=0)):
        for kind in ("return", "compare", "arith", "noop", "const"):
            if i < len(by_kind[kind]):
                mutants.append(by_kind[kind][i])
                if len(mutants) >= cap:
                    return mutants
    return mutants


def has_mutable_construct(
    workspace: Any,
    source_files: list[str],
    changed: dict[str, set[int]] | None = None,
    *,
    cap: int = _MUTATION_CAP,
) -> bool:
    """Whether ANY mutant is generatable for the changed regions — pure AST, no sandbox.

    `suite_catches_a_mutation` collapses four different situations into ``None``: no tests, no
    mutable source, no run could execute, and (at the caller) an exception. The Layer-2 record has
    to tell them apart, because they imply opposite fixes — and F83 was itself two hours lost to a
    record that named a cause nobody had measured. Naming that cause again from a bare ``None``
    would repeat the defect one level up, so this MEASURES the "no mutable construct" branch
    instead of asserting it.

    Deliberately cheap: reuses the same generator the real check uses, so the two cannot disagree
    about what is mutable, and needs no container.
    """
    for rel in source_files:
        try:
            text = (workspace.root / rel).read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        lines = changed.get(rel) if changed else None
        if any(m != text for m in _all_mutations(text, lines, cap)):
            return True
    return False


def no_verdict_reason(
    workspace: Any, source: list[str], changed: dict[str, set[int]], *, failed: bool
) -> str:
    """WHY the mutation check produced no verdict — measured, not guessed.

    ``suite_catches_a_mutation`` returns ``None`` for no tests, no mutable source, OR no executable
    run, and the caller adds a fourth (it raised). The first draft of F83 printed *"no mutable
    construct in the change"* for all four. That is an unmeasured cause in the one record whose
    entire job is to separate causes — the exact mistake F83 was fixing. So: ask the AST.
    """
    if failed:
        return "the mutation check errored before reaching a verdict"
    if not has_mutable_construct(workspace, source, changed):
        return "the mutation check could not run — no mutable construct in the change"
    return "the mutation check produced no verdict though the change IS mutable (no runnable test?)"


def suite_catches_a_mutation(
    workspace: Workspace,
    sandbox: SandboxWorker,
    source_files: list[str],
    test_files: list[str],
    changed: dict[str, set[int]] | None = None,
    *,
    comprehensive: bool = False,
    cap: int = _MUTATION_CAP,
) -> bool | None:
    """Whether the suite CATCHES a deterministic mutation of the DELIVERED code — the cheapest real
    measure of "can this oracle fail bad code". Mutates the changed source, runs the tests
    network-off, checks they go RED, then ALWAYS reverts.

    - ``True``  — a mutation was caught (red) and NONE survived: the suite can fail bad code.
    - ``False`` — some mutation SURVIVED (suite stayed green): a proven rubber stamp.
    - ``None``  — inconclusive (no tests, no mutable source, or no run could execute).

    ``changed`` maps each source file to its changed line numbers; when given, each file's mutation
    is confined to those lines (so it exercises the coder's actual change, not a well-tested
    construct elsewhere in the file). ``changed=None`` mutates the first mutable construct per file.

    ``comprehensive`` (ADR-0071): when True, mutate EVERY eligible construct in each file's changed
    region (up to ``cap`` mutants total) and require the suite to catch ALL — so a SECOND unasserted
    region a single mutation would miss surfaces a survivor. When False, one mutation per file (the
    ADR-0049/#39 baseline). Either way it is FAIL-CLOSED (the FIRST survivor across files/mutants
    returns ``False`` — an early catch must never mask a later rubber stamp) and each mutant is
    reverted byte-for-byte in a ``finally``. A ``False`` only ever DOWNGRADES a vouched run.
    """
    if not test_files:
        return None
    # Gather each changed file's mutants. Read/restore the original as BYTES so the revert is
    # byte-for-byte: text I/O would translate newlines (LF↔CRLF) and `errors="replace"` would burn
    # non-UTF-8 bytes to U+FFFD, corrupting the delivered file the check reverts to (red-team A1).
    # The decode only feeds the AST mutators; only the restore must be exact.
    work: list[tuple[Path, bytes, list[str]]] = []
    for rel in source_files:
        path = workspace.root / rel
        try:
            original_bytes = path.read_bytes()
        except OSError:
            continue
        original_text = original_bytes.decode("utf-8", errors="replace")
        lines = changed.get(rel) if changed else None
        gen = (
            _all_mutations(original_text, lines, cap)
            if comprehensive
            else _single(original_text, lines)
        )
        mutants = [m for m in gen if m != original_text]
        if mutants:
            work.append((path, original_bytes, mutants))
    # ROUND-ROBIN by mutant index (red-team #74): schedule EVERY file's baseline (index 0) before a
    # file's index-1, so a caught-heavy file that sorts first can never STARVE a later file's
    # baseline survivor. The cap then truncates only the highest-index BREADTH mutants, fairly
    # across files — never a file's first (single-check) mutant, so it is never weaker than single.
    schedule: list[tuple[Path, bytes, str]] = []
    for i in range(max((len(ms) for _, _, ms in work), default=0)):
        schedule.extend((path, ob, ms[i]) for path, ob, ms in work if i < len(ms))
    truncated = len(schedule) > cap or any(len(ms) >= cap for _, _, ms in work)
    n = len(schedule[:cap])
    caught_any = False
    for path, original_bytes, mutated in schedule[:cap]:
        try:
            path.write_text(mutated, encoding="utf-8")
            plan = resolve_plan(
                workspace, [sys.executable, "-m", "pytest", "-q", *test_files], install=False
            )
            outcome = run_plan(plan, sandbox, cwd=workspace.root)
        finally:
            path.write_bytes(original_bytes)  # ALWAYS restore the delivered code, byte-for-byte
        if outcome.passed is True:
            _log_mutation(comprehensive, n, False)  # a survivor ⇒ proven rubber stamp
            return False
        if _never_collected(outcome):
            # pytest 4 (usage error) and 5 (no tests collected) are NON-ZERO, so `passed is False`
            # — and reading that as "the mutation was caught" means a suite that never ran vouches
            # for itself. "pytest refused to start" is not evidence of strength in either
            # direction, so it is INCONCLUSIVE: no `caught_any`, and the truncation rule below
            # then yields `None` rather than a vouch. Red team 2026-08-22.
            continue
        if outcome.passed is False:
            caught_any = True
    # FAIL-SAFE (red-team #74): a TRUNCATED all-caught run is INCONCLUSIVE, not a vouch — a
    # construct beyond the cap could be a rubber stamp, so return None (no downgrade, no false
    # "verified") rather than True. An untruncated all-caught run asserts every changed behaviour.
    verdict = None if (not caught_any or truncated) else True
    _log_mutation(comprehensive, n, verdict)
    return verdict


def _never_collected(outcome: Any) -> bool:
    """Did pytest decline to run at all? Reads the real exit code, never the prose.

    `run_plan` records each step's `exit_code` in `step_results` (validation.py), so this asks the
    process what happened instead of pattern-matching its output — which would drift with pytest's
    wording and is the second-origin shape this repo keeps paying for.
    """
    return any(int(r.get("exit_code") or 0) in (4, 5) for r in (outcome.step_results or []))


def _log_mutation(comprehensive: bool, n_mutants: int, verdict: bool | None) -> None:
    """Env-gated diagnostic (``MOSAERA_MUTATION_LOG``): one JSONL line per mutation check — whether
    COMPREHENSIVE was active, how many mutants ran, and the verdict — so an A/B can confirm the
    check actually FIRED (n_mutants > 1 under comprehensive) rather than being silently inert, and
    sees its True/False/None verdict (the scoreboard hides it). Zero-impact off; never raises."""
    import json
    import os

    path = os.environ.get("MOSAERA_MUTATION_LOG")
    if not path:
        return
    try:
        row = {"comprehensive": comprehensive, "n_mutants": n_mutants, "verdict": verdict}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:  # noqa: S110 — a diagnostic write must never break a run
        pass


def _single(src: str, changed: set[int] | None) -> list[str]:
    """The one-mutation baseline as a 0-or-1 element list (so the runner loop is shared)."""
    m = _mutate_source(src, changed)
    return [m] if m is not None else []
