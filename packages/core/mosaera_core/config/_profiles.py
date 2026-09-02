"""Intent-level settings profiles: the Core surface that DERIVES the mechanics (ADR-0122).

The operator states *intent* — how hard to try, how high to set the bar — and this module maps
that to the individual knobs. It is deliberately a **default provider, not a ceiling**: a knob the
operator actually set (env or ``settings.json``) always wins, so a profile can neither widen nor
narrow an existing deployment's permissions. The *clamp* semantics — a posture that knobs may not
exceed — are ADR-0046's restriction lattice and are NOT built here; conflating the two is the
mistake this docstring exists to prevent.

Why the profiles default to UNSET rather than to ``balanced``: every profile row below differs
from at least one shipped ``Knob.default``, so a default-on profile would silently change
behaviour for every existing install on upgrade. That is precisely the migration hazard the
settings-v2 spec §44 names. An install that never opts in therefore resolves to ``{}`` and keeps
today's defaults byte-for-byte (asserted in ``test_config_profiles.py``).

Kept in its own module rather than folded into ``_knobs.py`` or ``_settings.py`` because the
latter sits at 499 lines against the 500-line ceiling in ``scripts/check_file_sizes.py``. This
module imports nothing from ``config`` — it is pure data plus one function over field names, so it
stays a leaf and cannot create an import cycle with ``_knobs``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The four intent knobs, each an enumerable set (so ``Knob.choices`` renders a dropdown and
#: ``coerce_general_patch`` rejects anything else — the ADR-0005 invariant, enforced on both
#: layers by machinery that already exists).
AUTONOMY_CHOICES: tuple[str, ...] = ("conservative", "balanced", "aggressive")
QUALITY_CHOICES: tuple[str, ...] = ("standard", "high", "strict")
RECOVERY_CHOICES: tuple[str, ...] = ("minimal", "balanced", "persistent")
VERIFICATION_CHOICES: tuple[str, ...] = ("standard", "strict", "maximum")

#: Knobs NO profile may derive. Each one decides what the delivery gate permits or whether a
#: safety mechanism runs at all, so it stays a direct operator decision under an explicit control
#: path — never a side effect of picking "aggressive". ``test_profiles_never_derive_safety_knobs``
#: asserts this set is disjoint from every table below, so a future edit that quietly adds
#: ``deliver_unverified`` to a profile fails the suite rather than shipping.
#:
#: Settings-v2 §56 states the rule this encodes: aggressive means *more attempts*, never *weaker
#: evidence*.
NEVER_DERIVED: frozenset[str] = frozenset(
    {
        "deliver_unverified",
        "autonomous_verified",
        "scan_enabled",
        "hygiene_gate_enabled",
        "member_branch_delete",
        "allow_cloud_egress",
        "backlog_spec_lint",
        "stall_detection_enabled",
    }
)

# The tables. Each profile OWNS a disjoint set of knobs — two profiles writing the same field
# would make the resolved value depend on iteration order, which is why
# `test_profile_tables_are_disjoint` exists. The partition also resolves a genuine ambiguity in
# the settings-v2 spec, whose §4 (autonomy) and §6 (recovery) both claim the recovery knobs while
# §6 insists the two are separate concerns: recovery owns them, autonomy owns the sweep and
# iteration budget.

#: How much ground a run covers on its own before it stops making progress: the resilience sweep,
#: gap-closing, and the plan/fix iteration budget.
_AUTONOMY: dict[str, dict[str, Any]] = {
    "conservative": {
        "resilient_sweep": True,
        "resilient_recuration": False,
        "disposition_gap_close": False,
        "escalate_arm": False,
        "max_iterations": 5,
        "max_iterations_ceiling": 8,
    },
    "balanced": {
        "resilient_sweep": True,
        "resilient_recuration": True,
        "disposition_gap_close": True,
        "escalate_arm": False,
        "max_iterations": 8,
        "max_iterations_ceiling": 12,
    },
    "aggressive": {
        "resilient_sweep": True,
        "resilient_recuration": True,
        "disposition_gap_close": True,
        "escalate_arm": True,
        "max_iterations": 12,
        "max_iterations_ceiling": 16,
    },
}

#: What a run does when it is STUCK — reasoning attempts, model escalation, retry budget. Split
#: from autonomy because "how far does it range" and "how hard does it push on a wall" are
#: independent choices an operator makes for different reasons.
_RECOVERY: dict[str, dict[str, Any]] = {
    "minimal": {
        "max_escalations": 0,
        "reason_on_stall_enabled": False,
        "max_reason_attempts": 0,
        "model_escalation_enabled": False,
        "max_model_escalations": 0,
        "coder_test_repeat_limit": 2,
    },
    "balanced": {
        "max_escalations": 1,
        "reason_on_stall_enabled": True,
        "max_reason_attempts": 1,
        "model_escalation_enabled": True,
        "max_model_escalations": 2,
        "coder_test_repeat_limit": 3,
    },
    "persistent": {
        "max_escalations": 2,
        "reason_on_stall_enabled": True,
        "max_reason_attempts": 3,
        "model_escalation_enabled": True,
        "max_model_escalations": 3,
        "coder_test_repeat_limit": 5,
    },
}

#: The code-quality bar and how many revision passes are spent reaching it. The numeric
#: thresholds are INITIAL policy values (settings-v2 §22 says so explicitly) — they are meant to
#: be tuned against real run data, and nothing outside this table depends on the specific numbers.
_QUALITY: dict[str, dict[str, Any]] = {
    "standard": {
        "quality_revise_enabled": True,
        "quality_min": 70,
        "quality_dim_floor": 60,
        "quality_max_revises": 1,
        "review_fix_enabled": True,
        "review_max_fixes": 1,
        "hygiene_max_fixes": 1,
    },
    "high": {
        "quality_revise_enabled": True,
        "quality_min": 80,
        "quality_dim_floor": 70,
        "quality_max_revises": 2,
        "review_fix_enabled": True,
        "review_max_fixes": 2,
        "hygiene_max_fixes": 2,
    },
    "strict": {
        "quality_revise_enabled": True,
        "quality_min": 90,
        "quality_dim_floor": 80,
        "quality_max_revises": 3,
        "review_fix_enabled": True,
        "review_max_fixes": 3,
        "hygiene_max_fixes": 3,
    },
}

#: Which INDEPENDENT verification mechanisms run. Note what is absent: ``autonomous_verified``,
#: the master switch, stays a direct knob. This profile therefore governs GUIDED and ad-hoc runs
#: — on an autonomous run ``apply_oracle_posture`` already forces the oracle stack on regardless
#: (``POSTURE_FORCED_KNOBS``), and ``general_settings_view`` reports that as ``clamped_by``.
#: Making this profile the INPUT to that posture is the coherent end state and is deferred: it
#: changes what the delivery gate permits, which is CODEOWNERS-protected and red-team-required.
_VERIFICATION: dict[str, dict[str, Any]] = {
    "standard": {
        "tester_enabled": True,
        "tester_step_limit": 15,
        "oracle_coverage": False,
        "oracle_mutation_check": False,
    },
    "strict": {
        "tester_enabled": True,
        "tester_step_limit": 20,
        "oracle_coverage": True,
        "oracle_mutation_check": True,
    },
    "maximum": {
        "tester_enabled": True,
        "tester_step_limit": 30,
        "oracle_coverage": True,
        "oracle_mutation_check": True,
        "oracle_mutation_comprehensive": True,
        "oracle_structural_spec": True,
    },
}

#: profile field -> choice -> {derived knob field: value}. The single source of truth; both
#: ``resolve_profiles`` and the settings view's provenance read it, so they cannot drift.
PROFILE_DERIVED: dict[str, dict[str, dict[str, Any]]] = {
    "autonomy_profile": _AUTONOMY,
    "quality_profile": _QUALITY,
    "recovery_profile": _RECOVERY,
    "verification_profile": _VERIFICATION,
}


def resolve_profiles(values: Mapping[str, Any]) -> dict[str, Any]:
    """The knob values the selected profiles derive: ``{knob field: value}``.

    ``values`` maps a profile field to its selected choice (typically the env>stored>default
    layering of the four profile knobs). An unset, blank, or unrecognised choice contributes
    nothing — a profile can only ever ADD a value for a knob the operator did not set, so an
    invalid selection degrades to today's defaults rather than to an exception. The write path
    (``coerce_general_patch`` against ``Knob.choices``) is what rejects a bad value loudly; this
    read path must stay total because it runs on every ``Settings.from_env()``.
    """
    out: dict[str, Any] = {}
    for profile_field, table in PROFILE_DERIVED.items():
        choice = values.get(profile_field)
        if not isinstance(choice, str):
            continue
        out.update(table.get(choice, {}))
    return out


def derived_by(values: Mapping[str, Any]) -> dict[str, str]:
    """``{knob field: the profile field that supplied it}`` — provenance for the settings UI, so
    a derived value can be shown as coming from a profile rather than looking hand-set."""
    out: dict[str, str] = {}
    for profile_field, table in PROFILE_DERIVED.items():
        choice = values.get(profile_field)
        if not isinstance(choice, str):
            continue
        for knob_field in table.get(choice, {}):
            out[knob_field] = profile_field
    return out
