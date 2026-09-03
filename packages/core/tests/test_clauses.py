"""Ratified clauses (ADR-0082 tier 2) — the read path, and what it refuses to honour."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from mosaera_core.clauses import (
    Clause,
    apply_to_constraints,
    clause_for,
    clause_task_suffix,
    clauses_prompt_block,
    load_clauses,
    ratify_clause,
    weave_criteria,
)
from mosaera_core.structural_spec import StructuralConstraints, extract_structural_constraints
from mosaera_policies import standards


class _FakeStore:
    """The store contract only — shape validation, no policy knowledge (it is a leaf)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def clause_insert(self, clause_id: str, **kw: Any) -> dict[str, Any]:
        row = {"id": clause_id, **kw}
        self.rows = [
            r
            for r in self.rows
            if (r["project_id"], r["standard_id"], r["binds"])
            != (kw["project_id"], kw["standard_id"], kw["binds"])
        ]
        self.rows.append(row)
        return row

    def clause_list(
        self, project_id: str | None = None, *, include_superseded: bool = False
    ) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["project_id"] in (None, project_id)]


def _load(store: _FakeStore) -> tuple[Clause, ...]:
    """Clauses with the posture knob ON. The default is OFF — deny-by-default — so a caller that
    forgets to thread the setting gets today's behaviour rather than silently activating a
    feature still awaiting its bench A/B."""
    return load_clauses(store, "p1", enabled=True)


def _ratify(store: _FakeStore, **over: Any) -> Clause:
    kwargs: dict[str, Any] = {
        "standard_id": "standards/house-style",
        "binds": "structural.body_statements",
        "value_kind": "number",
        "value_num": 5,
        "project_id": "p1",
        "because": "correctness over line count",
    }
    kwargs.update(over)
    return ratify_clause(store, **kwargs)


# --- the write path -----------------------------------------------------------------------


def test_the_measured_decision_is_ratifiable() -> None:
    store = _FakeStore()
    clause = _ratify(store)
    assert clause.value_num == 5
    assert _load(store)[0].id == clause.id


def test_a_refused_clause_never_reaches_the_store() -> None:
    """The write-time check runs BEFORE the store sees anything — a refusal leaves no trace."""
    store = _FakeStore()
    with pytest.raises(ValueError, match="not a registered oracle parameter"):
        _ratify(store, binds="module.max_lines", value_num=800)
    with pytest.raises(ValueError, match="does not leave"):
        _ratify(store, standard_id="standards/layer-direction")
    assert store.rows == []


def test_scope_is_inherited_from_the_standard_never_chosen() -> None:
    """A caller cannot widen or narrow a standard's reach by asking (ADR-0082 §3)."""
    store = _FakeStore()
    # A repo-scoped standard forces project_id to None even when a project is supplied.
    repo = _ratify(store, standard_id="standards/module-ceiling", project_id="p1")
    assert repo.project_id is None
    # And a project-scoped standard cannot be ratified without one.
    with pytest.raises(ValueError, match="needs a project"):
        _ratify(store, standard_id="standards/house-style", project_id=None)


# --- the read path: the real guarantee -----------------------------------------------------


def test_read_time_beats_write_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "A clause minted before the list grew cannot grandfather a waiver in" — executed.

    The clause is legitimately ratified, then the world changes underneath it. Nothing rewrites
    the row; it simply stops loading.
    """
    store = _FakeStore()
    _ratify(store)
    assert len(_load(store)) == 1

    proof_bearing = standards.OracleParam(
        "structural.body_statements", "int", 1, 50, "tests_tampered"
    )
    monkeypatch.setitem(standards.PARAMS, "structural.body_statements", proof_bearing)
    assert _load(store) == (), "a now-proof-bearing parameter must stop loading"


def test_a_retired_standard_takes_its_clauses_with_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """No expiry dates: validity is a FUNCTION of the parent (ADR-0082 §3)."""
    store = _FakeStore()
    _ratify(store)
    monkeypatch.delitem(standards.STANDARDS, "standards/house-style")
    assert _load(store) == ()


def test_a_row_that_bypassed_ratify_is_still_refused() -> None:
    """The read check is not a repeat of the write check — it is the one that covers rows the
    write path never saw: a restored backup, a manual INSERT, a future second writer."""
    store = _FakeStore()
    store.clause_insert(
        "cl-smuggled",
        project_id="p1",
        standard_id="standards/house-style",
        binds="gate.verdict",  # never registrable
        value_kind="number",
        value_num=1,
        when_param=None,
        when_op=None,
        when_num=None,
        because="",
        author="",
        provenance={},
    )
    assert _load(store) == ()


def test_a_store_failure_falls_back_to_asking() -> None:
    class _Broken(_FakeStore):
        def clause_list(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
            raise RuntimeError("db down")

    # The safe direction: the cost of a missing clause is one question; the cost of a wrongly
    # honoured one is an unenforced standard.
    assert load_clauses(_Broken(), "p1", enabled=True) == ()
    assert load_clauses(None, "p1", enabled=True) == ()


# --- what a clause is allowed to be ---------------------------------------------------------


def test_the_clause_field_set_is_the_limit() -> None:
    """The negative-space test: caught by ADDITION, not by use.

    A future `waives_reason` / `override` / `verdict` field would give a clause the vocabulary to
    stand between a run and its evidence. That is a change to what this artifact can express —
    an ADR, not a patch — so it fails here first.
    """
    assert {f.name for f in dataclasses.fields(Clause)} == {
        "id",
        "project_id",
        "standard_id",
        "binds",
        "value_kind",
        "value_num",
        "when_param",
        "when_op",
        "when_num",
        "because",
        "author",
    }


# --- conditions ------------------------------------------------------------------------------


def test_a_condition_that_cannot_be_shown_to_hold_does_not_apply() -> None:
    store = _FakeStore()
    _ratify(store, when=("module_lines", "<", 500))
    clauses = _load(store)

    assert clause_for(clauses, "structural.body_statements", module_lines=400) is not None
    assert clause_for(clauses, "structural.body_statements", module_lines=600) is None
    # No fact supplied: a condition that silently defaulted to true would be a waiver with
    # extra steps, so the clause simply does not apply.
    assert clause_for(clauses, "structural.body_statements") is None


# --- the overlay: what makes a clause bind an oracle rather than decorate a prompt -----------


def test_a_clause_fills_in_the_number_the_brief_left_open() -> None:
    brief = (
        "Refactor `checkout_total` into a short orchestrator that delegates to at least three "
        "helper functions, without changing behaviour."
    )
    constraints = extract_structural_constraints(brief)
    assert constraints is not None
    assert constraints.max_body is None and constraints.wants_shorter is True

    store = _FakeStore()
    _ratify(store)
    overlaid = apply_to_constraints(constraints, _load(store))
    assert overlaid is not None
    assert overlaid.max_body == 5
    assert overlaid.wants_shorter is False  # resolved to a number, no longer a relative ask


def test_a_clause_never_overrules_a_number_the_item_stated() -> None:
    """A standing decision fills gaps; it does not overrule the item in front of it."""
    stated = StructuralConstraints(target="f", min_helpers=3, max_body=9, wants_shorter=False)
    store = _FakeStore()
    _ratify(store)
    overlaid = apply_to_constraints(stated, _load(store))
    assert overlaid is not None and overlaid.max_body == 9


def test_the_overlay_is_a_noop_without_constraints_or_clauses() -> None:
    assert apply_to_constraints(None, ()) is None
    stated = StructuralConstraints(target="f", min_helpers=None, max_body=None, wants_shorter=True)
    assert apply_to_constraints(stated, ()) == stated


# --- rendering (one-way) ---------------------------------------------------------------------


def test_the_prompt_block_states_the_number_and_is_never_parsed_back() -> None:
    store = _FakeStore()
    _ratify(store)
    block = clauses_prompt_block(_load(store))
    assert "at most 5" in block
    assert "correctness over line count" in block
    assert "not suggestions" in block
    assert clauses_prompt_block(()) == ""


def test_a_minimum_is_never_rendered_as_a_maximum() -> None:
    """Direction matters more than phrasing.

    `min_helpers` is a floor. Rendering every number as "at most" would state the OPPOSITE of the
    ratified decision to the model that reads it — worse than not rendering it at all.
    """
    store = _FakeStore()
    _ratify(store, binds="structural.min_helpers", value_num=3)
    block = clauses_prompt_block(_load(store))
    assert "at least 3 helpers" in block
    assert "at most" not in block


def test_an_advisory_clause_says_the_operator_declined_to_fix_a_number() -> None:
    store = _FakeStore()
    _ratify(store, value_kind="advisory", value_num=None)
    block = clauses_prompt_block(_load(store))
    assert "left to your judgement" in block
    # …and it binds no number, so the oracle overlay leaves the brief's own ask untouched.
    stated = StructuralConstraints(target="f", min_helpers=None, max_body=None, wants_shorter=True)
    assert apply_to_constraints(stated, _load(store)) == stated


def test_the_posture_knob_is_deny_by_default() -> None:
    """Off unless asked for, at the load boundary rather than at each caller.

    ADR-0082's definition-of-done requires a clauses ON-vs-OFF bench A/B before any effectiveness
    claim, so the feature has to be genuinely inert by default — and a caller that forgets to
    thread the setting must get today's behaviour, not tomorrow's.
    """
    store = _FakeStore()
    _ratify(store)
    assert load_clauses(store, "p1") == ()  # default: off
    assert load_clauses(store, "p1", enabled=False) == ()
    assert len(load_clauses(store, "p1", enabled=True)) == 1


def test_ratify_clause_is_the_only_writer() -> None:
    """Backstops the one structural compromise in this design.

    `memory` is a leaf and cannot import `mosaera_policies`, so the WRITE-time policy check lives
    in `ratify_clause` rather than in the store. That is only safe while `ratify_clause` is the
    single caller of `clause_insert` — a second writer would be a hole, and would look like
    ordinary code. Read-time re-validation still catches it, but this fails first and says why.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    callers: list[str] = []
    for path in root.rglob("*.py"):
        # RELATIVE to root, deliberately. `.claude/worktrees/` holds sibling CHECKOUTS of this same
        # repo — CLAUDE.md mandates one worktree per session, so a tree-wide scan would find one
        # copy of every caller per active branch and report N instead of 1. Excluding them is not
        # loosening the guard: each worktree runs this same test against its own tree.
        #
        # Matching on ABSOLUTE parts broke exactly that promise. A worktree's own root IS
        # `.claude/worktrees/<name>`, so every path inside it contains "worktrees" and the filter
        # excluded the entire tree — the test then found 0 callers and failed, in the one place it
        # was written to keep working. Found 2026-08-11 running the slice-4 gates from a worktree.
        if set(path.relative_to(root).parts) & {"tests", ".venv", "migrations", "worktrees"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # The definition itself and the Protocol declaration are not calls.
        for line in text.splitlines():
            if re.search(r"(?<!def )\bclause_insert\(", line) and "def clause_insert" not in line:
                callers.append(f"{path.relative_to(root)}: {line.strip()[:80]}")
    assert len(callers) == 1, f"clause_insert must have exactly one caller, found: {callers}"
    assert "clauses.py" in callers[0]


def test_clauses_survive_the_graph_state_contract() -> None:
    """The failure my unit tests could not see.

    `apply_to_constraints` was tested directly and passed, while the value never actually reached
    it: `clauses` was seeded at launch but not DECLARED in `RunState`, so LangGraph dropped it
    between nodes and the oracle overlay never fired — in the bench or the product. A control
    that cannot fire is the exact class ADR-0081 exists to catch, and it caught this one on its
    first real use, in the feature that added it.

    So this asserts the contract itself: every key the launch path seeds must be a declared
    channel, or it is silently discarded.
    """
    from mosaera_core.graph.state import RunState

    declared = set(RunState.__annotations__)
    assert "clauses" in declared, "seeded-but-undeclared state is dropped between nodes"
    assert "claims" in declared  # the precedent this follows


def test_the_task_suffix_is_what_the_structural_gate_can_actually_read() -> None:
    """The channel fix, pinned as a property rather than as prose.

    Measured 2026-08-05: the same number in a separate "Standing decisions" block moved NOTHING
    (0/12 vs 0/4), while writing it into the brief moved 0/6 to 5/6. The diagnosis was channel,
    not prompt strength — that block lands in the planning overview, while the Proctor's authoring
    ask, the coder's instruction and `evaluate_structural_spec` all read `state["task"]`.

    So the test is: does the woven task make the number VISIBLE to the extractor the gate uses?
    """
    brief = (
        "Refactor `checkout_total` into a short orchestrator that delegates to at least three "
        "helper functions, without changing behaviour."
    )
    assert extract_structural_constraints(brief).max_body is None  # type: ignore[union-attr]

    store = _FakeStore()
    _ratify(store)
    woven = brief + "\n\n" + clause_task_suffix(_load(store))
    got = extract_structural_constraints(woven)
    assert got is not None and got.max_body == 5


def test_both_renderers_state_one_clause_identically() -> None:
    """Two surfaces, one sentence. A clause that reads differently in the task and in the prompt
    is two decisions wearing one id."""
    store = _FakeStore()
    _ratify(store)
    clauses = _load(store)
    assert "a function body is at most 5 statements" in clause_task_suffix(clauses)
    assert "a function body is at most 5 statements" in clauses_prompt_block(clauses)


def test_no_clause_means_no_suffix() -> None:
    # Deny-by-default reaches the task string too: nothing ratified, nothing woven, task unchanged.
    assert clause_task_suffix(()) == ""


def test_the_item_is_never_mutated_only_the_run_is() -> None:
    """Per-run, not written back — and this is the design's load-bearing property.

    A clause is REVOCABLE by design. If it were applied by rewriting the stored acceptance, then
    retiring it would not un-write the text, and an item already delivered would have its
    acceptance silently changed after the fact — retroactively altering what the MR claimed was
    accepted. Weaving per run keeps "the item's acceptance" meaning "what the operator asked for".
    """
    store = _FakeStore()
    _ratify(store)
    acceptance = "`f` reads as a short orchestrator delegating to helpers."
    woven = weave_criteria(acceptance, _load(store))

    assert acceptance in woven and "at most 5 statements" in woven
    assert woven != acceptance
    # The input is untouched — there is no write path here at all, which is the point.
    assert acceptance == "`f` reads as a short orchestrator delegating to helpers."
    # And with the decision retired, the next run is byte-identical to before it existed.
    assert weave_criteria(acceptance, ()) == acceptance


def test_the_woven_criteria_and_the_claims_cannot_disagree() -> None:
    """Claims must be minted from the WOVEN text.

    Mint them from the stored acceptance instead and the gate judges a different contract from the
    one the coder was handed — the claim set stops covering what the prompt asks for.
    """
    from mosaera_core.claims import claims_from_acceptance

    store = _FakeStore()
    _ratify(store)
    # The acceptance must LEAVE THE PARAMETER OPEN, or there is nothing to weave and this pins
    # nothing (it read "prints every matching note." until 2026-08-24, when weaving became
    # conditional). The assertion is unchanged; only the fixture now exercises it.
    woven = weave_criteria("`f` reads as a short orchestrator delegating to helpers.", _load(store))
    texts = [c.text for c in claims_from_acceptance(1, woven)]
    assert any("at most 5 statements" in t for t in texts)


def test_the_launch_task_has_exactly_one_definition() -> None:
    """The assertion that justifies extracting `build_run_task` rather than copying it.

    An instrument that rebuilds production's task string grades a contract production never sends.
    That is not hypothetical: the clause tier's first A/B came back null because the number was
    delivered through a channel `state["task"]` never touched. So the launch path and every
    harness call ONE function, and this pins that the flattening order and the claim source are
    the ones every downstream prompt was written against.
    """
    import inspect

    from mosaera_api.app_context import _launch
    from mosaera_core.task_spec import build_run_task

    store = _FakeStore()
    _ratify(store)
    item = {
        "id": 7,
        "title": "Refactor checkout",
        "description": "Split the long function.",
        "acceptance": "`f` reads as a short orchestrator delegating to helpers.",
    }
    task, claims = build_run_task(item, _load(store))

    # The order every prompt downstream assumes.
    assert task.startswith(
        "Refactor checkout\n\nSplit the long function.\n\nAcceptance criteria:\n"
    )
    assert "at most 5 statements" in task, "the decision must reach the task string"
    # Claims come from the WOVEN text, not the stored acceptance — mint them from the stored text
    # and the gate judges a different contract from the one the coder was handed.
    assert any("at most 5 statements" in c["text"] for c in claims)

    # And the launch path has no second copy of this logic.
    src = inspect.getsource(_launch)
    assert "build_run_task(" in src
    assert "Acceptance criteria:" not in src, "the launch path must not re-derive the task string"


# --- relevance: a standing decision may only enter an item that left it open ------------------


def test_A_BRIEF_THAT_ASKED_NOTHING_STRUCTURAL_GETS_NO_CLAUSE() -> None:
    """THE REGRESSION. Measured on MCB-01, 2026-08-24.

    This brief is a greenfield todo CLI: it says nothing about function length, orchestrators or
    delegation. Weaving "a function body is at most 5 statements" into it bound no oracle — the
    claim rendered `[ENTAILED -> none]`, so no deterministic check could ever mark it satisfied —
    while the REVIEWER read it as a requirement and returned REQUEST_CHANGES on every iteration.
    Five of five runs parked at ~1.7M tokens each on a tree the hidden grader passed 8/8.

    `reviewer_requested_changes` is an `objection` in `gate.py` and can never ship, so an unbound
    criterion is not a stricter standard: it is an unbounded model judgement with veto power.
    """
    store = _FakeStore()
    _ratify(store)
    brief = (
        "Build a small, self-contained command-line todo manager in Python.\n"
        '- `python -m todo add "<title>"` — add a task; print its new id.\n'
        "- Tasks persist across invocations in a JSON file.\n"
        "- Keep it dependency-free where reasonable (the standard library is enough)."
    )
    assert extract_structural_constraints(brief) is None, "fixture: the brief states no shape"
    assert weave_criteria(brief, _load(store)) == brief


def test_a_brief_that_LEFT_THE_NUMBER_OPEN_still_gets_it() -> None:
    """THE POSITIVE CONTROL, and it has already earned its place — a first cut of the filter
    dropped the clause from MCB-05/15 too, which "fixes" the regression by never weaving anything.

    This is the case ADR-0082 names and the owner ratified on 2026-08-12 (ledger E5: delivered
    7->18, over-park 8->2, 0 false ships). The brief asks for a short orchestrator WITHOUT a
    number, ADR-0072 forbids deriving one from the prose, and the clause supplies it.
    """
    store = _FakeStore()
    _ratify(store)
    brief = (
        "Refactor `checkout_total` into a short orchestrator that delegates to at "
        "least three helpers."
    )
    woven = weave_criteria(brief, _load(store))

    assert "a function body is at most 5 statements" in woven
    # And it still BINDS the check, not merely the prose.
    bound = apply_to_constraints(extract_structural_constraints(brief), _load(store))
    assert bound is not None and bound.max_body == 5


def test_the_items_OWN_number_is_not_overruled_by_a_standing_decision() -> None:
    """An explicit "<= 3 statements" is the operator's own statement. A standing decision fills in
    what was left open; it does not overrule what was asked for — so it binds nothing here, and
    therefore has no business in the criteria either. `apply_to_constraints` already refused to
    overrule it; before this change the TEXT said otherwise, and the reviewer reads the text."""
    store = _FakeStore()
    _ratify(store)
    brief = "Refactor `f` so its body is at most 3 statements, delegating to helpers."
    stated = extract_structural_constraints(brief)
    assert stated is not None and stated.max_body == 3, "fixture: the brief states its own number"

    assert weave_criteria(brief, _load(store)) == brief
    bound = apply_to_constraints(stated, _load(store))
    assert bound is not None and bound.max_body == 3


def test_a_clause_this_filter_cannot_JUDGE_is_kept_not_dropped() -> None:
    """Deliberate, and the safer direction. Every registered parameter is structural today, so
    this is presently unreachable — but a parameter added to the registry and not to
    `_BINDABLE_CONSTRAINTS` must not silently vanish from the criteria. Dropping a ratified
    operator decision because this function did not recognise it would be a waiver with extra
    steps, and the operator would never see it happen."""
    from mosaera_core.clauses import binding_clauses

    unknown = dataclasses.replace(_ratify(_FakeStore()), binds="house.some_future_param")
    kept = binding_clauses((unknown,), "a brief that states no structural shape at all")
    assert kept == (unknown,)


def test_relevance_is_judged_on_the_WHOLE_item_not_the_acceptance_field() -> None:
    """`build_run_task` weaves the acceptance field, but an operator routinely puts the structural
    ask in the TITLE or DESCRIPTION. Judging on the acceptance alone would drop a clause the item
    genuinely left open — the false-negative twin of the MCB-01 defect."""
    from mosaera_core.task_spec import build_run_task

    store = _FakeStore()
    _ratify(store)
    item = {
        "id": 7,
        "title": "Refactor `checkout_total` into a short orchestrator",
        "description": "It delegates to at least three helpers.",
        "acceptance": "The existing tests still pass.",
    }
    assert extract_structural_constraints(str(item["acceptance"])) is None, (
        "fixture: the acceptance field ALONE states no shape — the ask is in the title"
    )
    task, claims = build_run_task(item, _load(store))
    assert "at most 5 statements" in task
    assert any("at most 5 statements" in c["text"] for c in claims)


def test_a_CONDITIONAL_clause_is_not_woven_but_is_still_CHECKED() -> None:
    """A decision, pinned so it cannot become an accident.

    At weave time the code does not exist, so `module_lines` cannot be supplied and the condition
    cannot be shown to hold — `clause_for` already reads an unknown fact that way. Rendering the
    line anyway would state a requirement that may not apply to the tree finally produced: the
    MCB-01 shape with an extra step.

    The requirement is NOT lost. `apply_to_constraints` runs again at claim-evaluation time with
    real facts, so a condition that does hold still binds the check there.
    """
    store = _FakeStore()
    _ratify(store, when=("module_lines", "<", 500))
    brief = "Refactor `f` into a short orchestrator that delegates to at least three helpers."
    clauses = _load(store)

    # Not in the brief the agent reads — no fact, so nothing to show it applies.
    assert weave_criteria(brief, clauses) == brief
    # But supply the fact, as the claim oracle does, and it binds.
    bound = apply_to_constraints(extract_structural_constraints(brief), clauses, module_lines=400)
    assert bound is not None and bound.max_body == 5
