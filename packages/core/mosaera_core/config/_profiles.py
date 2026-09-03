"""Intent-level settings profiles: the Core surface that DERIVES the mechanics (ADR-0122).

The operator states *intent* — how hard to try, how high to set the bar, how much independent
checking to demand — and this module maps that to the individual knobs. It is deliberately a
**default provider, not a ceiling**: a knob the operator actually set (env or ``settings.json``)
always wins, so a profile can neither widen nor narrow an existing deployment's permissions. The
*clamp* semantics — a posture that knobs may not exceed — are ADR-0046's restriction lattice and
are NOT built here; conflating the two is the mistake this docstring exists to prevent.

**Three profiles, not four.** ``autonomy`` and ``recovery`` were separate in the first cut and no
operator could tell them apart: both answered "how hard does it try?". The source proposal
contradicted *itself* about which one owned the recovery knobs, which was the evidence that the
distinction was not real. They are now one ``effort_profile``.

**``effort_profile`` drives ``reliability_sensitivity`` rather than competing with it.** That knob
(#51, ADR-0056) already scaled every self-stop budget, and it is applied in ``build_graph`` — i.e.
*after* this layer. A profile that set ``max_escalations`` directly was therefore silently
overwritten: ``recovery_profile=persistent`` with ``reliability_sensitivity=cautious`` resolved to
``max_escalations=0``, the exact opposite of what was asked for, with nothing to tell the operator.
The fix is not another override but a division of ownership — see ``SENSITIVITY_OWNED``.

Why the profiles default to UNSET rather than to ``balanced``: every profile row below differs from
at least one shipped ``Knob.default``, so a default-on profile would silently change behaviour for
every existing install on upgrade. An install that never opts in resolves to ``{}`` and keeps
today's defaults byte-for-byte (asserted in ``test_config_profiles.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The three intent knobs, each an enumerable set (so ``Knob.choices`` renders a dropdown and
#: ``coerce_general_patch`` rejects anything else — the ADR-0005 invariant, enforced on both
#: layers by machinery that already exists).
#:
#: ``EFFORT_CHOICES`` deliberately reuses the ``reliability_sensitivity`` vocabulary rather than
#: inventing a third one. Before this, ``balanced`` and ``persistent`` each meant two different
#: things in the same product depending on which dial you were looking at.
EFFORT_CHOICES: tuple[str, ...] = ("cautious", "balanced", "persistent")
QUALITY_CHOICES: tuple[str, ...] = ("standard", "high", "strict")
VERIFICATION_CHOICES: tuple[str, ...] = ("standard", "strict", "maximum")

#: Knobs ``graph.build.apply_reliability_sensitivity`` OVERWRITES at graph-build time. No profile
#: may derive one: the profile layer runs first, so anything set here would be silently replaced,
#: and the operator would see a control that demonstrably did nothing.
#:
#: ``test_profiles_never_touch_sensitivity_owned_knobs`` enforces this. It is the guard on a defect
#: that already happened once, not a hypothetical.
SENSITIVITY_OWNED: frozenset[str] = frozenset(
    {
        "max_iterations",
        "max_escalations",
        "stall_limit",
        "tester_step_limit",
        "plan_stall_limit",
        "gate_stall_limit",
    }
)

#: Knobs NO profile may derive. Each decides what the delivery gate permits or whether a safety
#: mechanism runs at all, so it stays a direct operator decision under an explicit control path —
#: never a side effect of picking "persistent". Settings-v2 §56 states the rule this encodes:
#: **more attempts, never weaker evidence.**
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
# would make the resolved value depend on iteration order.

#: How hard a run tries: how far it ranges, how many recovery attempts it gets, how long it
#: persists before parking honestly. Sets ``reliability_sensitivity``, which scales the self-stop
#: budgets it does not set directly.
_EFFORT: dict[str, dict[str, Any]] = {
    "cautious": {
        "reliability_sensitivity": "cautious",
        "resilient_recuration": False,
        "disposition_gap_close": False,
        "escalate_arm": False,
        "reason_on_stall_enabled": False,
        "max_reason_attempts": 0,
        "model_escalation_enabled": False,
        "max_model_escalations": 0,
        "coder_test_repeat_limit": 2,
        "max_iterations_ceiling": 8,
    },
    "balanced": {
        "reliability_sensitivity": "balanced",
        "resilient_recuration": True,
        "disposition_gap_close": True,
        "escalate_arm": False,
        "reason_on_stall_enabled": True,
        "max_reason_attempts": 1,
        "model_escalation_enabled": True,
        "max_model_escalations": 2,
        "coder_test_repeat_limit": 3,
        "max_iterations_ceiling": 12,
    },
    "persistent": {
        "reliability_sensitivity": "persistent",
        "resilient_recuration": True,
        "disposition_gap_close": True,
        "escalate_arm": True,
        "reason_on_stall_enabled": True,
        "max_reason_attempts": 3,
        "model_escalation_enabled": True,
        "max_model_escalations": 3,
        "coder_test_repeat_limit": 5,
        "max_iterations_ceiling": 16,
    },
}

#: The code-quality bar and how many revision passes are spent reaching it. The numeric thresholds
#: are INITIAL policy values, meant to be tuned against run data; nothing outside this table
#: depends on the specific numbers.
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

#: Which INDEPENDENT verification mechanisms run. Note what is absent: ``autonomous_verified``, the
#: master switch, stays a direct knob; and ``tester_step_limit`` belongs to
#: ``reliability_sensitivity``. This profile governs GUIDED and ad-hoc runs — on an autonomous run
#: ``apply_oracle_posture`` forces the oracle stack on regardless, which
#: ``general_settings_view`` reports as ``clamped_by``.
_VERIFICATION: dict[str, dict[str, Any]] = {
    "standard": {
        "tester_enabled": True,
        "oracle_coverage": False,
        "oracle_mutation_check": False,
    },
    "strict": {
        "tester_enabled": True,
        "oracle_coverage": True,
        "oracle_mutation_check": True,
    },
    "maximum": {
        "tester_enabled": True,
        "oracle_coverage": True,
        "oracle_mutation_check": True,
        "oracle_mutation_comprehensive": True,
        "oracle_structural_spec": True,
    },
}

#: profile field -> choice -> {derived knob field: value}. The single source of truth; the
#: resolver, the settings view's provenance and the UI comparison all read it, so they cannot
#: drift. The UI is served FROM this — it does not keep a copy.
PROFILE_DERIVED: dict[str, dict[str, dict[str, Any]]] = {
    "effort_profile": _EFFORT,
    "quality_profile": _QUALITY,
    "verification_profile": _VERIFICATION,
}

#: What each derived knob DOES, in a sentence an operator can act on.
#:
#: This exists because the first cut of the settings page showed rows like
#: ``max_reason_attempts: 3`` — a mechanism name presented as an intent control, which is precisely
#: what made the profiles feel like theatre. A profile is only meaningful if the reader can predict
#: what changes, and a knob identifier predicts nothing.
#:
#: Written as "what the run will do", never as an outcome promise. Nothing here claims a profile
#: delivers more often: that has not been measured, and the difference between describing effort
#: and promising results is the difference between an honest control and a marketing label.
EFFECTS: dict[str, str] = {
    # Effort
    "reliability_sensitivity": "Scales every self-stop budget to how much rope the run gets",
    "resilient_recuration": "Lets the PM re-scope a stuck item before giving up on it",
    "disposition_gap_close": "Chases a missing decision rather than parking on the gap",
    "escalate_arm": "Escalates to a stronger model when the current one stalls",
    "reason_on_stall_enabled": "Reasons about WHY it is stuck instead of retrying blindly",
    "max_reason_attempts": "How many times it may stop and reason about being stuck",
    # S2 (readiness review): `role_escalation` — the ladder these two actually drive
    # (`_model_escalation.py`) — has no route/UI to populate yet, so setting these has NO
    # effect on any run today. Said here rather than removed: removing the entry would make
    # `effectIn`'s fallback show the bare field name instead, which predicts even less.
    "model_escalation_enabled": "May retry a failed step on a stronger model — no effect yet: "
    "there is no way to configure the escalation ladder it would use",
    "max_model_escalations": "How many times it may move up to a stronger model — same caveat",
    "coder_test_repeat_limit": "Identical test failures before the coder is told to stop and yield",
    "max_iterations_ceiling": "The hard ceiling on plan/fix loops, whatever else is configured",
    # Quality
    "quality_revise_enabled": "Revises code that scores below the quality bar",
    "quality_min": "The overall quality score a change must reach",
    "quality_dim_floor": "The floor any single quality dimension must clear",
    "quality_max_revises": "How many quality revision passes it may spend",
    "review_fix_enabled": "Fixes what the reviewer objects to instead of parking",
    "review_max_fixes": "How many review-fix rounds it may spend",
    "hygiene_max_fixes": "How many lint/format cleanup rounds it may spend",
    # Verification
    "tester_enabled": "An independent Proctor writes the acceptance test, not the coder",
    "oracle_coverage": "Requires the changed code to actually be covered by a test",
    "oracle_mutation_check": "Checks the test FAILS when the change is broken on purpose",
    "oracle_mutation_comprehensive": "Runs the full mutation battery, not a sample",
    "oracle_structural_spec": "Checks the change matches the shape the spec described",
}


def resolve_profiles(values: Mapping[str, Any]) -> dict[str, Any]:
    """The knob values the selected profiles derive: ``{knob field: value}``.

    ``values`` maps a profile field to its selected choice. An unset, blank or unrecognised choice
    contributes nothing — a profile can only ever ADD a value for a knob the operator did not set,
    so an invalid selection degrades to today's defaults rather than raising. The write path
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
    """``{knob field: the profile field that supplied it}`` — provenance for the settings UI, so a
    derived value can be shown as coming from a profile rather than looking hand-set."""
    out: dict[str, str] = {}
    for profile_field, table in PROFILE_DERIVED.items():
        choice = values.get(profile_field)
        if not isinstance(choice, str):
            continue
        for knob_field in table.get(choice, {}):
            out[knob_field] = profile_field
    return out


def profile_catalogue() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Every profile's options with what each one does, for a side-by-side comparison.

    ``{profile field: {choice: [{field, value, effect}, ...]}}``. Served to the settings page so it
    can render the options against each other instead of asking an operator to decode an adjective
    — and served rather than duplicated so the UI cannot drift from the tables above.
    """
    return {
        profile_field: {
            choice: [
                {"field": f, "value": v, "effect": EFFECTS.get(f, "")}
                for f, v in sorted(derived.items())
            ]
            for choice, derived in table.items()
        }
        for profile_field, table in PROFILE_DERIVED.items()
    }


def profile_reference() -> dict[str, Any]:
    """The settings page's profile reference block: what each option does, and what nothing can
    touch. Assembled here rather than in the API route because the payload shape belongs to the
    tables it describes — and because a route module is not the place to keep product copy."""
    return {"profiles": profile_catalogue(), "constant": sorted(NEVER_DERIVED)}
