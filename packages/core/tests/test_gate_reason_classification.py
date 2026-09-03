"""The gate's reason vocabulary is TOTALLY classified, and both arms derive from it (ADR-0090).

Why this file exists, precisely. `_GIVE_UP_ALLOWED_REASONS` was hand-written on 2026-07-23
(ADR-0075) as a deny-by-default allowlist of gate reasons. On 2026-08-02 ADR-0079 Wave 2 minted
`unsatisfied_claim` — a reason that allowlist had never heard of — and because the predicate is
`set(reasons) - allowed`, every park carrying the new reason became non-convertible by BOTH
disposition arms. Measured: 7 of 18 stored over-parks, reproduced live on three independent cases,
and the direct cause of the ESCALATE arm stopping a run it could then not ask about (#68, F62).

**Every test stayed green throughout.** Nothing related the `GateReason` Literal in
`packages/policies` to the frozenset in core, so there was nothing to fail. These tests are that
relation. `typing.get_args` is used rather than an AST scan on purpose: a `Literal`'s members are a
runtime-truthful read, and re-deriving them by parsing would be a second, weaker origin for a fact
Python already hands us — the exact defect class this file guards against.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import mosaera_policies.gate as gate_mod
from mosaera_core.eligibility import _GIVE_UP_ALLOWED_REASONS, give_up_allowed_reasons
from mosaera_policies.gate import REASON_CLASS, GateReason, ReasonClass, reasons_of_class

DECLARED = frozenset(get_args(GateReason))


def _totality_gaps(
    declared: frozenset[str], classified: frozenset[str]
) -> tuple[list[str], list[str]]:
    """(unclassified, stale) — pure, so the guard itself is testable on synthetic input."""
    return sorted(declared - classified), sorted(classified - declared)


def test_every_gate_reason_is_classified() -> None:
    """A new GateReason must arrive with its class, or this fails naming it."""
    unclassified, _ = _totality_gaps(DECLARED, frozenset(REASON_CLASS))
    assert not unclassified, (
        f"unclassified GateReason(s) {unclassified} — every reason must carry a ReasonClass in "
        "REASON_CLASS (packages/policies/mosaera_policies/gate.py, beside the Literal). "
        "See ADR-0090: an unclassified reason silently narrows both disposition arms."
    )


def test_no_stale_classification() -> None:
    """The reverse direction: a removed reason must not linger in the table."""
    _, stale = _totality_gaps(DECLARED, frozenset(REASON_CLASS))
    assert not stale, (
        f"REASON_CLASS classifies {stale}, which is not in the GateReason Literal — "
        "remove the entry or restore the reason (ADR-0090)."
    )


def test_the_totality_guard_actually_fires() -> None:
    """The guard is proven on synthetic input, so it cannot pass by vacuity.

    Asserting only over real data would leave `_totality_gaps` untested for the case it exists to
    catch — green-by-vacancy, which is its own recorded defect class here.
    """
    unclassified, stale = _totality_gaps(
        frozenset({"a", "b", "new_reason"}), frozenset({"a", "b", "removed_reason"})
    )
    assert unclassified == ["new_reason"]
    assert stale == ["removed_reason"]


def test_every_class_is_a_declared_reason_class() -> None:
    """No entry may invent a class the ReasonClass Literal does not declare."""
    allowed = set(get_args(ReasonClass))
    bad = {r: c for r, c in REASON_CLASS.items() if c not in allowed}
    assert not bad, f"REASON_CLASS uses undeclared class(es): {bad} (allowed: {sorted(allowed)})"


def test_emitted_reasons_are_declared() -> None:
    """Every literal appended to `reasons` inside gate.py is in the GateReason Literal.

    The other half of the drift: a reason can be EMITTED without ever being declared, in which case
    the Literal — and therefore both tests above — never sees it. This one needs the AST, because
    the fact lives in the source rather than in a runtime object.
    """
    tree = ast.parse(Path(gate_mod.__file__).read_text(encoding="utf-8"))
    emitted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"append", "extend"}:
            continue
        target = node.func.value
        if not (isinstance(target, ast.Name) and target.id == "reasons"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                emitted.add(arg.value)
            elif isinstance(arg, ast.List | ast.Tuple):
                emitted.update(
                    e.value
                    for e in arg.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                )
    assert emitted, "found no reason literals in gate.py — the AST walk has drifted, not the code"
    undeclared = sorted(emitted - DECLARED)
    assert not undeclared, (
        f"gate.py emits reason(s) {undeclared} that the GateReason Literal does not declare — "
        "add them to the Literal AND to REASON_CLASS (ADR-0090)."
    )


def test_the_admission_set_is_exactly_what_adr_0092_authorised() -> None:
    """The admission policy, pinned — and the ONE line whose change is a governance decision.

    This began as ADR-0090 MR1's behaviour-neutrality pin: `{validation_failed, reviewer_unknown,
    iteration_limit, oracle_unverified}`, ADR-0075's hand-written set reproduced by derivation. Its
    docstring said changing the literal *"is changing the admission policy, which is MR2 and needs
    its own ADR pass and red team — not a test edit."* This edit is that authorisation:
    **ADR-0092** adds `claim_behavioral_failed`, and nothing else.

    Why only that one: a behavioural claim's oracle is `state["tests_passed"]` verbatim, so its
    failure restates `validation_failed` — a reason the arms already admit — which #84 proved from
    the mechanism rather than inferring from correlation. `claim_structural_failed` stays an
    `objection` (it is the one genuinely independent claim evidence, and those parks are ~69%
    right), and `claim_integrity_failed` is `tamper` and never admissible.
    """
    assert give_up_allowed_reasons() == frozenset(
        {
            "validation_failed",
            "reviewer_unknown",
            "iteration_limit",
            "oracle_unverified",
            "claim_behavioral_failed",
        }
    )


def test_module_constant_matches_the_accessor() -> None:
    """The cached constant and the accessor cannot diverge."""
    assert _GIVE_UP_ALLOWED_REASONS == give_up_allowed_reasons()


def test_tamper_is_never_admissible() -> None:
    """An integrity violation is admissible to no arm, under any posture — pinned, not implied."""
    assert REASON_CLASS["tests_tampered"] == "tamper"
    # ADR-0092 adds a second member: a failed `tests_unmodified` claim is the tamper fact wearing a
    # claim's name. Provably co-present with `tests_tampered` today (both read
    # `state["tests_modified"]`), so it can never be the sole reason — classified anyway, because
    # the day those two oracles diverge is the day the classification has to already be right.
    # ADR-0099 adds a third: a pre-existing file emptied rather than deleted. Same family and
    # same reason — the producer destroyed something nobody asked it to touch, so there is no
    # criterion to finish and no arm it may be admitted to.
    assert reasons_of_class("tamper") == frozenset(
        {"tests_tampered", "claim_integrity_failed", "content_destroyed"}
    )
    assert not (reasons_of_class("tamper") & give_up_allowed_reasons())


def test_the_arms_share_one_origin() -> None:
    """Neither arm may keep its own copy, and neither may reach into the other's privates.

    `escalate_arm.py` imported `disposition._GIVE_UP_ALLOWED_REASONS` — a private name across a
    module boundary, which is a second origin waiting for the two to disagree (the F71/F79 defect
    class). It now uses the public accessor; this fails if that regresses.
    """
    root = Path(__file__).resolve().parents[1] / "mosaera_core"
    sources = {p: p.read_text(encoding="utf-8") for p in root.rglob("*.py")}

    # The origin MOVED (disposition.py -> eligibility.py, 2026-08-09 split) — it did not multiply.
    # Updating which file owns it is layout; asserting one owner is the invariant, and that stands.
    definitions = [p.name for p, src in sources.items() if "_GIVE_UP_ALLOWED_REASONS = " in src]
    assert definitions == ["eligibility.py"], (
        f"_GIVE_UP_ALLOWED_REASONS is defined in {definitions} — it must have exactly one origin "
        "(ADR-0090)."
    )

    borrowers = [
        p.name
        for p, src in sources.items()
        if p.name != "eligibility.py" and "_GIVE_UP_ALLOWED_REASONS" in src
    ]
    assert not borrowers, (
        f"{borrowers} reach into eligibility's private allowlist — use the public "
        "give_up_allowed_reasons() accessor instead (ADR-0090)."
    )
