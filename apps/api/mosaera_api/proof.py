"""Project-wide proof: what the DELIVERED work of a project stands on.

The console's Overview answers "how well proven is what shipped?" for the whole project. Three of
its axes (independence, checks, integrity) are answerable from the run list. The other three —
**review, security, proof depth** — only exist inside each run's sealed receipt, and a page cannot
fetch thirteen receipts to draw one panel. This is that read, done once, server-side.

A summary of sealed records is a new artifact, and the risk it introduces is that it says something
its own sources do not (ADR-0063: verification means proving the output at the door, so a summary
nobody can reconcile against the receipts is worse than no summary). Five rules prevent it, and
they are the reason this module exists rather than a convenient SQL count:

1. **ONE ORIGIN.** Every number comes from the receipt rows themselves — the same rows the run page
   renders and `parseReceipt` reads on the web — never from a parallel table, a cached rollup, or a
   second derivation of the same facts. No state is stored: this is recomputed per request, so it
   cannot drift from the receipts the way a materialized summary would.
2. **NO SYNTHESIS.** An axis reports only a verdict the receipt LITERALLY carries. A missing field
   is `unknown`; it is never inferred from a sibling field, from the run's status, or from the
   absence of an objection. (Absence-as-proof is how the first draft of the web-side aggregate
   would have painted a perfect score over work nothing verified.)
3. **UNREADABLE IS UNKNOWN, NEVER PROVEN.** A receipt that is missing, truncated, or unparseable
   counts as `unknown` on every axis. Every error path fails toward "we do not know".
4. **THE SOURCE SET IS DISCLOSED.** The response names the run ids it read and the ones it could
   not, so any reader can reconcile the summary against the receipts by hand. A summary that cannot
   be audited against its sources is exactly the artifact this rule exists to forbid.
5. **THE DENOMINATOR IS WHAT WAS MEASURED.** Each axis reports proven / failed / unknown, and
   `measured = proven + failed`. An instrument that was not yet wired when a run happened must not
   read as that run failing — the vouch field returned "" on every run before 2026-08-13, and
   counting those blanks as failures would blame the engine for its own missing wiring.
"""

from __future__ import annotations

import json
from typing import Any

# The six axes, in display order. Independence leads: it is the weakest number on real projects and
# a governance product that hides its weakest number is a dashboard (owner decision, 2026-08-22).
_AXES = (
    ("independence", "Independence", "something other than the producer vouched for it"),
    ("checks", "Checks", "a real test suite ran and passed"),
    ("integrity", "Integrity", "the run did not edit the tests it was judged by"),
    ("review", "Review", "an independent reviewer approved the change"),
    ("security", "Security", "the security scan ran on the delivered tree"),
    ("proof_depth", "Proof depth", "the suite was deep enough to catch a planted fault"),
)

_UNKNOWN = "unknown"
_PROVEN = "proven"
_FAILED = "failed"


def _receipt_axis(axis: str, r: dict[str, Any], run: dict[str, Any]) -> str:
    """One axis's verdict from ONE delivery's sealed record.

    The record is the receipt row PLUS the run row it belongs to — the same two the run page reads.
    They are not two origins: they are one run's durable record, written by one delivery. What is
    forbidden is a SECOND INTERPRETATION, and the reader below deliberately mirrors
    `lib/radar.ts`'s per-run axes so the project summary and the run page can never disagree.

    Rule 2 (no synthesis) holds with one recorded exception, `security` — see below."""
    if axis == "independence":
        # `oracle_verified` IS the gate's independence verdict — the OR across every route
        # (`evaluate_oracle`, ADR-0044). Read it first, because it is the answer to the question
        # this axis asks.
        #
        # `oracle_vouched_by` is NOT that answer, and reading it as one was this axis's bug. It
        # diagnoses ONE route: the structural-claims vouch (ADR-0092 §3), which applies only to
        # BEHAVIOUR-PRESERVING changes. Every backlog item adds a feature, so that route never
        # applies, so it always records `no_vouch:not_behavior_preserving` — and the panel read one
        # shut door as nobody having got in. LedgerCLI showed 0 of 25 while every receipt carried
        # `oracle_verified: true` and `oracle_legs.independent: true` (live, 2026-08-24).
        #
        # Same family as the integrity/security bug fixed the day before: the rules held, the axis
        # was asking the wrong field.
        verified = r.get("oracle_verified")
        if verified is True:
            return _PROVEN
        if verified is False:
            return _FAILED
        # Pre-ADR-0044 receipts predate the field. Fall back to the vouch diagnostic, where an
        # EMPTY value is an unwired instrument (rule 5) and a recorded `no_vouch` is a real
        # failure to vouch — a route that could not apply is not one that tried and failed, but
        # without `oracle_verified` there is nothing better to read.
        vouch = str(r.get("oracle_vouched_by") or "")
        if not vouch:
            return _UNKNOWN
        return _FAILED if vouch.startswith("no_vouch") else _PROVEN
    if axis == "checks":
        passed = r.get("tests_passed")
        if passed is True:
            return _PROVEN
        if passed is False:
            return _FAILED
        return _UNKNOWN
    if axis == "integrity":
        # From the RUN row, not the receipt: `receipt_json` carries the gate's verdict, and
        # tampering/sealing are recorded on the run itself. Reading them off the receipt was the
        # first cut of this module and produced "not recorded" on all 13 deliveries of a project
        # whose runs plainly record both — the rules held (it refused to guess) but the axis was
        # asking the wrong row. Caught in live validation, 2026-08-23.
        #
        # A seal plus an explicit not-tampered verdict. Neither alone is proof: an unsealed record
        # cannot be replayed, and a sealed one with no verdict recorded nothing about tampering.
        modified = (run.get("diagnosis") or {}).get("tests_modified")
        if modified is True:
            return _FAILED
        if modified is False and run.get("receipt_id"):
            return _PROVEN
        return _UNKNOWN
    if axis == "review":
        verdict = str(r.get("reviewer_verdict") or "").upper()
        if verdict in {"APPROVE", "APPROVED"}:
            return _PROVEN
        if verdict in {"REQUEST_CHANGES", "REJECT", "BLOCKED"}:
            return _FAILED
        return _UNKNOWN  # "UNKNOWN"/absent: the reviewer's verdict could not be read
    if axis == "security":
        # THE ONE PLACE ABSENCE COUNTS, and it is recorded rather than assumed. ADR-0107 split
        # `security_not_attempted` from `security_unverified` and ADR-0108 added `security_stale`
        # precisely so that the reason set became TOTAL over security states: a gate that examined
        # security and had nothing to say emits no token, and a gate that could not examine it now
        # says so explicitly. Under a total reason set, absence IS the recorded verdict.
        #
        # This mirrors `securityAxis` in `lib/radar.ts` exactly, because the alternative is worse
        # than the exception: the run page would call a delivery "security scan clean" while the
        # project summary called the same delivery "not recorded", and a summary disagreeing with
        # its own sources is the artifact ADR-0109 exists to prevent.
        #
        # RESIDUAL, recorded not closed: receipts written BEFORE those ADRs cannot emit the tokens,
        # so a pre-ADR-0107 delivery that was merely silent reads as clean. The reason set is total
        # only going forward. Closing it needs a positive scan record in the receipt itself.
        reasons = [str(x) for x in (r.get("reasons") or [])]
        if "security_findings" in reasons:
            return _FAILED
        if any(
            t in reasons
            for t in ("security_stale", "security_not_attempted", "security_unverified")
        ):
            return _UNKNOWN  # never scanned THIS code — an absence of measurement, not a failure
        if (run.get("diagnosis") or {}).get("security_unavailable_cause"):
            return _UNKNOWN  # the scanner itself was unavailable
        return _PROVEN
    if axis == "proof_depth":
        # Both terms must be present: a full suite that no mutation was ever thrown at is not
        # evidence of depth, and a caught mutation on a shallow check is not a suite.
        strength = str(r.get("validation_strength") or "").lower()
        caught = r.get("tests_mutation_caught")
        if strength == "suite" and caught is True:
            return _PROVEN
        if strength in {"shallow", "none"} or caught is False:
            return _FAILED
        return _UNKNOWN
    return _UNKNOWN


def project_proof(memory: Any, project_id: str) -> dict[str, Any]:
    """Aggregate the sealed receipts of a project's DELIVERED runs.

    One entry per delivering unit — an item's newest APPROVED run, or an ad-hoc APPROVED run — so
    an item that parked eight times before shipping counts once, as the delivery it became.
    """
    detail = memory.project_detail(project_id) or {}
    runs = list(detail.get("runs") or [])

    # The delivering run per unit. Same rule as the web's `deliveringRuns`, and the two are pinned
    # against each other by a shared fixture rather than by hope.
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        item_id = r.get("item_id")
        key = f"item:{item_id}" if item_id is not None else f"run:{r.get('id')}"
        by_unit.setdefault(key, []).append(r)
    delivering: list[dict[str, Any]] = []
    for attempts in by_unit.values():
        approved = [a for a in attempts if str(a.get("status") or "") == "APPROVED"]
        if approved:
            approved.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
            delivering.append(approved[0])

    receipts: dict[str, str] = {}
    getter = getattr(memory, "project_receipts", None)
    if callable(getter):
        try:
            receipts = dict(getter(project_id) or {})
        except Exception:
            receipts = {}  # Rule 3: an unreadable store yields unknowns, never proofs.

    read: list[str] = []
    unreadable: list[str] = []
    parsed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for run in delivering:
        run_id = str(run.get("id") or "")
        raw = receipts.get(run_id)
        if not raw:
            unreadable.append(run_id)
            continue
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            unreadable.append(run_id)
            continue
        if not isinstance(obj, dict):
            unreadable.append(run_id)
            continue
        read.append(run_id)
        parsed.append((obj, run))

    axes = []
    for key, label, note in _AXES:
        proven = failed = unknown = 0
        for r, run in parsed:
            verdict = _receipt_axis(key, r, run)
            if verdict == _PROVEN:
                proven += 1
            elif verdict == _FAILED:
                failed += 1
            else:
                unknown += 1
        # Rule 3 again, at the aggregate level: a delivery whose receipt could not be read is an
        # unknown on EVERY axis. It never silently shrinks the population instead.
        unknown += len(unreadable)
        axes.append(
            {
                "key": key,
                "label": label,
                "note": note,
                "proven": proven,
                "failed": failed,
                "unknown": unknown,
                "measured": proven + failed,
            }
        )

    return {
        "delivered": len(delivering),
        "axes": axes,
        # Rule 4: the source set, so the summary can be reconciled against the receipts by hand.
        "sources": {
            "receipts_read": sorted(read),
            "receipts_unreadable": sorted(unreadable),
        },
    }
