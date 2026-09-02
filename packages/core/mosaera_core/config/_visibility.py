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
#: intent, bound the resources, choose the privacy and delivery posture. Twelve decisions.
#:
#: The bar for adding one: it describes WHAT THE USER WANTS, not how Mosaera achieves it. A knob
#: describing mechanism belongs below, however useful it is.
CORE: frozenset[str] = frozenset(
    {
        # Intent — the four profiles derive most of the mechanics (ADR-0122).
        "autonomy_profile",
        "recovery_profile",
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
        "reason_on_stall_enabled",
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
        "reliability_sensitivity",
        "escalate_arm",
        "amendment_gate",
        "pm_chat_tools",
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
