"""The autonomous ORACLE POSTURE (#52, ADR-0057).

A pure ``Settings → Settings`` overlay that activates the full independent-oracle stack for an
autonomous run. Kept in its own module (not ``_settings.py``) to stay under the god-file ceiling.
It lives at the ``config`` layer — core's leaf — because BOTH callers import it: apps/api's
``_verify_overlay`` and the benchmark. It must NOT live in apps/api (the layer guard forbids
``core → mosaera_api``, and the bench is inside ``core``), and NOT in ``build_graph`` (this is
caller-applied, autonomous-only — unlike ``#51``'s universal ``apply_reliability_sensitivity``).
"""

from __future__ import annotations

from dataclasses import replace

from mosaera_core.config._settings import Settings

#: The knobs this overlay FORCES ON for an autonomous run (when ``autonomous_verified`` is set).
#: Named so the settings UI can say so: four of these are rendered as independent operator toggles,
#: and switching them off has no effect on the mode the product defaults to. The set was previously
#: only inferable by diffing dataclass fields (scripts/check_control_liveness.py), which is why the
#: UI could not tell the operator. `apply_oracle_posture` is the single writer — keep them in step.
POSTURE_FORCED_KNOBS: tuple[str, ...] = (
    "tester_enabled",
    "reason_on_stall_enabled",
    "oracle_coverage",
    "oracle_mutation_check",
    "tester_repairs_tests",
    "proctor_faithfulness_guard",
    "critic_enabled",
    "refactor_oracle_scaffold",
    "critic_claim_protocol",
)


def apply_oracle_posture(settings: Settings) -> Settings:
    """Activate the autonomous delivery oracle (#52, ADR-0057; leaned #56, ADR-0060).

    When the run OPTS IN via ``autonomous_verified`` (default True), turn on the independent
    oracle: the Proctor authors the asserting acceptance test (``tester_enabled``) + reason-on-stall
    recovery (ADR-0020), backed by change-coverage and the mutation check; and (#54, ADR-0058) the
    Proctor VALIDATES + REPAIRS tests before the coder (``tester_repairs_tests``). IDENTITY (same
    obj) when ``autonomous_verified`` is off — the deterministic-baseline opt-out. Idempotent.

    NOTE (#52 red-team): the gap-fill token-saver was deliberately NOT in the posture — it RATIFIED
    delivered code (a confirmation oracle) — and was subsequently REMOVED entirely (#56, ADR-0060).
    The reactive on-thrash LLM diagnosis (react_on_bad_test) was likewise removed (#56) — the
    honest-stop's deterministic diagnosis (failing-test names + count trend) replaces it.

    Autonomous-only by construction: guided / high-assurance / ad-hoc runs keep the human backstop
    at the delivery gate and never pay the extra LLM + sandbox cost, so this is applied ONLY by the
    autonomous callers (apps/api ``_verify_overlay`` and the benchmark), never inside build_graph.
    """
    if not settings.autonomous_verified:
        return settings
    return replace(
        settings,
        tester_enabled=True,
        reason_on_stall_enabled=True,
        oracle_coverage=True,
        oracle_mutation_check=True,
        # Test-steward (#54, ADR-0058): the Proctor validates+repairs the tests before the coder
        # (coder-blind → ungameable). The repair authority relies on oracle_mutation_check (above)
        # for its delivery gate — a proctor-edited run ships only on a PROVEN mutation-catch.
        tester_repairs_tests=True,
        # Proctor faithfulness guard (#57, ADR-0062): the deterministic over-strictness detector
        # names incidental-pin / contradictory authored assertions for the repair turn to loosen —
        # deterministic, one-sided, never weakens a behavioural assertion.
        proctor_faithfulness_guard=True,
        # The held-out critic (#60, ADR-0065): a veto-only, different-model judge of the delivered
        # OUTCOME between review and the gate — the correctness gate for a verified autonomous run,
        # catching the executed-but-unasserted false-ship class the deterministic oracle can't
        # (MCB-05/09). Downgrade-only: it can only ever turn a ship into an honest park.
        critic_enabled=True,
        # Behaviour-preservation Proctor (#60, ADR-0066): posture activation HELD (#60 measured
        # result). The prompt-led differential-golden-master guidance was measured on MCB-05 ON/OFF
        # and did NOT validate: the weak local Proctor authored a suite loose enough to let a WRONG
        # refactor SHIP (a `false_ship` on the ON arm the OFF arm did not show), and no ON run
        # delivered CORRECTLY — the exact false-ship reopening the #57 auto-loosen revert warned of.
        # So the guidance stays behind its knob (default OFF, still measurable via the bench lever)
        # until the deterministic golden-master SCAFFOLD (the engine authors the differential test
        # itself, not the weak model) makes it safe. The detector + the source_introspection finding
        # (pure over-strictness DETECTION, no loosening) stay live — only the auto-ship activation
        # is withdrawn. Re-enable here once the scaffold is measured correctness-neutral.
        #
        # Deterministic refactor-oracle SCAFFOLD (#60, ADR-0066 follow-up): the SAFE successor — the
        # ENGINE authors the differential golden-master (frozen module + differential behaviour test
        # over generated inputs + a name-agnostic decomposition check), so correctness does not rest
        # on the weak model. It validated (reds on the seed, greens on a correct refactor), so it IS
        # activated in the posture — replacing the reverted prompt-led guidance for refactors.
        refactor_oracle_scaffold=True,
        # Claims-protocol critic (#61, ADR-0065 amendment) — ACTIVATED 2026-08-03 by owner
        # decision, on measured evidence: over-vetoes 8 -> 1 at n=70/arm (Fisher p=0.033), true
        # catches preserved (2 vs 1), false ships identical (no new ship channel — veto-only by
        # construction), premise/fragment classes eliminated and regression-pinned. The
        # catch-retention question at event-level n is CONVERTED from a gate into a standing
        # production measurement: every veto now persists its quoted rows (critic Decision row +
        # scorecard critic_rows), so the ledger is the ongoing exam. Rollback is one line here
        # (the ADR-0065 registered lever). Record: engineering-history/
        # critic-calibration-ab-2026-08-03.md.
        critic_claim_protocol=True,
        # Structural-spec oracle (#80, ADR-0072 + relative-measure successor) — WITHDRAWN
        # 2026-08-02, the same day it was activated. The activation rested on an n=3 result
        # (MCB-05 3/3 false_ship -> 3/3 honest_park) that did NOT replicate: a frozen n=25/arm
        # interleaved A/B (100 runs) showed no effect — MCB-05 ON 21/25 vs OFF 23/25 false_ship
        # (Fisher p=0.667), MCB-15 ON 25/25 vs OFF 24/25 (p=1.0), pooled p=1.0. The safety half
        # DID hold: 0 false-parks in all 100 runs (95% upper bound ~3%), superseding the earlier
        # 0-of-20-references bound. So the oracle is safe and ineffective on the current model
        # tier — it pays a gate dependency for a measured-zero benefit. The knob (default OFF),
        # the pure `evaluate_structural_spec`, and the bench OFF-lever all stay: re-test once
        # acceptance claims are first-class and the check has a real contract to score against.
        # Full record: docs/engineering-history/structural-oracle-ab-2026-08-02.md.
    )
