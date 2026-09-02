"""The ``Settings`` dataclass + ``from_env`` layering (top of the config chain)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mosaera_core.config._paths import RunPaths
from mosaera_core.config._types import (
    DEFAULT_OLLAMA_BASE_URL,
    ProviderConfig,
    Role,
    RoleModel,
)


@dataclass(frozen=True)
class Settings(RunPaths):
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    # PM stays gpt-oss:20b: a reasoning-family model AND a reliable tool-caller — both properties
    # the tool-using planner needs. deepseek-r1:32b reasons better but emits no tool calls on
    # Ollama (verified 2026-07-11); a stronger PM comes from the BYOM seam instead.
    pm_model: str = "gpt-oss:20b"
    coder_model: str = "qwen3-coder:30b"
    reviewer_model: str = "gpt-oss:20b"
    # The tester authors acceptance tests (code), so it defaults to the coder model.
    tester_model: str = "qwen3-coder:30b"
    # The held-out critic (#60, ADR-0065): a veto-only, once-per-delivery judge of OUTCOME,
    # deliberately a DIFFERENT model from the coder so it is an INDEPENDENT check (held_out_ok).
    # Defaults to a local reasoning model (≠ coder's qwen3-coder) — $0, on-box, some judgment;
    # a stronger cloud tier is opt-in via role_escalation["critic"] (measured in MR-D).
    critic_model: str = "gpt-oss:20b"
    embed_model: str = "nomic-embed-text"
    # Ollama context window: the server default (2048) silently truncates our prompts (file
    # listings, plans, feedback). RAISED 16384 -> 32768 (2026-08-07) after 16k was MEASURED
    # insufficient for a tool-using agent on a five-slice repo — see `_knobs.py` for the numbers.
    # Both default models support >= 32k. Costs KV-cache VRAM on every role; see coder_num_ctx.
    ollama_num_ctx: int = 32768
    # Opt-in larger context for the coder ONLY (it accumulates the biggest
    # transcript). None → use ollama_num_ctx. A bigger value ~doubles the coder's
    # KV-cache VRAM, so it's opt-in via MOSAERA_OLLAMA_NUM_CTX_CODER.
    coder_num_ctx: int | None = None
    # httpx timeout per model call — a hung Ollama can't wedge a run; mirrors sandbox_timeout.
    ollama_timeout: float = 300.0
    home: Path = Path(".mosaera")
    sandbox_timeout: int = 300
    # Per-run wall-clock cap (autonomous chains run one item per run).
    run_max_seconds: int = 3600
    # Per-run spend ceilings (governance gate; None = off). When live spend crosses
    # one, the run PARKS for approval — raise the ceiling and continue, or stop —
    # it does not hard-fail. Checked between graph nodes off the live CostMeter, so
    # a single node can overshoot: this bounds the loop, not any one call. The
    # iteration dimension is the existing max_iterations.
    run_max_usd: float | None = None
    prompt_cache_enabled: bool = True  # anthropic-only; rationale in GENERAL_KNOBS
    ollama_keep_alive: str = "30m"  # model residency == local KV cache; see GENERAL_KNOBS
    run_max_tokens: int | None = None
    run_max_tool_calls: int | None = None
    # Daily runs/day quota per account (#37); 0 = no cap. Read live by apps/api ratelimit.py.
    run_quota_per_day: int = 0
    # Absolute HARD ceilings: unlike run_max_* (which park and can be raised), these
    # CANCEL the run outright when crossed — a non-re-askable backstop so a
    # non-converging run can never be funded forever. Off (None) by default.
    run_hard_max_usd: float | None = None
    run_hard_max_tokens: int | None = None
    sandbox_backend: str = "docker"
    sandbox_image: str = "mosaera-sandbox:dev"
    scan_image: str = "mosaera-scan:dev"
    scan_enabled: bool = True
    # Whether the coder gets a (human-gated, path-confined) delete_file tool. OFF by
    # default — deletion is destructive, so it is an opt-in capability an admin
    # enables. When off, deletion stays out of capability (surfaced as manual steps).
    delete_tool_enabled: bool = False
    # Autonomous MR last-mile (ADR-0019): when ON, an autonomous sweep OPENS the project
    # merge request (never merges — a human still merges) once the whole backlog is
    # delivered. OFF by default — auto-opening is an outward action, so it is an explicit
    # opt-in distinct from the project's autonomous flag; reuses the scoped-token,
    # write_repository-only push-options path. See docs/threat-models/TM-0002.
    auto_open_mr: bool = False
    # Revertable per-item MRs (ADR-0021): the shape of the auto-opened MR. "item" (default)
    # opens one stacked MR per backlog item — each a small, independently reviewable +
    # revertable change; "project" keeps the single whole-project MR (ADR-0019). Only takes
    # effect when auto_open_mr is on.
    mr_granularity: str = "item"
    # Autonomous correctness gate (ADR-0020): when ON, an autonomous run gets a verify+recover
    # overlay — the test-first tester (Proctor) authors spec-derived acceptance tests that flow
    # into `tests_passed` (an independent, EXECUTED oracle the reviewer/own-suite can't be), and
    # reason-on-stall recovery. ON by default — auto-delivering UNVERIFIED code is the risk; an
    # operator can turn it off for speed. Autonomous-only; guided/HA/ad-hoc runs are untouched.
    autonomous_verified: bool = True
    # Branch DESTRUCTION is admin-only unless an admin opts members in (ADR-0004 amendment).
    member_branch_delete: bool = False
    docker_bin: str = "docker"
    # Dependency install for validation. ON by default so real repos validate
    # (and autonomous stops parking on ModuleNotFoundError). The install phase
    # opens egress (install_network) ONLY during install; the test phase stays
    # network-off. Kill switches: sandbox_install=False (no install, honest
    # fail) or sandbox_install_network="none" (venv-create, no egress).
    sandbox_install: bool = True
    sandbox_install_timeout: int = 600
    sandbox_install_network: str = "bridge"
    sandbox_index_url: str | None = None
    # A DSN carries a password (`postgresql://user:pass@host/db`) — a credential, not a setting.
    db_url: str | None = field(default=None, repr=False)
    gitlab_url: str = "https://gitlab.rengifo.me"
    # GitLab OAuth "Connect" (ADR-0104): env-only (never settings.json/client). Endpoints DERIVE
    # from gitlab_url (self-hosted first; gitlab.com never hardcoded) so the OAuth app must be
    # registered there; base_url is this instance's public origin for the exact redirect_uri.
    gitlab_oauth_client_id: str | None = field(default=None, repr=False)
    gitlab_oauth_client_secret: str | None = field(default=None, repr=False)
    base_url: str | None = None
    # repr=False on every secret: Settings is passed all over the engine, so it lands in
    # exception messages and log lines nobody wrote deliberately (see ProviderConfig.__repr__).
    gitlab_token: str | None = field(default=None, repr=False)
    # GitHub App delivery (ADR-0114). NOT an OAuth app: GitHub's setup-URL redirect carries a
    # spoofable installation_id, so Mosaera never reads one — it signs a JWT with this key and
    # asks GitHub which installation owns the project's own repo. `slug` builds the install
    # link shown to the operator; `api_url` is configurable rather than hardcoded, matching
    # ADR-0104's rule that a provider host is derived, never assumed.
    github_app_id: str | None = None
    github_app_private_key: str | None = field(default=None, repr=False)
    github_app_slug: str | None = None
    github_api_url: str = "https://api.github.com"
    # The SAME GitHub App's user-authorization credentials (ADR-0120). A GitHub App issues a
    # client id + secret at registration, so repo creation adds no second app to register —
    # these come off the settings page the operator is already on for the App id and key.
    # Used only to exchange an authorization code for a user token, which creates the repo and
    # is discarded in the same request; delivery keeps using installation tokens exclusively.
    github_oauth_client_id: str | None = field(default=None, repr=False)
    github_oauth_client_secret: str | None = field(default=None, repr=False)
    # Where the user is sent to authorize — the OAuth host, not the API host. Separate from
    # github_api_url so GHES (which splits them) works without special-casing.
    github_web_url: str = "https://github.com"
    # Per-model API prices (input, output $/1M tokens) for cost accounting.
    # UI-managed (settings.json) with MOSAERA_MODEL_PRICES as a per-model env
    # override; local models are absent → free.
    model_prices: dict[str, tuple[float, ...]] = field(default_factory=dict)
    # BYOM (#21): per-role provider override (role → init_chat_model provider id)
    # and provider credentials (provider id → ProviderConfig). Both empty by
    # default → every role resolves to Ollama at ollama_base_url (local-first).
    role_providers: dict[str, str] = field(default_factory=dict)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    # Cost-modes (#7): named per-role model profiles (Economy/Balanced/Premium).
    # cost_modes maps mode -> role -> RoleModel override; a role a mode omits
    # falls back to the base BYOM binding. active_cost_mode is the per-run overlay
    # (never persisted); default_cost_mode applies when a run picks none. All
    # empty by default → every mode resolves to the base binding (identical to pre-#7 behaviour).
    cost_modes: dict[str, dict[str, RoleModel]] = field(default_factory=dict)
    # Model escalation ladder (the DNA escalation ladder made runtime): role ->
    # ORDERED [RoleModel] tiers, tier 0 the cheapest starting model. When a run
    # fails to deliver, a DETERMINISTIC diagnosis attributes the bottleneck to ONE
    # role and that role alone is bumped one tier (cost discipline). Empty by default
    # → no escalation. Cloud tiers are OPERATOR-configured (no default cloud tier),
    # so escalation never auto-sends repo content off-box unless the operator put a
    # hosted model on the ladder. Benchmark-driven first cut (see ADR-0016).
    role_escalation: dict[str, list[RoleModel]] = field(default_factory=dict)
    # Reasoning-escalation ladder (ADR-0018): ORDERED reasoning tiers the reason node
    # climbs when the coder's own-model reason pass (ADR-0017) doesn't unstick it. Tier
    # index = reason_attempts - 1 (index 0 is the first escalation above the own-model
    # pass). Each tier is a one-off, TOOL-LESS reasoner call whose plan is handed back
    # down to the cheap coder. Empty by default (opt-in, needs reason_on_stall_enabled).
    # LOCAL-ONLY this cut — a hosted tier is dropped at runtime (provider_is_local guard);
    # cloud tiers are deferred until a live-egress gate + a hosted-tier-price check exist.
    reason_escalation: list[RoleModel] = field(default_factory=list)
    default_cost_mode: str = "balanced"
    active_cost_mode: str | None = None
    max_iterations: int = 3
    # Hard ceiling on max_iterations regardless of caller/UI input. Each iteration is
    # several graph super-steps, so an unbounded value (the UI once sent 999 for
    # "Unlimited") blows past the LangGraph recursion_limit and crashes the run with
    # GraphRecursionError instead of parking. Kept well under that headroom.
    max_iterations_ceiling: int = 12
    # No-progress circuit breaker: when a run produces the SAME failing validation or
    # the SAME reviewer rejection stall_limit times in a row, it is not converging —
    # stop and park honestly ("I can't complete this") instead of looping to the cap
    # or asking a human to fund more of the same loop. On by default (a safety guard);
    # stall_limit is conservative so a slow-but-progressing run is not cut off.
    stall_detection_enabled: bool = True
    stall_limit: int = 3
    # Honest-stop projected non-convergence (#65): when ON, the fix loop also concludes early (an
    # honest_park below the cap) when it is improving too SLOWLY to reach a green suite by the
    # iteration cap — not just on stagnation/oscillation (the streak breaker). Closes the dominant
    # thrash_park cause a weak coder produces: a 12→10→8→6 crawl that inches toward a bar it won't
    # clear in budget and otherwise rides to the cap. Conservative (optimistic average-rate
    # projection) so it never trips a run that would converge. Default ON; a strict thrash-reducer.
    honest_stop_projection: bool = True
    # Honest stop on an UNCOUNTABLE validator (#81). ADR-0060 deliberately left this branch as a
    # thrash park, reasoning that with no count signal a relabel would only flatter the metric.
    # That reasoning held while no language could count; SQL and Node now can (ADR-0032 packs +
    # LanguagePack.interpret), so the residual uncountable set is small and genuinely uncountable
    # — a well-formedness check, a schema that never applied, an operator --test-cmd. For those,
    # the run still earns its conclusion: the trip fires only after real fix iterations, the
    # give-up lands strictly BELOW the cap, and the reason names a concrete failure signature
    # rather than an anonymous "same way N times". Rode-to-cap remains thrash either way.
    # DEFAULT OFF — built, MEASURED, activation HELD (ADR-0077 §Measured result), the same
    # disposition ADR-0066 took. On MCB-26 (the exact case #81 was diagnosed on) the ON arm showed
    # NO conversion to honest_park, Reliability 67 vs 83 OFF, and +22% tokens. The likely mechanism
    # is that a granted re-scope consumes iterations and then rides to the cap — which is thrash,
    # i.e. worse than the immediate park it replaced. The MECHANISM is sound and tested; what is
    # missing is measured benefit, so it ships dormant rather than flattering a metric.
    # ON restores the honest ladder for uncountable validators (see _no_signal_path).
    honest_stop_no_signal: bool = False
    # Plan-level no-progress breaker (#51, ADR-0056): how many consecutive fallback/identical
    # plans before the run self-stops as an HONEST EARLY park (route plan→gate) instead of
    # burning design+implement then the supervise give-up (which sets stalled → thrash_park).
    # Kept <= 2 at balanced so it intercepts the supervise give-up (which fires at plan attempt
    # 2 when max_escalations=1). Scaled by reliability_sensitivity (cautious=1 … persistent=3).
    plan_stall_limit: int = 2
    # Gate-loop honest-stop (#67, ADR-0069): consecutive SAME-reason gate denials before an honest
    # give-up (the gate-deny → re-plan loop's breaker). Low (a gate cycle is a full re-plan =
    # several iterations); scaled by reliability_sensitivity (cautious=1 … persistent=3).
    gate_stall_limit: int = 2
    # Reliability sensitivity (#51, ADR-0056): the DIAL over every self-stop budget, scaled to
    # model strength — a strong model gets more rope (tries harder → delivers more), a weak model
    # self-stops early (parks honestly, cheaply). "balanced" is identity (today's budgets); the
    # scaling stays within max_iterations_ceiling so a future posture (ADR-0046) composes. Applied
    # once via apply_reliability_sensitivity in build_graph. User-declared (strength isn't stored).
    reliability_sensitivity: str = "balanced"  # cautious | balanced | persistent
    # Within one implement session the coder can re-run run_tests itself; if it returns
    # the SAME failure this many times with no intervening code change, run_tests hands
    # it a STOP directive to yield ('SUMMARY: blocked/escalate — …') instead of burning
    # its step budget re-running. Kept <= stall_limit so this cheap intra-node guard
    # fires before the inter-node breaker gets a second identical outcome.
    coder_test_repeat_limit: int = 3
    # Coder read-only probe tool (#55, ADR-0059): sandbox_exec runs a Python snippet in the sandbox
    # with the workspace mounted READ-ONLY so the coder observes behaviour instead of littering
    # tests/ with debug scripts. Docker-only (the subprocess backend can't enforce read-only → the
    # tool reports itself unavailable there). Built + advertised only when this is on.
    coder_repl_enabled: bool = True
    # Coder scratch space (#59, ADR-0064; ADR-0063 workbench): when on, `.mosaera/scratch/` in the
    # clone is a sanctioned write-anything space for throwaway probes/fixtures/notes — the coder may
    # write ANY name there (the debug/scratch-name refusal is lifted), it is NEVER delivered or
    # graded (excluded via .git/info/exclude, hidden by _SKIP_DIRS), and its writes are logged. It
    # closes the #55 tests/-abuse by giving the coder the scratch a capable agent needs. Default on.
    coder_scratch_enabled: bool = True
    # Coder fix-loop discipline (#55, ADR-0059): on a failing validation, the fix prompt requires a
    # one-line root-cause HYPOTHESIS before editing and shows the failing-count trend, so a weak
    # coder diagnoses instead of guess-and-rerun. Default on; the bench can A/B it.
    coder_diagnose_loop: bool = True
    # #118 lanes for a certified non-behavioural change. Both default OFF; the trade between
    # them, and why neither widens the acceptance class, is on the knobs in _knobs.py.
    reduced_lane: bool = False
    inert_oracle_scaffold: bool = False
    static_testkit: bool = False  # #129: tested static-site helpers; see the knob
    # Cohesive-team supervisor (ADR-0012): when an agent raises a hand (SUMMARY: blocked/
    # escalate), the mode-gated supervisor resolves it (autonomous → Quincy re-scopes,
    # recorded/non-blocking; guided/high_assurance → park for a human). This caps the
    # re-scope↔re-block round-trips before it gives up and finalizes honestly; 1 = a
    # single re-scope attempt, then honest incomplete.
    max_escalations: int = 1
    # Reason-before-park (ADR-0017): on the FIRST no-progress trip, instead of parking,
    # run ONE bounded reasoning pass with the coder's OWN model — "state the root cause,
    # take a DIFFERENT approach" — reset that loop's stall streak, and re-enter. Only if it
    # STILL repeats does the run park (today's behavior), now with a reasoned note. OFF by
    # default (opt-in). max_reason_attempts bounds it per RUN (default 1 = a single pass);
    # for a fresh multi-attempt retry the operator wants max_iterations > stall_limit.
    reason_on_stall_enabled: bool = False
    max_reason_attempts: int = 1
    # Deliver-with-caveat: when a project type has no automated validator (JS, or an
    # unrecognized repo), the gate parks forever. With this ON, such a run delivers
    # instead — the reviewer still gates acceptance — recorded honestly as
    # "unverified", not "pass". OFF by default (today's park behavior).
    deliver_unverified: bool = False
    # Phase-2 quality-revise loop (advisory ring graduating to a self-improvement
    # gate). OFF by default → Phase-1 advisory-only behavior. When on, a below-bar
    # change loops back for a targeted per-dimension revision before the delivery
    # gate; best-effort (never blocks working code). quality_max_revises bounds quality's
    # OWN revises within max_iterations (all coder loops share the one iteration budget —
    # see review_max_fixes for the honest cross-loop behaviour).
    quality_revise_enabled: bool = False
    quality_min: int = 80  # composite floor (0..100)
    quality_dim_floor: int = 70  # per-dimension floor (0..100)
    quality_max_revises: int = 1
    # Reviewer↔coder auto-fix loop: a reviewer REQUEST_CHANGES verdict routes back to a
    # TARGETED coder revise (bypassing plan/design) before the delivery gate, so the human
    # gate is reserved for delivery. ON by default — the correctness analogue of the
    # always-on test self-heal (fix_node); the no-progress breaker stops a loop that keeps
    # drawing the same rejection. Shares the max_iterations budget.
    review_fix_enabled: bool = True
    # Sub-cap on reviewer-fix revises (mirrors hygiene/quality sub-caps). Honest note on
    # cross-loop behaviour: all coder loops (fix / hygiene_fix / review_fix / quality_revise)
    # share the SINGLE max_iterations budget, so an earlier loop (e.g. cosmetic hygiene,
    # sequenced before correctness review) CAN consume it before a later loop runs. This
    # degrades safely — an out-of-budget run proceeds to the gate and parks honestly; it
    # never ships un-reviewed work. Each sub-cap bounds its own loop's count, not the run.
    review_max_fixes: int = 2
    # In-loop hygiene gate: after tests pass, auto-format + apply safe lint autofixes
    # (deterministic, no model), then loop the coder on the residual BLOCKING issues
    # (mypy type errors + ruff F-class real-bug lint). ON by default, Python-only,
    # best-effort. hygiene_max_fixes bounds hygiene's OWN loop within max_iterations
    # (see review_max_fixes for the shared-budget behaviour).
    hygiene_gate_enabled: bool = True
    hygiene_max_fixes: int = 2
    # Stream each agent turn's reasoning (its narration/CoT) to the run transcript so
    # the box is open — what each agent is thinking, not just what it did. ON by
    # default; message-granularity (one block per model turn), never a token firehose.
    stream_reasoning: bool = True
    # Model calls the coder may make per implement invocation before it STOPS and
    # returns partial work (which then parks on failing validation) — bounds a
    # runaway ReAct loop well under the graph's recursion_limit=150.
    coder_step_limit: int = 25
    # Same bound for the reviewer's read-tool loop (it only reads + verdicts, so a
    # smaller budget); a degenerate reviewer STOPS instead of hitting recursion_limit.
    reviewer_step_limit: int = 15
    # Bound for the tester's read+write-tests loop (author acceptance tests, then stop).
    tester_step_limit: int = 15
    # Cap on the number of test FILES the tester (Proctor) may write in one authoring pass
    # (#51, ADR-0056): stops the runaway red-hunt where an already-satisfied task makes the
    # tester write ~13 files chasing a red it can never obtain. A legit acceptance suite is
    # 1-4 files; 10 sits above that but well below the runaway. Bounds cost, not correctness.
    tester_file_cap: int = 10
    # Test-first tester (ADR-0013): when ON, an author_tests node runs between design and
    # implement — Proctor writes the acceptance tests (protected) that the coder must pass.
    # OFF by default (opt-in): it adds a model call on the critical path; enable to measure
    # the correctness gain (e.g. on the MCB benchmark) before making it the default.
    tester_enabled: bool = False
    # Test-steward (#54, ADR-0058): the Proctor VALIDATES + REPAIRS acceptance/pre-existing tests
    # against the spec BEFORE the coder is deployed (coder-blind → it can't relax a test to fit the
    # coder's code). Edits get an actor-scoped, quality-gated tamper-excuse. OFF by default, ON in
    # the autonomous posture. Implies oracle_mutation_check so a weakening cannot launder.
    tester_repairs_tests: bool = False
    repair_loosen_only: bool = False  # #129 — see the knob
    coder_prefetch: bool = False  # #129 slice 4 — plan-named files in the coder's ask
    # Proctor faithfulness guard (#57, ADR-0062): a deterministic AST detector flags authored
    # assertions pinning incidental detail the spec leaves open (exact stdout whitespace, a
    # rendering literal, a private symbol name) or mutually contradictory, and hands the NAMED
    # findings to the Proctor's coder-blind repair turn. It only NAMES targets, never rewrites the
    # oracle (ADR-0062 MR-C). Default OFF; posture ON. No-op unless tester_repairs_tests is also ON.
    # One-sided: never weakens a behavioural assertion.
    proctor_faithfulness_guard: bool = False
    # The held-out critic (#60, ADR-0065): a veto-only, once-per-delivery, DIFFERENT-model judge of
    # OUTCOME (does the delivered code meet the spec?), wired between review and the gate. It can
    # ONLY downgrade ship→park (a confident VETO adds the `critic_vetoed` gate reason); it can never
    # create a ship. Runs once per distinct delivered tree (memoized), only on a green run, degrades
    # to no-verdict on any fault. OFF by default; ON in the autonomous posture — it IS the
    # correctness gate for verified autonomous runs. Guided/HA keep the human at the gate.
    critic_enabled: bool = False
    # #61: claims-protocol critic — the agent proposes per-claim verdicts with verbatim
    # quotes; core's critic_policy verifies the quotes deterministically and disposes.
    # Default OFF pending the A/B (ADR-0081).
    critic_claim_protocol: bool = False
    # Behaviour-preservation Proctor (#60, ADR-0066): when ON, a deterministic detector recognises a
    # REFACTOR (behaviour-preserving) task from the spec and injects differential-golden-master +
    # loose-structural authoring guidance for it — so the Proctor asserts "output equals original
    # across inputs" (no hand-computed goldens) + the LOOSE structural property (not a specific
    # private helper name), instead of over-strict pins a correct refactor fails. Default OFF; ON in
    # the autonomous posture. Prompt-led (guidance only) — no gate/policy change.
    behavior_preservation_guard: bool = False
    # Deterministic refactor-oracle scaffold (#60, ADR-0066 follow-up): when ON, for a detected
    # behaviour-preserving task the ENGINE (not the weak model) authors the differential golden-
    # master oracle — a frozen copy of the target module + a differential behaviour test over
    # generated inputs + a name-agnostic decomposition check. Replaces the Proctor's over-strict/
    # wrong authoring for refactors (the prompt-led `behavior_preservation_guard` reopened false-
    # ship — this is its safe successor). Deny-by-default: no-op unless it can author. Posture ON.
    refactor_oracle_scaffold: bool = False
    # Mutation-check the oracle (oracle-make-real Phase 1b): when ON, a GREEN run whose suite
    # vouched for it gets one deterministic mutation applied to the coder's own changed source; if
    # the suite stays green (the mutation SURVIVED) the suite is a rubber stamp and oracle_verified
    # is downgraded, so autonomous delivery parks. OFF by default (opt-in): it costs an extra
    # sandbox run per green iteration, and one surviving mutation on an incidental line is weak.
    oracle_mutation_check: bool = False
    # Does a PROVEN surviving mutation VETO delivery, or merely get recorded? True = today. The
    # A/B lever (MOSAERA_ORACLE_MUTATION_VETOES) for the 2026-08-11 finding: 7 firings on the
    # 125-run baseline, all 7 refusing work the hidden grader confirms was correct, 0 true
    # positives — though that corpus had 0 false ships, so nothing bad existed for it to catch.
    # OFF drops ONLY the proven-False veto; a sanctioned test edit (ADR-0058 repair / ADR-0087 §5)
    # still demands a PROVEN catch, so that backstop stands and the arms differ in one behaviour.
    oracle_mutation_vetoes: bool = True
    # DIAGNOSTIC (#129), env-only: poll every oracle leg, not just up to the first vouch. Changes
    # no verdict; costs a workspace walk. Why, and the safety argument: `graph/_oracle_legs.py`.
    oracle_record_all_legs: bool = False
    # Comprehensive mutation (ADR-0071): when ON (needs oracle_mutation_check) the check mutates
    # EVERY eligible construct in the changed region (to a cap) and requires the suite to catch
    # ALL — closing the executed-but-unasserted false_ship. Deterministic, downgrade-only. Trade:
    # it parks MORE (an equivalent mutant survives → a false park). Default OFF, posture HELD
    # pending measurement; A/B lever MOSAERA_ORACLE_MUTATION_COMPREHENSIVE. See #74/ADR-0071.
    oracle_mutation_comprehensive: bool = False
    # Structural-spec oracle (#80, ADR-0072): when ON, a refactor task whose brief states a
    # STRUCTURAL acceptance criterion ("a short orchestrator that delegates to >= N helpers") is
    # checked deterministically — the delivered function's AST must meet the requested shape. An
    # unmet-but-stated criterion downgrades oracle_verified → honest_park (the MCB-05 false_ship
    # class, which has NO behavioural signature so the mutation oracle can't catch it). Layer-1
    # floor: downgrade-only, deny-by-default (unmet ⇒ park; absent/unverifiable ⇒ None ⇒ no effect).
    # Default OFF; posture activation WITHDRAWN 2026-08-02 after a null n=25/arm A/B (pooled
    # Fisher p=1.0; 0 false-parks/100 runs — safe but ineffective on the current model tier).
    # (MOSAERA_ORACLE_STRUCTURAL_SPEC)
    oracle_structural_spec: bool = False
    # Change-coverage oracle (oracle-make-real #29): when ON, the standing-suite credit is set by
    # runtime line COVERAGE of the changed lines (does a test actually execute them?) instead of the
    # coarse static import heuristic. OFF by default (opt-in) until the arc lands: it adds one
    # instrumented sandbox run and needs `coverage` in the sandbox image (infra prerequisite).
    oracle_coverage: bool = False
    # Onboarding map scoping (#42, ADR-0047 §2): when ON, Quincy's planning prior gains an UNTRUSTED
    # "## Project map" block — recon observations, quoted + attributed + fenced — so a run is scoped
    # as gap-analysis against the durable map instead of a cold look. OFF by default (opt-in).
    # The map is a hypothesis generator, NEVER evidence — it informs SCOPING and never reaches the
    # gate. A first run with no/stale map degrades to the cold look and says so (§6).
    onboarding_map_scoping: bool = False
    # Model escalation (see role_escalation above): when ON, a failed run's diagnosed
    # bottleneck role is bumped one tier and the work re-run. OFF by default (opt-in) —
    # auto re-runs cost tokens/latency, and a cloud tier on the ladder means escalation
    # sends repo content off-box. max_model_escalations caps how many role-bumps one
    # piece of work may spend before it ends honestly incomplete.
    model_escalation_enabled: bool = False
    max_model_escalations: int = 2
    # Off-box egress consent (ADR-0024): OFF by default → autonomous runs are LOCAL-ONLY. ON
    # lets autonomous cloud tiers/bindings egress repo content to a third-party API, but only
    # when the model is also priced. Guided/ad-hoc runs (human-watched, in-UI-consented) aren't
    # gated. Pairs with the $0-price USD-cap fix so an enabled cloud run can't spend uncapped.
    allow_cloud_egress: bool = False
    # Resilient autonomous sweep (ADR-0023): ON by default — one stuck backlog item is
    # DEFERRED (status="deferred", surfaced with its reason) and the sweep keeps delivering
    # the rest, rather than the whole project halting. Honest + reversible (a human/Quincy
    # revives a deferred item). resilient_recuration (opt-in, default OFF) additionally asks
    # Quincy to re-curate a stuck item (split/re-scope/set-deps) before deferring — an LLM
    # call, so it's separate from the deterministic defer-and-continue.
    resilient_sweep: bool = True
    resilient_recuration: bool = False
    # Layer-2 park→ship disposition (ADR-0074/#76): on an autonomous oracle_unverified park, author
    # an independent asserting test and re-run the REAL oracle — green + mutation-proven ships
    # VERIFIED, else stays parked. The ship authority is deterministic execution, never an LLM
    # green-light. Default OFF: it can cause a ship, so it is measured (Layer-2 conversion rate)
    # and red-teamed before any posture activation.
    disposition_gap_close: bool = False
    # ADR-0094 measurement widening — admits a `claim_structural_failed`-only park into the
    # gap-close arm. Does NOT relax the ship gate (green + mutation still decide). OFF.
    layer2_admit_structural_claim: bool = False
    # The ESCALATE arm (#64 F49): a hand-raise whose failing tests are ALL protected from the
    # producer is unfixable by re-planning, so the run concludes honestly and raises a clarification
    # on the backlog item instead of looping. Deliberately NOT a posture knob — it is not flipped by
    # `apply_oracle_posture`, so the ADR-0081 liveness ratchet ("a new posture knob below C4 is a
    # failure") does not apply. Default OFF: it moves when runs park.
    escalate_arm: bool = False
    # The escalation-gate AMENDMENT (ADR-0087, #65; full rationale in `graph/_amendment.py`). The
    # arm above asks the operator and then ignores the answer, so a delivered test can never be
    # amended and a behaviour-CHANGING item deadlocks. ON, the operator may authorize amending the
    # blocking test(s) and the PROCTOR rewrites them once. Not a posture knob; default OFF because
    # a new authority path over the ADR-0036 boundary earns activation with measurement.
    amendment_gate: bool = False
    # Acceptance spec-lint at the decompose boundary (ADR-0073): deterministic detection of
    # over-specified / refactor-phrase / near-duplicate acceptance in a freshly-generated
    # backlog, plus ONE bounded Quincy re-curate pass built from the findings. ON by default:
    # detection is pure code, and the pass is a single PM call only when findings exist —
    # against the run-level thrash a bad acceptance provably costs (#53 live drive).
    backlog_spec_lint: bool = True
    clauses_enabled: bool = False
    intake_ask_undecidable: bool = False  # ADR-0080 axis 2 — ask-rate is a measured dial
    intake_ask_unreachable: bool = False  # ADR-0089 axis 3 — same posture, same reason
    # Bound for the PM PLANNER's read-tool loop; raised 12 → 20 (2026-08-07) when the planner
    # spent the whole budget exploring and never wrote a plan. Full note in `_knobs.py`.
    pm_step_limit: int = 20
    pm_chat_tools: bool = False  # ledger tools in the PM CHAT (ADR-0111); off = one plain call
    # Inject the trusted global planning doctrine (+ per-project reference docs) into
    # the planner. A budget kill-switch: turn off for a very small local model whose
    # context window can't spare the doctrine block.
    doctrine_enabled: bool = True

    def role_model(self, role: Role) -> RoleModel:
        """The ``(provider, model)`` bound to ``role`` under the ACTIVE cost-mode
        (per-run overlay, else ``default_cost_mode``). This is what ``get_chat_model``
        resolves through."""
        return self.role_model_for(self.active_cost_mode or self.default_cost_mode, role)

    def disallowed_cloud_roles(self, roles: Sequence[Role]) -> list[tuple[Role, str, str]]:
        """Active bindings an AUTONOMOUS run may NOT use (ADR-0024). See ``config/_roles.py``."""
        from mosaera_core.config._roles import disallowed_cloud_roles

        return disallowed_cloud_roles(self, roles)  # type: ignore[return-value]

    def role_model_for(self, mode: str, role: Role) -> RoleModel:
        """The binding ``role`` resolves to under a SPECIFIC cost-mode (#7). See ``_roles.py``."""
        from mosaera_core.config._roles import role_model_for

        return role_model_for(self, mode, role)  # type: ignore[no-any-return]

    def held_out_ok(self) -> bool:
        """Whether the critic is a genuinely INDEPENDENT check — a different model from the
        coder (#60, ADR-0065). See ``_roles.py``."""
        from mosaera_core.config._roles import held_out_ok

        return held_out_ok(self)

    def provider_config(self, provider: str) -> ProviderConfig:
        """Credentials/endpoint for ``provider``. For ``ollama`` the base_url
        falls back to the legacy ``ollama_base_url``; other providers return
        their stored config (or an empty one → native-env-var fallback)."""
        cfg = self.providers.get(provider)
        if provider == "ollama":
            base = (cfg.base_url if cfg and cfg.base_url else None) or self.ollama_base_url
            return ProviderConfig(api_key=None, base_url=base)
        return cfg or ProviderConfig()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Layer env > stored ``settings.json`` > default. The builder lives in ``_from_env``
        (a module-scope function, so this hot config file stays under the god-file ceiling)."""
        from mosaera_core.config._from_env import build_settings

        return build_settings(cls, env)
