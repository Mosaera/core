"""Decision-table tests for the delivery-gate policy.

The parametrized table below is the normative spec: every combination of
validation result x reviewer verdict x findings, in human and autonomous
modes, below and at the iteration cap.
"""

from __future__ import annotations

import pytest
from mosaera_policies import GateDecision, autonomous_resolution, evaluate_gate

# (tests_passed, verdict, findings_count) -> (reasons, human_action, autonomous_resolution)
TABLE = [
    (True, "APPROVE", 0, [], "deliver", "approve"),
    (True, "APPROVE", 2, ["security_findings"], "require_human", "park"),
    (
        True,
        "REQUEST_CHANGES",
        0,
        ["reviewer_requested_changes"],
        "require_human",
        "deny_with_feedback",
    ),
    (
        True,
        "REQUEST_CHANGES",
        1,
        ["reviewer_requested_changes", "security_findings"],
        "require_human",
        "park",
    ),
    (True, "BLOCK", 0, ["reviewer_blocked"], "require_human", "park"),
    (True, "BLOCK", 1, ["reviewer_blocked", "security_findings"], "require_human", "park"),
    # NB: (True, "UNKNOWN", 0) — reviewer SILENCE with passing validation — is the ADR-0031
    # backstop case: autonomous APPROVES (not park), which breaks this table's uniform
    # "non-empty reasons → park" shape. It is covered by the dedicated backstop tests below.
    (True, "UNKNOWN", 1, ["reviewer_unknown", "security_findings"], "require_human", "park"),
    (False, "APPROVE", 0, ["validation_failed"], "require_human", "park"),
    (False, "APPROVE", 1, ["validation_failed", "security_findings"], "require_human", "park"),
    (
        False,
        "REQUEST_CHANGES",
        0,
        ["validation_failed", "reviewer_requested_changes"],
        "require_human",
        "park",
    ),
    (
        False,
        "REQUEST_CHANGES",
        1,
        ["validation_failed", "reviewer_requested_changes", "security_findings"],
        "require_human",
        "park",
    ),
    (False, "BLOCK", 0, ["validation_failed", "reviewer_blocked"], "require_human", "park"),
    (
        False,
        "BLOCK",
        1,
        ["validation_failed", "reviewer_blocked", "security_findings"],
        "require_human",
        "park",
    ),
    (False, "UNKNOWN", 0, ["validation_failed", "reviewer_unknown"], "require_human", "park"),
    (
        False,
        "UNKNOWN",
        1,
        ["validation_failed", "reviewer_unknown", "security_findings"],
        "require_human",
        "park",
    ),
    (None, "APPROVE", 0, ["validation_unavailable"], "require_human", "park"),
    (None, "APPROVE", 1, ["validation_unavailable", "security_findings"], "require_human", "park"),
    (
        None,
        "REQUEST_CHANGES",
        0,
        ["validation_unavailable", "reviewer_requested_changes"],
        "require_human",
        "park",
    ),
    (
        None,
        "REQUEST_CHANGES",
        1,
        ["validation_unavailable", "reviewer_requested_changes", "security_findings"],
        "require_human",
        "park",
    ),
    (None, "BLOCK", 0, ["validation_unavailable", "reviewer_blocked"], "require_human", "park"),
    (
        None,
        "BLOCK",
        1,
        ["validation_unavailable", "reviewer_blocked", "security_findings"],
        "require_human",
        "park",
    ),
    (None, "UNKNOWN", 0, ["validation_unavailable", "reviewer_unknown"], "require_human", "park"),
    (
        None,
        "UNKNOWN",
        1,
        ["validation_unavailable", "reviewer_unknown", "security_findings"],
        "require_human",
        "park",
    ),
]


@pytest.mark.parametrize(
    ("tests_passed", "verdict", "findings", "reasons", "human_action", "auto"), TABLE
)
def test_decision_table_below_cap(
    tests_passed: bool | None,
    verdict: str,
    findings: int,
    reasons: list[str],
    human_action: str,
    auto: str,
) -> None:
    human = evaluate_gate(
        tests_passed=tests_passed,
        reviewer_verdict=verdict,
        findings_count=findings,
        iteration=1,
        max_iterations=3,
        autonomous=False,
    )
    assert human.reasons == reasons  # fixed derivation order
    assert human.action == human_action
    assert autonomous_resolution(human) == auto

    autonomous = evaluate_gate(
        tests_passed=tests_passed,
        reviewer_verdict=verdict,
        findings_count=findings,
        iteration=1,
        max_iterations=3,
        autonomous=True,
    )
    expected_action = {
        "approve": "deliver",
        "deny_with_feedback": "revise",
        "park": "require_human",
    }[auto]
    assert autonomous.action == expected_action


@pytest.mark.parametrize(("tests_passed", "verdict", "findings", "reasons", "_h", "auto"), TABLE)
def test_decision_table_at_cap(
    tests_passed: bool | None,
    verdict: str,
    findings: int,
    reasons: list[str],
    _h: str,
    auto: str,
) -> None:
    d = evaluate_gate(
        tests_passed=tests_passed,
        reviewer_verdict=verdict,
        findings_count=findings,
        iteration=3,
        max_iterations=3,
        autonomous=True,
    )
    if not reasons:
        # All-clear at the cap still delivers — same as today.
        assert d.reasons == [] and autonomous_resolution(d) == "approve"
    else:
        assert d.reasons == [*reasons, "iteration_limit"]
        # The bounded deny-loop: REQUEST_CHANGES-only becomes park at the cap.
        assert autonomous_resolution(d) == "park"


def test_resolution_accepts_serialized_payload_dict() -> None:
    d = evaluate_gate(
        tests_passed=False,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=1,
        max_iterations=3,
    )
    assert autonomous_resolution(d.as_dict()) == "park"
    assert autonomous_resolution({"reasons": []}) == "approve"
    assert (
        autonomous_resolution({"reasons": ["reviewer_requested_changes"]}) == "deny_with_feedback"
    )
    # Malformed payloads never approve (deny-by-default).
    assert autonomous_resolution({"reasons": "garbage"}) == "park"
    assert autonomous_resolution({}) == "park"


def test_as_dict_round_trip() -> None:
    d = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="REQUEST_CHANGES",
        findings_count=0,
        iteration=2,
        max_iterations=3,
        autonomous=True,
    )
    raw = d.as_dict()
    assert raw == {
        "action": "revise",
        "reasons": ["reviewer_requested_changes"],
        "tests_passed": True,
        "reviewer_verdict": "REQUEST_CHANGES",
        "autonomous": True,
        "oracle_verified": False,
        # No plan was passed → deny-by-default strength (never "suite", so never ships
        # on reviewer silence). ADR-0034.
        "validation_strength": "unknown",
        # ADR-0079 Wave 2 (owner-accepted 2026-08-03): the per-claim field. Extending this
        # exact-shape lock IS the deliberate act the lock exists to force.
        "unsatisfied_claims": [],
    }
    assert isinstance(GateDecision(**raw), GateDecision)


# --- ADR-0029: reviewer-as-veto + oracle-approve backstop ----------------------


def _gate(
    verdict: str,
    *,
    tests_passed: bool | None = True,
    findings: int = 0,
    oracle: bool = True,
    strength: str = "suite",
    unverified: bool = False,
    security_status: str = "clean",
    claims_failed: list[str] | None = None,
):
    return evaluate_gate(
        tests_passed=tests_passed,
        reviewer_verdict=verdict,
        findings_count=findings,
        iteration=1,
        max_iterations=3,
        oracle_verified=oracle,
        validation_strength=strength,
        validation_unverified=unverified,
        security_status=security_status,
        claims_failed=claims_failed,
    )


def test_backstop_delivers_on_reviewer_silence_when_oracle_verified() -> None:
    # The core case: reviewer emits no verdict, but the tester's acceptance suite passed
    # and the scan is clean → an autonomous run DELIVERS instead of false-parking.
    d = _gate("UNKNOWN")
    assert d.reasons == ["reviewer_unknown"]  # reasons unchanged (human still parks)
    assert d.oracle_verified is True
    assert autonomous_resolution(d) == "approve"
    assert autonomous_resolution(d.as_dict()) == "approve"  # serialized payload too


def test_backstop_is_autonomous_only_human_still_parks() -> None:
    # Human-gated action is unchanged — a person still decides on reviewer silence.
    d = _gate("UNKNOWN")
    assert d.action == "require_human"


def test_backstop_does_not_override_a_real_objection() -> None:
    # A veto is a veto — BLOCK / REQUEST_CHANGES resolve normally even with the oracle green.
    assert autonomous_resolution(_gate("BLOCK")) == "park"
    assert autonomous_resolution(_gate("REQUEST_CHANGES")) == "deny_with_feedback"


def test_backstop_requires_a_clean_scan() -> None:
    # Security findings block regardless of reviewer silence + oracle.
    assert autonomous_resolution(_gate("UNKNOWN", findings=1)) == "park"


def test_backstop_never_rescues_failing_or_absent_validation() -> None:
    # Reviewer silence delivers ONLY on POSITIVE validation. A failing/absent result keeps
    # validation_failed / validation_unavailable in `core`, so silence still parks — the
    # backstop can never ship un-validated code (ADR-0031 rests delivery on executed evidence).
    d = _gate("UNKNOWN", tests_passed=False)
    assert d.oracle_verified is False
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(_gate("UNKNOWN", tests_passed=None)) == "park"


def test_backstop_parks_on_silence_without_an_independent_oracle() -> None:
    # oracle-make-real Phase 3 RE-TIGHTENS ADR-0031: reviewer SILENCE + a green SUITE that is the
    # coder's OWN (oracle_verified False) must NOT ship autonomously. A distinct `oracle_unverified`
    # reason fires (strength "suite" + not oracle_verified), disqualifying the silence backstop.
    # Supersedes the old "ships on silence without the tester oracle" — that WAS the false-ship.
    d = _gate("UNKNOWN", oracle=False)
    assert "oracle_unverified" in d.reasons
    assert autonomous_resolution(d) == "park"
    # It fires on the reviewer-APPROVE path too — the coder's own suite can't ship on APPROVE alone.
    assert autonomous_resolution(_gate("APPROVE", oracle=False)) == "park"
    # A testless / shallow project (never strength "suite") is untouched — no oracle_unverified.
    assert "oracle_unverified" not in _gate("APPROVE", oracle=False, strength="shallow").reasons
    # At the cap it still parks — the extra reasons ride along.
    at_cap = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="UNKNOWN",
        findings_count=0,
        iteration=3,
        max_iterations=3,
        oracle_verified=False,
        validation_strength="suite",
    )
    assert at_cap.reasons == ["reviewer_unknown", "oracle_unverified", "iteration_limit"]
    assert autonomous_resolution(at_cap) == "park"


def test_independent_oracle_ships_on_silence() -> None:
    # The positive side: WITH an independent oracle (oracle_verified True — a tester suite, a
    # pre-existing baselined suite, or an operator --test-cmd), reviewer silence still DELIVERS.
    assert "oracle_unverified" not in _gate("UNKNOWN", oracle=True).reasons
    assert autonomous_resolution(_gate("UNKNOWN", oracle=True)) == "approve"


def test_backstop_survives_the_iteration_cap() -> None:
    # reviewer_unknown is still the sole blocker at the cap (iteration_limit rides along).
    d = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="UNKNOWN",
        findings_count=0,
        iteration=3,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
    )
    assert d.reasons == ["reviewer_unknown", "iteration_limit"]
    assert autonomous_resolution(d) == "approve"


# --- ADR-0034: silence may only be overridden by EXECUTED evidence -------------------


def test_backstop_never_delivers_on_shallow_validation() -> None:
    # THE hole ADR-0034 closes. `tests_passed is True` is not one claim: on a testless repo
    # the plan is `compileall`, so green means "it parses". Reviewer silence + a syntax check
    # is no evidence at all — park for a human. (A reviewer APPROVE still delivers: that is a
    # judgement, and reasons would be empty.)
    d = _gate("UNKNOWN", strength="shallow")
    assert d.reasons == ["reviewer_unknown"]
    assert d.validation_strength == "shallow"
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(d.as_dict()) == "park"  # serialized payload too
    assert autonomous_resolution(_gate("APPROVE", strength="shallow")) == "approve"


def test_backstop_never_delivers_on_unknown_strength() -> None:
    # Deny-by-default: no plan reached the gate (or a LanguagePack forgot to declare) →
    # "unknown" is not "suite" → silence parks. A pack that forgets fails SAFE.
    assert autonomous_resolution(_gate("UNKNOWN", strength="unknown")) == "park"


def test_already_satisfied_green_pre_impl_suite_still_parks() -> None:
    # #44 (ADR-0052 redesign): an already-satisfied run has a green-PRE-IMPL authored suite, so it
    # is NOT an independent oracle (oracle_verified False) → oracle_unverified fires → PARK. The
    # gate has no already-satisfied exemption; the honest early-conclude lives outside the policy
    # (the run parks with an accurate reason, never an unattended auto-deliver on unconfirmed work).
    d = _gate("UNKNOWN", oracle=False)
    assert "oracle_unverified" in d.reasons
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(_gate("APPROVE", oracle=False)) == "park"


def test_backstop_never_delivers_when_validation_is_unverified() -> None:
    # `deliver_unverified` coerces tests_passed None→True UPSTREAM of the gate, so the gate
    # sees a True that stands for zero executed validation. Before ADR-0034 that composed with
    # reviewer silence into an autonomous ship with NO evidence of any kind. Now the flag
    # forces strength="none" and silence parks — while a reviewer APPROVE still delivers,
    # which is exactly what the flag's own contract always promised ("the reviewer still
    # gates acceptance").
    d = _gate("UNKNOWN", unverified=True)
    assert d.validation_strength == "none"
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(_gate("APPROVE", unverified=True)) == "approve"


def test_a_conflicting_verdict_is_not_silence_and_never_ships() -> None:
    # Verdict-conflict poisoning: a genuine REQUEST_CHANGES alongside an echoed/injected
    # "VERDICT: APPROVE" (from repo content, the coder's diff, or quoted test output) used to
    # parse to UNKNOWN — i.e. SILENCE — and then ride the backstop straight to delivery,
    # laundering a real veto into a ship. A conflict is now its own blocking reason: we cannot
    # tell what the reviewer said, so a human decides. Even with a perfect suite.
    d = _gate("CONFLICT")
    assert d.reasons == ["reviewer_conflict"]  # NOT reviewer_unknown
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(d.as_dict()) == "park"
    assert d.action == "require_human"


# --- ADR-0036: test-tampering is a first-class blocker autonomous mode can't ship past -----


def test_tampering_parks_even_with_a_perfect_suite_and_approval() -> None:
    # The coder weakened a pre-existing test to go green (tests_tampered). Even with a real
    # suite that "passed" AND a reviewer APPROVE, this must never auto-deliver — a green suite
    # obtained by weakening it is not evidence. It is a distinct reason, so a human decides.
    d = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=1,
        max_iterations=3,
        validation_strength="suite",
        tests_tampered=True,
    )
    assert "tests_tampered" in d.reasons
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(d.as_dict()) == "park"
    assert d.action == "require_human"


def test_tampering_never_rides_the_silence_backstop() -> None:
    # A silent reviewer + a tamper: core is not ["reviewer_unknown"] alone, so the ADR-0034
    # backstop can't fire — the tamper reason rides alongside and forces a park.
    d = evaluate_gate(
        tests_passed=False,  # the tamper branch also sets tests_passed False
        reviewer_verdict="UNKNOWN",
        findings_count=0,
        iteration=1,
        max_iterations=3,
        validation_strength="suite",
        tests_tampered=True,
    )
    assert "tests_tampered" in d.reasons
    assert autonomous_resolution(d) == "park"


def test_evaluate_gate_action_and_autonomous_resolution_cannot_disagree() -> None:
    # Both surfaces route through the one policy function. They drifted before: ADR-0031
    # taught only the runner about the backstop, so evaluate_gate(autonomous=True).action
    # said "require_human" for a case autonomous_resolution shipped.
    for strength in ("suite", "shallow", "none", "unknown"):
        for verdict in ("APPROVE", "REQUEST_CHANGES", "BLOCK", "CONFLICT", "UNKNOWN"):
            d = evaluate_gate(
                tests_passed=True,
                reviewer_verdict=verdict,
                findings_count=0,
                iteration=1,
                max_iterations=3,
                autonomous=True,
                validation_strength=strength,
            )
            expected = {
                "approve": "deliver",
                "deny_with_feedback": "revise",
                "park": "require_human",
            }[autonomous_resolution(d)]
            assert d.action == expected, f"{verdict}/{strength}: {d.action} != {expected}"


# --- #60 (ADR-0065): the held-out critic's veto — a universal, downgrade-only park ----------


def _gate_critic(verdict: str, *, vetoed: bool):
    # A run that would otherwise SHIP: green suite, independent oracle, clean scan. The only
    # variable is the critic's veto — so any change in outcome is attributable to it alone.
    return evaluate_gate(
        tests_passed=True,
        reviewer_verdict=verdict,
        findings_count=0,
        iteration=1,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
        critic_vetoed=vetoed,
    )


def test_critic_veto_parks_even_on_reviewer_approve() -> None:
    # THE case #60 exists for: a run the reviewer APPROVED and the oracle vouched (the
    # executed-but-unasserted false-ship, MCB-05/09) parks when the held-out critic vetoes. The
    # veto is a UNIVERSAL downgrade — it fires on the reviewer-APPROVE path, not just on silence.
    assert autonomous_resolution(_gate_critic("APPROVE", vetoed=False)) == "approve"  # would ship
    vetoed = _gate_critic("APPROVE", vetoed=True)
    assert "critic_vetoed" in vetoed.reasons
    assert vetoed.action == "require_human"  # human mode parks
    assert autonomous_resolution(vetoed) == "park"  # autonomous parks
    assert autonomous_resolution(vetoed.as_dict()) == "park"  # serialized payload parks too


def test_critic_veto_defeats_the_reviewer_silence_backstop() -> None:
    # Silence + a green oracle would ride the ADR-0031 backstop to a ship; a veto makes
    # core != ["reviewer_unknown"], so the backstop can't fire → park.
    vetoed = _gate_critic("UNKNOWN", vetoed=True)
    assert vetoed.reasons == ["reviewer_unknown", "critic_vetoed"]
    assert autonomous_resolution(vetoed) == "park"


def test_critic_is_downgrade_only_and_never_creates_a_ship() -> None:
    # With no veto the decision is byte-identical to the pre-critic gate — the critic adds NO
    # approve branch, so it can never create OR rescue a delivery.
    assert _gate_critic("APPROVE", vetoed=False).as_dict() == _gate("APPROVE").as_dict()
    # And a veto can never flip a would-be PARK into a ship: a failing run stays parked even
    # though `critic_vetoed` is, structurally, only ever an ADDED reason (monotonic).
    failing = evaluate_gate(
        tests_passed=False,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=1,
        max_iterations=3,
        critic_vetoed=True,
    )
    assert autonomous_resolution(failing) == "park"


def test_critic_veto_rides_the_iteration_cap() -> None:
    # At the cap the veto still parks (iteration_limit rides along, never rescues).
    d = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=3,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
        critic_vetoed=True,
    )
    assert d.reasons == ["critic_vetoed", "iteration_limit"]
    assert autonomous_resolution(d) == "park"


# --- Security evidence deny-by-default (ADR-0076): the security_status tri-state. ---


def test_security_unverified_parks_over_approve_and_green_oracle() -> None:
    # Everything else says ship (APPROVE, tests pass, independent oracle green), but the scan
    # could not run → the run parks on security_unverified. "We did not look" is not "clean".
    d = _gate("APPROVE", security_status="unavailable")
    assert d.reasons == ["security_unverified"]
    assert d.action == "require_human"
    assert autonomous_resolution(d) == "park"


def test_security_unverified_defeats_the_reviewer_silence_backstop() -> None:
    # Reviewer silence + green oracle would DELIVER (the backstop). An unverified scan blocks
    # it: a distinct reason makes core != ["reviewer_unknown"].
    assert autonomous_resolution(_gate("UNKNOWN")) == "approve"  # baseline: backstop ships
    blocked = _gate("UNKNOWN", security_status="unavailable")
    assert blocked.reasons == ["reviewer_unknown", "security_unverified"]
    assert autonomous_resolution(blocked) == "park"


def test_clean_findings_disabled_add_no_security_unverified() -> None:
    for status in ("clean", "findings", "disabled"):
        assert "security_unverified" not in _gate("APPROVE", security_status=status).reasons
    # a real finding still parks — via security_findings, not the unverified reason
    d = _gate("APPROVE", findings=1, security_status="findings")
    assert d.reasons == ["security_findings"]
    assert autonomous_resolution(d) == "park"


def test_security_findings_precede_security_unverified() -> None:
    # Both can fire (findings parsed AND another scanner gave no verdict): fixed order.
    d = _gate("APPROVE", findings=2, security_status="unavailable")
    assert d.reasons == ["security_findings", "security_unverified"]


def test_security_unverified_rides_the_iteration_cap() -> None:
    d = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=3,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
        security_status="unavailable",
    )
    assert d.reasons == ["security_unverified", "iteration_limit"]
    assert autonomous_resolution(d) == "park"


def test_security_status_clean_is_byte_identical_to_omitting_it() -> None:
    # Monotonicity guard: the "clean" default leaves every existing caller/table row unchanged.
    without = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=1,
        max_iterations=3,
        autonomous=True,
    )
    with_clean = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=1,
        max_iterations=3,
        autonomous=True,
        security_status="clean",
    )
    assert without.as_dict() == with_clean.as_dict()


# --- ADR-0079 Wave 2: per-claim evidence (owner-accepted 2026-08-03) -----------


def test_unsatisfied_claim_parks_in_every_mode() -> None:
    # Downgrade-only, the critic_vetoed construction: an otherwise-shippable run (green,
    # APPROVE, independent oracle) parks when a bound claim's oracle evaluated and failed.
    d = _gate("APPROVE", claims_failed=["7-c2"])
    assert d.action == "require_human"
    assert d.reasons == ["unsatisfied_claim"]
    assert d.unsatisfied_claims == ["7-c2"]
    assert autonomous_resolution(d) == "park"
    assert autonomous_resolution(d.as_dict()) == "park"  # the serialized-payload path too


def test_unsatisfied_claim_reason_is_stable_and_id_free() -> None:
    # The gate-stall breaker fingerprints sorted(set(reasons)) — many failing claims, ONE
    # stable reason string; the ids ride the field, never the reason.
    d = _gate("APPROVE", claims_failed=["1-c1", "1-c2", "1-c3"])
    assert d.reasons.count("unsatisfied_claim") == 1
    assert d.unsatisfied_claims == ["1-c1", "1-c2", "1-c3"]


def test_no_failed_claims_changes_nothing() -> None:
    # Defaulted-off: None and [] are both byte-identical to the pre-claims gate.
    for claims_failed in (None, list[str]()):
        d = _gate("APPROVE", claims_failed=claims_failed)
        assert d.action == "deliver" and d.reasons == [] and d.unsatisfied_claims == []


def test_unsatisfied_claim_orders_after_critic_before_iteration_limit() -> None:
    # The order-lock (the security_findings/security_unverified precedent): the new reason
    # slots after critic_vetoed and iteration_limit stays last.
    d = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=3,
        max_iterations=3,
        oracle_verified=True,
        validation_strength="suite",
        critic_vetoed=True,
        claims_failed=["1-c1"],
    )
    assert d.reasons == ["critic_vetoed", "unsatisfied_claim", "iteration_limit"]


def test_unsatisfied_claim_never_rescues_a_failing_run() -> None:
    # Never flips a deny to a ship: a failing run with a failed claim parks with BOTH reasons.
    d = _gate("APPROVE", tests_passed=False, claims_failed=["1-c1"])
    assert "validation_failed" in d.reasons and "unsatisfied_claim" in d.reasons
    assert autonomous_resolution(d) == "park"


def test_unsatisfied_claim_cannot_ride_the_silence_backstop() -> None:
    # core != ["reviewer_unknown"] whenever a claim failed → the backstop never ships it.
    d = _gate("", claims_failed=["1-c1"])  # reviewer silent + failed claim
    assert autonomous_resolution(d) == "park"


# --- "we never validated" is not "there is no validator" (F39 / issue #71) ---------------------
#
# `tests_passed is None` had TWO causes that demand opposite responses. On 2026-08-07 an operator
# read `validation_unavailable`, concluded the sandbox was broken, and spent an hour on Docker —
# while the truth was that the planner gave up and the run never reached `test_node` at all.


def _gate_attempted(attempted: bool, *, verdict: str = "APPROVE", tampered: bool = False):
    return evaluate_gate(
        tests_passed=None,
        reviewer_verdict=verdict,
        findings_count=0,
        iteration=1,
        max_iterations=8,
        autonomous=True,
        oracle_verified=True,
        validation_strength="suite",
        validation_attempted=attempted,
        tests_tampered=tampered,
    )


def test_never_attempted_is_a_distinct_reason() -> None:
    d = _gate_attempted(False)
    assert "validation_not_attempted" in d.reasons
    assert "validation_unavailable" not in d.reasons


def test_a_real_validator_that_could_not_decide_still_says_unavailable() -> None:
    """The other half: a run that DID reach validation and got no verdict keeps today's reason.
    The two must not collapse in either direction."""
    d = _gate_attempted(True)
    assert "validation_unavailable" in d.reasons
    assert "validation_not_attempted" not in d.reasons


def test_the_default_is_todays_behaviour() -> None:
    """Every existing caller omits the new argument and must be byte-identical."""
    d = evaluate_gate(
        tests_passed=None,
        reviewer_verdict="APPROVE",
        findings_count=0,
        iteration=1,
        max_iterations=8,
    )
    assert "validation_unavailable" in d.reasons


def test_the_new_reason_can_never_permit_what_the_old_one_blocked() -> None:
    """THE trust-boundary property. `_resolve` is a positive allowlist, so a new reason can only
    ever park — but that is a property of the current implementation, and this pins it as a
    contract. This change splits a MESSAGE; it must never split a PERMISSION."""
    for verdict in ("APPROVE", "UNKNOWN", "REQUEST_CHANGES", "BLOCK"):
        for tampered in (False, True):
            old = _gate_attempted(True, verdict=verdict, tampered=tampered)
            new = _gate_attempted(False, verdict=verdict, tampered=tampered)
            assert new.action == old.action
            assert autonomous_resolution(new) == autonomous_resolution(old) == "park"
