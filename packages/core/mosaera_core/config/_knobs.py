"""UI-manageable knob system: the GENERAL_KNOBS spec + layering/validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from mosaera_core.config._profiles import (
    AUTONOMY_CHOICES,
    PROFILE_DERIVED,
    QUALITY_CHOICES,
    RECOVERY_CHOICES,
    VERIFICATION_CHOICES,
    resolve_profiles,
)
from mosaera_core.config._types import DEFAULT_OLLAMA_BASE_URL


class Knob(NamedTuple):
    """A UI-manageable config knob layered ``env > stored > default``. The field name
    doubles as its ``settings.json`` key; ``kind`` drives both parsing and the UI widget.
    ``choices`` (when set) is the supported value set — the UI renders a dropdown and the
    write path rejects anything outside it, so a typo can't produce invalid config.

    Which knobs the settings page SHOWS is deliberately not a field here — it lives in
    ``_visibility.py`` as two readable sets, so "what does a user actually see?" is answerable by
    reading one list rather than by scanning 85 constructor calls (ADR-0122 §6)."""

    field: str
    env: str
    kind: str  # int | float | opt_int | opt_float | bool | str | opt_str
    default: Any
    choices: tuple[str, ...] | None = None


# The operational knobs the Settings page manages. Deliberately EXCLUDES infra /
# bootstrap / secret knobs (API host/port/token, admin token, db_url, sandbox backend/
# image, home) — those stay env-only. Each field here is added to settings_store's
# allow-list; a stored value applies only when the env var is unset (env always wins).
GENERAL_KNOBS: tuple[Knob, ...] = (
    # INTENT profiles (ADR-0122). The Core surface: the operator states how hard to try and how
    # high the bar is, and `_profiles.PROFILE_DERIVED` maps that to the mechanics below. They
    # supply DEFAULTS, never ceilings — an explicitly set knob still wins — which is why they can
    # be added to a shipped install without changing its behaviour.
    #
    # Default UNSET, not "balanced": every profile row differs from at least one shipped default,
    # so a default-on profile would silently re-tune every existing deployment on upgrade (the
    # settings-v2 §44 hazard). Opting in is a deliberate act; until then nothing changes.
    Knob(
        "autonomy_profile",
        "MOSAERA_AUTONOMY_PROFILE",
        "opt_str",
        None,
        AUTONOMY_CHOICES,
    ),
    Knob(
        "quality_profile",
        "MOSAERA_QUALITY_PROFILE",
        "opt_str",
        None,
        QUALITY_CHOICES,
    ),
    Knob(
        "recovery_profile",
        "MOSAERA_RECOVERY_PROFILE",
        "opt_str",
        None,
        RECOVERY_CHOICES,
    ),
    Knob(
        "verification_profile",
        "MOSAERA_VERIFICATION_PROFILE",
        "opt_str",
        None,
        VERIFICATION_CHOICES,
    ),
    # Run budgets & limits
    Knob("run_max_seconds", "MOSAERA_RUN_MAX_SECONDS", "int", 3600),
    Knob("run_max_usd", "MOSAERA_RUN_MAX_USD", "opt_float", None),
    Knob("run_max_tokens", "MOSAERA_RUN_MAX_TOKENS", "opt_int", None),
    Knob("run_max_tool_calls", "MOSAERA_RUN_MAX_TOOL_CALLS", "opt_int", None),
    # Anthropic prompt caching. This workload is ~96-97% INPUT tokens (measured: 440,075/13,058 and
    # 271,490/9,745 on two runs) and each model call is the previous call's messages plus a suffix,
    # which is the shape caching is built for. ON by default; the knob exists so the effect can be
    # A/B'd from one deployment rather than a redeploy. Anthropic-only by construction — Ollama
    # reports no cache metrics, so there is nothing to request and nothing to measure there.
    Knob("prompt_cache_enabled", "MOSAERA_PROMPT_CACHE_ENABLED", "bool", True),
    # How long Ollama keeps a model resident. Its default is 5 MINUTES, and an unload dumps the KV
    # cache — so the local prefix cache, which is automatic and needs no request flag, is silently
    # thrown away whenever a run idles. GUIDED mode is the worst case: a human reading a write gate
    # routinely takes longer than that, and the next call then recomputes the whole transcript. Not
    # a dropdown: a duration string Ollama parses ("30m", "-1" = never unload).
    Knob("ollama_keep_alive", "MOSAERA_OLLAMA_KEEP_ALIVE", "str", "30m"),
    # Daily runs/day quota per account (#37, ADR-0050 addendum): a fairness POLICY, promoted from
    # env-only to a UI knob because it's run-adjacent and read only on the rare POST /runs path. A
    # bounded quantity (>= 0 via coerce), NOT an enumerable set — so a number box, not a dropdown;
    # 0 = no cap. The request-rate limit stays env-only (API-infra, ADR-0005). Enforced in
    # apps/api ratelimit.py, which reads this live so a UI save applies with no restart.
    Knob("run_quota_per_day", "MOSAERA_RUN_QUOTA_PER_DAY", "int", 0),
    Knob("run_hard_max_usd", "MOSAERA_RUN_HARD_MAX_USD", "opt_float", None),
    Knob("run_hard_max_tokens", "MOSAERA_RUN_HARD_MAX_TOKENS", "opt_int", None),
    # RAISED 3 -> 8 (2026-08-07) after measuring what the cap actually does. It is NOT a terminal
    # ceiling — `nodes_impl` only enters the fix loop `if iteration < max_iter`, so at the cap a run
    # walks to the gate with failing tests instead of trying again.
    #
    # Measured over 24 LedgerCLI runs: every DELIVERY converged in 1-2 iterations (1,1,1,2); every
    # failure spent 2-6. The cap has never produced a delivery — it only ever bounds failures, and
    # three other mechanisms bound them better:
    #   * stall_limit + progress.py — fingerprints outcomes and trips on repetition ("not going
    #     anywhere"), which is the question the cap only proxies for;
    #   * honest_stop_projection (#65) — concludes when improving too slowly to converge;
    #   * the budget caps — bound COST directly, and PARK for a human rather than terminating.
    # Concrete harm: run 20260806-225706 authored the correct acceptance tests, hit iteration_limit
    # before implementing, and 1.1M tokens of correct work was discarded. It was progressing; a
    # counter that cannot see progress stopped it.
    #
    # And the cap TRUNCATES THE DATA needed to set it: at 3, no run can teach us that a class of
    # work needs 5. Raised for baseline-gathering — dynamic per-item suggestion needs a
    # distribution first, and n=4 deliveries is not one.
    #
    # COUPLING to know before changing this again: `remaining = ctx.max_iter - iteration` feeds
    # `wont_converge`, so raising the cap also makes the projection guard more lenient. That is
    # intended (more budget genuinely means more chance to converge) but it is not free.
    Knob("max_iterations", "MOSAERA_MAX_ITERATIONS", "int", 8),
    Knob("max_iterations_ceiling", "MOSAERA_MAX_ITERATIONS_CEILING", "int", 12),
    # No-progress breaker
    Knob("stall_detection_enabled", "MOSAERA_STALL_DETECTION", "bool", True),
    Knob("stall_limit", "MOSAERA_STALL_LIMIT", "int", 3),
    # Honest-stop projected non-convergence (#65): conclude early when improving too slowly to pass
    # by the cap (the dominant thrash_park cause), not just on stagnation. Default ON; strict fix.
    Knob("honest_stop_projection", "MOSAERA_HONEST_STOP_PROJECTION", "bool", True),
    # Honest stop when the validator reports NO countable result (#81): a repeatedly-identical
    # failure climbs the same reason→supervise ladder the counted path uses, instead of setting
    # `stalled` and being bucketed as thrash. OFF restores the pre-#81 fingerprint park verbatim.
    # Default OFF — MEASURED, activation HELD (ADR-0077 §Measured result): on MCB-26 the ON arm
    # showed no conversion, Reliability 67 vs 83, and +22% tokens. Same disposition as ADR-0066.
    Knob("honest_stop_no_signal", "MOSAERA_HONEST_STOP_NO_SIGNAL", "bool", False),
    Knob("plan_stall_limit", "MOSAERA_PLAN_STALL_LIMIT", "int", 2),
    Knob("gate_stall_limit", "MOSAERA_GATE_STALL_LIMIT", "int", 2),
    Knob("coder_test_repeat_limit", "MOSAERA_CODER_TEST_REPEAT", "int", 3),
    # Coder read-only probe tool (#55, ADR-0059): a Python-snippet sandbox_exec so the coder
    # observes behaviour instead of writing debug scripts into tests/. Docker-only (read-only work).
    Knob("coder_repl_enabled", "MOSAERA_CODER_REPL", "bool", True),
    # Coder scratch space (#59, ADR-0064): sanctioned `.mosaera/scratch/` write-anything dir, never
    # delivered/graded (info/exclude + _SKIP_DIRS), logged. Closes the #55 tests/-abuse. Default on.
    Knob("coder_scratch_enabled", "MOSAERA_CODER_SCRATCH", "bool", True),
    # Coder fix-loop discipline (#55, ADR-0059): on a failing iteration, require a one-line
    # root-cause HYPOTHESIS before editing and surface the failing-test-count trend (converging?).
    Knob("coder_diagnose_loop", "MOSAERA_CODER_DIAGNOSE", "bool", True),
    # Reduced lane (#118, Approach A): a DETERMINISTICALLY certified non-behavioural change
    # skips design + the Proctor authoring pass. The acceptance class is UNCHANGED — the same
    # gate reads the same evidence model, and the oracle comes from the existing
    # `standing_suite` leg, which already requires baselined tests that assert something real
    # AND reference the changed module. No standing suite that vouches => oracle_unverified =>
    # the run parks, exactly as today. Default OFF, UNMEASURED.
    Knob("reduced_lane", "MOSAERA_REDUCED_LANE", "bool", False),
    # Engine-authored inert oracle (#118, Approach B). On a certified non-behavioural lane the
    # ENGINE writes the acceptance test -- module imports, public surface unchanged -- instead
    # of the Proctor spending a model call inventing one. Adds an assertion that did not exist,
    # so it can only ever refuse MORE; the acceptance class narrows, never widens. Default OFF.
    Knob("inert_oracle_scaffold", "MOSAERA_INERT_ORACLE", "bool", False),
    # Static-site testkit (#129). On a deliverable with no natural harness the Proctor authors
    # verification INFRASTRUCTURE -- a parser, a link checker -- and it is wrong: every one of
    # MCB-02's ten failures across two sweeps was a bug in its own helpers, not in the page.
    # ON installs a tested stdlib module at tests/_statickit.py and points the persona at it.
    # PROMPT-LEVEL, so the model may simply ignore it -- three prompt levers measured NULL this
    # arc. `statickit_used` on the scorecard is how that gets answered rather than assumed.
    Knob("static_testkit", "MOSAERA_STATIC_TESTKIT", "bool", False),
    Knob("max_escalations", "MOSAERA_MAX_ESCALATIONS", "int", 1),
    # Reliability sensitivity (#51, ADR-0056): the dial scaling every self-stop budget to model
    # strength — cautious (weak model: self-stop early, cheap) … persistent (strong model: more
    # rope, more deliveries). balanced = today's budgets. A dropdown so a typo can't break it.
    Knob(
        "reliability_sensitivity",
        "MOSAERA_RELIABILITY_SENSITIVITY",
        "str",
        "balanced",
        choices=("cautious", "balanced", "persistent"),
    ),
    Knob("reason_on_stall_enabled", "MOSAERA_REASON_ON_STALL", "bool", False),
    Knob("max_reason_attempts", "MOSAERA_MAX_REASON_ATTEMPTS", "int", 1),
    # Reasoning
    Knob("stream_reasoning", "MOSAERA_STREAM_REASONING", "bool", True),
    # Quality / review / hygiene loops
    Knob("deliver_unverified", "MOSAERA_DELIVER_UNVERIFIED", "bool", False),
    Knob("quality_revise_enabled", "MOSAERA_QUALITY_REVISE", "bool", False),
    Knob("quality_min", "MOSAERA_QUALITY_MIN", "int", 80),
    Knob("quality_dim_floor", "MOSAERA_QUALITY_DIM_MIN", "int", 70),
    Knob("quality_max_revises", "MOSAERA_QUALITY_MAX_REVISES", "int", 1),
    Knob("review_fix_enabled", "MOSAERA_REVIEW_FIX", "bool", True),
    Knob("review_max_fixes", "MOSAERA_REVIEW_MAX_FIXES", "int", 2),
    Knob("hygiene_gate_enabled", "MOSAERA_HYGIENE_GATE", "bool", True),
    Knob("hygiene_max_fixes", "MOSAERA_HYGIENE_MAX_FIXES", "int", 2),
    Knob("coder_step_limit", "MOSAERA_CODER_STEP_LIMIT", "int", 25),
    Knob("reviewer_step_limit", "MOSAERA_REVIEWER_STEP_LIMIT", "int", 15),
    Knob("tester_step_limit", "MOSAERA_TESTER_STEP_LIMIT", "int", 15),
    Knob("tester_file_cap", "MOSAERA_TESTER_FILE_CAP", "int", 10),
    Knob("tester_enabled", "MOSAERA_TESTER", "bool", False),
    # Test-steward (#54, ADR-0058): the Proctor VALIDATES + REPAIRS the tests against the spec
    # BEFORE the coder runs (coder-blind → ungameable). OFF by default; ON in the autonomous
    # posture (apply_oracle_posture). tester_repairs_tests implies oracle_mutation_check.
    Knob("tester_repairs_tests", "MOSAERA_TESTER_REPAIRS_TESTS", "bool", False),
    # Loosen-only repair (#129). The repair ask does two opposite things; measured over 30
    # paired runs, the loosening works (flagged assertions 15 -> 2) while the strengthening
    # grows suites 24% and raises the over-strictness rate 6.8% -> 10.2%, netting out to a
    # wash on over-park. ON drops the strengthening half. Only meaningful with
    # tester_repairs_tests. Default OFF, UNMEASURED.
    Knob("repair_loosen_only", "MOSAERA_REPAIR_LOOSEN_ONLY", "bool", False),
    # Coder prefetch (#129 slice 4). The coder's opening message carries task + plan + design
    # and NO file contents, so it re-reads from scratch what the DESIGNER was already handed:
    # `build_grounding` renders the plan-named files and only design_node uses it. Cost is
    # round trips x a flat context tax, and the prompt-level lever to cut round trips measured
    # NULL (coder_batch_reads 1/30 vs 0/30) -- so this removes the model's discretion instead
    # of asking for it, the same move that worked in ADR-0124. Precedent: ADR-0059 hands the
    # coder the authored test BODIES for exactly this reason.
    #
    # NOT obviously a win: the opening message is re-sent every turn, so prefetched content is
    # paid on EVERY round trip while saving only the first few reads. Whether that nets out is
    # the measurement, and `calls` and `total_tokens` are both on the scorecard. Default OFF.
    Knob("coder_prefetch", "MOSAERA_CODER_PREFETCH", "bool", False),
    # Proctor faithfulness guard (#57, ADR-0062): deterministic detector names over-strict authored
    # assertions for the repair turn to loosen. OFF by default; ON in the autonomous posture.
    Knob("proctor_faithfulness_guard", "MOSAERA_PROCTOR_FAITHFULNESS_GUARD", "bool", False),
    # Held-out critic (#60, ADR-0065): a veto-only, different-model judge of outcome between review
    # and the gate. OFF by default; ON in the autonomous posture (it IS the correctness gate).
    Knob("critic_enabled", "MOSAERA_CRITIC_ENABLED", "bool", False),
    # #61: the claims-protocol critic (per-claim REFUTED/SUPPORTED/INSUFFICIENT + the
    # deterministic quote verifier in critic_policy). Default OFF; activation only via a
    # fingerprint-validated A/B (ADR-0081 discipline).
    Knob("critic_claim_protocol", "MOSAERA_CRITIC_CLAIM_PROTOCOL", "bool", False),
    # Behaviour-preservation Proctor (#60, ADR-0066): inject differential-golden-master + loose-
    # structural authoring guidance for a detected refactor task. OFF by default; ON in the posture.
    Knob("behavior_preservation_guard", "MOSAERA_BEHAVIOR_PRESERVATION_GUARD", "bool", False),
    # Deterministic refactor-oracle scaffold (#60, ADR-0066 follow-up): the ENGINE authors the
    # differential golden-master for a detected refactor. OFF by default; ON in the posture.
    Knob("refactor_oracle_scaffold", "MOSAERA_REFACTOR_ORACLE_SCAFFOLD", "bool", False),
    Knob("oracle_mutation_check", "MOSAERA_ORACLE_MUTATION_CHECK", "bool", False),
    # NOTE: `oracle_mutation_vetoes` is deliberately NOT here. It relaxes a delivery-gate veto, so
    # surfacing it in the settings UI would let an admin disable a safety control from the
    # dashboard — a product-surface decision that needs its own ADR, not a side effect of an
    # experiment. It is env-only (MOSAERA_ORACLE_MUTATION_VETOES), built in `_from_env.py`
    # alongside the other env-only fields.
    # Comprehensive mutation (ADR-0071): mutate EVERY changed construct, require ALL caught. Default
    # OFF; posture activation HELD pending measurement. Needs oracle_mutation_check.
    Knob("oracle_mutation_comprehensive", "MOSAERA_ORACLE_MUTATION_COMPREHENSIVE", "bool", False),
    # Structural-spec oracle (#80/ADR-0072): deterministic AST check that a refactor met the
    # requested shape (short orchestrator + >= N helpers). Downgrade-only. Default OFF; posture
    # activation withdrawn 2026-08-02 (null n=25/arm A/B).
    Knob("oracle_structural_spec", "MOSAERA_ORACLE_STRUCTURAL_SPEC", "bool", False),
    Knob("oracle_coverage", "MOSAERA_ORACLE_COVERAGE", "bool", False),
    Knob("onboarding_map_scoping", "MOSAERA_ONBOARDING_MAP_SCOPING", "bool", False),
    Knob("model_escalation_enabled", "MOSAERA_MODEL_ESCALATION", "bool", False),
    Knob("max_model_escalations", "MOSAERA_MAX_MODEL_ESCALATIONS", "int", 2),
    # Off-box egress consent (ADR-0024): OFF by default → autonomous runs stay LOCAL-ONLY.
    # ON lets autonomous escalation/reason ladders (and cloud primary bindings) use CLOUD
    # models — which send repo content off-box to a third-party API — but ONLY when the model
    # is also priced (so the USD cap can bound it). Guided/ad-hoc runs are never gated here.
    Knob("allow_cloud_egress", "MOSAERA_ALLOW_CLOUD_EGRESS", "bool", False),
    # Resilient autonomous sweep (ADR-0023): when ON (default), a stuck item is DEFERRED
    # (surfaced with its reason) and the sweep keeps delivering the rest — instead of the
    # whole project halting on one stuck item. resilient_recuration adds an opt-in Quincy
    # re-curation attempt (split/re-scope the stuck item) before deferring (an LLM call).
    Knob("resilient_sweep", "MOSAERA_RESILIENT_SWEEP", "bool", True),
    Knob("resilient_recuration", "MOSAERA_RESILIENT_RECURATION", "bool", False),
    # Layer-2 park→ship disposition (ADR-0074/#76): when an autonomous item honest-parks on
    # oracle_unverified (green, but the tests are the coder's own), Quincy authors an INDEPENDENT
    # asserting test and re-runs the REAL oracle — green + mutation-proven ships VERIFIED, else
    # stays parked. NEVER an LLM green-light. Default OFF (it can cause a ship — measure first).
    Knob("disposition_gap_close", "MOSAERA_DISPOSITION_GAP_CLOSE", "bool", False),
    # The ESCALATE arm (#64 F49) — the close-the-gap arm's opposite. When the producer raises its
    # hand AND every failing test is one it may not edit, a re-scope cannot help: it just sends the
    # producer back at the same wall until the iteration cap (measured 6/6 on the guided corpus).
    # ON: the run stops promptly and honestly, and the ITEM gets a one-click question for the
    # operator. It never ships and never edits a test — only the operator owns requirements.
    # Default OFF: it changes when runs park, so it earns activation with measurement.
    Knob("escalate_arm", "MOSAERA_ESCALATE_ARM", "bool", False),
    # The escalation-gate AMENDMENT (ADR-0087, #65). The ESCALATE arm above stops and asks — and
    # then ignores the answer: an oracle conflict forces give-up whatever the operator says, so a
    # delivered test can never be legitimately amended and any item whose PURPOSE is to change
    # behaviour deadlocks. ON, the operator may authorize amending the specific blocking test(s);
    # the PROCTOR (never the coder) rewrites them, once, and the result lands in `proctor_edits`
    # under the existing content-pinned rule. Default OFF: it is a new authority path over the
    # ADR-0036 trust boundary, so OFF must stay byte-identical to today and it earns activation
    # with measurement — the same bar `escalate_arm` had.
    Knob("amendment_gate", "MOSAERA_AMENDMENT_GATE", "bool", False),
    # Acceptance spec-lint at the decompose boundary (ADR-0073): deterministic detection of
    # over-specified/collision-prone acceptance in a freshly-generated backlog + ONE bounded
    # Quincy re-curate pass. Detection is free; the pass is one PM call when findings exist.
    Knob("backlog_spec_lint", "MOSAERA_BACKLOG_SPEC_LINT", "bool", True),
    # Standing decisions (ADR-0082 tier 2): a ratified clause fills in a number the brief left
    # open and stops the same question being asked on the next item. Default OFF — with no clause
    # ratified the system is byte-identical to today, and ADR-0082's definition-of-done requires a
    # clauses ON-vs-OFF bench A/B ("clauses must not move false_ship"). A knob added AFTER the
    # measurement is a story, not an experiment.
    Knob("clauses_enabled", "MOSAERA_CLAUSES", "bool", False),
    # Intake ask on the DECIDABILITY axis (ADR-0080 §1): an item whose check binds but whose text
    # never fixes the answer raises ONE operator question at decompose, instead of Quincy silently
    # inventing the answer. Default OFF — ADR-0080 names clarification fatigue as the hazard and
    # the ask-rate as a measured dial. NOT dependent on clauses_enabled: with clauses off nothing
    # is settled, so MORE asks fire, which is the strict direction.
    Knob("intake_ask_undecidable", "MOSAERA_INTAKE_ASK_UNDECIDABLE", "bool", False),
    # F76/#78. Default OFF like its sibling: the ask-rate is a measured dial and a false ask
    # blocks legitimate work behind a question. The VERDICT is derived and displayed either way,
    # so the signal is visible before it is binding.
    Knob("intake_ask_unreachable", "MOSAERA_INTAKE_ASK_UNREACHABLE", "bool", False),
    # The PM planner's read-tool budget. Raised 12 -> 20 on 2026-08-07 after it was measured
    # spending ALL of it: the planner made ~10 read calls (list_files, 4x file_read, 3x search)
    # on a five-slice repo and had none left to WRITE the plan, so it silently returned the
    # fallback -- twice -- and the run parked telling the operator their ITEM needed
    # clarification. It was the smallest budget in the system (coder 25, reviewer 15, tester
    # 15) despite being the only agent that must both explore AND write, and it serves BOTH
    # plan and design. 20 leaves room for both; still below the coder.
    # HYPOTHESIS, not a proven fix -- if a run still falls back, `plan_fallback_reason` now
    # says which of budget/transport/empty it was, in one line (F39, issue #71).
    Knob("pm_step_limit", "MOSAERA_PM_STEP_LIMIT", "int", 20),
    # Lets the PM CHAT look things up mid-conversation instead of answering from whatever the
    # server guessed to assemble (ADR-0111, slice 3 of docs/design/agentic-pm-chat.md). Read-only
    # ledger queries only; the repository stays out of the chat.
    #
    # OFF by default, and OFF is byte-identical to the single call it replaces — that is what
    # makes turning it on a clean before/after rather than a confound, and what keeps the QMB
    # chat arm unchanged. Turning it on costs several model calls per turn, so it wants the
    # streaming work (slice 4) before anyone but the author flips it.
    Knob("pm_chat_tools", "MOSAERA_PM_CHAT_TOOLS", "bool", False),
    Knob("doctrine_enabled", "MOSAERA_DOCTRINE", "bool", True),
    # Autonomous delivery last-mile (ADR-0019)
    Knob("auto_open_mr", "MOSAERA_AUTO_OPEN_MR", "bool", False),
    # Revertable per-item merge requests (ADR-0021): the SHAPE of the auto-opened
    # MR — "item" = one stacked MR per backlog item (reviewable + revertable),
    # "project" = one whole-project MR (the ADR-0019 behavior). Gated by auto_open_mr.
    Knob(
        "mr_granularity",
        "MOSAERA_MR_GRANULARITY",
        "str",
        "item",
        choices=("item", "project"),
    ),
    # Autonomous correctness gate (ADR-0020)
    Knob("autonomous_verified", "MOSAERA_AUTONOMOUS_VERIFIED", "bool", True),
    # Who may DESTROY delivery branches (ADR-0004 amendment, red-team 2026-08-18 finding 6).
    # Default OFF = prune + single-branch delete are admin-only. A member may drive delivery end
    # to end, but spending an admin-INSTALLED credential irreversibly on the real repository is a
    # separate authority — installing the project token is admin-gated, so spending it destructively
    # should be too. `retarget` is deliberately NOT covered: it destroys nothing and is how a member
    # unsticks their own MR. Read on the live path in routes/project_delivery.py — see the
    # reviewer_advisory note below for why a knob that gates nothing is worse than no knob.
    Knob("member_branch_delete", "MOSAERA_MEMBER_BRANCH_DELETE", "bool", False),
    # NOTE: `reviewer_advisory` was REMOVED (#81 cleanup). ADR-0029 introduced it as an off-switch
    # for the reviewer-silence backstop, but ADR-0031 → ADR-0034 rebuilt that backstop as a pure
    # deterministic conjunction in `policies/gate.py` (`reviewer_unknown` sole blocker AND
    # tests_passed AND strength=="suite"), which never read the knob. It had ZERO engine reads while
    # still presenting an ON toggle over gate policy in the UI — an honesty hazard, not a control.
    # Sandbox
    Knob("scan_enabled", "MOSAERA_SCAN", "bool", True),
    Knob("sandbox_timeout", "MOSAERA_SANDBOX_TIMEOUT", "int", 300),
    Knob("sandbox_install", "MOSAERA_SANDBOX_INSTALL", "bool", True),
    Knob("sandbox_install_timeout", "MOSAERA_SANDBOX_INSTALL_TIMEOUT", "int", 600),
    Knob(
        "sandbox_install_network",
        "MOSAERA_SANDBOX_INSTALL_NETWORK",
        "str",
        "bridge",
        # "host" was here and is GONE (ADR-0035). `--network host` shares the HOST network
        # namespace with the target repo's install code (setup.py, npm postinstall), which
        # then reaches the loopback-open Mosaera API, Ollama, and the dev Postgres. It was
        # an ordinary dropdown option with no warning. Removing it from `choices` only
        # closes the UI write path — the sandbox clamps the value too (create_sandbox), since
        # a stored settings.json, an env var, and a direct constructor call all bypass this.
        choices=("bridge", "none"),
    ),
    Knob("sandbox_index_url", "MOSAERA_SANDBOX_INDEX_URL", "opt_str", None),
    # Ollama tuning
    Knob("ollama_base_url", "MOSAERA_OLLAMA_BASE_URL", "str", DEFAULT_OLLAMA_BASE_URL),
    # RAISED 16384 -> 32768 (2026-08-07). At 16k a tool-using agent on a five-slice repo runs
    # out of CONTEXT before it can answer, and the failure is silent: the prompt grows with each
    # tool result until the model is cut off mid-generation and returns empty content, which the
    # engine reads as "the agent produced nothing". Measured on the PM planner, from the
    # fallback-evidence capture (#71, F39) — three consecutive calls:
    #     in=15027 out=182  done_reason='stop'
    #     in=16155 out=165  done_reason='stop'
    #     in=16374 out=10   done_reason='length'   <- ten tokens of headroom left
    # Raising it produced the first grounded plan of the day on the very next run.
    #
    # This cost roughly a day to find because THREE layers misreported it: the planner returned
    # the fallback silently, the graph blamed the ITEM ("needs clarification"), and the gate said
    # "validation unavailable" — sending the operator to check Docker. All three now say what
    # actually happened, but the DEFAULT is what stops anyone else paying that price.
    #
    # NOT free: this ~doubles KV-cache VRAM for EVERY role, on every deployment. Chosen anyway —
    # a silent truncation that reads as incapacity is worse than a memory cost you can see and
    # tune down. A constrained box should set MOSAERA_OLLAMA_NUM_CTX back to 16384 deliberately.
    Knob("ollama_num_ctx", "MOSAERA_OLLAMA_NUM_CTX", "int", 32768),
    Knob("coder_num_ctx", "MOSAERA_OLLAMA_NUM_CTX_CODER", "opt_int", None),
    Knob("ollama_timeout", "MOSAERA_OLLAMA_TIMEOUT", "float", 300.0),
)


def _coerce_knob(kind: str, raw: Any) -> Any:
    """Coerce a raw value (env string, or JSON scalar from settings.json) to the knob's
    type. Returns None for absent/blank/malformed so a layer falls through to the next.
    A bool ``"0"``/``False`` is a real value (returns False), not a fall-through."""
    if raw is None:
        return None
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        return None if s == "" else s not in ("0", "false", "no")
    value: Any = raw.strip() if isinstance(raw, str) else raw
    if isinstance(value, str) and value == "":
        return None
    try:
        if kind in ("int", "opt_int"):
            return int(value)
        if kind in ("float", "opt_float"):
            return float(value)
    except (ValueError, TypeError):
        return None
    return str(value) if kind in ("str", "opt_str") else None


def _layer_knob(
    e: Mapping[str, str],
    stored: Mapping[str, Any],
    k: Knob,
    derived: Mapping[str, Any] | None = None,
) -> Any:
    env_v = _coerce_knob(k.kind, e.get(k.env))
    if env_v is not None:
        return env_v
    stored_v = _coerce_knob(k.kind, stored.get(k.field))
    if stored_v is not None:
        return stored_v
    if derived is not None and k.field in derived:
        return derived[k.field]
    return k.default


def selected_profiles(e: Mapping[str, str], stored: Mapping[str, Any]) -> dict[str, Any]:
    """The env > stored > default choice of each of the four profile knobs (ADR-0122)."""
    return {k.field: _layer_knob(e, stored, k) for k in GENERAL_KNOBS if k.field in PROFILE_DERIVED}


def layer_knobs(e: Mapping[str, str], stored: Mapping[str, Any]) -> dict[str, Any]:
    """Effective value for every GENERAL_KNOB, as a kwargs dict.

    Precedence is ``env > stored > profile > default`` (ADR-0122). The profile layer sits BELOW
    stored on purpose: it may only supply a value the operator never set, so selecting a profile
    can neither override nor weaken an explicit setting. With no profile selected the profile
    layer is empty and this reduces exactly to the ``env > stored > default`` of ADR-0005.
    """
    derived = resolve_profiles(selected_profiles(e, stored))
    return {k.field: _layer_knob(e, stored, k, derived) for k in GENERAL_KNOBS}


def coerce_general_patch(patch: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a UI settings patch against the knob spec for ``write_settings``: unknown
    fields dropped; ``None`` = unset (delete the stored key); numbers must be >= 0
    (raises ValueError otherwise); blank/invalid values are skipped (left unchanged)."""
    by_field = {k.field: k for k in GENERAL_KNOBS}
    out: dict[str, Any] = {}
    for field_name, raw in patch.items():
        k = by_field.get(field_name)
        if k is None:
            continue
        if raw is None:
            out[field_name] = None  # unset
            continue
        value = _coerce_knob(k.kind, raw)
        if value is None:
            continue  # blank/invalid → leave as-is
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
            raise ValueError(f"{field_name} must be >= 0")
        if k.choices is not None and str(value) not in k.choices:
            raise ValueError(f"{field_name} must be one of {', '.join(k.choices)}")
        out[field_name] = value
    return out
