"""WHO gets an independent verification attempt — Layer-2's eligibility predicates.

Split out of `disposition.py` on 2026-08-09, at exactly the 500-line ceiling. The boundary is
genuine and worth naming: this module decides **who is checked**; `disposition.py` **performs the
check**. Confusing the two is how eligibility quietly became a safety control nobody was measuring.

Eligibility is NOT the ship gate — `close_oracle_gap`'s green + mutation steps are. But it is not
inert either: it is what keeps a security-objected or critic-vetoed park from ever reaching an
automated ship. So widening it is a trust-boundary decision, and every widening here is
knob-gated, default OFF, and carries the measurement that justified it.

Measured 2026-08-09 over 193 runs: 74 honest parks, 13 eligible (18%). Of the 61 turned away, 41
were work the hidden grader PASSED. Eligibility — not the mutation oracle — is what makes Layer 2
almost unreachable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from mosaera_policies.gate import ReasonClass, reasons_of_class

from mosaera_core.progress import parse_failing_tests
from mosaera_core.testintegrity import is_collection_control, is_test_file

# --- the convertible class (shared by the API sweep rung + the bench measurement) --------------
# A park's blocking reasons minus these are the "core" objection: `iteration_limit` rides along on
# any non-empty reasons, `reviewer_unknown` is silence — neither disqualifies the convertible class.
_BENIGN_REASONS = frozenset({"iteration_limit", "reviewer_unknown"})
# Out-of-band honest-stop / hand-raise channels: a run's REAL stop reason lives here, NOT in
# `gate_decision.reasons` (`_termination_reason` reads them with HIGHER priority). A thrash stop
# (`stalled`), an early plan/supervise give-up, or a coder hand-raise is a safety stop / the
# escalate arm — never the close-the-gap arm, even with an incidental green `oracle_unverified`.
_HONEST_STOP_CHANNELS = (
    "stalled",
    "give_up_reason",
    "plan_unworkable_reason",
    "blocked_reason",
    "escalate_reason",
)


# --- the structural-claim widening (knob-gated, default OFF) ------------------------------------
# MEASURED 2026-08-09, 193 runs. 17 parks were blocked by `claim_structural_failed` ALONE — no
# reviewer objection, no security finding, no critic veto, no failed/absent validation. The hidden
# grader passed 10 of them and failed 7.
#
# That 10/7 split is the entire reason this exists, and it is NOT a bid to convert the 10. Every
# other turned-away bucket is degenerate: reviewer objections were 8-for-8 on WRONG work (the
# control working), validation-failed/not-attempted cannot ship on principle, and
# `security_unverified` is never ALONE in a reason set — but see the correction below before
# reusing that fact. This bucket is the only MIXED one, and so the only one that puts genuinely
# wrong deliveries in front of the gate.
#
# CORRECTED 2026-08-09 (F84). The original note here said relaxing `security_unverified` "would
# unlock exactly zero runs". That was computed under CLASS-1 rules, where `validation_failed` is
# itself disqualifying. Under CLASS 2, `validation_failed` is a `shortfall` and ADMISSIBLE — that
# is class 2's entire premise — so for class 2 `security_unverified` IS the sole blocker, on 25
# parks. The reasoning was wrong; the DECISION below is unaffected, because this bucket was chosen
# for being the only mixed one, which the correction does not touch. The class-2 shortfall is
# F84's subject: a 17% scanner NO-VERDICT rate, not a security finding (zero of those in 193 runs).
#
# Why that matters: across those 193 runs every single eligible park was on work the grader PASSED.
# The WRONG column was EMPTY, so the gate's 12 refusals could not be scored as correct — there was
# nothing wrong to catch. Measured discrimination is currently UNDEFINED, not good. This admits 7
# known-wrong deliveries so the mutation gate can be shown to catch them, or shown not to.
#
# **This does not weaken the ship gate.** `close_oracle_gap`'s green + comprehensive-mutation steps
# are untouched; a park still stands unless they independently vouch for it. What widens is who is
# ATTEMPTED. But eligibility is not inert — it is what keeps a security-objected park away from an
# automated ship — so this stays knob-gated, default OFF, and bench-first.
#
# `REASON_CLASS` is deliberately NOT edited: `claim_structural_failed` remains an `objection`
# (ADR-0092). Reclassifying it would widen every consumer of that table at once. This is a narrow,
# named exception in ONE predicate, which is why it can be measured and reversed.
_STRUCTURAL_CLAIM_REASON = "claim_structural_failed"


def is_oracle_unverified_park(
    final: Mapping[str, Any], *, admit_structural_claim: bool = False
) -> bool:
    """Layer-2 convertible class 1: the run parked ONLY because its green suite was the
    coder's OWN (``oracle_unverified``) — no real objection AND no out-of-band honest-stop. Every
    other park (a failed/absent validator, tamper, a reviewer/security objection, a held-out critic
    veto, a thrash/plan/supervise stop, a coder hand-raise) is NOT convertible. Pure read of the
    run's final state; deny-by-default.

    ``admit_structural_claim`` (knob ``layer2_admit_structural_claim``, default OFF) additionally
    admits a park whose only other blocking reason is ``claim_structural_failed`` — the measurement
    widening documented above. EVERY other condition below still applies unchanged.
    """
    gate = final.get("gate_decision") or {}
    core = set(gate.get("reasons") or []) - _BENIGN_REASONS
    admissible = {"oracle_unverified"}
    if admit_structural_claim:
        admissible.add(_STRUCTURAL_CLAIM_REASON)
    # Non-empty AND a subset — an empty `core` is not a park this arm may touch, and the subset
    # test (not equality) is what lets a structural-claim-only park in when the knob is on.
    if not core or not core <= admissible:
        return False  # any other blocking reason ⇒ a real objection/safety stop, not convertible
    if final.get("tests_passed") is not True:
        return False  # the suite must have actually run green (belt-and-suspenders)
    if final.get("tests_modified"):
        return False  # any test edit ⇒ never launder a tamper into a ship
    verdict = final.get("outcome_verdict")
    if isinstance(verdict, dict) and verdict.get("vetoed"):
        return False  # the held-out critic found a real defect
    if any(final.get(k) for k in _HONEST_STOP_CHANNELS):
        return False  # a safety stop / human-judgement hand-raise — must NOT auto-ship in its place
    return True


# --- convertible class 2: the engine-blocked give-up (#76 widening, ADR-0075) -------------------
# The deep dive measured the dominant correct-code park: the run GAVE UP because the only failing
# tests were the ENGINE'S OWN authored/protected oracle (a wrong — sometimes unsatisfiable — test
# the coder may not edit). That is not a coder-capability stop; it is the engine trapped by its own
# work-product. Convertible ONLY under this evidence gate; every other give-up stays parked.
#
# Gate reasons a qualifying give-up park may carry: the engine tests failing (validation_failed),
# reviewer silence, the cap marker, and the no-independent-oracle reason. Anything else (tamper,
# security, a reviewer objection, a critic veto, validation_unavailable) ⇒ NOT convertible.
#
# DERIVED, never hand-written (ADR-0090). This used to be a literal frozenset here, and it went
# stale the moment a later feature minted a gate reason it had never heard of: `unsatisfied_claim`
# landed ten days after this set was written and silently narrowed BOTH arms to nothing on the
# dominant over-park shape, with every test green (#68, F62). The admission policy — *a shortfall
# or an incidental fact does not disqualify; an objection or a tamper does* — is stated once, and
# the membership follows from `REASON_CLASS`, which is total over `GateReason` and guarded by
# `test_gate_reason_classification.py`. A new reason cannot silently join or miss this set again.
_ADMISSIBLE_CLASSES: tuple[ReasonClass, ...] = ("shortfall", "incidental")


def give_up_allowed_reasons() -> frozenset[str]:
    """Gate reasons that do NOT disqualify a parked run from disposition (ADR-0090).

    Public because the ESCALATE arm needs the same membership and must not reach into this
    module's privates for it — a shared private constant is a second origin waiting for the two
    to disagree (the F71/F79 defect class).
    """
    return reasons_of_class(*_ADMISSIBLE_CLASSES)


_GIVE_UP_ALLOWED_REASONS = give_up_allowed_reasons()
# `give_up_reason` is ORIGIN-BLIND (red-team R1 F1): `supervise_node` sets it for the no-progress
# breaker, a coder BLOCKED/ESCALATE hand-raise (clearing `blocked_reason`/`escalate_reason` in the
# same return), OR the gate-loop breaker — and the predicate must convert ONLY the no-progress
# engine-test trap. The engine-CONTROLLED prefixes below (from nodes_plan/nodes_review, not model
# text) identify the non-convertible origins; a coder hand-raise also survives in `coder_escalated`.
_NON_NOPROGRESS_GIVEUP_PREFIXES = ("blocked:", "escalation unresolved:", "gate kept denying")


def effective_test_output(final: Mapping[str, Any]) -> str:
    """The validation output that describes this run's tree — the ENGINE's, else the coder's.

    One function because there are two parsers of it (``_failing_test_files`` here and
    ``blocking_test_ids`` in ``escalate_arm``), and a second copy of "which output counts?" is
    exactly the drift that makes a control and its operator surface disagree.

    ``test_output`` always wins: it is the engine's own validation and no producer chose its
    timing. The fallback exists because a coder HAND-RAISE routes ``implement → capture →
    supervise`` without ever passing through ``test``, so on that branch ``test_output`` can be
    absent and the escalation had no failing set to name — the offer was withheld on precisely the
    branch where the producer is saying a protected test blocks it (F70, #75, measured live twice).

    ``coder_test_output`` is already tree-hash-pinned at ``capture_node``; nothing here re-decides
    that, and nothing here may, since this must stay a pure function of state.
    """
    return str(final.get("test_output") or "") or str(final.get("coder_test_output") or "")


def _failing_test_files(final: Mapping[str, Any], output: str | None = None) -> set[str] | None:
    """The failing test FILES parsed from the terminal ``test_output`` (``failing_tests`` does not
    survive to final state). Returns ``None`` when nothing parseable (deny-by-default). Uncapped —
    the cap is a DISPLAY bound; the subset check must see EVERY failure or a coder-owned failure
    printed after 50 forged lines could hide (red-team R1 F2).

    ``output`` lets a caller name the source EXPLICITLY, and the default is deliberately the
    narrow one. #75 red team, FIX-NOW: routing `effective_test_output` through here silently
    widened the coder-timed fallback into ``trapping_engine_tests`` — the CLOSE-THE-GAP arm, which
    retracts tests and **ships**. The fallback was argued for the arm that STOPS and ASKS a human;
    the arm that delivers must not inherit it by sharing a helper. So the escalate arm passes its
    source in, and every other caller keeps the engine's own validation."""
    source = output if output is not None else str(final.get("test_output") or "")
    ids = parse_failing_tests(source, cap=10_000)
    files = {node.split("::", 1)[0].replace("\\", "/").removeprefix("./") for node in ids}
    return files or None


def _pre_existing_tests(final: Mapping[str, Any]) -> set[str]:
    """Every test path that existed in the PRISTINE clone at run start — a HUMAN/baselined test that
    supersession must NEVER delete. ``integrity_baseline`` (snapshotted in plan_node from the
    pristine tree: pre-existing tests + conftests + config) is the authoritative set;
    ``proctor_edits`` (the Proctor's baselined-test repairs) is folded in belt-and-suspenders."""
    pre: set[str] = set()
    for key in ("integrity_baseline", "proctor_edits"):
        val = final.get(key)
        if isinstance(val, dict):
            pre |= {str(f).replace("\\", "/") for f in val}
    return pre


def _collected_now(final: Mapping[str, Any]) -> set[str]:
    """Paths this run treats as COLLECTED tests: the authored ones plus the baseline's test half.

    Union rather than baseline-only because a legitimately authored NEW test is not in the pristine
    baseline — that is the whole point of authoring one. Collection controls are excluded from both
    halves; they are never a "test" that could trap a park.
    """
    out = {
        str(f).replace("\\", "/")
        for f in (final.get("integrity_baseline") or {})
        if not is_collection_control(str(f).replace("\\", "/"))
    }
    out |= {
        str(f).replace("\\", "/")
        for f in (final.get("authored_tests") or [])
        # `is_test_file` STAYS here, unlike the sibling site in `persist.py`, and the asymmetry is
        # deliberate. Dropping it widens what supersession may DELETE: `authored_tests` rides the
        # wide protection set, so a pre-existing `tests/helpers.py` would become deletable again —
        # the defect this guard was added to close, and the suite caught the reopening immediately.
        # The cost is that on a `python_files` repo supersession never fires. That fails CLOSED
        # (a park stands), which is the right side of a control that calls `unlink()`.
        if is_test_file(str(f)) and not is_collection_control(str(f).replace("\\", "/"))
    }
    return out


def trapping_engine_tests(final: Mapping[str, Any]) -> tuple[str, ...]:
    """The tester's OWN NEW test files trapping a give-up park, or ``()`` when the park does not
    qualify. Deny-by-default. **POSITIVE ALLOWLIST (red-team R2):** the deletable set is
    ``authored_tests`` MINUS every pre-existing/baselined test (``integrity_baseline`` +
    ``proctor_edits``) — a path is supersedable ONLY if it is proven NOT to have existed in the
    pristine clone. A baselined human test can leak into ``authored_tests`` (the run's tester may
    edit a pre-existing test during its first authoring turn, before ``protected_paths`` is set), so
    a name-only ``authored_tests`` membership is NOT sufficient — deleting a baselined human test to
    make a run ship is the tamper the ADR-0036 guard forbids. The failing set (from ``test_output``)
    must be NON-EMPTY and a SUBSET of this allowlist; one coder-, repo-, or baselined-owned failing
    test ⇒ ``()`` (the code may genuinely be wrong — the park stands)."""
    authored = {str(f).replace("\\", "/") for f in (final.get("authored_tests") or [])}
    engine_owned = authored - _pre_existing_tests(final)  # only PROVEN-NEW tester files
    # ...and only files that are actually TESTS. `authored_tests` is derived from the PROTECTION set
    # (deliberately wide — it also covers helpers and fixtures under a tests dir), while
    # `_pre_existing_tests` reads the integrity baseline (deliberately exact). Anything in that gap
    # — a pre-existing `tests/helpers.py`, a fixture — is absent from the baseline, so the
    # subtraction above leaves it looking engine-owned, and this function's own docstring promise
    # ("proven NOT to have existed in the pristine clone") is false for exactly that class. A file
    # pytest does not collect can never be the test trapping the park, so requiring collection costs
    # nothing and closes the path that DELETES A HUMAN'S FILE (`disposition.supersede_engine_tests`
    # calls `target.unlink()`). The baseline is collected-plus-controls and controls are
    # config-independent, so the collected set is recoverable here without a workspace.
    engine_owned = {f for f in engine_owned if not is_collection_control(f)} & _collected_now(final)
    if not engine_owned:
        return ()
    failing_files = _failing_test_files(final)
    if not failing_files or not failing_files <= engine_owned:
        return ()  # empty ⇒ nothing attributable; a non-authored failure ⇒ maybe a real defect
    return tuple(sorted(failing_files))


def is_engine_blocked_give_up(final: Mapping[str, Any]) -> bool:
    """Layer-2 convertible class 2: the run gave up via the NO-PROGRESS breaker and every failing
    test is the engine's OWN authored oracle. Deny-by-default. Excludes: any other honest-stop
    channel standing; a coder hand-raise (`coder_escalated`, or a `blocked:`/`escalation
    unresolved:`/gate-loop give-up prefix — red-team R1 F1); tamper; a critic veto; any non-benign
    gate reason; a failing set that isn't a subset of the tester's own authored files."""
    reason = str(final.get("give_up_reason") or "")
    if not reason:
        return False
    if final.get("coder_escalated"):
        return False  # a coder hand-raise (escalate) — the ESCALATE arm, not the close-the-gap arm
    if reason.startswith(_NON_NOPROGRESS_GIVEUP_PREFIXES):
        return False  # a blocked/escalate hand-raise or the gate-loop breaker — not a test trap
    for channel in _HONEST_STOP_CHANNELS:
        if channel != "give_up_reason" and final.get(channel):
            return False  # any OTHER safety stop standing ⇒ not this class
    if final.get("tests_modified"):
        return False  # never launder a tamper into a ship
    verdict = final.get("outcome_verdict")
    if isinstance(verdict, dict) and verdict.get("vetoed"):
        return False  # the held-out critic found a real defect
    gate = final.get("gate_decision") or {}
    if set(gate.get("reasons") or []) - _GIVE_UP_ALLOWED_REASONS:
        return False  # a real objection (tamper/security/reviewer/critic) rode the park
    return bool(trapping_engine_tests(final))


ConvertibleClass = Literal["oracle_unverified", "engine_blocked_give_up"]


def convertible_decline_reason(
    final: Mapping[str, Any], *, admit_structural_claim: bool = False
) -> str:
    """WHY this park is not convertible, or ``""`` when it is. Diagnosis only — never a decision.

    Added after the 2026-08-05 over-park sweep, where a park with gate reasons
    ``['oracle_unverified']`` alone — the exact class-1 shape — was declined and **nothing recorded
    why**. Its reasons ruled out every documented decline, the remaining candidates were
    `blocked_reason`/`escalate_reason`, neither was persisted, and the run's final state was gone.
    The cause is permanently unrecoverable.

    This is the `vouch` treatment applied to the disposition: *"a control whose non-firing is
    invisible costs a day of archaeology — this field cost 6 lines"* (`nodes_review.py`).

    `test_disposition.py` pins the invariant that this is non-empty exactly when
    `convertible_park_class` returns None, so the two cannot drift apart.
    """
    if convertible_park_class(final, admit_structural_claim=admit_structural_claim) is not None:
        return ""
    gate = final.get("gate_decision") or {}
    reasons = set(gate.get("reasons") or [])
    core = reasons - _BENIGN_REASONS
    # `give_up_reason` is excluded here for the same reason `is_engine_blocked_give_up` skips it:
    # on the class-2 path a give-up is REQUIRED, not a disqualifier. Reporting it as a safety stop
    # would hide the actual cause — which is exactly what it did on first run, masking the
    # `unsatisfied_claim` allowlist gap behind a plausible-sounding wrong answer.
    stops = [c for c in _HONEST_STOP_CHANNELS if c != "give_up_reason" and final.get(c)]

    # Ordered most-specific first: name the thing a reader would act on.
    if final.get("tests_modified"):
        return "tests_modified: never launder a tamper into a ship"
    verdict = final.get("outcome_verdict")
    if isinstance(verdict, dict) and verdict.get("vetoed"):
        return "critic_vetoed: the held-out critic found a real defect"
    if final.get("coder_escalated"):
        return "coder_escalated: a hand-raise is the ESCALATE arm, not the close-the-gap arm"
    if stops:
        return f"honest_stop: {', '.join(stops)} — a safety stop, not a verification gap"
    if not core:
        return "no blocking gate reason: not a park this disposition is for"
    # Class 1 wanted exactly {oracle_unverified}; class 2 wanted a give-up whose reasons all sit in
    # the allowed set. Report the reasons that disqualified each, which is what actually diagnoses
    # the `unsatisfied_claim` gap: it is absent from `_GIVE_UP_ALLOWED_REASONS` and blocks class 2.
    if not final.get("give_up_reason"):
        extra = sorted(core - {"oracle_unverified"})
        if final.get("tests_passed") is not True:
            return "class1: the suite did not run green"
        return f"class1: core reasons beyond oracle_unverified: {extra}"
    disallowed = sorted(reasons - _GIVE_UP_ALLOWED_REASONS)
    if disallowed:
        return f"class2: gate reason(s) outside the allowlist: {disallowed}"
    return "class2: the failing tests are not a subset of the engine's own authored tests"


def convertible_park_class(
    final: Mapping[str, Any], *, admit_structural_claim: bool = False
) -> ConvertibleClass | None:
    """Which Layer-2 convertible class this park belongs to, or ``None`` (stays parked). The two
    classes are disjoint by construction (class 1 requires give_up_reason falsy; class 2 requires
    it truthy) — tried in historical order."""
    if is_oracle_unverified_park(final, admit_structural_claim=admit_structural_claim):
        return "oracle_unverified"
    if is_engine_blocked_give_up(final):
        return "engine_blocked_give_up"
    return None
