"""Acceptance claims as first-class artifacts (ADR-0079) — the claim contract, Wave 1.

A claim is one material assertion from a backlog item's acceptance criteria, carried as
structured data instead of dissolving into the task string at launch. Wave 1 is the SCHEMA and
the deterministic derivation; nothing consumes claims for gating yet (the `evaluate_gate` change
is a later wave with its own red-team) — they ride RunState read-only and render in the report.

Provenance decides authority (ADR-0079 §2): only ENTAILED (traceable to operator-approved
acceptance text) and REPOSITORY_INVARIANT (a checked-in rule) may ever gate; INFERRED (a model's
belief about intent) never silently joins the contract. Everything `claims_from_acceptance`
derives is ENTAILED by construction — it quotes the acceptance text verbatim, sentence by
sentence. This is a versioned artifact schema (coding-standards §15, first implementation):
a breaking change to the shape bumps SCHEMA_VERSION and requires an ADR + migration + replay
analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

PROVENANCES = ("ENTAILED", "REPOSITORY_INVARIANT", "INFERRED")
# The measured oracle vocabulary (brief-checkability-2026-08-02): every structural claim in the
# bench suite binds to one of these; `none` is the explicit honest "no binding yet", which is a
# parked claim under the (future) gate, never a dropped one.
ORACLE_KINDS = (
    "acceptance_test",
    "validation_exit",
    "tests_unmodified",
    "ast_transformation_contract",
    "wellformedness_parse",
    "non_use",
    "consumer_impact",
    "none",
)

# What KIND of evidence a failed claim of each oracle kind actually is (ADR-0092). The gate needs
# this to say WHICH sort of thing went unsatisfied, and it must be computed HERE:
# `packages/policies` may not import core, so mirroring `ORACLE_KINDS` there would recreate
# ADR-0090's own defect at a new seam — a vocabulary owned by core, copied into policies, with
# nothing forcing the two to move together. A seventh oracle kind would silently bucket as
# unknown and emit nothing. So core partitions and hands policies the CLASS; policies declares
# only the three-member class vocabulary.
#
#   behavioral  the oracle is `state["tests_passed"]` VERBATIM (see claim_oracles.evaluate_claims),
#               so a failure here restates `validation_failed` and carries no per-claim information
#               (#84 measured this: 18 of 24 MCB cases mint nothing else).
#   structural  `ast_transformation_contract` — the ONLY kind that reads the delivered tree, and
#               therefore the only genuinely independent claim evidence.
#   integrity   `tests_unmodified` — the tamper guard wearing a claim's name.
#   removal     `non_use` — a SUBTRACT item's proof that nothing references the removed thing
#               (verb-arc slice 1). Its own class, not `structural`, and the reason is concrete:
#               `claim_structural_failed` is the bucket ADR-0094 widened for Layer-2 eligibility,
#               so an unproven removal landing there would become auto-ship-eligible — and Layer 2
#               verifies by authoring a BEHAVIOURAL test and mutating it, which says nothing about
#               whether the removed thing is still referenced. It could convert a removal that
#               breaks every caller. A separate class keeps it out of that set BY CONSTRUCTION.
#
# TOTAL over ORACLE_KINDS, guarded by test_claim_evidence_class.py. `none` is absent on purpose: it
# resolves `unbound` and can never appear in a FAILED set (`failed_claim_ids` filters on "failed").
CLAIM_EVIDENCE_CLASS: dict[str, str] = {
    "acceptance_test": "behavioral",
    "validation_exit": "behavioral",
    "wellformedness_parse": "behavioral",
    "ast_transformation_contract": "structural",
    "tests_unmodified": "integrity",
    "non_use": "removal",
    # verb-arc slice 4. Its own class for the same reason `removal` has one: Layer 2 verifies by
    # authoring a BEHAVIOURAL test and mutating it, which is exactly the evidence a behaviour
    # CHANGE invalidates — it would happily convert a change nothing witnesses.
    "consumer_impact": "impact",
}

# Transformation verbs (the 8/24 structural ceiling, validated offline 18/18 by
# scripts/experiments/claim_predicates_stage0.py): a sentence stating one of these shapes binds
# to a deterministic AST contract. The regexes recognise the CLAIM; the predicates land with the
# gate wave.
_TRANSFORMATION = re.compile(
    r"\b(orchestrat\w*|delegat\w*|extract\w*|data-driven|table-driven|refactor\w*"
    r"|module-level helper|helper function|keep the .{0,40}(layout|module)|don'?t collapse"
    r"|single if\b|one if\b)",
    re.IGNORECASE,
)
# Observable behaviour: inputs/outputs/errors a test can independently assert.
# SUBTRACT verbs (verb-arc slice 1). Deliberately NARROW, and the asymmetry is the reason:
# under-matching falls back to today's behaviour (a material claim with no oracle, which parks),
# while OVER-matching turns ordinary items into unproven removals that cannot ship. Only one of
# those directions is safe.
#
# A bare verb search was measured against all 27 MCB briefs and produced FIVE false positives —
# every one a case where `delete` names a feature BEING BUILT, not code being removed:
#   "`add`, `done`, and `delete` persist the change..."   (MCB-01/23, CLI verbs)
#   "`delete(self, key)` -- remove `key` if present..."   (MCB-10, a dict method)
#   '`{"action": "delete", "key": k}` -- remove `k`'      (MCB-18, a payload)
# The distinguishing signal is grammatical: in a real subtract item the verb governs the SENTENCE;
# in all five false positives it sits inside a code span naming an API. So: a leading imperative
# (optionally behind a list bullet) or an explicit passive, and nothing else.
_REMOVAL = re.compile(
    r"^[-*\d.)\s]*(remove|delete|drop|purge|eliminate)\b"
    r"|\bbe (removed|deleted|dropped|purged|eliminated)\b",
    re.IGNORECASE,
)

# MODIFY verbs (verb-arc slice 4). Sits BELOW `_REMOVAL` — a removal is a modification in the
# loosest sense, and the removal oracle is the stronger claim — and ABOVE `_BEHAVIOURAL`, which
# otherwise swallows it: "Change `load_config` to RETURN an empty dict" matches the behavioural
# verb list today and binds to `state["tests_passed"]` verbatim. That is the whole defect. A
# behavioural claim cannot distinguish *"the test failed"* from *"the test was SUPPOSED to fail,
# because this item changes the behaviour it asserts"* — the two are the same boolean.
#
# Breadth, corrected 2026-08-10 — the earlier figure here described a pattern that never shipped.
# It read "17 of 372 sentences (4.6%), 8 briefs", which is the **bare-verb** search
# `\b(change|update|modify|rename|replace|switch)\b` that MOTIVATED anchoring this pattern; measured
# now it is 14 hits across those same 8 briefs. The breadth of the pattern BELOW — anchored to a
# leading imperative or explicit passive — is **0 of 372** on the 25 shipped briefs, and 1 on the 26
# (MCB-28's own criterion). The `_REMOVAL` comment above says explicitly that its five false
# positives came from "a bare verb search"; this one did not, and read as the shipped pattern's
# breadth. A narrow pattern was viable; the oracle is still the discriminator (see
# `consumer_impact.eval_consumer_impact`), because "did this symbol already exist?" is a FACT the
# regex cannot see, which makes an over-match harmless instead of merely unlikely.
_MODIFY = re.compile(
    r"^[-*\d.)\s]*(change|update|modify|rename|replace|switch)\b"
    r"|\bbe (changed|updated|modified|renamed|replaced)\b",
    re.IGNORECASE,
)

_BEHAVIOURAL = re.compile(
    r"\b(returns?|prints?|outputs?|raises?|exits?|persists?|matches?|rejects?|accepts?"
    r"|fails?|passes|evaluates?|produces?|contains?|behaviou?r)\b",
    re.IGNORECASE,
)
# Tests-untouched phrasing → the tamper guard, the one REPOSITORY_INVARIANT oracle that already
# exists end-to-end (integrity baseline → `tests_tampered` gate reason).
_TESTS_UNMODIFIED = re.compile(
    r"\b(do not|don'?t|never)\s+(delete|skip|weaken|modify|change|edit)\b.{0,40}\btests?\b",
    re.IGNORECASE,
)
# Markup/document structure (the MCB-02 class): DOM predicates a well-formedness parse can
# assert deterministically — named tags, anchor↔id pairing, local-asset existence.
_MARKUP = re.compile(
    r"(<[a-z][a-z0-9]*>|\bwell-formed\b|\banchor\b|\bhref\b|\bsrc\b|\bstylesheet\b"
    r"|\bid=|\bcopyright line\b|\.(html|css|svg)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    """One acceptance claim. `predicate` is the single shared binding (gate AND grader consume
    it, never re-interpreting `text`) — empty in Wave 1, authored when the contract compiler
    lands. `material=False` marks quality-soft phrasing that may inform review but never gates."""

    id: str
    item_id: int | None
    text: str
    provenance: str
    oracle_kind: str
    predicate: str = ""
    oracle_ref: str = ""
    material: bool = True
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCES:
            raise ValueError(f"unknown provenance {self.provenance!r}")
        if self.oracle_kind not in ORACLE_KINDS:
            raise ValueError(f"unknown oracle_kind {self.oracle_kind!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "text": self.text,
            "provenance": self.provenance,
            "oracle_kind": self.oracle_kind,
            "predicate": self.predicate,
            "oracle_ref": self.oracle_ref,
            "material": self.material,
            "schema_version": self.schema_version,
        }


def _sentences(acceptance: str) -> list[str]:
    """Sentence-split that survives markdown: a single newline is a LINE WRAP (joined), not a
    boundary — only sentence punctuation followed by whitespace, blank lines, and bullet starts
    split. The old `[.!?\\n]+` splitter minted FRAGMENT claims from wrapped sentences and from
    dots inside paths (`tests/test_stats.py::...` → a "claim" reading `py::test_median_even
    fails`) — the residual over-veto source in the 2026-08-03 A/B (an orphaned premise tail
    became a material unbound claim with verifiable quotes)."""
    # Join wrapped lines: a newline NOT followed by a bullet/heading/numbered item continues
    # the sentence it wraps.
    text = re.sub(r"\n(?!\s*(?:[-*#\u2022]|\d+\.))", " ", acceptance)
    # Split on sentence punctuation ONLY when followed by whitespace/end (a dot inside
    # `stats.py` or `1.5` never splits), plus any remaining (structural) newlines.
    parts = re.split(r"[.!?]+(?=\s|$)|\n+", text)
    out = []
    for s in parts:
        s = s.strip().lstrip("-*\u2022# ").strip()
        if s:
            out.append(s)
    return out


# PREMISE phrasing (#61 A/B abort, 2026-08-03): sentences DESCRIBING the starting state —
# "the suite has a\W*failing test", "implemented as a long if/elif ladder", "you are working
# in" — are context, not acceptance. Minting them as material claims inverts the goal: after
# successful work the premise is FALSE, and a critic that checks it refutes the run FOR
# SUCCEEDING (measured live: MCB-03 vetoed with evidence "exit code 0", MCB-13 with the
# ladder's own removal line). Premise sentences are recorded non-material, never gate-capable.
_PREMISE = re.compile(
    r"\b(you are working|has grown into|is implemented as|implemented as a long"
    r"|the current implementation|currently (fails|crashes|is)|today it|it works and has"
    r"|users report|the (test )?suite has a\W*failing|the bug is real|is subtly wrong"
    r"|the implementation is broken|crashes with raw tracebacks|it is wrong for)\b",
    re.IGNORECASE,
)

# Quality-soft phrasing: real intent, but not independently checkable as stated — recorded
# non-material rather than dropped (the operator SAID it; hiding it would be a silent narrowing).
_SOFT = re.compile(
    r"\b(clean|readable|well-named|semantic|reasonable|appropriate|conventions?|style|idiomatic"
    r"|maintainable|clear|nice|good)\b",
    re.IGNORECASE,
)


def classify_sentence(sentence: str) -> tuple[str, bool]:
    """(oracle_kind, material) for one acceptance sentence — pure, deterministic, ordered.

    Order matters and is deny-by-default at the bottom: tests-unmodified beats behavioural
    (its sentences usually contain 'delete/skip' verbs too); transformation beats behavioural
    (a shape claim often also mentions behaviour); an unmatched sentence that isn't
    quality-soft is a MATERIAL claim with NO oracle — `none`, the parked-not-dropped case.
    """
    if _PREMISE.search(sentence):
        return "none", False  # premise/context — never a claim about the DELIVERED work
    if len(sentence.split()) < 3:
        # A heading or fragment ("Constraints", "Quality") states nothing checkable — and a
        # 2-word "claim" was the last residual over-veto shape (2026-08-03 A/B).
        return "none", False
    if _TESTS_UNMODIFIED.search(sentence):
        return "tests_unmodified", True
    if _TRANSFORMATION.search(sentence):
        return "ast_transformation_contract", True
    if _MARKUP.search(sentence):
        return "wellformedness_parse", True
    # BELOW tests-unmodified (whose sentences carry "delete/skip" verbs too — the existing comment
    # above says so) and below transformation ("extract X into Y" is a reshape, not a removal).
    # ABOVE behavioural, because a removal sentence often also states what no longer happens
    # ("...so `export()` no longer returns the legacy shape"), and the removal is the real claim.
    if _REMOVAL.search(sentence):
        return "non_use", True
    # ABOVE behavioural on purpose — see `_MODIFY`. A behavioural claim here would restate
    # `tests_passed` and lose the only thing worth knowing: that the failure was the point.
    if _MODIFY.search(sentence):
        return "consumer_impact", True
    if _BEHAVIOURAL.search(sentence):
        return "acceptance_test", True
    if _SOFT.search(sentence):
        return "none", False
    return "none", True


def claims_from_acceptance(item_id: int | None, acceptance: str) -> list[Claim]:
    """Derive structured claims from operator-approved acceptance text.

    Every derived claim is ENTAILED: it quotes a sentence of the text the operator approved.
    INFERRED claims (model proposals) enter via ADR-0080's clarification path, never here.
    An empty/missing acceptance yields no claims — current behaviour, byte-for-byte.
    """
    claims: list[Claim] = []
    for i, sentence in enumerate(_sentences(acceptance)):
        kind, material = classify_sentence(sentence)
        claims.append(
            Claim(
                id=f"{item_id if item_id is not None else 'task'}-c{i + 1}",
                item_id=item_id,
                text=sentence,
                provenance="ENTAILED",
                oracle_kind=kind,
                material=material,
            )
        )
    return claims


def claims_as_dicts(claims: list[Claim]) -> list[dict[str, Any]]:
    return [c.as_dict() for c in claims]
