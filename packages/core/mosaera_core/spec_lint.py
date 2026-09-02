"""Deterministic acceptance spec-lint for freshly-decomposed backlog items (#54 slice 0, ADR-0073).

The #53 live backlog drive showed the specs, not the engine, causing thrash: decompose invented
exact reason-tuples the coder could never satisfy (the Proctor pins tamper-protected tests to the
acceptance text verbatim), armed refactor-only validation on a feature via "same output as <input
path>" phrasing, and emitted a near-duplicate item that parked as already-satisfied. This module is
the cheap, deterministic detector for those three defect classes — no I/O, no LLM. Disposition
stays with Quincy (one bounded re-curate pass built from ``curate_instruction``), and application
stays with the deny-by-default changeset applier; the lint itself never mutates anything.

Precision over recall: a missed defect costs one honest park downstream; a false flag costs one
sentence in a curate instruction the model may ignore.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from mosaera_core.behavior_preservation import preservation_matches
from mosaera_core.progress import normalize


class SpecFinding(NamedTuple):
    """One lint finding: the item it concerns, the rule slug, and a curator-ready sentence.

    ``param`` names the registered oracle parameter this finding is ABOUT, when there is one
    (ADR-0082). It is the deterministic link that lets a ratified clause answer a finding without
    this module knowing anything about clauses — spec_lint stays pure, and the suppression lives
    at the caller. Empty for findings that no standing decision could settle.
    """

    item_id: int
    rule: str  # "exact_value" | "refactor_phrase" | "near_duplicate" | "undecidable_claim" | …
    detail: str
    param: str = ""


# R1 — exact-value over-specification. Three sharp signatures of "the acceptance pins a literal
# machine value" (the #53 thrash shape was `(1, ['too short (len < 8)'])`):
#   a literal tuple-with-list return shape;
#   returns/prints/outputs followed by a backticked literal containing quotes/brackets;
#   a fenced code block introduced as exact output.
_TUPLE_WITH_LIST = re.compile(r"\(\s*-?\d+\s*,\s*\[[^\]]*\]\s*\)")
_EXACT_BACKTICK = re.compile(
    r"\b(returns?|prints?|outputs?)\b[^`\n]{0,60}`[^`]*['\"\[\(][^`]*`", re.IGNORECASE
)
_EXACT_FENCE = re.compile(r"\b(outputs?|prints?)\s*(exactly|:)\s*\n\s*```", re.IGNORECASE)

# R3 — near-duplicate scope. Token-set Jaccard over normalized title+acceptance; two backlog
# items this similar are (or will become) the same work.
_WORD = re.compile(r"[a-z0-9]{3,}")
_JACCARD_THRESHOLD = 0.5

# R4 — existence-only acceptance (the #53/#54 validation-drive scaffolding class: "the file
# exists and can be imported"). Such an item has no behaviour a test can independently assert,
# so under the autonomous posture it can never earn oracle credit — a guaranteed defer. A
# sentence is existence-only when it matches one of these; the rule fires only when EVERY
# sentence does (one behavioural sentence anywhere suppresses it — precision over recall).
_EXISTENCE_PAT = re.compile(
    r"\b(exists?|is\s+(created|present)|can\s+be\s+imported|import\w*[^.!?\n]*succeed\w*"
    r"|(should\s+)?succeeds?|without\s+(an\s+)?errors?|no\s+errors?\s+occur|runs?\s+without)\b",
    re.IGNORECASE,
)


def _existence_only(acceptance: str) -> bool:
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", acceptance) if s.strip()]
    return bool(sentences) and all(_EXISTENCE_PAT.search(s) for s in sentences)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(normalize(text)))


def _exact_value_snippet(acceptance: str) -> str | None:
    """The first exact-literal demand found in ``acceptance``, or None."""
    for pattern in (_TUPLE_WITH_LIST, _EXACT_BACKTICK, _EXACT_FENCE):
        m = pattern.search(acceptance)
        if m:
            return m.group(0).strip()[:80]
    return None


def lint_backlog(items: list[dict[str, Any]]) -> list[SpecFinding]:
    """Lint the open (``todo``) backlog items; in-flight/settled items are never re-scoped.

    Pure and deterministic: same items in, same findings out.
    """
    todo = [i for i in items if str(i.get("status", "todo")) == "todo"]
    findings: list[SpecFinding] = []

    for item in todo:
        item_id = int(item["id"])
        acceptance = str(item.get("acceptance") or "")
        if not acceptance.strip():
            continue
        snippet = _exact_value_snippet(acceptance)
        if snippet:
            findings.append(
                SpecFinding(
                    item_id,
                    "exact_value",
                    f"item #{item_id} pins exact literal values in its acceptance "
                    f"({snippet!r}); acceptance should state observable behaviour and reason "
                    "SUBSTRINGS, never exact strings/tuples/output formats, unless the "
                    "stakeholder demanded them — rewrite the acceptance via enhance.",
                )
            )
        spans = preservation_matches(acceptance)
        if spans:
            findings.append(
                SpecFinding(
                    item_id,
                    "refactor_phrase",
                    f"item #{item_id}'s acceptance contains behaviour-preservation phrasing "
                    f"({spans[0]!r}) that will trigger refactor-only validation; if this item "
                    "is NOT a pure refactor, rephrase it (e.g. 'matches the output of X' "
                    "instead of 'same output as X') via enhance; if it genuinely is a "
                    "refactor, keep it.",
                )
            )
        if _existence_only(acceptance):
            findings.append(
                SpecFinding(
                    item_id,
                    "no_behaviour",
                    f"item #{item_id}'s acceptance asserts only existence/importability — "
                    "no observable behaviour a test can independently verify, so it can "
                    "never earn oracle credit; fold it into the item that uses it (merge) "
                    "or give it behavioural acceptance (inputs and observable outputs) via "
                    "enhance.",
                )
            )

    for i, a in enumerate(todo):
        ta = _tokens(f"{a.get('title', '')} {a.get('acceptance', '')}")
        if not ta:
            continue
        for b in todo[i + 1 :]:
            tb = _tokens(f"{b.get('title', '')} {b.get('acceptance', '')}")
            if not tb:
                continue
            jaccard = len(ta & tb) / len(ta | tb)
            if jaccard >= _JACCARD_THRESHOLD:
                findings.append(
                    SpecFinding(
                        int(a["id"]),
                        "near_duplicate",
                        f"items #{a['id']} and #{b['id']} have overlapping scope/acceptance "
                        f"(similarity {jaccard:.0%}); if they cover the same work, fold one "
                        "into the other via merge (or narrow their acceptance so they don't "
                        "overlap).",
                    )
                )
    return findings


# --- DECIDABILITY (does the claim determine ONE answer?) ---------------------------------
#
# `checkability` below asks whether a claim BINDS to an oracle. That is necessary and not
# sufficient: a claim can bind and still leave its value unstated, which is the dangerous
# combination — binding grants false confidence. Three observed instances:
#
#   MCB-05 / MCB-15  "a short orchestrator (a handful of statements)" — graders assert <=6
#                    and <=7 from near-identical prose. 100% of the suite's false_ship.
#   demos/greenfield "prints a strength score 0-4 plus reasons" — no composition rule, so
#                    two runs invented two different scoring models; the second passed 48
#                    tests written to match its own invention.
#
# The North Star calls the missing property a "near-deterministic brief". These patterns are
# narrow ON PURPOSE (this module's bar: precision over recall) and are scoped to shapes with
# real failures behind them — widen only when a new failure class is observed.

# A magnitude word that does not resolve to a count. Deliberately excludes bare adjectives
# like "small"/"short": across the 24-case corpus those almost always describe the PROJECT
# ("build a small, self-contained todo manager") rather than a countable requirement, and
# flagging them cost 5 false positives on the first scoring of this detector.
_VAGUE_MAGNITUDE = re.compile(
    r"\b(a\s+handful|a\s+few|a\s+couple|a\s+sentence\s+or\s+two|some\s+number)\b",
    re.IGNORECASE,
)
# An output SCALE named as a range — "score 0-4", "rating 1 to 5". The scale noun is required:
# a bare "N - M" also matches arithmetic in an example ("1 + 2 - 3" cost a false positive),
# and a range only needs a composition rule when it is the value being produced.
_OUTPUT_SCALE = re.compile(
    r"\b(score|rating|grade|level|strength|scale|rank)\b[^.!?\n]{0,40}?"
    # The dashes are \u escapes, not literals: an en dash is load-bearing here
    # (the greenfield brief writes its range with one) and a literal trips RUF001.
    r"\b\d+\s*(?:-|\u2013|\u2014|to)\s*\d+\b",
    re.IGNORECASE,
)
# Language that FIXES a value: a mapping, a threshold, an explicit count, a preservation rule.
# Any of these makes the claim decidable and suppresses the flag.
_RULE_LANGUAGE = re.compile(
    r"(->|=>|\bif\b|\bwhen\b|\botherwise\b|\bper\b|\beach\b|\bmaps?\s+to\b"
    r"|\bbased\s+on\b|\bat\s+least\b|\bat\s+most\b|\bexactly\b|\bno\s+more\s+than\b"
    r"|\bno\s+fewer\s+than\b|[<>]=?\s*\d|\bidentical\b|\bunchanged\b|\bmust\s+still\b"
    r"|\bpreserv\w*\b)",
    re.IGNORECASE,
)


# Clause boundaries. The suppressor must be LOCAL: MCB-05 says "read as a short orchestrator
# (a handful of statements) that delegates to at least three helper functions" — one sentence
# carrying an undecidable clause AND a decidable one. Scoped sentence-wide, "at least three"
# silently excused "a handful", which is the very claim the graders disagree over.
_CLAUSE_SPLIT = re.compile(r"[,;()\u2014]|\bthat\b|\bwhich\b|\bplus\b", re.IGNORECASE)


# Block boundaries: a blank line, or the start of a new bullet. Blocks matter because the two
# patterns need DIFFERENT suppressor scopes (see undecidable_reason).
_BLOCK_SPLIT = re.compile(r"\n\s*\n|\n(?=\s*[-*•]\s)")


def _block_for(sentence: str, acceptance: str) -> str:
    """The bullet/paragraph `sentence` came from, or the sentence itself if it can't be located.

    Falls back to the sentence — the narrower scope — so a lookup miss can only make the check
    stricter, never quieter.
    """
    if not acceptance:
        return sentence
    needle = normalize(sentence)[:30]
    if not needle:
        return sentence
    for block in _BLOCK_SPLIT.split(acceptance):
        if needle in normalize(block):
            return block
    return sentence


def undecidable_reason(sentence: str, acceptance: str = "") -> str:
    """Why this claim does not determine a unique answer, or "" if it does.

    Pure and deterministic. The two patterns get DIFFERENT suppressor scopes, because they fail
    for different reasons:

    * **Vague magnitude** is CLAUSE-scoped. MCB-05 says "read as a short orchestrator (a handful
      of statements) that delegates to at least three helper functions" — a countable elsewhere
      does not fix "a handful", it just sits next to it.
    * **A named output scale** is BLOCK-scoped (the bullet or paragraph). A brief legitimately
      names the output in one sentence and states its composition rule in the next — that is how
      a person writes it, and the value is determined either way. Found the hard way: a brief
      repaired exactly as this check's own finding instructed still scored UNDECIDABLE, because
      the rule landed one sentence later. Report-only that costs a false flag; gating anything,
      it would block correctly-written briefs.

    `acceptance` is the item's full text, used only to locate that block; omitted, the scope
    collapses to the sentence and the check is merely stricter.
    """
    scope = _block_for(sentence, acceptance)
    for clause in _CLAUSE_SPLIT.split(sentence):
        if not clause or _RULE_LANGUAGE.search(clause):
            continue
        vague = _VAGUE_MAGNITUDE.search(clause)
        if vague:
            return (
                f"'{vague.group(0)}' states a magnitude that does not resolve to a count — two "
                "readers get two different answers"
            )
        scale = _OUTPUT_SCALE.search(clause)
        if scale and not _RULE_LANGUAGE.search(scope):
            return (
                f"names the range '{scale.group(0)}' as an output but states no rule for how "
                "the value is composed"
            )
    return ""


def decidability(items: list[dict[str, Any]]) -> dict[int, str]:
    """Per-item DECIDABLE / UNDECIDABLE — does the acceptance determine ONE answer?

    A sibling of `checkability`, deliberately NOT folded into it: that verdict is consumed
    as an exact string in several places, and the two axes are orthogonal (a claim can be
    bound-but-undecidable, which is the case that has cost us three times).

    Same contract as `checkability`: todo-only, pure, deterministic, no I/O.
    """
    from mosaera_core.claims import claims_from_acceptance

    verdicts: dict[int, str] = {}
    for item in items:
        if str(item.get("status", "todo")) != "todo":
            continue
        item_id = int(item["id"])
        acceptance = str(item.get("acceptance") or "")
        claims = claims_from_acceptance(item_id, acceptance)
        undecidable = [c for c in claims if c.material and undecidable_reason(c.text, acceptance)]
        verdicts[item_id] = "UNDECIDABLE" if undecidable else "DECIDABLE"
    return verdicts


# The finding -> parameter map, and it stays at ONE entry on purpose. A growing phrase->parameter
# table would be the re-parse trap returning through a side door: the whole point of a clause is
# that its value is a stored integer, not something re-derived from prose. A second entry needs a
# second registered parameter and the measurement to justify it.
_STATEMENT_SHAPED = re.compile(r"\bstatements?\b", re.IGNORECASE)


def finding_param(claim_text: str) -> str:
    """The registered oracle parameter a standing decision could settle, or ``""``.

    Judged on the CLAIM, not on the refusal message: the reason names the offending phrase ("a
    handful"), while the countable thing it qualifies ("statements") is in the sentence itself.
    """
    return "structural.body_statements" if _STATEMENT_SHAPED.search(claim_text) else ""


def decidability_findings(items: list[dict[str, Any]]) -> list[SpecFinding]:
    """UNDECIDABLE claims as findings for the SAME one-pass re-curate loop the checkability
    findings already feed. Report-only by design: nothing blocks on this yet, because the
    ask-rate is a measured dial (ADR-0080's stated hazard is clarification fatigue)."""
    from mosaera_core.claims import claims_from_acceptance

    findings: list[SpecFinding] = []
    for item in items:
        if str(item.get("status", "todo")) != "todo":
            continue
        item_id = int(item["id"])
        acceptance = str(item.get("acceptance") or "")
        for claim in claims_from_acceptance(item_id, acceptance):
            reason = undecidable_reason(claim.text, acceptance) if claim.material else ""
            if reason:
                findings.append(
                    SpecFinding(
                        item_id,
                        "undecidable_claim",
                        f'item #{item_id}: "{claim.text[:90]}" {reason}. State the rule that '
                        "fixes the value (a mapping, a threshold, an explicit count) so the "
                        "delivered work has one correct answer rather than a guessed one.",
                        finding_param(claim.text),
                    )
                )
    return findings


def checkability(items: list[dict[str, Any]]) -> dict[int, str]:
    """Per-item Checkability verdict (ADR-0079 §3), derived from the item's claims.

    CHECKABLE            every material claim binds to an oracle kind.
    PARTIALLY_CHECKABLE  some material claims bind; the unbound ones will PARK delivery
                         (never silently drop) once the gate consumes claims (a later wave).
    UNDER_SPECIFIED      no material claim binds at all → ADR-0080's clarification case.

    Deny-by-default: an item with EMPTY acceptance is UNDER_SPECIFIED — nothing checkable was
    stated. Pure and deterministic, same contract as lint_backlog.
    """
    from mosaera_core.claims import claims_from_acceptance

    verdicts: dict[int, str] = {}
    for item in items:
        if str(item.get("status", "todo")) != "todo":
            continue
        item_id = int(item["id"])
        claims = claims_from_acceptance(item_id, str(item.get("acceptance") or ""))
        material = [c for c in claims if c.material]
        bound = [c for c in material if c.oracle_kind != "none"]
        if not material or not bound:
            verdicts[item_id] = "UNDER_SPECIFIED"
        elif len(bound) < len(material):
            verdicts[item_id] = "PARTIALLY_CHECKABLE"
        else:
            verdicts[item_id] = "CHECKABLE"
    return verdicts


def checkability_findings(items: list[dict[str, Any]]) -> list[SpecFinding]:
    """UNDER_SPECIFIED items rendered as findings for the EXISTING one-pass re-curate loop —
    deliberate ADR-0080 pre-wiring: Quincy is asked to make the acceptance checkable (or the
    operator is, via the curate card) without any new interrupt machinery in this wave."""
    return [
        SpecFinding(
            item_id,
            "under_specified",
            f"item #{item_id}'s acceptance states no independently checkable behaviour — no "
            "claim in it can bind to an oracle (a test, a structural contract, the tamper "
            "guard). State observable inputs/outputs, a required shape, or an error contract "
            "via enhance; as written, delivery of this item cannot be evidence-gated.",
        )
        for item_id, verdict in checkability(items).items()
        if verdict == "UNDER_SPECIFIED"
    ]


class ItemDiagnosis(NamedTuple):
    """One item's intake standing, computed the same way whatever its status.

    ``compliant`` answers a narrow question: *would this acceptance text fail today's intake
    bar* — nothing binds at all (UNDER_SPECIFIED, which parks a run today) or the text does not
    fix its answer (UNDECIDABLE, which ships invented evidence). ``reasons`` names each failure.

    PARTIALLY_CHECKABLE is deliberately NOT a failure. It is the modal state of a good brief —
    both demo briefs are partial, including the brownfield one that produced correct code in
    zero fix iterations — and it blocks nothing in the engine today. Calling it non-compliant
    made the best brief we own read as non-compliant, which is a marker that cries wolf on
    everything and gets ignored. It stays visible in ``checkability``; it is not a flag.
    """

    item_id: int
    status: str
    checkability: str
    decidability: str
    compliant: bool
    reasons: list[str]


def diagnose_item(item: dict[str, Any]) -> ItemDiagnosis:
    """Intake standing for ONE item, ignoring status — the backfill primitive.

    `checkability` / `decidability` judge `todo` items only, deliberately: settled work isn't
    re-judged during a run. That filter is also why work authored before those checks existed
    is invisible to them, so a backfill needs a status-blind entry point rather than a widened
    filter (which would silently change what every existing caller sees).

    IMPORTANT, and carried into every message this produces: a non-compliant SETTLED item does
    NOT mean the delivered code is wrong. It means the acceptance text could not have gated it
    — the evidence was weaker than we would accept today. Reading it as a retroactive false-ship
    claim would be exactly the over-claim the anti-gaming rules forbid.
    """
    single = [{**item, "status": "todo"}]
    item_id = int(item["id"])
    check = checkability(single)[item_id]
    decide = decidability(single)[item_id]
    reasons: list[str] = []
    if check == "UNDER_SPECIFIED":
        reasons.append("no material acceptance claim binds to any oracle")
    if decide == "UNDECIDABLE":
        reasons.append("the text names a value it never states a rule for")
    return ItemDiagnosis(
        item_id=item_id,
        status=str(item.get("status", "todo")),
        checkability=check,
        decidability=decide,
        compliant=not reasons,
        reasons=reasons,
    )


def diagnose_backlog(items: list[dict[str, Any]]) -> list[ItemDiagnosis]:
    """The whole backlog's intake standing, settled work included. Pure; nothing is mutated,
    nothing is stored — the verdict is DERIVED at read, so it stays honest as the detectors
    improve instead of freezing today's judgement into a column that silently goes stale."""
    return [diagnose_item(i) for i in items]


def curate_instruction(findings: list[SpecFinding]) -> str:
    """Render findings as ONE bounded re-curate instruction for Quincy.

    The curator proposes ops; the deny-by-default changeset applier validates them — the lint
    never edits the backlog itself.
    """
    if not findings:
        return ""
    lines = "\n".join(f"- {f.detail}" for f in findings)
    return (
        "A deterministic spec-lint flagged the following acceptance-criteria problems in the "
        "backlog you just authored. Fix ONLY what genuinely needs fixing (enhance to rewrite "
        "acceptance, merge to fold duplicates); propose nothing else.\n" + lines
    )
