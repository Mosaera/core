"""Which knobs the product SHOWS (ADR-0122 §6) — the settings surface, declared in one place.

The classification lives here as two sets rather than as a field on each of the 85 ``Knob``
entries, for one reason that matters more than tidiness: *"what does a new user actually see?"*
must be answerable by reading a single list. Spread across 85 constructor calls it is answerable
only by a script, and a surface nobody can read is a surface nobody can defend.

**This module hides; it does not lock.** Every knob here remains fully functional and settable by
its environment variable, whatever its visibility — hiding is a presentation decision, reversible
by editing one line, and it crosses no trust boundary. Making a knob genuinely unchangeable is a
different and larger change: it must ignore env and stored config, which contradicts the ADR-0005
precedence invariant, and for the safety knobs it touches the delivery gate. Do not conflate the
two, and do not describe a hidden knob as "locked" — an operator with shell access can still set
it, and saying otherwise in a sales context would be false.
"""

from __future__ import annotations

#: What a normal operator sees without opening anything. The whole product surface: state the
#: intent, bound the resources, choose the privacy and delivery posture. Eleven decisions.
#:
#: The bar for adding one: it describes WHAT THE USER WANTS, not how Mosaera achieves it. A knob
#: describing mechanism belongs below, however useful it is.
CORE: frozenset[str] = frozenset(
    {
        # Intent — the four profiles derive most of the mechanics (ADR-0122).
        "effort_profile",
        "quality_profile",
        "verification_profile",
        # Resources — the user-facing contract is "spend <= X, runtime <= Y, runs/day <= Z".
        # The token and tool-call ceilings enforce these underneath and are developer-only:
        # nobody chooses a budget in tokens.
        "run_max_usd",
        "run_max_seconds",
        "run_quota_per_day",
        # Privacy — the one knob that decides whether repository content leaves the box.
        "allow_cloud_egress",
        # Delivery.
        "auto_open_mr",
        "mr_granularity",
        # What the run transcript shows.
        "stream_reasoning",
        # The master verification switch. Kept visible deliberately even though
        # `verification_profile` now shapes the oracle: this is the one control that decides
        # whether an autonomous run must clear an independent oracle at all, and burying the
        # decision that governs unattended delivery would be the wrong kind of simplification.
        "autonomous_verified",
    }
)

#: Never rendered. Two populations, and the distinction is worth keeping straight because only
#: one of them is a candidate for genuine locking later:
#:
#: 1. **Safety mechanisms that should simply always run.** Presenting them as toggles invites a
#:    support ticket asking how to turn a safety control off. Hiding is the honest first step;
#:    LOCKING them (ignoring env too) is the trust-boundary change that follows, and needs
#:    CODEOWNERS approval plus a red-team pass.
#: 2. **Engine internals that were never reachable in the UI anyway** — 23 of these existed as
#:    env-only knobs before this module, so hiding them removes nothing an operator had.
INTERNAL: frozenset[str] = frozenset(
    {
        # --- 1. Always-on safety. Hidden now; the lock proposal is tracked in the roadmap. ---
        # The gate bypass. There is no version of this that belongs on a dashboard.
        "deliver_unverified",
        "scan_enabled",
        "hygiene_gate_enabled",
        "stall_detection_enabled",
        # `stall_limit` reunited with `stall_detection_enabled` above (S1, readiness review):
        # GeneralSettings used to show "Identical outcomes before stopping" with NO enable
        # toggle next to it (the toggle went internal, the number box didn't), which read as
        # an orphaned control. The pair hides or shows together.
        "stall_limit",
        "backlog_spec_lint",
        "doctrine_enabled",
        # --- The oracle stack. `apply_oracle_posture` FORCES these on for every autonomous run,
        # and `verification_profile` now owns the rest, so rendering them as independent toggles
        # showed a choice that was not one. That was previously mitigated with a "forced when
        # autonomous" badge; removing the control is better than explaining why it is inert. ---
        "tester_enabled",
        "tester_repairs_tests",
        "tester_step_limit",
        "tester_file_cap",
        # NOTE what is NOT here: `reason_on_stall_enabled` and `max_reason_attempts` are NOT
        # dead controls (checked against `graph/build.py` + `graph/nodes_reason.py`, not
        # assumed) — pass 0 is the coder's OWN model rethinking (ADR-0017), which needs no
        # ladder, so the toggle has a real effect with `reason_escalation` empty. They stay
        # visible (in AutonomySettings).
        #
        # `model_escalation_enabled` + `max_model_escalations` (S2, readiness review) are the
        # genuinely inert pair: `_model_escalation.py`'s `_try_model_escalation` reads
        # `settings.role_escalation`, which has NO route/UI to populate — an empty ladder means
        # `escalate_role` always returns None and the toggle can never fire. Hidden until a
        # ladder is configurable; `_profiles.py.EFFECTS` says so for the profile comparison too.
        "model_escalation_enabled",
        "max_model_escalations",
        "oracle_coverage",
        "oracle_mutation_check",
        "oracle_mutation_comprehensive",
        "oracle_structural_spec",
        "proctor_faithfulness_guard",
        "refactor_oracle_scaffold",
        "critic_enabled",
        "critic_claim_protocol",
        "behavior_preservation_guard",
        # --- 2. Engine internals, none of which were UI-reachable before. ---
        "clauses_enabled",
        "coder_diagnose_loop",
        "coder_repl_enabled",
        "coder_scratch_enabled",
        "gate_stall_limit",
        "plan_stall_limit",
        "honest_stop_no_signal",
        "honest_stop_projection",
        "intake_ask_undecidable",
        "intake_ask_unreachable",
        "onboarding_map_scoping",
        "prompt_cache_enabled",
        # #118/#129 unmeasured experiment levers (readiness review 3A): each ships OFF, has no
        # curated-list entry, and its own docstring in _settings.py says why — "UNMEASURED",
        # "measured NULL", or a paired A/B still running. Same disposition as the oracle-stack
        # experiment knobs above: a toggle for an arm nobody has read results for yet is not a
        # product control, it's a lab dial. Promote individually once an arm is decided.
        "reduced_lane",
        "inert_oracle_scaffold",
        "static_testkit",
        "repair_loosen_only",
        "coder_prefetch",
        "reliability_sensitivity",
        "escalate_arm",
        "amendment_gate",
        # NOTE: `pm_chat_tools` is NOT here, though it looks like the rest of this block at a
        # glance. It IS UI-reachable (AdvancedSettings' "Planner (Quincy)" group,
        # `pm-steps.test.tsx`'s "the knob has a control" tests) — pinned there for exactly the
        # gap this module exists to prevent: a knob settable by env/API with no browser control.
        # A prior pass here miscategorized it into this set (`"2. Engine internals, none of
        # which were UI-reachable before"` did not hold for this one) and every field in that
        # AdvancedSettings group silently vanished through KnobForm's filter (S1, readiness
        # review) — caught by the two tests above still asserting the control exists.
    }
)


# NOT hidden, though the settings-v2 proposal moves it to an Organization/Permissions surface:
# `member_branch_delete` is the only way an admin grants members branch-deletion, and that surface
# does not exist yet. Hiding it would take away an administrative action rather than tidy one, so
# it stays reachable (behind the disclosure) until there is somewhere better to put it.


def visibility_of(field: str) -> str:
    """``core`` | ``internal`` | ``developer`` — developer is the default.

    Defaulting to ``developer`` rather than ``core`` is deliberate: a knob added tomorrow with no
    entry in either set stays OUT of the twelve-control surface until someone decides it belongs
    there. The failure mode of the opposite default is a Core surface that grows by accident,
    which is the condition this module exists to end.
    """
    if field in CORE:
        return "core"
    return "internal" if field in INTERNAL else "developer"
