"""A MODIFY item names the test that asserts the behaviour it changes (ADR-0098).

Split out of ``_proctor_authoring.py`` at the 500-line god-file ceiling, the same precedent
``_exec.py`` set. The module is cohesive on its own terms: it answers one question — *which
pre-existing test currently asserts the behaviour this item deliberately changes?* — and the answer
is a deterministic AST enumeration, no model call.

**It grants no authority.** ADR-0058 already lets the Proctor repair pre-existing tests, once,
coder-blind, content-pinned into ``proctor_edits``. This only NAMES the target, exactly as the
faithfulness guard (ADR-0062) names over-strict assertions. See ADR-0098 for the safety argument
and for the measured deadlock it closes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState
from mosaera_core.nonuse import consumers_of, removal_target
from mosaera_core.testintegrity import is_collection_control


def _module_prefix(target: str) -> str:
    """``pricing.discount.apply`` -> ``pricing.discount``; a bare symbol -> ``""``."""
    head, _, tail = target.rpartition(".")
    return head if head and tail else ""


def _imports_from(root: Path, rel: str, prefix: str) -> bool:
    """Does ``rel`` import from the module ``prefix`` names? Deny-by-default on any read failure."""
    try:
        tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == prefix or node.module.endswith(f".{prefix}"):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == prefix or alias.name.startswith(f"{prefix}."):
                    return True
    return False


def _resolved_targets(
    root: Path, target: str, referencing: list[str], defining: list[str]
) -> list[str]:
    """The referencing tests that provably concern THIS symbol — never merely one of its name.

    **Red team R2 (2026-08-11), CONFIRMED and fixed here.** `consumers_of` matches a BARE NAME
    (`_symbol_of` discards the module path, and `_references_in` matches any `ast.Attribute.attr`),
    so a claim about `pricing.discount.apply` nominated an unrelated baselined test asserting
    `Tax().apply(100) == 120`. Reproduced deterministically before this fix existed.

    ADR-0097 argued that over-matching "is harmless by construction" — TRUE of the oracle, where a
    wider consumer set only makes `impact_unassessed` fire more often (conservative). ADR-0098
    inherited that enumeration for a different job: choosing files the Proctor may REWRITE under
    the tamper excuse. There the same over-matching is permissive, not conservative — an edit to a
    name-collided test is excused, so the tamper guard stands down on a contract nothing asked to
    change. The claim was sound in its original context and unsound in the borrowed one.

    Narrowed one-sidedly; this can only ever nominate FEWER files:

    - the claim names a module (``pkg.mod.sym``) — the test must import from that module;
    - a bare symbol with exactly ONE definition in the tree — unambiguous, unchanged;
    - a bare symbol with SEVERAL definitions — nominate nothing. Which behaviour is being changed
      is genuinely unknowable, and handing out edit rights on a guess is the unsafe direction.
    """
    prefix = _module_prefix(target)
    if prefix:
        return [rel for rel in referencing if _imports_from(root, rel, prefix)]
    if len(defining) == 1:
        return list(referencing)
    return []


def _modify_amendment_targets(ctx: RunContext, state: RunState) -> list[tuple[str, str, str]]:
    """``(claim_text, symbol, test_path)`` for every PRE-EXISTING test asserting a behaviour this
    item deliberately changes. Deterministic — AST reference enumeration, no model call.

    Verb-arc slice 4 shipped the `consumer_impact` oracle and MCB-28 still could not deliver. The
    measured reason was not the oracle: the item requires editing `tests/test_pricing.py`, editing
    it sets ``tests_modified`` → immediate stall, and `amendment_offer` then returns ``{}`` **by
    design** ("a run that already TAMPERED may not be handed authorization to amend"). The only
    sanctioned route ran through a HUMAN at an escalation gate, and an autonomous run has none —
    with `amendment_gate` default-OFF and outside `apply_oracle_posture`, that path was inert for
    all 52 runs of the integration sweep.

    **This adds no authority.** ADR-0058 already lets the Proctor repair pre-existing tests, once,
    coder-blind, with the result content-pinned into ``proctor_edits``. What was missing is that
    nothing ever told it a MODIFY item *requires* restating the test that asserts the old
    behaviour — so it left the contradiction standing and the coder walked into it. Naming the
    target inside an existing authority is exactly what `_faithfulness_block` does above.

    Bounded by construction, in three ways that matter:

    - only ENTAILED claims — sentences quoted from the acceptance text the operator approved, never
      a model's proposal (`claims_from_acceptance` sets the provenance);
    - only files that reference the claim's own symbol, by AST, reusing slice 4's `consumers_of`;
    - only files already in ``integrity_baseline`` — a test authored THIS run is not a
      pre-existing bar, and pointing the Proctor at its own output is a loop, not an amendment.
    """
    root = getattr(ctx.workspace, "root", None)
    if root is None:
        return []
    baseline = set(state.get("integrity_baseline") or {})
    if not baseline:
        return []
    out: list[tuple[str, str, str]] = []
    for claim in state.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        if claim.get("oracle_kind") != "consumer_impact":
            continue
        if str(claim.get("provenance") or "") != "ENTAILED":
            continue
        text = str(claim.get("text") or "")
        target = removal_target(text)  # same code-span convention as a removal claim
        if not target:
            continue
        found = consumers_of(root, target)
        if found is None:
            continue
        referencing, defining = found
        # Red team R2: `consumers_of` matches a bare NAME, which is conservative for the oracle and
        # PERMISSIVE here — see `_resolved_targets`. Narrow before anything is nominated.
        for rel in _resolved_targets(root, target, referencing, defining):
            # Same derived rule as `_proctor_authoring`: the baseline is config-aware, so
            # `is_test_file` (pytest's defaults) would drop every real test on a `python_files`
            # repo and silently offer no amendment targets at all.
            if rel in baseline and not is_collection_control(rel):
                out.append((text, target, rel))
    return out


def _modify_amendment_block(ctx: RunContext, state: RunState) -> str:
    """Render the MODIFY targets as an explicit repair instruction, or ``""`` when there are none.

    Says *restate*, never *delete* or *loosen*: the assertion-profile check downstream refuses the
    tamper excuse for any repair that drops or shrinks a test function, so an instruction inviting
    removal would produce a park rather than an amendment. The item changes what a behaviour IS —
    the test should assert the new value, with the same functions still asserting.
    """
    targets = _modify_amendment_targets(ctx, state)
    if not targets:
        return ""
    lines = [
        "",
        "## Pre-existing tests that assert the behaviour this item CHANGES",
        "This item deliberately changes behaviour, so the tests below currently assert the OLD "
        "behaviour and will fail no matter how correct the implementation is. That failure is the "
        "POINT of the item, not a defect — and the coder may not edit these files. You may, once, "
        "now, before any implementation exists.",
        "For EACH: restate the affected assertions against the NEW behaviour the task specifies. "
        "Keep every test function and keep them asserting — do NOT delete a test, weaken one to a "
        "tautology, or drop a case. Anything the item does not change must keep asserting exactly "
        "what it asserts today.",
    ]
    for text, symbol, rel in targets:
        lines.append(f"- `{rel}` — asserts `{symbol}`, which this item changes: {text}")
    return "\n\n".join(("", "\n".join(lines)))
