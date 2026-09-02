"""Deterministic structural-spec check for refactor / decomposition tasks (#80, ADR-0072).

A refactor task can carry a **structural** acceptance criterion — *"refactor ``f`` into a short
orchestrator that delegates to at least three helpers"* — that has **no behavioural signature**:
the delivered code can be perfectly behaviour-preserving (the refactor oracle vouches, the suite is
green) yet miss the requested *shape* (a 7-statement orchestrator when a handful was asked). That is
the MCB-05 false_ship class — distinct from the executed-but-unasserted class the mutation oracle
(#74) catches, because here there is nothing to mutate: the behaviour is correct.

This module extracts such asks from the task brief and checks the delivered function's AST against
them. It is the **Layer-1 floor** (ADR-0072): it can only ever *downgrade*.

- ``True``  — a structural constraint was found and the delivered function meets it.
- ``False`` — a structural constraint was found and is UNMET → the gate downgrades
  ``oracle_verified`` → the run parks honestly (never ships a shape it can't verify).
- ``None``  — no structural constraint in the brief, the target can't be located / parsed, **or a
  constraint was present but no predicate could actually be evaluated** (unverifiable) → **no
  effect** (deny-by-default: never downgrades, never vouches).

That third ``None`` case is load-bearing and was once a ``True``: a constraint can be present and
still be unmeasurable — no pre-refactor baseline to compare against, or nothing large enough to
decompose — and an empty list of complaints cannot tell "every check passed" from "no check ran".
Because a *satisfied* structural claim is the sole input to the #60 refactor vouch
(``satisfied_structural_claim_ids`` → ``structural_vouch_ids`` → ``oracle_verified``), a verdict
reached without executing a single predicate would be independence evidence manufactured from
nothing. **Zero executed predicates is never met.**

It never ships anything — a ``False`` can only turn a would-be ship into a park, so it can never
manufacture a false_ship. The Phase-2 iterate that converts such a park → deliver is wired
separately; this module is only the honest floor.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass

# The soft bound for an EXPLICIT "<= N statements" ask. Retained only for that case — a brief that
# names a number is stating a real constraint, not asking us to guess one.
#
# The BARE "a handful of statements" language no longer resolves to a constant (ADR-0072
# successor). The old `_HANDFUL = 6` was provably unsound: MCB-05 and MCB-15 use near-identical
# brief wording, both extracted 6, yet their graders score <=6 and <=7 — no fixed integer satisfies
# both. That contradiction is not fixable by better brief-extraction (the deterministic cousin of
# the ADR-0070 LLM-judge dead end). It is replaced by a RELATIVE measure — see `_SHRINK_NUM/DEN`.
_HANDFUL = 6

# "Short orchestrator" measured against the function's OWN pre-refactor self, not a guessed
# absolute. Measured on the two refactor cases' known-correct references:
#
#     MCB-05  checkout_total   8 statements -> 4  (50%)   loops 1 -> 0
#     MCB-15  parse_log_line   8 statements -> 3  (38%)   loops 1 -> 0
#
# ...versus a delivered-but-wrong shape that keeps the work inline: 7 of 8 (88%).
#
# ONE dimensionless ratio separates both references from that, where no single absolute could
# separate MCB-05 from MCB-15. 2/3 is deliberately loose: it clears both references with a
# statement of headroom, because the error this must avoid is a FALSE PARK of a correct refactor.
_SHRINK_NUM, _SHRINK_DEN = 2, 3

_NUMWORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"

# The task must actually ask for a structural decomposition, not just any change.
_INTENT = re.compile(r"\b(refactor|decompose|orchestrat|delegat|extract\s+\w+\s+into)", re.I)

# "delegates to at least three helper functions" / "3 helpers"
_HELPERS = re.compile(_NUM + r"\s+(?:\w+[\s,-]+){0,3}?(?:helper|sub-?function)", re.I)
# explicit "no more than 6 statements" / "under 5 lines"
_MAX_BODY = re.compile(
    r"(?:no more than|at most|under|fewer than|up to|within|<=|≤)\s*"
    + _NUM
    + r"\s*(?:statement|line)",
    re.I,
)
# soft "short orchestrator" / "a handful of statements"
_SOFT_BODY = re.compile(
    r"short orchestrator|concise orchestrator"
    r"|a handful of (?:statement|line)|a few (?:statement|line)",
    re.I,
)


def _num(token: str) -> int | None:
    # Deny-by-default on an absurd magnitude: a >6-digit count is not a real body/helper bound, and
    # int() on a >4300-digit token raises ValueError (Python's int-str limit, red-team F1) — treat
    # both as no-constraint rather than letting the module raise out of its "never raises" contract.
    if token.isdigit():
        return int(token) if len(token) <= 6 else None
    return _NUMWORDS.get(token.lower())


@dataclass(frozen=True)
class StructuralConstraints:
    """The structural acceptance asks extracted from a task brief."""

    target: str | None  # the function to refactor, if the brief names it
    min_helpers: int | None  # "delegates to >= N helpers"
    max_body: int | None  # an EXPLICIT "<= N statements" only — never a guessed "handful"
    # The brief asked for a "short orchestrator" WITHOUT naming a number. Checked relatively,
    # against the function's own pre-refactor body — see `check_structural_compliance`.
    wants_shorter: bool = False

    @property
    def has_check(self) -> bool:
        return self.min_helpers is not None or self.max_body is not None or self.wants_shorter


def _extract_target(brief: str) -> str | None:
    """The function the task asks to refactor, if it names one (backtick-quoted identifier)."""
    for pat in (
        r"refactor\w*[\s*_`]{0,3}`?([A-Za-z_]\w*)`",  # "Refactor `checkout_total`" (tolerates **)
        r"`([A-Za-z_]\w*)`\s+(?:should|must)\s+(?:read|be|become|delegat)",  # "`x` should read as…"
        r"refactor\w*\s+the\s+`?([A-Za-z_]\w*)`?\s+function",  # "refactor the checkout function"
    ):
        m = re.search(pat, brief, re.I)
        if m:
            return m.group(1)
    # Fallback: the most frequently backtick-quoted bare identifier is very likely the subject.
    ids = re.findall(r"`([A-Za-z_]\w*)`", brief)
    return Counter(ids).most_common(1)[0][0] if ids else None


def extract_structural_constraints(brief: str) -> StructuralConstraints | None:
    """Parse a task brief for a structural decomposition criterion. ``None`` when the brief states
    no such shape (nothing to check → the check has no effect)."""
    if not brief or not _INTENT.search(brief):
        return None
    helpers = _HELPERS.search(brief)
    min_helpers = _num(helpers.group(1)) if helpers else None
    explicit = _MAX_BODY.search(brief)
    max_body = _num(explicit.group(1)) if explicit else None
    # A bare "short orchestrator / a handful" no longer invents a number (ADR-0072 successor): it
    # records the ASK, and the check resolves it against the pre-refactor body.
    wants_shorter = max_body is None and bool(_SOFT_BODY.search(brief))
    if min_helpers is None and max_body is None and not wants_shorter:
        return None
    return StructuralConstraints(_extract_target(brief), min_helpers, max_body, wants_shorter)


def _target_fn(
    mod: ast.Module, target: str | None
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    fns = [n for n in mod.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if target:
        return next((n for n in fns if n.name == target), None)
    return None  # deny-by-default: no named target → we won't guess which function to judge


def _body_stmts(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Top-level statements in ``fn``, EXCLUDING a leading docstring.

    The docstring is excluded because a well-documented refactor must not be penalised for it —
    the old absolute check counted it, which is one more way a fixed number misjudged shape.

    MEASURED CONSEQUENCE (2026-08-12): instruments that count ``len(fn.body)`` raw — the MCB
    graders do — read one MORE than this on any documented function, so a clause bound of N here
    admits work such a grader scores N+1 and refuses. That one-statement gap produced E4's two
    false ships (clause=6 vs a ``<= 6`` grader). The ratified bench default is therefore 5, not
    6: changing this counter instead was rejected because it would penalise documentation, which
    is this docstring's own rationale.
    """
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return len(body)


def _total_stmts(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """EVERY statement anywhere in ``fn`` — nested ones included — minus the def and a docstring.

    RED-TEAM R1 (ADR-0072 successor): a top-level count is trivially defeated by one level of
    nesting — wrap nine statements in `if True:` and the body "is" one statement. ADR-0072's
    original red-team found exactly this against the ABSOLUTE check ("trivially defeated by one
    level of nesting"); its disposition dropped that check, so the mitigation was never written,
    and the relative measure inherited the hole. Measured: the nesting dodge reads 11% of the
    original when counted top-level (passes) and 111% counted in full (caught).

    Counting in full also gives correct refactors MORE headroom, because the work they extracted
    was nested: the known-correct references fall to 25% and 23% of their originals, versus 50%
    and 38% top-level. Nested `def`s count on purpose — a helper defined INSIDE the orchestrator
    is not delegation to a module helper.
    """
    n = sum(1 for x in ast.walk(fn) if isinstance(x, ast.stmt)) - 1  # -1: the def itself
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        n -= 1
    return n


def _has_loop(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Does ``fn`` still iterate? Comprehensions count — they are iteration too."""
    return any(isinstance(n, (ast.For, ast.While, ast.comprehension)) for n in ast.walk(fn))


def _original_target(originals: dict[str, str] | None, target: str | None):
    """The PRE-refactor target function, from the diff's old side. ``None`` when unavailable —
    a new file, a greenfield task, or an unparseable original — which makes every relative check
    inert (deny-by-default: no baseline, no claim)."""
    if not originals or not target:
        return None
    for src in originals.values():
        try:
            mod = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError):
            continue
        fn = _target_fn(mod, target)
        if fn is not None:
            return fn
    return None


def check_structural_compliance(
    changed_sources: dict[str, str],
    c: StructuralConstraints,
    originals: dict[str, str] | None = None,
) -> tuple[bool | None, str]:
    """Check the delivered target function against ``c``. ``(True, …)`` met, ``(False, reason)``
    unmet → downgrade, ``(None, reason)`` unverifiable → no effect."""
    if not c.has_check:
        return None, "no structural constraint"
    # Every changed file defining the target, not just the first. RED-TEAM R2: returning on the
    # first match made the verdict depend on dict insertion order — a trivially-compliant decoy
    # `f` in one file shadowed the real, bloated `f` in another and produced a vouch.
    verdicts: list[tuple[bool, str]] = []
    for src in changed_sources.values():
        try:
            mod = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError):
            # Deny-by-default: a null-byte source (ValueError) or pathologically nested source
            # (RecursionError, red-team F2) is unverifiable → skip it, never raise out of the
            # module's "parse fault → None" contract onto the near-delivery path.
            continue
        fn = _target_fn(mod, c.target)
        if fn is None:
            continue
        module_fns = {
            n.name for n in mod.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        reasons: list[str] = []
        # Predicates REQUESTED by the brief vs predicates that actually EXECUTED. A constraint
        # can be present and still be unevaluable (no baseline to measure against, nothing
        # large enough to decompose), and an empty `reasons` list cannot tell that apart from
        # "every check passed". A satisfied structural claim VOUCHES
        # (satisfied_structural_claim_ids -> structural_vouch_ids -> oracle_verified), so a
        # `True` here becomes evidence the gate trusts — and may only be earned when every
        # requested predicate ran. RED-TEAM R1: "short orchestrator delegating to >= 2 helpers"
        # with no baseline used to pass on the helper count alone, reporting that the shape was
        # met when only half of it had been looked at.
        requested = sum((c.max_body is not None, c.wants_shorter, c.min_helpers is not None))
        checks_run = 0
        if c.max_body is not None:
            # The brief NAMED a number — check it as stated.
            checks_run += 1
            if _body_stmts(fn) > c.max_body:
                reasons.append(
                    f"`{fn.name}` body is {_body_stmts(fn)} statements (the task asked for "
                    f"<= {c.max_body}) — extract the remaining work into helpers"
                )
        if c.wants_shorter:
            # "Short orchestrator" with no number: measure against the function's OWN pre-refactor
            # body (ADR-0072 successor). No baseline → no claim, so a greenfield/new function is
            # inert rather than judged against an invented constant.
            before = _original_target(originals, c.target)
            if before is not None:
                # Counted in FULL (nested included) so the ratio cannot be dodged by nesting,
                # and self-consistently on both sides.
                was, now = _total_stmts(before), _total_stmts(fn)
                # RED-TEAM R3 (false-park generator): on a SMALL original the ratio is
                # unsatisfiable, so a perfectly good refactor would be parked. An orchestrator
                # delegating to N helpers needs at least N+1 statements (one call each, plus a
                # return), so the bound `was * 2/3` is impossible whenever it falls below that.
                # The floor is DERIVED from the brief's own helper count, not guessed — and it can
                # only ever make the check more permissive, never park more.
                floor = ((c.min_helpers or 1) + 1) * _SHRINK_DEN
                if was * _SHRINK_NUM < floor:
                    # Nothing meaningful to decompose → no claim (deny-by-default). Deliberately
                    # does NOT count as an executed predicate: "too small to judge" is not "passed".
                    pass
                else:
                    checks_run += 1
                    if now * _SHRINK_DEN > was * _SHRINK_NUM:
                        reasons.append(
                            f"`{fn.name}` is {now} statements where it was {was} — a short "
                            f"orchestrator should be at most {_SHRINK_NUM}/{_SHRINK_DEN} of what "
                            "it replaced; the work is still inline"
                        )
                    elif _has_loop(before) and _has_loop(fn):
                        # Constant-free companion: "extract into helpers" means the ITERATION
                        # moves out. Both known-correct references go 1 loop -> 0. A
                        # shrunk-but-still-looping orchestrator kept the work it was asked to
                        # delegate.
                        reasons.append(
                            f"`{fn.name}` still iterates — the loop it was asked to extract is "
                            "still in the orchestrator, not in a helper"
                        )
        if c.min_helpers is not None:
            checks_run += 1
            called = {
                node.func.id
                for node in ast.walk(fn)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in module_fns
                and node.func.id != fn.name
            }
            if len(called) < c.min_helpers:
                reasons.append(
                    f"`{fn.name}` delegates to {len(called)} module helper(s) "
                    f"(wanted >= {c.min_helpers})"
                )
        if reasons:
            verdicts.append((False, "; ".join(reasons)))
            continue
        if checks_run < requested:
            # Some (or all) of the ask could not be measured — no baseline to compare against,
            # or nothing large enough to decompose. Unevaluable, never met: a partial look is
            # not proof of the shape, and this verdict vouches.
            return None, (
                f"`{fn.name}`: {checks_run} of {requested} structural checks could be "
                "evaluated (no pre-refactor baseline, or nothing large enough to decompose)"
            )
        verdicts.append((True, f"`{fn.name}` meets the requested structure"))

    unmet = [r for met, r in verdicts if not met]
    if unmet:
        # A real unmet ask anywhere among the changed files is an honest downgrade.
        return False, "; ".join(unmet)
    if len(verdicts) > 1:
        # Several changed files define the target and all look compliant. Which one the brief
        # meant is genuinely ambiguous, and this verdict VOUCHES — so it is not earned.
        return None, (
            f"`{c.target}` is defined in {len(verdicts)} changed files — ambiguous target, "
            "the structural ask cannot be attributed"
        )
    if verdicts:
        return verdicts[0]
    return None, "target function not found in the changed files"


def evaluate_structural_spec(
    brief: str, changed_sources: dict[str, str], originals: dict[str, str] | None = None
) -> tuple[bool | None, str]:
    """Extract the structural asks from ``brief`` and check the delivered ``changed_sources``.

    Returns ``(verdict, reason)`` where verdict is ``True`` (met) / ``False`` (unmet → downgrade) /
    ``None`` (no constraint or unverifiable → no effect). Pure, deterministic, no sandbox.
    """
    constraints = extract_structural_constraints(brief)
    if constraints is None:
        return None, "no structural spec in the brief"
    return check_structural_compliance(changed_sources, constraints, originals)
