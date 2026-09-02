"""Standing standards and the vocabulary a derived clause may speak (ADR-0082 tiers 1-2).

The problem this exists for, measured 2026-08-04: a brief said "a short orchestrator (a handful
of statements)"; the hidden graders asserted `<= 6` and `<= 7`; runs delivered 8 and 9 and parked.
Stating "at most 5 statements" moved a paired benchmark from 0/6 to 5/6 grader-clean (Fisher exact
p = 0.015). The repair was authored by hand and nothing recorded it, so the next item asked again.
A **clause** is that decision written down once, so it is inherited rather than re-litigated.

The whole design question is what a clause may SAY, because a policy layer that can express
"skip the check" is a waiver mechanism wearing a governance costume. Three independent limits,
any ONE of which is sufficient to refuse:

1. **A clause may only name a registered oracle parameter** (`PARAMS`). "Change the verdict" and
   "drop the oracle" have no name here, so they cannot be written down at all.
2. **A clause may only bind a parameter its cited standard leaves OPEN** (`Standard.open_params`).
   This is the strong one and it is nearly free: `standards/module-ceiling` FIXES the 500-line
   limit and leaves `structural.body_statements` open, so "waive the god-file ceiling" is
   unsayable for the same structural reason as "change the verdict" — no name exists for it.
3. **No clause may touch a proof-bearing gate reason** (`PROOF_BEARING`), checked at write AND at
   read, so a clause minted before the list grew cannot grandfather a waiver in.

Tier 1 is CODE-DECLARED, not stored, and bootstrapped from the guards that already fail CI — a
standard is a fact about this repository, changed by a reviewed diff. That also gives staleness
for free: delete or rename a standard and every clause citing it fails validation at load.

Pure: no I/O, no imports outside this package. Layer note — `memory` is a leaf and cannot import
this, so the WRITE-time check lives in `mosaera_core.clauses`; read-time is the real guarantee.
"""

from __future__ import annotations

from typing import Any, NamedTuple, get_args

from mosaera_policies.gate import GateReason

# --- tier 1: the standards, bootstrapped from the guards that already have teeth -------------


class Standard(NamedTuple):
    """One standing standard. ``open_params`` is the load-bearing field.

    A standard states a bar AND which of its parameters remain the operator's to set. Anything
    the standard itself fixes is simply absent from `PARAMS`, so no clause can name it. Never
    register a guard's own enforced constant (the 500 in `check_file_sizes.py`) as a parameter:
    that would convert this registry from a decision surface into a waiver surface.
    """

    id: str
    title: str
    scope: str  # "repo" | "project" — a clause INHERITS this; it is never chosen
    enforced_by: str  # the guard or document that already carries this bar
    open_params: tuple[str, ...]  # parameters this standard leaves to the operator


STANDARDS: dict[str, Standard] = {
    s.id: s
    for s in (
        Standard(
            id="standards/module-ceiling",
            title="No module over 500 lines",
            scope="repo",
            enforced_by="scripts/check_file_sizes.py",
            # The ceiling itself is FIXED. What it leaves open is how short "short" is inside a
            # module — which is exactly the ADR's worked example: "no fixed statement count,
            # unless the module would cross 500".
            open_params=("structural.body_statements",),
        ),
        Standard(
            id="standards/layer-direction",
            title="One-way dependency direction (agents/api -> core -> policies; memory a leaf)",
            scope="repo",
            enforced_by="scripts/check_layer_imports.py",
            open_params=(),
        ),
        Standard(
            id="standards/doc-links",
            title="Every relative documentation link resolves",
            scope="repo",
            enforced_by="scripts/check_doc_links.py",
            open_params=(),
        ),
        Standard(
            id="standards/control-liveness",
            title="Every posture knob has an honest liveness record",
            scope="repo",
            enforced_by="scripts/check_control_liveness.py",
            open_params=(),
        ),
        Standard(
            id="standards/doc-claims",
            title="No documented claim contradicts another fact in this repo",
            scope="repo",
            enforced_by="scripts/check_doc_claims.py",
            open_params=(),
        ),
        Standard(
            id="standards/house-style",
            title="How code here should read (coding-standards.md)",
            scope="project",
            enforced_by="coding-standards.md",
            open_params=("structural.body_statements", "structural.min_helpers"),
        ),
    )
}


# --- the registered oracle parameters: the only things a clause may bind ----------------------


class OracleParam(NamedTuple):
    """A parameter a clause may set.

    ``affects`` names the gate reason this parameter can influence, or None when it can only ever
    make a check STRICTER or is downgrade-only. It exists so the proof-bearing deny-list is a
    structural check rather than a string match on prose: mark a parameter proof-bearing and every
    clause binding it is refused, including ones ratified years earlier.
    """

    name: str
    kind: str  # "int" — the only kind v1 admits; a value is a number, never prose
    minimum: int
    maximum: int
    affects: str | None


PARAMS: dict[str, OracleParam] = {
    p.name: p
    for p in (
        # The structural-spec oracle is downgrade-only by construction (ADR-0072): it can park a
        # run, never vouch for one. Setting these can therefore never open a ship channel.
        OracleParam("structural.body_statements", "int", 1, 50, None),
        OracleParam("structural.min_helpers", "int", 1, 20, None),
    )
}

# `when` conditions draw from a SEPARATE, deliberately tiny vocabulary, so a condition can never
# smuggle in a bindable name. One comparison, no expression language, nothing evaluated.
CONDITION_PARAMS: frozenset[str] = frozenset({"module_lines"})
CONDITION_OPS: frozenset[str] = frozenset({"<", "<=", ">", ">="})

VALUE_KINDS: frozenset[str] = frozenset({"advisory", "number", "unbounded"})

# Reasons that carry PROOF. A clause may rebind a threshold; it may never stand between a run and
# the evidence that it works. Kept beside the gate's own vocabulary so the two cannot drift.
PROOF_BEARING: frozenset[str] = frozenset(
    {
        "validation_failed",
        "validation_unavailable",
        "security_findings",
        "security_unverified",
        "tests_tampered",
        "oracle_unverified",
        "critic_vetoed",
        "unsatisfied_claim",
        "validation_not_attempted",
        # ADR-0107: the security half of the same split. PROOF-BEARING for exactly the reason its
        # `validation_` twin is — the reason fires BECAUSE no scan proof exists, so a clause able
        # to waive it would waive the absence itself. Note the class differs (`not_run`, so the ASK
        # arm may speak) while the proof status does NOT: whether a reason carries proof and which
        # decisions may admit it are different questions, which is the whole of ADR-0107.
        "security_not_attempted",
        # ADR-0108: proof exists, but for another tree — so for THIS one there is none.
        "security_stale",
        "reviewer_stale",
        # ADR-0092: a failed acceptance claim is proof, whichever class it belongs to.
        "claim_behavioral_failed",
        "claim_structural_failed",
        "claim_integrity_failed",
        # verb-arc slice 1: an unproven removal. PROOF-BEARING in the strictest sense — the reason
        # fires precisely BECAUSE the proof is absent, so a clause that could waive it would waive
        # the only evidence standing between a removal and every caller it breaks.
        "removal_unproven",
        # ADR-0099: a pre-existing file emptied rather than deleted. PROOF-BEARING because the
        # reason fires precisely BECAUSE no proof was ever offered — a clause that could waive
        # it would waive the only record that content was destroyed at all.
        "content_destroyed",
        # verb-arc slice 4: an unassessed behaviour change. PROOF-BEARING for the same reason —
        # the reason fires BECAUSE the blast radius is unknown, so waiving it waives the only
        # evidence about who the change breaks.
        "impact_unassessed",
    }
)

# The complement: reasons that carry no PROOF, so a clause may legitimately touch them. Declared
# rather than inferred, because the pair must PARTITION `GateReason` — see `_verify_registries`.
#
# This exists because the one-directional check below let a reason go missing for six days.
# `validation_not_attempted` was added to the gate on 2026-08-07 (F39) and never reached
# PROOF_BEARING: the guard only caught a name the Literal had LOST, never one it had GAINED, so a
# new proof-bearing reason was silently un-protected and a clause could have waived it. Same shape
# as #68 — a later feature landing on a registry that had no way to notice.
NOT_PROOF_BEARING: frozenset[str] = frozenset(
    {
        "reviewer_requested_changes",
        "reviewer_blocked",
        "reviewer_unknown",
        "reviewer_conflict",
        "iteration_limit",
    }
)


def _verify_registries() -> None:
    """Import-time invariants. Raised, never asserted: `python -O` strips asserts, and an
    invariant that disappears under an optimisation flag is not a guarantee."""
    declared = set(get_args(GateReason))
    unknown = (PROOF_BEARING | NOT_PROOF_BEARING) - declared
    if unknown:
        raise RuntimeError(
            f"PROOF_BEARING/NOT_PROOF_BEARING name {sorted(unknown)}, which GateReason no longer "
            "has — a renamed reason silently drops out of the deny-list, which is how a waiver "
            "gets grandfathered in. Fix the name here."
        )
    unclassified = declared - PROOF_BEARING - NOT_PROOF_BEARING
    if unclassified:
        raise RuntimeError(
            f"GateReason has {sorted(unclassified)}, which neither PROOF_BEARING nor "
            "NOT_PROOF_BEARING claims. A new reason must be classified here, or it is silently "
            "waivable by a clause — that is exactly how `validation_not_attempted` went "
            "unprotected for six days."
        )
    both = PROOF_BEARING & NOT_PROOF_BEARING
    if both:
        raise RuntimeError(
            f"{sorted(both)} is both proof-bearing and not — the pair must partition"
        )
    waivers = {name for name, p in PARAMS.items() if p.affects in PROOF_BEARING}
    if waivers:
        raise RuntimeError(
            f"registered oracle parameter(s) {sorted(waivers)} influence a proof-bearing gate "
            "reason — that is a waiver, not a setting (ADR-0082 §4); remove them from PARAMS."
        )


_verify_registries()


def validate_clause(record: Any) -> str:
    """Why this clause is refused, or ``""`` when it may stand. Deny-by-default.

    Called at BOTH write and read. Read-time is the guarantee: it re-judges every stored clause
    against today's registries, so a clause survives only as long as the standard it cites, the
    parameter it binds, and the deny-list all still permit it.
    """
    if not isinstance(record, dict):
        return "not a clause record"

    standard = STANDARDS.get(str(record.get("standard_id", "")))
    if standard is None:
        # Also the staleness path: a standard that was renamed or retired takes its clauses with
        # it, which is ADR-0082's "no expiry dates" — validity is a function of the parent.
        return f"cites an unknown standard {record.get('standard_id')!r}"

    binds = str(record.get("binds", ""))
    param = PARAMS.get(binds)
    if param is None:
        return f"binds {binds!r}, which is not a registered oracle parameter"
    if binds not in standard.open_params:
        return f"{standard.id} does not leave {binds!r} open — it is fixed by the standard"
    if param.affects in PROOF_BEARING:
        return f"{binds!r} affects the proof-bearing reason {param.affects!r}"

    kind = str(record.get("value_kind", ""))
    if kind not in VALUE_KINDS:
        return f"unknown value kind {kind!r}"
    value = record.get("value_num")
    if kind == "number":
        if not isinstance(value, int) or isinstance(value, bool):
            return "a numeric clause needs an integer value"
        if not (param.minimum <= value <= param.maximum):
            return f"{value} is outside {binds}'s range [{param.minimum}, {param.maximum}]"
    elif value is not None:
        return f"a {kind!r} clause carries no number"

    cond = (record.get("when_param"), record.get("when_op"), record.get("when_num"))
    if any(c is not None for c in cond):
        if not all(c is not None for c in cond):
            return "a condition needs all of parameter, operator and value"
        if str(cond[0]) not in CONDITION_PARAMS:
            return f"unknown condition parameter {cond[0]!r}"
        if str(cond[1]) not in CONDITION_OPS:
            return f"unknown condition operator {cond[1]!r}"
        if not isinstance(cond[2], int) or isinstance(cond[2], bool):
            return "a condition needs an integer value"
    return ""


def standard_scope(standard_id: str) -> str | None:
    """The scope a clause citing ``standard_id`` inherits, or None when unknown."""
    standard = STANDARDS.get(standard_id)
    return standard.scope if standard else None
