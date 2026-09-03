"""Per-claim oracle evaluation (ADR-0079 Wave 2) — core evaluates, the gate only consumes.

`evaluate_claims` maps each structured claim (Wave 1 schema) to a verdict:

    satisfied    the bound oracle evaluated and passed
    failed       the bound oracle evaluated and FAILED — the only verdict that parks
    unbound      `oracle_kind: none` — intake's job (owner decision 2026-08-03), never a park
    unevaluable  the oracle exists but could not run here (no target, no baseline, a crash) —
                 deny-by-default in BOTH directions: no park, no vouch (the
                 `structural_spec_ok` None semantics)

The AST predicates are the four transformation contracts validated offline 18/18
(`scripts/experiments/claim_predicates_stage0.py`, engineering-history 2026-08-02), ported with
the two red-team lessons baked in: statements are counted RECURSIVELY (the nesting dodge,
ADR-0072 successor R1 — reuse `structural_spec._total_stmts`) and predicates evaluate the
DELIVERED tree, never a partial overlay. Parameter extraction is deny-by-default: a target we
cannot name deterministically is `unevaluable`, never guessed.

Layer note: this module is core; `packages/policies` never imports it. The gate receives only
the reduced `claims_failed` id list (ADR-0079 §4 — the gate stays pure).
"""

from __future__ import annotations

import ast
import contextlib
import re
from typing import Any

from mosaera_core.claims import CLAIM_EVIDENCE_CLASS
from mosaera_core.clauses import (
    Clause,
    applied_marks,
    apply_to_constraints,
    clauses_from_state,
)
from mosaera_core.consumer_impact import eval_consumer_impact
from mosaera_core.quality import changed_python_files
from mosaera_core.structural_spec import (
    _has_loop,
    _target_fn,
    check_structural_compliance,
    extract_structural_constraints,
)
from mosaera_core.testintegrity import is_test_file

VERDICTS = ("satisfied", "failed", "unbound", "unevaluable")

_BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)(?:\([^)]*\))?`")
_SINGLE_IF = re.compile(r"\b(single|one)\s+`?if`?\b|\b(data|table)-driven\b", re.IGNORECASE)
_SHARED_HELPER = re.compile(
    r"\b(one|single|a)\b.{0,30}\b(module-level\s+)?helper\b.{0,60}\bboth\b", re.IGNORECASE
)
_LAYOUT = re.compile(r"\b(keep|preserve)\b.{0,50}\b(layout|module)|don'?t collapse", re.IGNORECASE)


# ── the ported contracts (18/18 offline; see the experiment for the falsification record) ──
def data_driven_single_if(src: str, fn_name: str) -> bool | None:
    """≤1 `if` counted RECURSIVELY (an elif ladder is nested ast.If) + the table drive
    (a loop or comprehension). None = target absent/unparseable."""
    try:
        fn = _target_fn(ast.parse(src), fn_name)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if fn is None:
        return None
    ifs = sum(isinstance(n, ast.If) for n in ast.walk(fn))
    return ifs <= 1 and _has_loop(fn)


def extract_shared_helper(src: str, fn_a: str, fn_b: str) -> bool | None:
    """One module-level helper BOTH named functions call, with the shared raises moved out of
    both bodies. None = either function absent/unparseable."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return None
    module_fns = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    a, b = _target_fn(tree, fn_a), _target_fn(tree, fn_b)
    if a is None or b is None:
        return None

    def calls(fn: ast.AST) -> set[str]:
        return {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }

    shared = (calls(a) & calls(b) & module_fns) - {fn_a, fn_b}
    inline_raises = sum(isinstance(n, ast.Raise) for f in (a, b) for n in ast.walk(f))
    return bool(shared) and inline_raises == 0


def layout_preserved(root: Any, modules: list[str]) -> bool | None:
    """Every named module still exists somewhere under ``root`` as a non-trivial .py file
    (≥1 top-level def/class), all inside ONE package dir — "extend it, don't collapse it".
    Evaluates the DELIVERED tree (the overlay lesson). None = the named modules were never
    locatable together (no baseline to hold — deny-by-default)."""
    from pathlib import Path

    rootp = Path(root)
    candidates: dict[Path, int] = {}
    for m in modules:
        for f in rootp.rglob(f"{m}.py"):
            if ".mosaera" in f.parts or any(p.startswith(".") for p in f.parts):
                continue
            candidates[f.parent] = candidates.get(f.parent, 0) + 1
    homes = [d for d, n in candidates.items() if n == len(modules)]
    if not homes:
        return None if not candidates else False  # some named modules gone → collapsed
    for d in homes:
        ok = True
        for m in modules:
            try:
                tree = ast.parse((d / f"{m}.py").read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                ok = False
                break
            if not any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) for n in tree.body):
                ok = False
                break
        if ok:
            return True
    return False


# ── parameter extraction (deny-by-default: no deterministic target → unevaluable) ──
def _named_functions(text: str, sources: dict[str, str]) -> list[str]:
    """Backticked identifiers in ``text`` that are module-level function names in the delivered
    sources — the only names we will ever judge (never guessed)."""
    defined: set[str] = set()
    for src in sources.values():
        with contextlib.suppress(SyntaxError, ValueError, RecursionError):
            defined |= {n.name for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    seen: list[str] = []
    for name in _BACKTICKED.findall(text):
        if name in defined and name not in seen:
            seen.append(name)
    return seen


def _module_names(text: str) -> list[str]:
    return list(dict.fromkeys(_BACKTICKED.findall(text)))


def _in_test_tree(rel: str) -> bool:
    """Does ``rel`` live under a test directory? Complements the basename check.

    `is_test_file` matches the pytest BASENAME pattern (`test_*.py` / `*_test.py`) and is shared
    with the ADR-0036 tamper guard, so it must not be widened here. But a structural contract
    judges DELIVERED SOURCE, and a helper the engine itself wrote into `tests/` is neither.

    **Wired in 2026-08-12, second attempt.** The first landing was reverted the same day:
    applying it alone fixed MCB-15 (over-park 4/5 -> 0/5) and produced **2 false ships on
    MCB-05**, which had delivered 0/5 before. The frozen copy's guaranteed `False` had been
    accidentally masking a missing contract: the briefs say "a short orchestrator" with no
    number, ADR-0072 forbids deriving the constant from prose, and the relative shrink fallback
    is more permissive than the cases' own acceptance tests — so removing the accidental block
    let under-decomposed work satisfy the claim, which cleared `claim_structural_failed` and
    shipped. The exclusion therefore lands TOGETHER with the ratified
    `structural.body_statements=5` bench default (`bench/_clauses._RATIFIED_DEFAULT`), which
    states the number and is woven into the brief. Measured together (ledger E5): delivered
    7→18, over-park 8→2, false ships 0.

    Measured 2026-08-12 (MCB-15, 5/5 parks with the hidden grader PASSING): the refactor scaffold
    (ADR-0066) writes a golden-master snapshot to `tests/_frozen_<module>.py` containing the
    PRE-refactor function verbatim. That name does not match the pytest pattern, so it entered
    "delivered sources" and `check_structural_compliance` judged it — and a frozen copy of the
    original can never satisfy "refactor this", by construction. The red-team R2 rule (judge EVERY
    file defining the target, so a decoy cannot shadow a bloated real one) then made that failure
    authoritative. The engine was grading its own scaffolding as the agent's work product.
    """
    return any(part in ("test", "tests") for part in rel.split("/")[:-1])


def _delivered_sources(workspace: Any) -> tuple[dict[str, str], dict[str, str]]:
    """(changed non-test python sources, their HEAD originals) — the nodes_impl idiom."""
    sources: dict[str, str] = {}
    originals: dict[str, str] = {}
    try:
        diff = workspace.diff_all()
    except Exception:
        return sources, originals
    for f in changed_python_files(diff):
        path = workspace.root / f
        # One-sided: this can only ever judge FEWER files, never more. RE-LANDED 2026-08-12
        # together with the ratified `structural.body_statements=5` clause (now the bench
        # default — `bench/harness._RATIFIED_DEFAULT`). Alone it produced false ships on
        # MCB-05: removing the accidental block exposed that the RELATIVE shrink check cannot
        # decide an unquantified "short orchestrator" (ADR-0082 names that gap; ADR-0072
        # forbids deriving the constant from prose). Measured together: delivered 7→18,
        # over-park 8→2, false ships 0 (ledger E4/E5).
        if is_test_file(f) or _in_test_tree(f) or not path.is_file():
            continue
        with contextlib.suppress(OSError):
            sources[f] = path.read_text(encoding="utf-8", errors="replace")
        with contextlib.suppress(Exception):
            originals[f] = workspace.repo.git.show(f"HEAD:{f}")
    return sources, originals


# Which standing decisions actually changed a check this process. Module-level because the
# evaluator is pure by contract and the graph state it returns is not threaded back here; the
# bench reads it once per run. Never a control input — only a record of what already happened.
_APPLIED: set[str] = set()


def clauses_applied() -> list[str]:
    """The standing decisions that demonstrably fired. Read once per run, then reset."""
    return sorted(_APPLIED)


def reset_clauses_applied() -> None:
    _APPLIED.clear()


def _eval_transformation(
    claim_text: str, workspace: Any, task: str, clauses: tuple[Clause, ...] = ()
) -> tuple[str, str]:
    """(verdict, oracle_ref) for one ast_transformation_contract claim.

    A ratified clause (ADR-0082) fills in a number the brief left open — "a short orchestrator"
    with no count. That is what makes a standing decision BIND this oracle rather than merely
    appear in a prompt; without it the clause would be a suggestion the model may ignore.
    """
    sources, originals = _delivered_sources(workspace)
    if not sources:
        return "unevaluable", "no delivered python sources to judge"
    # Verb 1-2: short orchestrator + >= N helpers — the existing red-teamed check, driven by
    # the claim's own sentence (falling back to the task for the constraint phrasing).
    for text in (claim_text, task):
        stated = extract_structural_constraints(text)
        constraints = apply_to_constraints(stated, clauses)
        if constraints is not None:
            _APPLIED.update(applied_marks(stated, constraints))
            verdict, reason = check_structural_compliance(sources, constraints, originals)
            if verdict is None:
                return "unevaluable", reason or "structural check inert (no baseline/target)"
            return ("satisfied" if verdict else "failed"), f"structural_spec: {reason or 'met'}"
    # Verb 3: data/table-driven single-if.
    if _SINGLE_IF.search(claim_text):
        names = _named_functions(claim_text, sources) or _named_functions(task, sources)
        if len(names) != 1:
            return "unevaluable", "single-if contract: no unambiguous target function"
        for src in sources.values():
            got = data_driven_single_if(src, names[0])
            if got is not None:
                return ("satisfied" if got else "failed"), f"data_driven_single_if({names[0]})"
        return "unevaluable", f"single-if contract: `{names[0]}` not found in delivered sources"
    # Verb 4: extract-shared-helper.
    if _SHARED_HELPER.search(claim_text):
        names = _named_functions(claim_text, sources) or _named_functions(task, sources)
        if len(names) < 2:
            return "unevaluable", "shared-helper contract: need two named callers"
        for src in sources.values():
            got = extract_shared_helper(src, names[0], names[1])
            if got is not None:
                outcome = "satisfied" if got else "failed"
                return outcome, f"extract_shared_helper({names[0]}, {names[1]})"
        return "unevaluable", "shared-helper contract: named callers not found together"
    # Verb 5: module-layout preservation.
    if _LAYOUT.search(claim_text):
        modules = [m for m in _module_names(claim_text) if m.isidentifier()]
        if len(modules) < 2:
            return "unevaluable", "layout contract: no named module list"
        got = layout_preserved(workspace.root, modules)
        if got is None:
            return "unevaluable", "layout contract: named modules not locatable"
        return ("satisfied" if got else "failed"), f"layout_preserved({', '.join(modules)})"
    return "unevaluable", "transformation claim with no extractable contract parameters"


def _eval_non_use(text: str, workspace: Any) -> tuple[str, str]:
    """A removal claim's verdict (slice 1.2). **Unprovable is FAILED here, not unevaluable.**

    Every other oracle kind resolves an unaskable question to ``unevaluable``, which the gate
    deliberately ignores (owner decision 2026-08-03: unbound claims are intake's job). That is right
    for a claim about behaviour — absent evidence is not an objection. It is **wrong for a claim of
    absence**: "nothing references `X`" that cannot be proven must not ship, because the failure
    mode is a removal that breaks every caller. The slice's requirement is literally *removal
    without a non-use proof cannot ship*.

    So the deny-by-default lives here, in the per-kind policy — which is where this function's own
    contract says kind-specific policy belongs — rather than in the shared reducers or the gate.
    Downstream (`failed_claim_ids`, `failed_claim_classes`, the gate) is untouched.

    The distinction between the two failing causes is not lost: it rides in ``oracle_ref``, which is
    the record that says WHICH thing went wrong. Collapsing causes into one unexplained verdict is
    the F83 defect, and it cost two hours the first time.
    """
    from mosaera_core.nonuse import non_use_proven, removal_target

    root = getattr(workspace, "root", None)
    if root is None:
        return "failed", "no workspace to examine — removal unproven"
    target = removal_target(text)
    if not target:
        return "failed", "the claim names no removable symbol (use a `code span`) — unproven"
    proven, evidence = non_use_proven(root, target)
    if proven is True:
        return "satisfied", evidence
    if proven is False:
        return "failed", evidence
    return "failed", f"could not prove non-use: {evidence}"


def evaluate_claims(
    claims: list[dict[str, Any]], workspace: Any, state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Verdict rows `{claim_id, verdict, oracle_ref}` for every claim, in claim order.

    Pure policy per oracle_kind; ANY evaluator crash degrades that one claim to
    ``unevaluable`` — a fault in claim evaluation must never crash the gate visit
    (the mutation-check hardening precedent, nodes_impl).
    """
    rows: list[dict[str, Any]] = []
    task = str(state.get("task") or "")
    # Standing decisions ride in RunState, resolved once at launch — this evaluator is pure and
    # must not reach a database mid-gate.
    clauses = clauses_from_state(state.get("clauses"))
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", "?"))
        kind = str(c.get("oracle_kind", "none"))
        text = str(c.get("text", ""))
        try:
            if kind == "none":
                verdict, ref = "unbound", "no oracle bound (intake's job, never the gate's)"
            elif kind in ("acceptance_test", "validation_exit", "wellformedness_parse"):
                passed = state.get("tests_passed")
                if passed is True:
                    verdict, ref = "satisfied", "validation pipeline passed"
                elif passed is False:
                    verdict, ref = "failed", "validation pipeline failed"
                else:
                    verdict, ref = "unevaluable", "no automated validator ran"
            elif kind == "tests_unmodified":
                tampered = bool(state.get("tests_modified"))
                verdict = "failed" if tampered else "satisfied"
                ref = "tamper guard (integrity baseline)"
            elif kind == "ast_transformation_contract":
                verdict, ref = _eval_transformation(text, workspace, task, clauses)
            elif kind == "non_use":
                verdict, ref = _eval_non_use(text, workspace)
            elif kind == "consumer_impact":
                verdict, ref = eval_consumer_impact(text, workspace)
            else:
                verdict, ref = "unevaluable", f"unknown oracle_kind {kind!r}"
        except Exception as exc:  # deny-by-default: no park, no vouch
            verdict, ref = "unevaluable", f"evaluator fault: {type(exc).__name__}"
        rows.append({"claim_id": cid, "verdict": verdict, "oracle_ref": ref})
    return rows


def failed_claim_ids(dispositions: list[dict[str, Any]]) -> list[str]:
    """The ids the gate receives — ONLY evaluated failures (owner decision 2026-08-03)."""
    return [str(d["claim_id"]) for d in dispositions if d.get("verdict") == "failed"]


def failed_claim_classes(
    dispositions: list[dict[str, Any]], claims: list[dict[str, Any]]
) -> list[str]:
    """The EVIDENCE CLASSES present among failed claims — what the gate consumes (ADR-0092).

    Core classifies; the gate only names the three classes. This is the seam that keeps
    `ORACLE_KINDS` from being mirrored into `packages/policies`, where nothing would force the two
    copies to move together — ADR-0090's own defect, which MR2 would otherwise recreate one layer
    down. Adding a seventh oracle kind fails `test_claim_evidence_class.py` here, loudly, instead
    of silently emitting no reason over there.

    Sorted and deduplicated so the gate's reason order is deterministic, and so the stall breaker
    sees a stable value. An unclassifiable kind is DROPPED rather than guessed — the totality test
    is what makes that safe, and guessing a class is how a tamper would get a benign label.
    """
    kinds = {
        str(c.get("id")): str(c.get("oracle_kind", "none")) for c in claims if isinstance(c, dict)
    }
    classes = {
        CLAIM_EVIDENCE_CLASS[kind]
        for d in dispositions
        if isinstance(d, dict) and d.get("verdict") == "failed"
        for kind in [kinds.get(str(d.get("claim_id")), "none")]
        if kind in CLAIM_EVIDENCE_CLASS
    }
    return sorted(classes)


def failed_claim_kinds(
    dispositions: list[dict[str, Any]], claims: list[dict[str, Any]]
) -> dict[str, int]:
    """How many FAILED claims of each ``oracle_kind`` — the instrument behind ADR-0090.

    ``unsatisfied_claim`` is one reason string over evidence classes with opposite meanings: for the
    behavioural kinds the "oracle" is ``state["tests_passed"]`` verbatim (see ``evaluate_claims``
    above), so a failure there restates ``validation_failed``; an ``ast_transformation_contract``
    failure is a genuinely independent fact; a ``tests_unmodified`` failure IS the tamper guard.
    Reading the ids alone cannot tell them apart, which is why the 2026-08-08 measurement had to
    proxy the split on the co-presence of ``validation_failed`` (n=118: 86% grader-pass with it,
    31% without). Recording the kind makes that split a direct read.

    Counts, not ids — the ids already ride ``GateDecision.unsatisfied_claims``, and an instrument
    that reports a number keeps what produced it without duplicating it.
    """
    kinds = {
        str(c.get("id")): str(c.get("oracle_kind", "none")) for c in claims if isinstance(c, dict)
    }
    out: dict[str, int] = {}
    for d in dispositions:
        if isinstance(d, dict) and d.get("verdict") == "failed":
            kind = kinds.get(str(d.get("claim_id")), "unknown")
            out[kind] = out.get(kind, 0) + 1
    return out


def satisfied_structural_claim_ids(
    dispositions: list[dict[str, Any]], claims: list[dict[str, Any]]
) -> list[str]:
    """Satisfied MATERIAL ``ast_transformation_contract`` claims — the #60 refactor-vouch
    input, and ONLY that kind by design: ``tests_unmodified`` rows ARE the tamper guard and
    behavioral rows ARE ``tests_passed`` — counting either as an *independent* oracle would
    double-count evidence the conjunction already holds. A structural satisfaction is the one
    genuinely NEW fact: the delivered AST provably has the shape the operator asked for."""
    kinds = {
        str(c.get("id")): str(c.get("oracle_kind", ""))
        for c in claims
        if isinstance(c, dict) and c.get("material", True)
    }
    return [
        str(d["claim_id"])
        for d in dispositions
        if d.get("verdict") == "satisfied"
        and kinds.get(str(d.get("claim_id"))) == "ast_transformation_contract"
        # DELTA-PROVING only (red-team FIX-NOW, 2026-08-03): a preservation-style predicate
        # (layout) is TRUE BEFORE ANY WORK by design, so a trivial touched delivery could
        # satisfy it and vouch unfinished work — a NEW ship channel, not a degrade-to-
        # baseline residual. Shrink/single-if/shared-helper are false on the seed by
        # construction; layout is excluded from vouching (it still parks when violated).
        and not str(d.get("oracle_ref", "")).startswith("layout_preserved")
    ]
