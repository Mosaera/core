"""The structured record of HOW a run ended — one definition, shared by the bench and live runs.

The bench has computed this for months (`bench/cli.py`'s scorecard meta). A live run recorded
`termination_reason`, an 80-character string, and nothing else. So every failure observed through
the UI was an anecdote: no outcome bucket, no park cause, no gate reasons, no vouch diagnosis —
nothing that lets "did this recur?" be answered three days later.

That asymmetry is why the benchmark found defects the product never surfaced, and it is the reason
this module exists as ONE function rather than a second copy: a live run's `outcome` must mean
exactly what a bench run's `outcome` means, or the two bodies of evidence cannot be compared.

Deliberately NOT included: anything requiring a hidden grader. A live run has no ground truth, so
`Fidelity`/over-park stays a bench-only measurement. What a live run CAN honestly record is the
decision and the evidence behind it, which is what this captures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mosaera_core.bench.reliability import classify_outcome, classify_park_cause
from mosaera_core.graph.nodes_scan import security_unavailable_cause

# Out-of-band stop channels. `blocked_reason` and `escalate_reason` are here because the over-park
# arc (2026-08-05) hit a park that Layer 2 declined for a reason NOTHING recorded — its gate reasons
# ruled out every documented decline, and these two were the only candidates left. The run's final
# state was gone, so the cause is permanently unrecoverable. Six fields would have answered it.
_STOP_CHANNELS = (
    "stall_reason",
    "give_up_reason",
    "plan_unworkable_reason",
    "blocked_reason",
    "escalate_reason",
)


def build_diagnosis(
    final: Mapping[str, Any],
    *,
    errored: bool = False,
    acceptance_failed: bool = False,
    max_iterations: int | None = None,
    evidence_home: str = "",
) -> dict[str, Any]:
    """The full structured record of one finished run.

    ``acceptance_failed`` is the hidden-grader contradiction and is available only to the bench;
    a live run passes False, which `classify_outcome` documents as "a delivery with no grader
    counts as clean here — reliability asks *did it conclude honestly*".
    """
    gate = final.get("gate_decision")
    gate_reasons = list((gate or {}).get("reasons") or []) if isinstance(gate, dict) else []
    diagnosis: dict[str, Any] = {
        "outcome": classify_outcome(
            final,
            errored=errored,
            acceptance_failed=acceptance_failed,
            max_iterations=max_iterations,
        ),
        "park_cause": classify_park_cause(final, max_iterations=max_iterations),
        "gate_reasons": gate_reasons,
        # Why the oracle vouched, or which guard said no (#60). BOTH of these live inside
        # `gate_decision`, not at the top of RunState — `terminal_vouch` is a BENCH-harness
        # dataclass field and `vouch` is nothing at all, so this read returned "" on every live
        # run for as long as it existed, in the one module whose stated purpose is that a live
        # run's outcome means what a bench run's outcome means. Caught by check_state_keys; the
        # test pinned only `key in diagnosis`, i.e. the presence of the empty value (F66's shape).
        "vouch": str((gate or {}).get("oracle_vouched_by") or "") if isinstance(gate, dict) else "",
        # WHICH term of the oracle AND refused. `vouch` above explains only the structural-vouch
        # disjunct, and reading it as the refusal reason is a documented mis-inference — a live
        # run must be able to answer "which leg?" the same way a scorecard now can.
        "oracle_blocked_by": [
            str(x)
            for x in (((gate or {}).get("oracle_legs") or {}).get("blocked_by") or [])
            if isinstance(gate, dict)
        ],
        "unsatisfied_claims": [str(c) for c in ((gate or {}).get("unsatisfied_claims") or [])]
        if isinstance(gate, dict)
        else [],
        "iteration": int(final.get("iteration", 0) or 0),
        "max_iterations": max_iterations,
        "stalled": bool(final.get("stalled")),
        "tests_modified": bool(final.get("tests_modified")),
        # WHY a sanctioned repair did not land — an empty `proctor_edits` alone cannot tell
        # "the Proctor never edited" from "it edited and the profile check refused it".
        "amendment_refusals": dict(final.get("amendment_refusals") or {}),
        "coder_escalated": bool(final.get("coder_escalated")),
        # WHERE this run wrote its evidence — the ABSOLUTE resolved store path (TM-0001).
        # `Settings.home` is cwd-relative, so a process started in the wrong directory writes
        # to whatever store is there and nothing notices: every gate watches delivered code,
        # not the record. On 2026-08-10 ~2,500 scorecards were destroyed with a clean gate (a
        # committed `.mosaera` symlink, materialised over the store by git under
        # core.symlinks=false — closed 2026-08-11). Recording before enforcement: this makes a
        # misdirected write DIAGNOSABLE, not impossible.
        "evidence_home": evidence_home,
        # Why security was unverified — "the scan failed" vs "no scan was attempted". Both
        # produced an EMPTY reason before, so the record could not tell them apart; the corpus
        # showed 73 firings all empty, which only the second explains. Recording only.
        "security_unavailable_cause": security_unavailable_cause(final),
    }
    for channel in _STOP_CHANNELS:
        diagnosis[channel] = str(final.get(channel) or "")
    return diagnosis


def diagnosis_summary(diagnosis: Mapping[str, Any]) -> str:
    """One human line for a log or a UI row. The full record stays structured; this is the label.

    Names the FIRST out-of-band stop channel that fired, because that is the run's real reason —
    the gate's reasons describe what was missing at the door, not why the run stopped walking.
    """
    outcome = str(diagnosis.get("outcome") or "?")
    for channel in _STOP_CHANNELS:
        if diagnosis.get(channel):
            return f"{outcome}: {channel.removesuffix('_reason')} — {diagnosis[channel]}"[:200]
    reasons = diagnosis.get("gate_reasons") or []
    if reasons:
        return f"{outcome}: gate blocked on {', '.join(str(r) for r in reasons)}"[:200]
    return outcome
