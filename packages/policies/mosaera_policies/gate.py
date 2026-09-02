"""Delivery-gate policy: what the evidence allows, before anyone approves.

The gate decision is computed from signals the pipeline already produces —
validation result, parsed reviewer verdict, structural security findings, and
the iteration cap. It is embedded in the approval-gate payload (so humans
decide informed), consulted by the autonomous runner (which may never
override), and recorded in the run report.

Policy invariants (P0-1 "Make the Gate Real"):
- Autonomous approval happens ONLY when the reasons list is empty, OR — the sole
  refinement (ADR-0029, broadened by ADR-0031, narrowed by ADR-0034) — when the ONLY
  blocking reason is the reviewer's SILENCE (``reviewer_unknown``) and the run's
  DETERMINISTIC validation both PASSED and actually MEANS something: ``tests_passed is
  True`` AND ``validation_strength == "suite"`` (a real executed test suite ran). The
  reviewer is a VETO, not a required sign-off, so a flaky local reviewer that emits no
  verdict can't false-park deterministically-validated work — but silence may only ever
  be overridden by POSITIVE EXECUTED evidence, never by a syntax check. A real objection
  (``reviewer_blocked`` / ``reviewer_requested_changes`` / ``reviewer_conflict``) vetoes.
- The executed suite must also be INDEPENDENT of the coder (oracle-make-real, ADR-0044): a
  spec-derived tester oracle that FAILS pre-impl and ASSERTS something real, OR a pre-existing
  tamper-guarded baselined suite, OR an operator ``--test-cmd`` (that OR is computed in
  ``gate_node`` as ``oracle_verified``). A green ``strength == "suite"`` run with NONE of those is
  the coder's OWN suite → adds ``oracle_unverified`` and parks, closing the "ship on the coder's
  own tests" residual. Fires on the reviewer-APPROVE path too; testless/shallow runs are untouched.
- A reviewer REQUEST_CHANGES alone earns a bounded revise loop; everything
  else that is not all-clear parks the run for a human.
- An UNKNOWN verdict never approves for a HUMAN-gated run (a human decides); the
  backstop is autonomous-only (it lives in ``autonomous_resolution``). An unavailable
  validation result is never approval in any mode.
- A CONFLICTING verdict (``reviewer_conflict``) is NOT silence and never rides the
  backstop: if we cannot tell whether the reviewer approved or objected, a human decides.
- Security evidence is deny-by-default (ADR-0076): a scan that was EXPECTED but produced no
  verdict (``security_status == "unavailable"``) adds ``security_unverified`` and parks —
  "we did not check" is never "clean". An operator opt-out (``disabled``) or a clean scan
  passes through; a real finding still parks via ``security_findings``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

GateReason = Literal[
    "validation_failed",
    "validation_unavailable",
    "validation_not_attempted",
    "reviewer_requested_changes",
    "reviewer_blocked",
    "reviewer_unknown",
    "reviewer_conflict",
    "security_findings",
    "security_unverified",
    "security_not_attempted",
    "security_stale",
    "reviewer_stale",
    "tests_tampered",
    "content_destroyed",
    "oracle_unverified",
    "critic_vetoed",
    "unsatisfied_claim",
    "claim_behavioral_failed",
    "claim_structural_failed",
    "claim_integrity_failed",
    "removal_unproven",
    "impact_unassessed",
    "iteration_limit",
]

# The legacy UNION of the three claim reasons above (ADR-0092), kept for two reasons.
#
# 1. STORED DATA. `give_up_allowed_reasons()` is evaluated against stored reason arrays on live
#    paths — the API disposition sweep, `convertible_decline_reason`, the bench park-reason tally.
#    Removing it would make every historical park carrying it non-admissible again, which is #68's
#    shape re-created over stored data, on 118 scorecards. Its class stays `objection` (what it was
#    when every stored row was written): reclassifying the union would retroactively admit all of
#    them to Layer 2, a permission change hiding in a compatibility line.
# 2. It is the honest FALLBACK when a caller supplies failed-claim ids without classes — "a claim
#    failed, we cannot say which kind" is precisely what this string has always meant.
UNCLASSIFIED_CLAIM_REASON = "unsatisfied_claim"

# What KIND of claim evidence failed. Policies declares only these three; the mapping from the
# six oracle kinds lives in `mosaera_core.claims.CLAIM_EVIDENCE_CLASS`, because core owns that
# vocabulary and policies may not import it (ADR-0092).
ClaimEvidenceClass = Literal["behavioral", "structural", "integrity", "removal", "impact"]

# Which reason each evidence class emits. Data, not an f-string, because `removal` breaks the
# `claim_{cls}_failed` pattern deliberately: a SUBTRACT item's blocker is that the removal is
# UNPROVEN (the oracle failed, or could not run at all), not that a claim "failed" — and naming it
# for what it is keeps the operator from reading it as an ordinary claim miss.
#
# Order is the emission order and is load-bearing: this stays the last content-bearing append
# before `iteration_limit`, and `_resolve` compares `core == ["reviewer_unknown"]` as a LIST.
_CLASS_REASON: tuple[tuple[str, str], ...] = (
    ("behavioral", "claim_behavioral_failed"),
    ("structural", "claim_structural_failed"),
    ("integrity", "claim_integrity_failed"),
    ("removal", "removal_unproven"),
    ("impact", "impact_unassessed"),
)

GateAction = Literal["deliver", "revise", "require_human"]
AutonomousResolution = Literal["approve", "deny_with_feedback", "park"]

# WHAT KIND of fact each gate reason is (ADR-0090). Downstream policies — the Layer-2 close-the-gap
# arm and the ESCALATE arm — decide admission from the CLASS, never from a privately held list.
#
# This exists because a hand-written list silently went stale: `_GIVE_UP_ALLOWED_REASONS` was
# written 2026-07-23 (ADR-0075) and `unsatisfied_claim` was minted 2026-08-02 (ADR-0079 Wave 2) — a
# later feature added a reason a deny-by-default allowlist had never heard of, which narrowed BOTH
# disposition arms to nothing on the dominant over-park shape with every test green (#68, F62). The
# classification lives HERE, one edit from the `GateReason` Literal, so a new reason and its class
# land together and the same CODEOWNERS review sees both.
#
#   objection   someone or something found a real problem with the delivered work or its review.
#               The park stands on its own terms; no disposition arm may act over it.
#   shortfall   an evidence bar was not met, with nothing objecting. This is precisely the class
#               the disposition arms exist to address.
#   incidental  carries no independent information — it rides along on any non-empty reasons, or
#               it is silence. Never disqualifying by itself.
#   tamper      an integrity violation. Never laundered, by any arm, under any posture.
#   not_run     THE CHECK DID NOT RUN — never entered (ADR-0107) or ran on a different tree
#               (ADR-0108) — as against it ran and objected. Deny for SHIP, not for ASK.
ReasonClass = Literal["objection", "shortfall", "incidental", "tamper", "not_run"]

REASON_CLASS: dict[GateReason, ReasonClass] = {
    "validation_failed": "shortfall",
    "validation_unavailable": "objection",
    "validation_not_attempted": "not_run",  # `unavailable` RAN and stayed silent: objection
    "reviewer_requested_changes": "objection",
    "reviewer_blocked": "objection",
    "reviewer_unknown": "incidental",
    "reviewer_conflict": "objection",
    "security_findings": "objection",
    "security_unverified": "objection",
    # ADR-0107. `scan_node` was never entered, so there is no verdict to have an opinion about.
    # Kept OUT of every SHIP arm all the same — `not_run` is admissible only to arms that declare
    # it, and `give_up_allowed_reasons()` does not.
    "security_not_attempted": "not_run",
    "security_stale": "not_run",  # ADR-0108: ran, on a tree that is not the one shipping
    "reviewer_stale": "not_run",  # ditto, independence leg
    "tests_tampered": "tamper",
    # ADR-0099. A STANDING PROHIBITION, in the tamper family and for the same reason: the
    # producer destroyed something it was never asked to touch, so there is no criterion to
    # "finish" and nothing for the coder to fix by trying harder. `tamper` is the class whose
    # admissible-set membership is already nil, which is exactly right here.
    "content_destroyed": "tamper",
    "oracle_unverified": "shortfall",
    "critic_vetoed": "objection",
    # The legacy union (ADR-0092) — see UNCLASSIFIED_CLAIM_REASON. Stays `objection`.
    "unsatisfied_claim": "objection",
    # The split (ADR-0092), and the reason the classes differ is measured, not asserted:
    # `behavioral` is `state["tests_passed"]` verbatim, so it restates `validation_failed` — a
    # reason the arms already admit — and it correlated 88% grader-PASS over n=50. `structural`
    # reads the delivered AST and is the one genuinely independent claim evidence; it correlated
    # 69% grader-FAIL over n=54, i.e. those parks are mostly RIGHT. See #84 for the mechanism.
    "claim_behavioral_failed": "shortfall",
    "claim_structural_failed": "objection",
    # An unproven removal is an OBJECTION, never a shortfall. It must stay out of every
    # admissible set: Layer-2's close-the-gap arm verifies by authoring a BEHAVIOURAL test and
    # mutating it, which says nothing about whether the removed thing is still referenced — so
    # admitting this class would let it convert a removal that breaks every caller.
    "removal_unproven": "objection",
    # verb-arc slice 4. An OBJECTION, never a shortfall, and out of every admissible set: Layer 2
    # verifies by authoring a behavioural test and mutating it — the very evidence a behaviour
    # CHANGE invalidates — so it would convert a change nothing witnesses.
    "impact_unassessed": "objection",
    # Provably co-present with `tests_tampered` today (both read `state["tests_modified"]`), so it
    # can never be the sole reason. Emitted anyway: no suppression argument to defend, and a guard
    # for the day the tamper claim's oracle diverges from the guard's.
    "claim_integrity_failed": "tamper",
    "iteration_limit": "incidental",
}


def reason_class(reason: str) -> str:
    """The class of one reason, or the reason itself when unclassified.

    Deny-by-default in the sense that matters for the stall breaker: an unclassified reason keeps
    its own identity rather than collapsing into a shared bucket, so it can still end a loop. The
    totality test means "unclassified" should be unreachable — this is the behaviour if it is not.
    """
    classes: dict[str, str] = {str(k): str(v) for k, v in REASON_CLASS.items()}
    return classes.get(reason, reason)


def reasons_of_class(*classes: ReasonClass) -> frozenset[str]:
    """The reason strings belonging to any of ``classes``.

    The generic accessor: this module classifies, it does not decide admission. Which classes a
    given control admits is that control's policy and lives with the control (ADR-0090) — the gate
    must not grow knowledge of the disposition arms.
    """
    wanted = set(classes)
    return frozenset(reason for reason, cls in REASON_CLASS.items() if cls in wanted)


# How much the run's executed validation is actually WORTH — declared by the LanguagePack
# that produced the plan (ADR-0032/0034), not inferred here.
#   "suite"   a real test suite executed (pytest, `npm test`, an operator --test-cmd, the
#             tester's acceptance suite). This is the only evidence strong enough to let
#             the autonomous backstop deliver over a silent reviewer.
#   "shallow" something ran, but it only proves the code PARSES: `compileall`, a JSON/TOML
#             parse, an HTML well-formedness check, a typecheck with no tests.
#   "none"    no validator at all (incl. `deliver_unverified`, which coerces tests_passed
#             to True upstream of this gate — see evaluate_gate).
#   "unknown" no plan reached the gate. Deny-by-default: not "suite", so it never ships.
ValidationStrength = Literal["suite", "shallow", "none", "unknown"]


@dataclass(frozen=True)
class GateDecision:
    """Structured, auditable verdict of the delivery gate's evidence check."""

    action: GateAction
    reasons: list[str]
    tests_passed: bool | None
    reviewer_verdict: str
    autonomous: bool
    # True when an INDEPENDENT oracle vouched for correctness this run — the tester's
    # spec-derived acceptance suite ran and passed (folded into tests_passed), so the
    # autonomous backstop may deliver on reviewer SILENCE (ADR-0029). Never set on
    # reviewer objection or a failing/absent oracle.
    oracle_verified: bool = False
    # What `tests_passed is True` is actually WORTH on this run. Carried on the decision
    # (not just used to compute it) so the serialized interrupt payload — which is all
    # `autonomous_resolution` and the human gate panel ever see — can tell a green pytest
    # suite apart from a green `compileall`. See ValidationStrength.
    validation_strength: str = "unknown"
    # The ids of acceptance claims whose bound oracle evaluated and FAILED (ADR-0079). The ids
    # live HERE, not in the reason string: the gate-stall breaker fingerprints
    # sorted(set(reasons)), so the reason must stay the stable "unsatisfied_claim" while the
    # specific ids ride the decision for the report/ledger/human panel. Defaulted so every
    # pre-claims constructor call (and GateDecision(**old_payload)) keeps working.
    unsatisfied_claims: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reasons": list(self.reasons),
            "tests_passed": self.tests_passed,
            "reviewer_verdict": self.reviewer_verdict,
            "autonomous": self.autonomous,
            "oracle_verified": self.oracle_verified,
            "validation_strength": self.validation_strength,
            "unsatisfied_claims": list(self.unsatisfied_claims),
        }


def _resolve(reasons: list[str], tests_passed: bool | None, strength: str) -> AutonomousResolution:
    """THE autonomous policy — the single place that decides what may ship unattended.

    ``evaluate_gate``'s ``action`` and ``autonomous_resolution`` both route through this,
    so the two surfaces cannot drift apart (they did: ADR-0031 taught only the runner
    about the backstop, leaving ``evaluate_gate(autonomous=True).action`` reporting
    ``require_human`` for a case the runner shipped).
    """
    if not reasons:
        return "approve"
    # The reviewer-silence backstop (ADR-0029 → ADR-0031 → narrowed by ADR-0034).
    # `iteration_limit` rides along on any non-empty reasons, so ignore it when asking
    # "is silence the SOLE blocker". Everything else must be positive executed evidence:
    # a green run whose plan only ran `compileall` proves syntax, not behaviour, and may
    # not override a reviewer who never spoke.
    core = [r for r in reasons if r != "iteration_limit"]
    if core == ["reviewer_unknown"] and tests_passed is True and strength == "suite":
        return "approve"
    if set(reasons) == {"reviewer_requested_changes"}:
        return "deny_with_feedback"
    return "park"


def evaluate_gate(
    *,
    tests_passed: bool | None,
    reviewer_verdict: str,
    findings_count: int,
    iteration: int,
    max_iterations: int,
    autonomous: bool = False,
    oracle_verified: bool = False,
    validation_strength: str = "unknown",
    validation_unverified: bool = False,
    validation_attempted: bool = True,
    tests_tampered: bool = False,
    content_destroyed: bool = False,
    critic_vetoed: bool = False,
    security_status: str = "clean",
    scan_attempted: bool = True,
    scan_fresh: bool = True,
    review_fresh: bool = True,
    claims_failed: list[str] | None = None,
    claims_failed_classes: Sequence[str] | None = None,
) -> GateDecision:
    """Derive the gate decision from the run's real evidence.

    Reason order is fixed and deterministic; ``iteration_limit`` is appended
    only when other reasons exist (an all-clear run at the cap delivers — same
    comparison ``iteration >= max_iterations`` as the graph's routing).

    ``validation_strength`` is the LanguagePack's own declaration of what its plan
    proves (see ValidationStrength). ``validation_unverified`` says the run had no
    validator at all and ``deliver_unverified`` coerced ``tests_passed`` to True
    *upstream of this gate* — so a True here can be worth nothing, and the gate must be
    told. Either way the run may still deliver on a reviewer APPROVE (that is what the
    flag has always promised); what it may NOT do is ride the reviewer-silence backstop,
    which exists to stand on executed evidence.
    """
    strength = "none" if validation_unverified else (validation_strength or "unknown")

    reasons: list[str] = []
    if tests_passed is False:
        reasons.append("validation_failed")
    elif tests_passed is None:
        # A missing verdict has TWO causes that demand opposite responses from a human, and
        # collapsing them cost an operator an hour on 2026-08-07 (F39, issue #71): they read
        # "validation unavailable", concluded the sandbox was broken, and went looking at Docker
        # — while the truth was that the run never got as far as validating, because the planner
        # had already given up. `validation_attempted` is not an inference: `test_node` writes a
        # validation_plan whenever it runs, so its ABSENCE is proof the node was never entered.
        #
        # Deny-preserving by construction: `_resolve` is a positive allowlist (only
        # `["reviewer_unknown"]` may approve), so a NEW reason can only ever park. This splits a
        # message, never a permission.
        reasons.append(
            "validation_unavailable" if validation_attempted else "validation_not_attempted"
        )
    if tests_tampered:
        # The coder edited/deleted a pre-existing or protected test, or its collection config
        # (ADR-0036). A green suite obtained by weakening it is not evidence. Distinct from
        # validation_failed: it is never the coder's to "fix" by finishing the tamper, and it
        # can never satisfy the reviewer-silence backstop (core != ["reviewer_unknown"]).
        reasons.append("tests_tampered")
    if content_destroyed:
        # ADR-0099. A pre-existing file was reduced to nothing without being deleted — still
        # present, still tracked, holding nothing. Measured live 2026-08-10: with no delete
        # tool and no git tool, the producer emptied four tracked build artefacts to simulate
        # removing them, and NO control examined it.
        #
        # A PROHIBITION, not a criterion — which is why it arrives as a flag and not as a
        # failed claim. Nobody asks for "do not empty this file"; the run must simply never do
        # it. Routing it through the claims channel was the first design and it could not
        # work: the class-derived reasons only emit when a failed claim ID exists, and an
        # undeclared harm has no ID by construction.
        #
        # Downgrade-only, by the same construction as `tests_tampered` and `critic_vetoed`:
        # `_resolve` is a POSITIVE allowlist whose non-park branches require
        # `core == ["reviewer_unknown"]` or `set(reasons) == {"reviewer_requested_changes"}`,
        # so appending here can only ever turn a ship into a park, never the reverse.
        reasons.append("content_destroyed")
    if reviewer_verdict == "REQUEST_CHANGES":
        reasons.append("reviewer_requested_changes")
    elif reviewer_verdict == "BLOCK":
        reasons.append("reviewer_blocked")
    elif reviewer_verdict == "CONFLICT":
        # Not silence: the reviewer may well have objected, and we cannot tell. Distinct
        # reason so it can never satisfy the `core == ["reviewer_unknown"]` backstop.
        reasons.append("reviewer_conflict")
    elif reviewer_verdict != "APPROVE":
        reasons.append("reviewer_unknown")
    if findings_count > 0:
        reasons.append("security_findings")
    if security_status == "unavailable":
        # Deny-by-default security (ADR-0076), mirroring validation_unavailable: a scan was
        # EXPECTED this run but produced NO verdict — no scan sandbox, or a missing/crashed
        # scanner. "We did not check" is never "clean". A distinct reason so it can NEVER
        # satisfy the reviewer-silence backstop (core != ["reviewer_unknown"]) and parks in
        # every mode. Findings (count > 0) still park via security_findings — this only ever
        # ADDS a deny; "clean" passes through untouched, and so does "disabled" — see below.
        # ...SPLIT on whether it ran at all (ADR-0107): `scan_node` is the sole writer, so an
        # absent key proves it never ran. Deny-preserving: a message, not a permission.
        reasons.append("security_unverified" if scan_attempted else "security_not_attempted")
    elif security_status != "disabled" and not scan_fresh:
        # ADR-0108: scanned a tree that no longer exists — nothing clears the channel on a
        # re-plan, so a give-up after a post-scan write SHIPPED iteration 1's verdict. "disabled"
        # is EXCLUDED: no verdict to be stale, and the bench disables scanning on every run.
        reasons.append("security_stale")
    if reviewer_verdict == "APPROVE" and not review_fresh:
        reasons.append("reviewer_stale")  # same rule for the independence leg
    if tests_passed is True and strength == "suite" and not oracle_verified:
        # A real test suite ran and was GREEN, but it was not INDEPENDENT — no tester oracle, no
        # pre-existing baselined suite the coder can't weaken, and no operator --test-cmd (that
        # OR is computed in gate_node). Autonomous must not silence-ship OR APPROVE-ship on the
        # coder's OWN suite — the ADR-0034 residual, oracle-make-real Phase 3. A distinct reason:
        # it disqualifies BOTH autonomous approve paths in _resolve (core != ["reviewer_unknown"],
        # and reasons != []) → park; informational in guided. Only fires on strength "suite" +
        # green, so testless/shallow projects (never "suite") are untouched, and it can never be
        # the coder's to "fix" by writing more of its own tests. An already-satisfied run (#44)
        # has a green-pre-impl authored suite → oracle_verified stays False → this fires → the run
        # PARKS with an honest reason (see _termination_reason); it never auto-delivers.
        reasons.append("oracle_unverified")
    if critic_vetoed:
        # The held-out critic (#60, ADR-0065) judged the DELIVERED OUTCOME against the spec and
        # found a specific unmet requirement: the executed-but-unasserted class the deterministic
        # oracle structurally can't catch (MCB-05/09). Veto-only + downgrade-only by construction:
        # this reason is neither `reviewer_unknown` nor `reviewer_requested_changes`, so in _resolve
        # it makes `core != ["reviewer_unknown"]` AND `reasons != []` => PARK in every mode
        # (autonomous and on a reviewer APPROVE alike). It only ever flips a ship to a park, never
        # the reverse — the critic adds no approve branch and never rides on an otherwise-deny path.
        reasons.append("critic_vetoed")
    if claims_failed:
        # Per-claim evidence (ADR-0079 Wave 2, split by ADR-0092): core evaluated a BOUND
        # acceptance claim's oracle and it FAILED. The gate never evaluates predicates itself (it
        # stays pure; core reduces the verdict rows AND classifies them) and only ever consumes
        # evaluated FAILURES — an unbound or unevaluable claim adds nothing here (owner decision
        # 2026-08-03: unbound claims are intake's job).
        #
        # ONE reason PER EVIDENCE CLASS, not per claim: the ids still ride `unsatisfied_claims`,
        # so the reason count stays bounded at three and the stall breaker (which now fingerprints
        # CLASSES) is unaffected by how many claims failed. ADR-0079's "one stable string" is
        # narrowed, not abandoned — it is stable per class.
        #
        # Downgrade-only by the same construction as critic_vetoed, and this is the load-bearing
        # property of the whole split: `_resolve` is a POSITIVE allowlist whose only non-park
        # branches require `core == ["reviewer_unknown"]` or `set(reasons) == {"reviewer_requested
        # _changes"}`. Emitting k>=1 reasons exactly where the old code emitted 1 leaves
        # `bool(reasons)` invariant and can only GROW the list, so every ship predicate is
        # pointwise unchanged. This splits a MESSAGE, never a permission (a33e86e's argument,
        # audited and pinned by test_gate.py's monotonicity sweep).
        #
        # Position matters: this stays the LAST content-bearing append, before iteration_limit.
        # `core == ["reviewer_unknown"]` is a LIST equality, so reordering would weaken the proof.
        for cls, reason in _CLASS_REASON:
            if cls in set(claims_failed_classes or ()):
                reasons.append(reason)
        if not claims_failed_classes:
            # A caller that supplies ids but no classes (an older core, a hand-built payload) gets
            # the legacy UNION, which is exactly what it means: a claim failed and we cannot say
            # which kind. Classified `objection`, so it is the LEAST admissible answer — the first
            # draft of this fell back to `claim_behavioral_failed`, a `shortfall`, i.e. the most
            # permissive class. Deny-by-default has to be the fallback or it is not a default.
            reasons.append(UNCLASSIFIED_CLAIM_REASON)
    if reasons and iteration >= max_iterations:
        reasons.append("iteration_limit")

    resolution = _resolve(reasons, tests_passed, strength)
    if autonomous:
        action: GateAction = (
            "deliver"
            if resolution == "approve"
            else "revise"
            if resolution == "deny_with_feedback"
            else "require_human"
        )
    else:
        # A human never gets "revise" — denying at the gate is their revise.
        action = "deliver" if not reasons else "require_human"

    return GateDecision(
        action=action,
        reasons=reasons,
        tests_passed=tests_passed,
        reviewer_verdict=reviewer_verdict,
        autonomous=autonomous,
        # Can never claim verification unless the oracle actually passed this run.
        oracle_verified=bool(oracle_verified) and tests_passed is True,
        validation_strength=strength,
        unsatisfied_claims=list(claims_failed or []),
    )


def autonomous_resolution(decision: GateDecision | Mapping[str, Any]) -> AutonomousResolution:
    """How autonomous mode must resolve the gate. Pure over the decision, so it
    works on the serialized dict carried by the interrupt payload.

    Reviewer-as-veto backstop (ADR-0029 → ADR-0031 → narrowed by ADR-0034): the reviewer's
    SILENCE (``reviewer_unknown``, its only blocking reason) does not park an AUTONOMOUS
    run when the run's own DETERMINISTIC validation is green AND that validation actually
    executed something worth trusting. A local reviewer that emits no parseable verdict
    (~75% of correct MCB-21 runs) then delivers on positive executed evidence instead of
    false-parking on the ABSENCE of an LLM sign-off.

    ADR-0031 dropped ADR-0029's requirement that the INDEPENDENT tester oracle
    (``oracle_verified``) be present — the tester is off by default, so requiring it parked
    most correct runs. But it left ``tests_passed is True`` as the whole bar, and that is
    not the same claim for every project: for a testless repo the plan is ``compileall``,
    so "green" meant "it parses". **ADR-0034** therefore also requires
    ``validation_strength == "suite"`` — a real test suite ran. Silence may only ever be
    overridden by evidence, never by a syntax check, and never by ``deliver_unverified``
    (which coerces ``tests_passed`` to True with no validator at all → strength "none").

    A real objection (``reviewer_blocked`` / ``reviewer_requested_changes``) vetoes, as
    does a CONFLICTING verdict (``reviewer_conflict`` — we cannot tell what the reviewer
    said, so a human does). Autonomous-only by construction — human-gated runs never call
    this. See docs/threat-models/TM-0001.
    """
    if isinstance(decision, GateDecision):
        reasons = list(decision.reasons)
        tests_passed = decision.tests_passed
        strength = decision.validation_strength
    else:
        raw = decision.get("reasons")
        if not isinstance(raw, list):
            return "park"  # malformed/absent reasons never approve (deny-by-default)
        reasons = [str(r) for r in raw]
        tests_passed = decision.get("tests_passed")
        # An older/absent payload has no strength → "unknown" → not "suite" → never ships
        # on silence. Deny-by-default, same posture as the malformed-reasons guard above.
        strength = str(decision.get("validation_strength") or "unknown")
    return _resolve(reasons, tests_passed, strength)
