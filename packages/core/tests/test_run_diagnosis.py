"""The shared run diagnosis — the record a LIVE run now keeps, matching the bench's.

Before this, a live run recorded `termination_reason` (80 chars) and nothing else, so every
failure seen through the UI was an anecdote: no outcome bucket, no park cause, no gate reasons, no
vouch. The benchmark had all of it, which is why the benchmark found defects the product never
surfaced.
"""

from __future__ import annotations

from mosaera_core.bench.reliability import classify_outcome, classify_park_cause
from mosaera_core.run_diagnosis import build_diagnosis, diagnosis_summary


def test_the_bucket_is_the_benchmarks_bucket_not_a_second_opinion() -> None:
    """The point of sharing the classifier: a live `honest_park` must mean exactly what a bench
    `honest_park` means, or the two bodies of evidence cannot be compared at all."""
    final = {
        "approved": False,
        "gate_decision": {"reasons": ["validation_failed", "unsatisfied_claim"]},
        "give_up_reason": "no convergence: failing count 4 -> 4 -> 4",
        "iteration": 3,
    }
    d = build_diagnosis(final, max_iterations=6)
    assert d["outcome"] == classify_outcome(
        final, errored=False, acceptance_failed=False, max_iterations=6
    )
    assert d["park_cause"] == classify_park_cause(final, max_iterations=6)


def test_the_stop_channels_that_were_missing_are_recorded() -> None:
    """`blocked_reason` and `escalate_reason` are here because a park on 2026-08-05 was declined by
    Layer 2 for a reason nothing recorded — its gate reasons ruled out every documented cause and
    these two were the only candidates left. The final state was gone by then, so the cause
    is permanently unrecoverable."""
    d = build_diagnosis({"blocked_reason": "coder blocked on a missing dep"})
    assert d["blocked_reason"] == "coder blocked on a missing dep"
    d = build_diagnosis({"escalate_reason": "needs a human decision"})
    assert d["escalate_reason"] == "needs a human decision"
    # Absent channels are recorded as empty, never omitted — a missing KEY and a channel that did
    # not fire must not look the same to a reader three days later.
    for key in ("stall_reason", "give_up_reason", "plan_unworkable_reason", "blocked_reason"):
        assert key in build_diagnosis({})


def test_the_vouch_and_the_unsatisfied_claims_are_actually_POPULATED() -> None:
    """The 2026-08-07 audit finding, and the F66 shape a third time.

    `build_diagnosis` read `terminal_vouch` (a BENCH-harness dataclass field) and a top-level
    `unsatisfied_claims` (it lives under `gate_decision`). Neither is a declared RunState key, so
    LangGraph dropped both and **every live run recorded an empty vouch** — in the one module whose
    stated purpose is that a live run's `outcome` means what a bench run's `outcome` means.

    It survived because the existing coverage asserts `key in build_diagnosis({})` — the PRESENCE
    of the empty value. A field that is always "" satisfies that forever. This asserts the value.
    """
    d = build_diagnosis(
        {
            "gate_decision": {
                "reasons": ["unsatisfied_claim"],
                "oracle_vouched_by": "structural_claims:88-c2",
                "unsatisfied_claims": ["88-c1", "88-c2"],
            }
        }
    )
    assert d["vouch"] == "structural_claims:88-c2"
    assert d["unsatisfied_claims"] == ["88-c1", "88-c2"]


def test_a_run_with_no_gate_decision_reports_empty_rather_than_raising() -> None:
    """A run that never reached the gate has no vouch to report — that must be "" and [], not a
    crash and not an invented value."""
    d = build_diagnosis({"plan_unworkable_reason": "under_specified"})
    assert d["vouch"] == ""
    assert d["unsatisfied_claims"] == []


def test_a_delivery_is_diagnosed_too() -> None:
    """ "It concluded honestly" is a claim about deliveries as much as parks."""
    d = build_diagnosis({"approved": True, "iteration": 1}, max_iterations=6)
    assert d["outcome"] == "clean_deliver"
    assert d["park_cause"] == ""


def test_a_live_run_never_claims_a_false_ship() -> None:
    """A live run has no hidden grader, so it cannot know a delivery was wrong. `acceptance_failed`
    defaults False and `classify_outcome` documents that reading: reliability asks *did it conclude
    honestly*, and whether an ungraded delivery is CORRECT is a question only a grader can answer.
    Recording `false_ship` here would be asserting ground truth we do not have."""
    assert build_diagnosis({"approved": True})["outcome"] == "clean_deliver"


def test_the_summary_names_the_real_stop_not_the_gate_reasons() -> None:
    """The gate's reasons say what was missing at the door; the stop channel says why the run
    stopped walking. A reader wants the second one first."""
    line = diagnosis_summary(
        build_diagnosis(
            {
                "gate_decision": {"reasons": ["validation_failed"]},
                "stalled": True,
                "stall_reason": "no convergence: 4 -> 4 -> 4",
            }
        )
    )
    assert "stall" in line and "no convergence" in line

    # With no out-of-band stop, the gate's reasons ARE the explanation.
    gate_only = diagnosis_summary(
        build_diagnosis({"gate_decision": {"reasons": ["oracle_unverified"]}})
    )
    assert "oracle_unverified" in gate_only


def test_an_empty_final_does_not_raise() -> None:
    """A crashed run may have almost nothing. Diagnosis is best-effort instrumentation and must
    never be the thing that breaks a run's terminal path."""
    d = build_diagnosis({}, errored=True)
    assert d["outcome"] == "crash"
    assert diagnosis_summary(d)


def test_the_record_names_the_evidence_store_it_wrote_to() -> None:
    """TM-0001. `Settings.home` is cwd-relative, so a process started in the wrong directory writes
    to whatever store is there and NOTHING notices — every gate watches delivered code, not the
    record. On 2026-08-10 a convenience symlink pointed a worktree at the live store and ~2,500
    scorecards were destroyed behind a clean gate.

    Recording before enforcement: this makes a misdirected write DIAGNOSABLE after the fact. It does
    not make it impossible, and the threat model says so.
    """
    d = build_diagnosis({}, evidence_home="/srv/mosaera/.mosaera")
    assert d["evidence_home"] == "/srv/mosaera/.mosaera"


def test_the_evidence_store_field_is_always_present() -> None:
    """Absent would be indistinguishable from 'wrote nowhere' — the same unreadable-zero shape this
    field exists to close. A caller that does not supply it records the empty string, which is
    visibly 'not recorded' rather than silently missing."""
    assert "evidence_home" in build_diagnosis({})
