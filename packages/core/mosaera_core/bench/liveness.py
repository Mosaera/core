"""Control-liveness verdicts for A/B experiments (ADR-0081).

Four times in one week a control looked live and structurally could not fire; the worst case was
an A/B whose ON and OFF arms ran byte-identical code and whose noise drove a hold decision. This
module is the deterministic answer: compare the ARMS' execution fingerprints (captured by
``bench/harness.py`` — nodes entered, keys written, interrupt actions, terminal disposition;
never prompts or model payloads) and refuse to score an experiment whose arms never diverged.

The registry below records, per posture knob, the highest liveness rung PROVEN so far — honestly,
including the knobs that cannot currently be proven. ``scripts/check_control_liveness.py`` reports
it and fails on a posture knob missing from the registry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

INVALID_EXPERIMENT_IDENTICAL_EXECUTION = "INVALID_EXPERIMENT_IDENTICAL_EXECUTION"

# The C0-C5 ladder (ADR-0081 §Decision 1). Stored as strings so registry entries read as prose.
RUNGS = (
    "C0_DECLARED",
    "C1_READ",
    "C2_INFLUENTIAL",
    "C3_EXERCISED",
    "C4_ARM_DIVERGENT",
    "C5_OUTCOME_OBSERVABLE",
)


def _projection(fp: dict[str, Any]) -> tuple[Any, ...]:
    """The comparable core of a fingerprint: node/key trace, interrupt actions, terminal."""
    nodes = tuple((str(n), tuple(map(str, k))) for n, k in (fp.get("nodes") or []))
    return (nodes, tuple(map(str, fp.get("interrupts") or [])), str(fp.get("terminal", "")))


@dataclass(frozen=True)
class Divergence:
    """The comparison verdict for one A/B arm pair."""

    diverged: bool
    detail: str

    @property
    def verdict(self) -> str | None:
        return None if self.diverged else INVALID_EXPERIMENT_IDENTICAL_EXECUTION


def compare_fingerprints(a: dict[str, Any], b: dict[str, Any]) -> Divergence:
    """Deterministically compare two runs' fingerprints.

    Identical projections ⇒ the arms executed the same path and the experiment must not be
    scored. The detail names the FIRST point of divergence so a valid experiment's record shows
    where the control actually bit.
    """
    pa, pb = _projection(a), _projection(b)
    if pa == pb:
        return Divergence(False, "identical node trace, interrupts and terminal disposition")
    na, nb = pa[0], pb[0]
    for i, (va, vb) in enumerate(zip(na, nb, strict=False)):
        if va != vb:
            return Divergence(
                True, f"first divergence at visit {i}: {va[0]}{list(va[1])} vs {vb[0]}{list(vb[1])}"
            )
    if len(na) != len(nb):
        return Divergence(True, f"trace lengths differ: {len(na)} vs {len(nb)} visits")
    if pa[1] != pb[1]:
        return Divergence(True, f"interrupt actions differ: {list(pa[1])} vs {list(pb[1])}")
    return Divergence(True, f"terminal dispositions differ: {pa[2]!r} vs {pb[2]!r}")


def experiment_verdict(
    arm_a: list[dict[str, Any]], arm_b: list[dict[str, Any]]
) -> tuple[str | None, list[Divergence]]:
    """Judge a whole A/B: every cross-arm pair identical ⇒ INVALID, else None (scoreable).

    Deny-by-default on missing data: an arm with NO fingerprints cannot prove divergence, so the
    experiment is INVALID — absence of evidence is not evidence of divergence.
    """
    if not arm_a or not arm_b:
        return INVALID_EXPERIMENT_IDENTICAL_EXECUTION, []
    pairs = [compare_fingerprints(a, b) for a in arm_a for b in arm_b]
    if any(d.diverged for d in pairs):
        return None, pairs
    return INVALID_EXPERIMENT_IDENTICAL_EXECUTION, pairs


def fingerprints_of(cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every usable execution fingerprint carried by an arm's scorecards.

    Per-run cards carry ``meta["fingerprint"]``; an aggregate card carries the LIST
    ``meta["fingerprints"]`` (one per repeat, ``None`` for repeats that predate capture).
    Both shapes are accepted; unusable entries are dropped rather than counted, so an arm
    whose capture failed reads as *no evidence* — which `experiment_verdict` refuses to score.
    """
    out: list[dict[str, Any]] = []
    for card in cards:
        meta = card.get("meta") or {}
        one = meta.get("fingerprint")
        if isinstance(one, dict):
            out.append(one)
        for many in meta.get("fingerprints") or []:
            if isinstance(many, dict):
                out.append(many)
    return out


@dataclass(frozen=True)
class ExperimentReport:
    """An A/B's liveness verdict and — only if it is valid — its effectiveness numbers.

    ``effect is None`` is the enforcement of ADR-0081 Decision 3: an experiment whose arms
    executed identically has no effectiveness result to report, so there is none to quote.
    """

    verdict: str | None  # INVALID_EXPERIMENT_IDENTICAL_EXECUTION, or None when scoreable
    divergences: list[Divergence]
    effect: dict[str, dict[str, int]] | None

    @property
    def scoreable(self) -> bool:
        return self.verdict is None


def experiment_report(
    arm_a: Sequence[Mapping[str, Any]], arm_b: Sequence[Mapping[str, Any]]
) -> ExperimentReport:
    """Validate an A/B BEFORE scoring it (ADR-0081 Decision 3, mechanised).

    Decision 3 has been a human procedure since the ladder landed: `experiment_verdict` had no
    callers, so nothing stopped an arm-identical A/B from producing numbers that then reached a
    roadmap claim. Instance #4 is exactly that failure. This runs the check first and withholds
    the numbers when the arms never diverged — the verdict is the result.
    """
    verdict, divergences = experiment_verdict(fingerprints_of(arm_a), fingerprints_of(arm_b))
    if verdict is not None:
        # Second, INDEPENDENT validity path — for a lever that changes what the run is TOLD
        # rather than how the graph is routed (a brief edit, a standing decision). The
        # fingerprint is deliberately value-blind, so both arms walk the same nodes to the same
        # terminal while working from different instructions, and it reports INVALID.
        #
        # What this does NOT do, deliberately: accept "the arms' RESULTS differed" as validity.
        # Two runs of one configuration produce different outcomes routinely — that is model
        # nondeterminism, not an effect — so scoring on result-divergence would license
        # attributing noise to the lever, which is the exact failure this ladder exists to stop.
        #
        # It asks the same question the fingerprint asks, in the only place it is visible for an
        # input-side lever: did the control actually ENGAGE? `clauses_applied` is written by the
        # claim oracle when a standing decision really changed the constraint that was checked —
        # so an arm carrying it did something a bare arm did not.
        engaged = _engagement_divergence(arm_a, arm_b)
        if not engaged.diverged:
            return ExperimentReport(verdict, [*divergences, engaged], None)
        divergences = [*divergences, engaged]
    return ExperimentReport(None, divergences, {"a": _outcomes(arm_a), "b": _outcomes(arm_b)})


def _engaged(cards: Sequence[Mapping[str, Any]]) -> set[str]:
    """The controls that demonstrably FIRED in this arm (not merely those configured)."""
    fired: set[str] = set()
    for card in cards:
        for entry in (card.get("meta") or {}).get("clauses_applied") or []:
            fired.add(str(entry))
    return fired


def _engagement_divergence(
    arm_a: Sequence[Mapping[str, Any]], arm_b: Sequence[Mapping[str, Any]]
) -> Divergence:
    a, b = _engaged(arm_a), _engaged(arm_b)
    if a == b:
        return Divergence(False, f"no control engaged differently across arms ({sorted(a)})")
    return Divergence(True, f"controls engaged differ: {sorted(a)} vs {sorted(b)}")


def _outcomes(cards: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Terminal-bucket tally for one arm — the effectiveness number an A/B actually cites."""
    tally: dict[str, int] = {}
    for card in cards:
        outcome = str((card.get("meta") or {}).get("outcome") or "")
        if outcome:
            tally[outcome] = tally.get(outcome, 0) + 1
    return tally


@dataclass(frozen=True)
class LivenessRecord:
    """One posture knob's honestly-proven rung. `evidence` says WHAT proved it (a test name, a
    recorded experiment) — an unproven higher rung is recorded as exactly that, not rounded up."""

    knob: str
    rung: str
    evidence: str
    note: str = ""


# The registry: every knob `apply_oracle_posture` flips MUST have a row (the guard script fails
# otherwise), plus knobs with a liveness history worth pinning. Rungs are the HIGHEST PROVEN,
# not the highest hoped-for.
REGISTRY: tuple[LivenessRecord, ...] = (
    LivenessRecord(
        "tester_enabled",
        "C4_ARM_DIVERGENT",
        "test_control_liveness.py::test_tester_enabled_diverges_the_graph",
        "ON splices author_tests into the graph spine (build.py) — a structural divergence.",
    ),
    LivenessRecord(
        "reason_on_stall_enabled",
        "C2_INFLUENTIAL",
        "read + behavior sink verified by inspection; test_reason_ladder.py exists but its "
        "knob-ON drive is unverified",
        "C3/C4 sentinels not yet written — recorded honestly, not rounded up.",
    ),
    LivenessRecord(
        "oracle_coverage",
        "C2_INFLUENTIAL",
        "read + sink verified by inspection; coverage tests exist, knob-ON drive unverified",
        "C3/C4 sentinels not yet written — recorded honestly, not rounded up.",
    ),
    LivenessRecord(
        "oracle_mutation_check",
        "C2_INFLUENTIAL",
        "read + sink verified by inspection (nodes_review); no verified knob-ON fixture",
        "C3/C4 sentinels not yet written — recorded honestly, not rounded up.",
    ),
    LivenessRecord(
        "oracle_mutation_vetoes",
        "C3_EXERCISED",
        "test_oracle_legs.py::test_the_veto_knob_diverts_the_decision_and_nothing_else drives "
        "BOTH arms and asserts they decide differently on the same input",
        "Not C4: this changes the gate's DECISION, not the graph's shape, so no fingerprint "
        "divergence exists to claim. The A/B lever for the 2026-08-11 proven-False finding.",
    ),
    LivenessRecord(
        "oracle_record_all_legs",
        "C3_EXERCISED",
        "test_oracle_record_all_legs.py::test_ON_replaces_not_evaluated_with_a_real_answer "
        "drives both arms; test_the_verdict_is_IDENTICAL_in_both_arms pins 28 input "
        "combinations to the same verdict",
        "Not C4 and never will be: this knob is DIAGNOSTIC — divergence would mean it changes "
        "the decision, which is the one thing its tests exist to forbid.",
    ),
    LivenessRecord(
        "tester_repairs_tests",
        "C2_INFLUENTIAL",
        "read + sink verified by inspection; test_proctor_repair.py exists, drive unverified",
        "C3/C4 sentinels not yet written — recorded honestly, not rounded up.",
    ),
    LivenessRecord(
        "proctor_faithfulness_guard",
        "C2_INFLUENTIAL",
        "read + sink verified by inspection; test_faithfulness.py exists, drive unverified",
        "C3/C4 sentinels not yet written — recorded honestly, not rounded up.",
    ),
    LivenessRecord(
        "critic_enabled",
        "C5_OUTCOME_OBSERVABLE",
        "roadmap 2026-08-02 'the critic DECLINES' measurement (post-ADR-0078)",
        "Veto observable in terminal_reasons since ADR-0078; measured live on MCB-05/10.",
    ),
    LivenessRecord(
        "refactor_oracle_scaffold",
        "C2_INFLUENTIAL",
        "read + sink verified by inspection; test_refactor_scaffold.py exists, drive unverified",
        "C3/C4 sentinels not yet written — recorded honestly, not rounded up.",
    ),
    LivenessRecord(
        "oracle_structural_spec",
        "C4_ARM_DIVERGENT",
        "test_control_liveness.py::test_structural_spec_knob_diverges_state_writes",
        "Not posture-flipped (withdrawn 2026-08-02); C4 proven at unit level; the n=25 A/B was "
        "outcome-null, which is a C5 finding about EFFECT, not liveness.",
    ),
    LivenessRecord(
        "claims_gate_input",  # not a posture knob: data-driven (claims present at launch)
        "C5_OUTCOME_OBSERVABLE",
        "claims-gate-ab-2026-08-03 (140-run fingerprint-validated A/B) + test_gate.py sentinels",
        "ADR-0079 Wave 2: C4 via gate-decision divergence tests; C5 proven live — "
        "unsatisfied-claim ids observed in scorecard meta during the A/B (MCB-21/22).",
    ),
    LivenessRecord(
        "critic_claim_protocol",  # #61 — posture-ON since 2026-08-03 (owner-decided)
        "C5_OUTCOME_OBSERVABLE",
        "test_control_liveness.py::test_critic_claim_protocol_diverges_the_dispose_path",
        "ON routes dispose() (verified rows), OFF is the legacy verdict byte-identical; "
        "C5 proven by the 2026-08-03 A/B (critic_rows observed in scorecard meta).",
    ),
    LivenessRecord(
        "honest_stop_no_signal",
        "C2_INFLUENTIAL",
        "test_control_liveness.py::test_honest_stop_no_signal_cannot_diverge_on_countable_input",
        "Instance #4 pinned: on countable validators the arms CANNOT diverge — the knob is "
        "unmeasurable on the current suite (needs an uncountable-validator case; tracked as "
        "the last checkbox of ADR-0077 'Definition of done' — the roadmap has no entry).",
    ),
)


def registry_by_knob() -> dict[str, LivenessRecord]:
    return {r.knob: r for r in REGISTRY}
