"""Every gate reason has an operator-facing sentence, in both surfaces, with ONE origin.

The gate's reason vocabulary is read by three places that must stay total over it: the durable
termination sentence (`_termination_reason`), the web copy map (`GATE_REASON` in `plain.ts`), and
the proof-bearing partition (`standards.PROOF_BEARING` / `NOT_PROOF_BEARING`, guarded at import).

**Why this file exists.** `a33e86e` split `validation_unavailable` into two reasons and updated
none of the three. Six days later `validation_not_attempted` still rendered as raw jargon in the
UI, still fell through to the generic termination sentence the split existed to prevent, and was
still absent from the deny-list a clause may not waive. Nothing failed, because each surface
enumerated the vocabulary *by hand* — a second origin per surface.

`typing.get_args(GateReason)` is the single origin. The `plain.ts` check is deliberately written in
PYTHON: a TypeScript test cannot read a Python Literal, so a TS-side enumeration is a second origin
by construction — which is exactly why `plain.test.ts` listed the same stale 13 tokens and passed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args

from mosaera_policies.gate import GateReason
from mosaera_policies.standards import NOT_PROOF_BEARING, PROOF_BEARING

DECLARED = frozenset(get_args(GateReason))
_REPO = Path(__file__).resolve().parents[3]


def _termination_branch_reasons() -> set[str]:
    """The reason strings `_termination_reason` actually branches on, read from its source.

    An AST walk rather than a hand-list, for the same reason the rest of this file exists.
    """
    src = (_REPO / "apps" / "api" / "mosaera_api" / "runner" / "_terminal.py").read_text()
    fn = next(
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_termination_reason"
    )
    return {
        node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in DECLARED
    }


def test_every_gate_reason_has_a_termination_sentence() -> None:
    """A parked run must say WHY in its durable 80-char column, for every reason.

    The one that made this urgent: a reviewer can APPROVE a run whose tests were tampered with, so
    `reasons == ["tests_tampered"]` alone is reachable — and it matched no branch, meaning the most
    serious park the engine can produce read "ended without meeting the acceptance criteria".
    """
    # `reviewer_*` are covered by a startswith branch, not a literal, so exempt them explicitly.
    covered = _termination_branch_reasons() | {r for r in DECLARED if r.startswith("reviewer")}
    missing = sorted(DECLARED - covered)
    assert not missing, (
        f"gate reason(s) {missing} have no branch in _termination_reason — they fall through to "
        "the generic 'ended without meeting the acceptance criteria', which is the sentence every "
        "one of these reasons exists to replace."
    )


def test_the_web_copy_map_is_total_over_the_gate_vocabulary() -> None:
    """`plain.ts`'s GATE_REASON covers every reason — checked from the Python side.

    `gateReason()` falls back to `token.replace(/_/g, " ")`, so a missing key does not error: the
    operator is simply shown engine jargon. Silent degradation is the failure mode, which is why
    this needs a guard rather than a code review.
    """
    src = (_REPO / "apps" / "web" / "src" / "lib" / "plain.ts").read_text()
    body = src.split("export const GATE_REASON: Record<string, string> = {", 1)[1].split("\n};", 1)[
        0
    ]
    keys = set(re.findall(r"^\s*([a-z_]+):", body, re.MULTILINE))
    assert keys, "could not parse GATE_REASON — the guard drifted, not the code"

    missing = sorted(DECLARED - keys)
    assert not missing, (
        f"plain.ts GATE_REASON is missing {missing} — the operator sees raw engine tokens via the "
        "gateReason() fallback. Add a plain-English sentence for each."
    )
    stale = sorted(keys - DECLARED)
    assert not stale, f"plain.ts GATE_REASON has {stale}, which GateReason no longer declares"


def _remedy_body() -> str:
    src = (_REPO / "apps" / "web" / "src" / "lib" / "remedy.ts").read_text()
    return src.split("export const GATE_REMEDY: Record<string, Remedy> = {", 1)[1].split("\n};", 1)[
        0
    ]


def test_every_gate_reason_names_a_remedy() -> None:
    """A reason says what was MISSING; a remedy says what supplies it (#121).

    #108 fixed the recording of why a run stopped and the screen still offered no next step, which
    for someone who has not read the docs is the same dead end. Same guard shape as GATE_REASON
    above and for the same reason: `gateRemedy()` returns null on a miss, so a new reason degrades
    SILENTLY to a park with no way out.
    """
    keys = set(re.findall(r"^  ([a-z_]+):", _remedy_body(), re.MULTILINE))
    assert keys, "could not parse GATE_REMEDY — the guard drifted, not the code"

    missing = sorted(DECLARED - keys)
    assert not missing, (
        f"remedy.ts GATE_REMEDY is missing {missing} — a run parked on one of these tells the "
        "operator what happened and nothing about what to do. Add a remedy sentence for each."
    )
    stale = sorted(keys - DECLARED)
    assert not stale, f"remedy.ts GATE_REMEDY has {stale}, which GateReason no longer declares"


def test_every_remedy_knob_is_a_real_knob() -> None:
    """A remedy that names a setting must name one that exists.

    "Turn on X" where X is not a knob is worse than saying nothing: the operator goes looking, does
    not find it, and stops trusting the next sentence too. The knob names are the SPA's only claim
    about server config, so this is the seam where they get checked.
    """
    from mosaera_core.config import GENERAL_KNOBS

    fields = {k.field for k in GENERAL_KNOBS}
    named = set(re.findall(r'knob:\s*"([a-z_]+)"', _remedy_body()))
    assert named, (
        "no remedy names a knob — either the guard drifted or the remedies lost their teeth"
    )
    unknown = sorted(named - fields)
    assert not unknown, (
        f"remedy.ts points the operator at {unknown}, which is not in GENERAL_KNOBS — the setting "
        "it tells them to change does not exist."
    )


def test_the_oracle_leg_remedies_cover_what_the_gate_records() -> None:
    """`blocked_by` is one of three terms, recorded on every run and never rendered until #121.

    A generic `oracle_unverified` sentence sends the operator to flip the Proctor when the Proctor
    was already on and the sabotage check is what refused. The three names come from
    `evaluate_oracle`'s own `blocked_by` list, so this fails if that grows a fourth.
    """
    src = (_REPO / "apps" / "web" / "src" / "lib" / "remedy.ts").read_text()
    body = src.split("export const ORACLE_LEG_REMEDY: Record<string, Remedy> = {", 1)[1].split(
        "\n};", 1
    )[0]
    covered = set(re.findall(r"^  ([a-z_]+):", body, re.MULTILINE))

    legs_src = (
        _REPO / "packages" / "core" / "mosaera_core" / "graph" / "_oracle_legs.py"
    ).read_text()
    recorded = set(
        re.findall(r'\(\s*"([a-z_]+)",\s*(?:independent|mutation_ok|structural_ok)\)', legs_src)
    )
    assert recorded, "could not parse evaluate_oracle's blocked_by terms — the guard drifted"
    missing = sorted(recorded - covered)
    assert not missing, f"remedy.ts has no remedy for oracle leg(s) {missing}"


def test_the_web_verdict_classification_mirrors_the_gate() -> None:
    """`verdict.ts`'s VERDICT_REASON_CLASS matches `REASON_CLASS` token-for-token, class-for-class.

    The de-firehose redesign derives the run pages' HEADLINE from a TS mirror of the Python
    classification — a second origin by construction, on the one string a human reads before
    deciding. A silently-drifted class there makes the headline wrong, which on a gate is an
    honesty bug of the first order. Same style as the GATE_REASON guard above: parsed from the
    Python side, so the TS file cannot drift without this failing.
    """
    from mosaera_policies.gate import REASON_CLASS

    src = (_REPO / "apps" / "web" / "src" / "lib" / "verdict.ts").read_text()
    body = src.split("export const VERDICT_REASON_CLASS: Record<string, ReasonClass> = {", 1)[
        1
    ].split("\n};", 1)[0]
    pairs = dict(re.findall(r'^\s*([a-z_]+):\s*"([a-z_]+)"', body, re.MULTILINE))
    assert pairs, "could not parse VERDICT_REASON_CLASS — the guard drifted, not the code"

    missing = sorted(set(REASON_CLASS) - set(pairs))
    assert not missing, f"verdict.ts is missing {missing} — the headline cannot rank them"
    stale = sorted(set(pairs) - set(REASON_CLASS))
    assert not stale, f"verdict.ts classifies {stale}, which GateReason no longer declares"
    wrong = {t: (pairs[t], REASON_CLASS[t]) for t in pairs if pairs[t] != REASON_CLASS[t]}
    assert not wrong, (
        f"verdict.ts disagrees with mosaera_policies.gate.REASON_CLASS on {wrong} — the WEB "
        "HEADLINE would rank these reasons differently than the gate itself does"
    )


def test_the_proof_bearing_partition_is_total() -> None:
    """PROOF_BEARING and NOT_PROOF_BEARING partition the vocabulary exactly.

    `standards._verify_registries` raises at import, so this is belt-and-braces — but it pins the
    *partition* property itself rather than trusting that an import-time check stayed two-way.
    """
    assert PROOF_BEARING | NOT_PROOF_BEARING == DECLARED
    assert not (PROOF_BEARING & NOT_PROOF_BEARING)


def test_the_totality_guards_actually_fire() -> None:
    """Proven on synthetic input, so none of the above can pass by vacuity.

    ADR-0090's own bar: a guard that has never been shown to fail is not evidence.
    """
    declared = frozenset({"a", "b", "a_later_feature_reason"})
    covered = frozenset({"a", "b"})
    assert sorted(declared - covered) == ["a_later_feature_reason"]
    assert sorted(covered - frozenset({"a", "a_later_feature_reason"})) == ["b"]
