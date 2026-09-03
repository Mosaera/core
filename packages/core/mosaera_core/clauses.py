"""Ratified clauses: reading, writing, and what they change (ADR-0082 tier 2).

The gap this closes, measured 2026-08-04: stating "at most 5 statements" in a brief moved a paired
benchmark from 0/6 to 5/6 grader-clean (Fisher p = 0.015) — but the repair was authored by hand and
nothing recorded it, so the next item asked the same question again. A clause is that decision
written down once. This module is the only place that knows what one DOES.

The layering is deliberate and worth stating, because the trust boundary is split:

- ``mosaera_policies.standards`` decides whether a clause MAY exist (three independent limits).
- ``mosaera_memory`` stores it, and validates SHAPE only — it is a leaf and cannot import policies.
- here: ``ratify_clause`` is the single write path (policy check before the store ever sees it),
  and ``load_clauses`` re-validates EVERY row on the way out.

Read-time is the real guarantee, not a belt-and-braces repeat of write-time. It is what makes a
clause minted before the deny-list grew fail to load, what retires every clause citing a standard
that was renamed, and what catches a row that reached the table by some other path — a restored
backup, a manual INSERT, a future second writer. A clause survives exactly as long as it would be
ratifiable today.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any, Protocol

from mosaera_policies.standards import (
    STANDARDS,
    standard_scope,
    validate_clause,
)

from mosaera_core.structural_spec import (
    StructuralConstraints,
    extract_structural_constraints,
)

_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


class _ClauseStore(Protocol):
    """The store surface this module needs — mirrors ``ClausesMixin`` exactly.

    Spelled out rather than ``**kwargs``: a structural type looser than the thing it describes
    would accept a store that silently ignores half the record.
    """

    def clause_insert(
        self,
        clause_id: str,
        *,
        project_id: str | None,
        standard_id: str,
        binds: str,
        value_kind: str,
        value_num: int | None = ...,
        when_param: str | None = ...,
        when_op: str | None = ...,
        when_num: int | None = ...,
        because: str = ...,
        author: str = ...,
        provenance: dict[str, Any] | None = ...,
    ) -> dict[str, Any]: ...
    def clause_list(
        self, project_id: str | None = ..., *, include_superseded: bool = ...
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class Clause:
    """One validated, ratified decision.

    **The field set IS the structural limit** — there is no ``waives``, no ``reason``, no
    ``verdict``, no ``oracle``. A clause can set a registered parameter and say why; it has no
    vocabulary for standing between a run and its evidence. A future field that gives it one is a
    change to what this artifact can express, which is an ADR, not a patch (pinned by
    ``test_the_clause_field_set_is_the_limit``).
    """

    id: str
    project_id: str | None
    standard_id: str
    binds: str
    value_kind: str  # advisory | number | unbounded
    value_num: int | None
    when_param: str | None
    when_op: str | None
    when_num: int | None
    because: str
    author: str


def _to_clause(row: dict[str, Any]) -> Clause:
    return Clause(
        id=str(row.get("id", "")),
        project_id=row.get("project_id"),
        standard_id=str(row.get("standard_id", "")),
        binds=str(row.get("binds", "")),
        value_kind=str(row.get("value_kind", "")),
        value_num=row.get("value_num"),
        when_param=row.get("when_param"),
        when_op=row.get("when_op"),
        when_num=row.get("when_num"),
        because=str(row.get("because", "")),
        author=str(row.get("author", "")),
    )


def make_clause(
    *,
    standard_id: str,
    binds: str,
    value_kind: str,
    value_num: int | None = None,
    project_id: str | None = None,
    author: str = "",
    because: str = "",
    when: tuple[str, str, int] | None = None,
) -> Clause:
    """A VALIDATED clause with no store behind it.

    Extracted so a caller with no database — the benchmark harness, chiefly — obeys exactly the
    same three limits as a ratified one. A bench arm that could express something the product
    cannot would measure a feature we do not ship.
    """
    when_param, when_op, when_num = when if when else (None, None, None)
    record = {
        "standard_id": standard_id,
        "binds": binds,
        "value_kind": value_kind,
        "value_num": value_num,
        "when_param": when_param,
        "when_op": when_op,
        "when_num": when_num,
    }
    refusal = validate_clause(record)
    if refusal:
        raise ValueError(f"clause refused: {refusal}")
    scope = standard_scope(standard_id)
    scoped = project_id if scope == "project" else None
    if scope == "project" and not scoped:
        raise ValueError(f"{standard_id} is project-scoped — a clause citing it needs a project")
    return Clause(
        id=f"cl-{uuid.uuid4().hex[:12]}",
        project_id=scoped,
        standard_id=standard_id,
        binds=binds,
        value_kind=value_kind,
        value_num=value_num,
        when_param=when_param,
        when_op=when_op,
        when_num=when_num,
        because=because,
        author=author,
    )


def ratify_clause(
    memory: _ClauseStore,
    *,
    standard_id: str,
    binds: str,
    value_kind: str,
    value_num: int | None = None,
    project_id: str | None = None,
    author: str = "",
    because: str = "",
    provenance: dict[str, Any] | None = None,
    when: tuple[str, str, int] | None = None,
) -> Clause:
    """Validate and store one clause. THE single caller of ``clause_insert``.

    ``project_id`` is a hint only: the stored scope is derived from the cited standard, because
    scope is inherited and never chosen (ADR-0082 §3). A repo-scoped standard forces ``None``
    whatever the caller passed, so a caller cannot narrow or widen a standard's reach by asking.
    """
    draft = make_clause(
        standard_id=standard_id,
        binds=binds,
        value_kind=value_kind,
        value_num=value_num,
        project_id=project_id,
        author=author,
        because=because,
        when=when,
    )
    when_param, when_op, when_num = draft.when_param, draft.when_op, draft.when_num
    row = memory.clause_insert(
        draft.id,
        project_id=draft.project_id,
        standard_id=standard_id,
        binds=binds,
        value_kind=value_kind,
        value_num=value_num,
        when_param=when_param,
        when_op=when_op,
        when_num=when_num,
        because=because,
        author=author,
        provenance=provenance or {},
    )
    return _to_clause(row)


def load_clauses(
    memory: _ClauseStore | None, project_id: str | None, *, enabled: bool = False
) -> tuple[Clause, ...]:
    """Every live clause that applies here, re-validated against TODAY's registries.

    ``enabled`` is the ``clauses_enabled`` posture knob and defaults to FALSE — deny-by-default,
    so a caller that forgets to thread the setting gets today's behaviour rather than silently
    activating a feature that is still awaiting its bench A/B.

    A row that would not be ratifiable now is dropped, not honoured. Best-effort by construction:
    a store failure yields no clauses, so the system falls back to asking — which is the safe
    direction, since the cost of a missing clause is one question and the cost of a wrongly
    honoured one is an unenforced standard.
    """
    if memory is None or not enabled:
        return ()
    try:
        rows = memory.clause_list(project_id)
    except Exception:
        return ()
    live: list[Clause] = []
    for row in rows:
        if validate_clause(row):
            continue  # stale, deny-listed, or never legitimate — see the module docstring
        live.append(_to_clause(row))
    return tuple(live)


def clauses_from_state(raw: Any) -> tuple[Clause, ...]:
    """Clauses as they come back out of ``RunState``.

    They ride the graph as plain dicts because the durable checkpointer serialises state to JSON —
    a dataclass would not survive an API restart, and a parked run rehydrating without its standing
    decisions would silently revert to the pre-clause behaviour mid-run. Re-validated here for the
    same reason ``load_clauses`` re-validates: a checkpoint can outlive the registry it was written
    against.
    """
    rows = [r for r in (raw or []) if isinstance(r, dict)]
    return tuple(_to_clause(r) for r in rows if not validate_clause(r))


def clause_for(clauses: tuple[Clause, ...], param: str, **facts: int) -> Clause | None:
    """The live clause binding ``param``, or None. Conditions are evaluated against ``facts``.

    A condition is one comparison drawn from a fixed vocabulary — no expression language, nothing
    evaluated. An unknown fact means the condition cannot be shown to hold, so the clause does not
    apply: a condition that silently defaults to true would be a waiver with extra steps.
    """
    for clause in clauses:
        if clause.binds != param:
            continue
        if clause.when_param:
            fact = facts.get(clause.when_param)
            op = _OPS.get(clause.when_op or "")
            if (
                fact is None
                or op is None
                or clause.when_num is None
                or not op(fact, clause.when_num)
            ):
                continue
        return clause
    return None


def applied_marks(
    before: StructuralConstraints | None, after: StructuralConstraints | None
) -> list[str]:
    """What a standing decision actually CHANGED, as stable strings for the record.

    Engagement, not configuration. A clause that was loaded but never altered the check did not
    fire, and an A/B cannot count it — the liveness ladder asks whether the control DID something,
    and this is the only place that answer exists for an input-side lever.
    """
    if before is None or after is None:
        return []
    marks = []
    if before.max_body != after.max_body:
        marks.append(f"structural.body_statements={after.max_body}")
    if before.min_helpers != after.min_helpers:
        marks.append(f"structural.min_helpers={after.min_helpers}")
    return marks


# The parameters `apply_to_constraints` below knows how to bind. Kept beside it deliberately: a
# parameter added there and not here would be silently dropped from the criteria by
# `binding_clauses`, which is the failure this pair must not have.
_BINDABLE_CONSTRAINTS = frozenset({"structural.body_statements", "structural.min_helpers"})


def apply_to_constraints(
    constraints: StructuralConstraints | None, clauses: tuple[Clause, ...], **facts: int
) -> StructuralConstraints | None:
    """Overlay ratified numbers onto the structural asks a brief stated.

    This is what makes a clause BIND an oracle parameter rather than merely decorate a prompt. It
    only ever fills in a number the brief left open (``wants_shorter`` — "a short orchestrator"
    with no count): an explicit ``<= N`` in the brief is the item's own statement and a standing
    decision does not overrule it. Numbers can therefore only become MORE determinate here, never
    looser than what was asked for.
    """
    if constraints is None:
        return None
    body = clause_for(clauses, "structural.body_statements", **facts)
    if body is not None and body.value_kind == "number" and constraints.max_body is None:
        constraints = replace(constraints, max_body=body.value_num, wants_shorter=False)
    helpers = clause_for(clauses, "structural.min_helpers", **facts)
    if helpers is not None and helpers.value_kind == "number" and constraints.min_helpers is None:
        constraints = replace(constraints, min_helpers=helpers.value_num)
    return constraints


# How each parameter reads in a sentence. Presentation lives here, NOT in `mosaera_policies` —
# that registry says what may be bound, and should not also decide how it is phrased. The
# direction matters: `min_helpers` is a floor, so rendering every number as "at most" would state
# the opposite of the ratified decision, which is worse than not rendering it at all.
_PHRASE: dict[str, tuple[str, str]] = {
    "structural.body_statements": ("a function body is at most {n} statements", "function length"),
    "structural.min_helpers": ("a refactor delegates to at least {n} helpers", "delegation"),
}


def _rule_sentence(clause: Clause) -> str:
    """The decision as one sentence. ONE source of truth, so the task string and the prompt block
    can never state the same clause differently."""
    template, subject = _PHRASE.get(
        clause.binds, ("{n}", clause.binds.rsplit(".", 1)[-1].replace("_", " "))
    )
    if clause.value_kind == "number":
        rule = template.format(n=clause.value_num)
    elif clause.value_kind == "unbounded":
        rule = f"{subject} has no fixed limit"
    else:
        rule = f"{subject} is deliberately left to your judgement"
    if clause.when_param:
        rule += f" when {clause.when_param.replace('_', ' ')} {clause.when_op} {clause.when_num}"
    return rule


def _render(clause: Clause) -> str:
    standard = STANDARDS.get(clause.standard_id)
    title = standard.title if standard else clause.standard_id
    line = f"- {_rule_sentence(clause)} ({clause.id}, cites {title})"
    return f"{line} — {clause.because}" if clause.because else line


def clause_task_suffix(clauses: tuple[Clause, ...]) -> str:
    """Ratified decisions as acceptance criteria, for the TASK string. ``""`` when there are none.

    Measured 2026-08-05, and the reason this exists: the same number delivered as a separate
    "Standing decisions" section moved NOTHING (0/12 control vs 0/4 treatment) while writing it
    into the brief moved 0/6 to 5/6. The diagnosis was not prompt strength — it was channel. That
    section lands in the planning OVERVIEW, while the Proctor's authoring ask, the coder's
    implement instruction and the structural gate all read ``state["task"]``. A decision that never
    enters the task reaches none of them.

    So this renders into the criteria the item already states, in the same voice, because that is
    the text every downstream consumer actually reads. Generated from the stored integer and never
    parsed back — the one-way rule the whole clause tier depends on.
    """
    if not clauses:
        return ""
    return "\n".join(f"- {_rule_sentence(c)} (standing decision {c.id})" for c in clauses)


def binding_clauses(
    clauses: tuple[Clause, ...], item_text: str, **facts: int
) -> tuple[Clause, ...]:
    """The clauses that actually BIND something in this item — the rest do not belong in its
    criteria.

    Measured 2026-08-24 (MCB-01, a greenfield CLI case): weaving unconditionally put "a function
    body is at most 5 statements" into a brief that asked for no such thing. It bound no oracle
    (`[ENTAILED → none]`), so nothing deterministic could ever confirm it — but the reviewer read
    it as a requirement and returned REQUEST_CHANGES forever. Five of five runs parked at ~1.7M
    tokens each on a tree the grader passed 8/8. An unbound criterion is not a stricter standard;
    it is an unbounded model judgement with veto power, which is what Deterministic Final Authority
    exists to prevent.

    The predicate is not new: this is the same `extract → apply → applied_marks` chain the claim
    oracle already uses to decide whether a clause ENGAGED (`claim_oracles.py`). Before this, the
    text and the record could disagree — MCB-01's scorecard reported `clauses_applied: []` while
    the run was being vetoed on the clause. Now they cannot.

    A clause binding a parameter `apply_to_constraints` does not handle passes through UNCHANGED.
    Every registered parameter is structural today, so this is presently unreachable — but dropping
    a ratified operator decision because this function did not recognise it would be a waiver with
    extra steps, and silence is the wrong default for that.

    A CONDITIONAL clause (`when module_lines < 500`) is not woven, and that is a decision rather
    than an oversight. At weave time the code does not exist, so no fact can be supplied and the
    condition cannot be shown to hold — the same reading `clause_for` already takes. Rendering it
    anyway would state a requirement that may not apply to the tree finally produced, which is the
    MCB-01 shape again. The CHECK still enforces it: `apply_to_constraints` runs at claim-evaluation
    time with real facts, so a condition that does hold is enforced there and the coder learns it
    from a failing structural check rather than from an unprovable line in the brief.
    """
    if not clauses:
        return ()
    handled = tuple(c for c in clauses if c.binds in _BINDABLE_CONSTRAINTS)
    passthrough = tuple(c for c in clauses if c.binds not in _BINDABLE_CONSTRAINTS)
    if not handled:
        return passthrough
    stated = extract_structural_constraints(item_text)
    bound = frozenset(
        mark.split("=", 1)[0]
        for mark in applied_marks(stated, apply_to_constraints(stated, handled, **facts))
    )
    return passthrough + tuple(c for c in handled if c.binds in bound)


def weave_criteria(
    acceptance: str, clauses: tuple[Clause, ...], *, item_text: str | None = None
) -> str:
    """The acceptance criteria a run is actually given: the item's own text plus the ratified
    standing decisions that ACTUALLY BIND it, as one list.

    Per RUN, never written back to the item. That is the whole reason this is a function and not
    an `enhance` op: a clause is revocable by design, so retiring one must take effect on the next
    run and must never be able to rewrite work already delivered — or the item's acceptance stops
    meaning "what the operator asked for".

    `item_text` is the text relevance is judged against, defaulting to `acceptance`. It exists
    because an item's structural ask often lives in its TITLE or DESCRIPTION while only the
    acceptance field is woven — judging on the acceptance alone would drop a clause the item really
    did leave open. A caller holding the whole item passes all of it (`task_spec.build_run_task`);
    a caller whose acceptance IS the whole brief (the bench) needs nothing.
    """
    suffix = clause_task_suffix(
        binding_clauses(clauses, item_text if item_text is not None else acceptance)
    )
    if not suffix:
        return acceptance
    return f"{acceptance}\n{suffix}" if acceptance else suffix


def clauses_prompt_block(clauses: tuple[Clause, ...]) -> str:
    """Ratified decisions rendered for a prompt, or ``""`` when there are none.

    Rendering is ONE-WAY. This text is generated FROM a structured integer and is never read back:
    a value re-derived from prose is the exact defect this arc exists to remove, and it would be an
    easy one to reintroduce here by parsing our own output.
    """
    if not clauses:
        return ""
    body = "\n".join(_render(c) for c in clauses)
    return (
        "## Standing decisions (ratified by the operator — honor them)\n"
        "These were settled once and apply to every item; they are not suggestions, and you do "
        "not need to ask about them again.\n" + body
    )
