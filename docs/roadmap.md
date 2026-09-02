# Roadmap

*What we're building, why, in what order, and where each piece stands.* Direction/end-goal is in
[`architecture/north-star.md`](architecture/north-star.md); binding decisions are in `docs/adr/`. The
full arc history — diagnoses, benchmark snapshots, red-team dispositions, and lessons — is preserved
in [`engineering-history/roadmap-and-arc-history.md`](engineering-history/roadmap-and-arc-history.md);
this file stays lean. Click an ADR for the detail.

**Engine version + maturity channel: read them from the code, not from here.** The authoritative
sources are `mosaera_core.__version__` and `__maturity__`; to print both, run
`uv run python scripts/bump_version.py --check`. Per-release benchmark snapshots are in
[`CHANGELOG.md`](../CHANGELOG.md). `0.x` is maturity-anchored
([ADR-0055](adr/ADR-0055-engine-versioning.md)); the channel is the separate how-much-to-trust-it
axis, `beta` until the ADR-0061 gates start closing
([ADR-0088](adr/ADR-0088-engine-maturity-channel.md)). Procedure:
[`runbooks/versioning.md`](runbooks/versioning.md).

> **Issue numbers.** Work is sequenced against an issue tracker on the authenticated origin,
> which is not reachable from this distribution. `#N` references throughout these documents name
> that tracker and are retained because the history refers to them; they are not links.

## How to read this

- **Single source of truth for build order.** Every MR that finishes or discovers work updates this
  file. GitLab issues (`#N`) are the unit of work; this is the map over them.
- **Each item is classified:** **[arc]** (part of a north-star arc; built when that arc runs) ·
  **[prereq]** (an arc can't start without it; build first) · **[debt]** (independent; slot as
  friction demands).
- **Sequence by leverage + dependency, not size** — a small piece that unblocks three others goes
  first.
- **Status labels:** DONE (merged) · IN-PROGRESS · NEXT · DIRECTION (not built) · PARKED · DEBT.

## Current focus (the "Now")

- **[debt] Operator friction — the control exists, but not when you need it (2026-08-24)** — five
  instances in one session, each observed directly with run ids attached. Measured cost of the first
  alone: **31 min / 1.29M tokens** on a run that could not be stopped and never executed a single
  validation. The engine's judgement was not the problem in any of them. Worked in clusters; three
  landed, two remain.
  - ~~**#116** `cancel run` renders only
    while a run is WORKING~~ — **DONE 2026-08-24** (`5422aa42`, cluster 1a). The control moved out
    of `RunningHero` into the row every non-terminal variant renders, so a parked run can still be
    abandoned without spending a model turn answering the gate first.
  - ~~**#108** the park reason is
    recorded but not rendered~~ — **DONE 2026-08-24** (`61461e8f` cluster 1d, tense fix in
    `b23c3d49`). Rendered from the same `plain.ts` vocabulary the settled diagnosis card uses, so a
    park reads the same live as it does afterwards; a diagnosis with nothing to say yields null
    rather than a guess. The tense fix is the lesson: settled wording in front of a LIVE gate
    claimed an ending that had not happened, which is why `livePauseCause` exists as a separate
    function rather than a flag.
  - ~~**#109** merge is not reachable
    from the Delivery page at all~~ — **DONE 2026-08-24**. Merge capability + a mergeability
    verdict that fails toward not-ready (`4e527b44`), item MR merge admin-gated (`f414bc3a`),
    console merge behind a confirmation that reads GitLab live (`0846c3f1`), recorded as an
    [ADR-0102 amendment](adr/ADR-0102-delivery-spine-truth-up.md) (`5652b791`). `b23c3d49` also corrected
    the count: item branches STACK, so "deliverable without an MR" was reading as UNDELIVERED over
    work that had merged hours earlier.
  - **STILL OPEN, both from #116:** the write-mode toggle silently does nothing while a run is
    paused (no `mode_change` recorded, no error), and the run page's live stream dies after every
    approval, forcing a reload per decision. Neither has an implementing commit as of 2026-08-24.

- **[debt] Fails closed when exposed — the defaults are dev-shaped (2026-08-28)** — four findings
  that are one defect class: safety depends on the operator configuring it, and every default is
  correct for the author's laptop. **The operator population is what changed** — the public
  installer and the onboarding arc mean "the operator sets it correctly" no longer means *us*.
  Routed through the control point that already exists rather than a new mechanism: `guard_bind`
  already refuses a non-loopback bind without a token, and with the `subprocess` sandbox, by
  `SystemExit` from both entrypoints. These add clauses to it. Raised by an outside review of the
  public mirror; **re-scoped after reading the code** — the review's proposed fix for the first item
  (short-lived SSE capability tokens) was rejected as new governance machinery to retire a dead path.
  - **#122** narrow the `?token=` accept
    to the one route that cannot use a header. The browser path is already fixed — ADR-0004 §49
    replaced bearer-in-`localStorage` with the session cookie *to remove this*, and `withToken()` is
    now a literal `return url`. **No in-repo producer of `?token=` remains**; only the server-side
    accept, and it spans every `/api/*` route where exactly one (`GET /api/runs/{id}/events`,
    EventSource being GET-only) needs it. A strict narrowing — can only remove permission.
  - **#123** an exposed bind requires
    `MOSAERA_SECRET_KEY`. GitLab and BYOM credentials are plaintext without it (`0600` is a
    permission, not encryption). The lazy migration already exists, so an existing install that adds
    a key keeps working — but this **breaks startup** for an exposed deployment with no key, which
    is the point and must not be silent.
  - **#124** an exposed bind must declare
    its TLS posture. **Not** "force `Secure` on a non-loopback bind" — that silently breaks every
    plain-HTTP LAN deploy, because a browser will not send a `Secure` cookie over `http://`, and the
    operator's fix under pressure is to disable the protection. Refuse to start while
    `MOSAERA_COOKIE_SECURE` is *undeclared* instead: the control refuses to act and says why.
  - **#125** rename the `subprocess`
    sandbox to say it is host execution. Naming only — the refusal already works. **Cut this first**
    if the arc needs to shrink; WONTFIX is a legitimate outcome.
  - **Gating:** all four touch auth/authz/secret handling → **CODEOWNERS-protected** (owner approval
    before implementation) and **red-team-required**. Batching them earns *one* red-team pass
    instead of four, which is most of the reason they are one arc.

- **[arc] Efficiency + over-park — the dominant cause is WRONG evidence, not missing evidence
  (#129, opened 2026-08-29)** — measured
  across **every surviving scorecard (n=198)**: over-park **28.8%**, and **100% of over-parked runs
  had the hidden grader PASS**. The decisive split: **`validation_failed` is on 54.4% of
  over-parks** against **`oracle_unverified` on 22.8%**. So **31 of 198 runs (15.7%) produced work
  the grader passes and were refused because the engine's OWN authored tests failed** — trivial 14,
  moderate 10, hard 7. The engine's own vouch string on 50 of 57 over-parks is
  `no_vouch:not_behavior_preserving`. **This corrects the framing this file has carried**: the
  engine is not usually failing to FIND an oracle, it is failing to AUTHOR a correct one, and the
  trivial tier is worst because the smaller the change the less an invented test can be right about.
  - ~~**Slice 1 — non-behavioural work: the ENGINE authors the oracle**~~ — **SHIPPED 2026-08-29**,
    [ADR-0124](adr/ADR-0124-the-trivial-task-lane.md). Two approaches were implemented and A/B'd;
    the engine-authored oracle won on measurement and architecture. On the shape it targets:
    delivery **33 → 100**, calls 47 → 18, tokens 294k → 47k, Capability 100/100. Ships default OFF.
    The losing approach (a reduced lane leaning on the `standing_suite` leg) was deleted rather than
    left half-built. Note the honest scope: **0 of the 26 pre-existing MCB cases arm it**, so it
    helps only non-behavioural items and is provably a no-op elsewhere.
  - **Slice 2 — the coverage defect** —
    **#128**. `change_is_covered` counts
    a line only if it ran under a test-function context, but a module-level statement executes at
    IMPORT time and is therefore structurally uncoverable. The gate credits a **comment** it cannot
    verify (no executable line at all) and refuses a **`__version__` bump** the standing suite
    genuinely does verify — reviewer APPROVE, critic 3/3, grader 2/2, still parks. Affects every
    module-level constant, `__all__`, dataclass default, decorator and import in any repo.
    Reproduced on MCB-30 vs MCB-32. **Deliberately unsized**: 10 of 13 `oracle_unverified`
    over-parks predate the oracle-leg instrumentation, so sizing is part of the work, not a gate.
  - **Slice 3 — the 31-run class (NEXT, and it is 54% of the problem).** Behavioural work where the
    authored oracle disagrees with the grader. Diagnose before designing: over-strict, wrong, or
    testing something the brief never asked? Answerable from **stored scorecards, no GPU**.
  - **Slice 4 — round trips (independent, pure efficiency).** Cost is round trips × a flat context
    tax (97% input). The prompt-level lever **measured NULL** (`coder_batch_reads` 1/30 vs 0/30 —
    [pre-registration](engineering-history/coder-batch-reads-preregistration-2026-08-29.md)); the
    successor is a deterministic `read_files(paths)` tool that removes the model's discretion.
    Reads are 44% of tool calls, so the ceiling is ~30% of coder round trips — not more.
  - **Discipline this arc inherits.** Every prior over-park attempt here measured null or found the
    wrong cause first. Before any code: state the noise floor, name the unit of independence (case,
    not run), and check the mechanism can fire on the corpus at all — the last A/B was null by
    construction on 26 of 26 cases and only a pre-flight check caught it.

- **[arc] The clean-clone check — would this work if you cloned it?
  (#104, merged 2026-08-23)** — the
  delivery gate proves the code works under the SANDBOX's conditions; a stakeholder reads it as
  proving the artifact is usable. LedgerCLI delivered **15 gate-approved items with the proof panel
  at 14/14 on every axis, and a fresh clone did not run.** Neither defect was catchable by any
  gate, and the reason is structural: `_install_step` builds the venv with `--system-site-packages`
  so the base image's pytest is importable no matter what the project DECLARES, and `run_setup` has
  already installed the package, so entry points are never exercised the way a consumer meets them.
  The criterion "pip list shows only standard library packages" was being checked in the one place
  the violation could not appear. Built: `mosaera_core.cleanroom` reads what the project declares
  against what its README promises (`42b53728`), wired into delivery (`11054d94`, merged
  `68ed4b72`). Carries the general lesson for the correctness program: **a check run inside the
  conditions it is meant to test is not a check.**

- **[arc] The PM can read the project's own record — [ADR-0111](adr/ADR-0111-pm-chat-may-read-its-own-ledgers.md)
  (proposed 2026-08-24)** — Quincy was a tool-using agent when he planned and blind when he talked
  to you: `pm/_backlog.py::chat` was one `robust_invoke` with no tools, and `repo_overview` is a
  tree listing, so in the one surface a human talks to him he reasoned about filenames. Design:
  [`agentic-pm-chat.md`](design/agentic-pm-chat.md). Shipped in five slices behind
  `MOSAERA_PM_CHAT_TOOLS` (**off by default**, and off is byte-identical to the single call it
  replaces, so the flip is a clean A/B and the QMB chat arm is unchanged):
  **0** the exfiltration leg — `PmMarkdown` rendered model-authored `![](url)` as a real `<img>`
  with no CSP anywhere, i.e. a zero-click GET to any host a reply named (`66149535`);
  **1** the changeset requires a fence, parse and strip fused into one function so they cannot
  disagree (`000859c8`);
  **2** a turn that did not complete says so — a transport failure was an unhandled 500 leaving a
  dangling user turn, and an unusable reply wore Quincy's avatar (`93505515`);
  **3** the ledger tool itself, scoped by a NEW `pm_chat` allowlist role naming `project_history`
  and nothing else, so ADR-0111's Category A/B split is enforced by the existing deny-by-default
  filter rather than by prose (`ddb6e684`);
  **4** streaming — deliberately NOT the runs' treatment, since EventSource is GET-only and a chat
  turn is a POST; the turn streams its own response and runs on a thread, so closing the tab loses
  the animation and never the answer (`a8b4754b`/`f108efc4`).
  Two prerequisites fell out of building it, both live defects: a backlog title could forge a `##`
  heading inside the standing memory block (`e8e05c6e`), and `_last_ai_text` skipped the budget
  sentinel but not the transport one — so a transport error came back AS THE PLAN, and because
  `plan_is_fallback` compares against `_FALLBACK_PLAN` it did not register as a fallback either
  (`8ae225dd`). That second one revealed the graph integration tests had been running a PM that
  never planned: `_patch_models` handed the "pm" role a fake with no `bind_tools`, so 30 tests
  passed on an error string. **Measured live 2026-08-24, and this is the finding that matters:**
  five questions with exact answers computed independently from LedgerCLI's ledger. Every lookup he
  made was exact — #83 with 15 runs/13 delivered, #87 with three criterion-deaths and their run
  ids, 14 orphans. But on the one question the standing block cannot answer he did **not** look,
  and asserted "Zero" against a true 14 — three times, twice wrapped in a fabricated fenced JSON block
  that reads exactly like tool output. An explicit prompt rule did not change it: he can quote the
  rule back verbatim and still guess (`e40e4a08`). **So the risk is not a tool returning bad data;
  it is the model answering a question it could have checked, in the register of something
  checked** — and the "checked N things" line is the only thing that tells them apart from the
  reply, which makes it evidence rather than decoration. NEXT, and unbuilt: the deterministic
  answer is to remove the gap rather than police it (put the cheap high-value facts in the standing
  block), because instruction demonstrably is not the lever on this model tier.

- **[arc] The trivial-task lane — task-scale routing (issue filed 2026-08-24; ADR OWED before any
  build)** — **#118**. Every run executes
  the full 15-node spine regardless of task size; no classifier of change scale exists anywhere in
  `graph/`. Measured floor: one comment line ~43k tokens; two comment lines 5 coder calls / 67k
  tokens; a `.gitignore` 1.34M tokens / 8 min / 7 revisions plus an operator override (F70). Cost is
  97.4% input tokens — a flat context re-send tax per round trip, so it scales with call count, not
  task size. **Capability:** a one-sentence, few-line change completes in seconds-to-a-minute of
  model time without waiving a single control's authority — the lane narrows *model* work (collapsed
  plan+design, reduced step budgets, review scope proportional to the diff) while every
  deterministic control and the gate evaluate the same evidence model. Hard constraints recorded on
  the issue: gate untouched (**Deterministic Final Authority**), evidence still required per
  criterion, misclassification escalates to the full lane rather than thrashing, ships default-OFF
  behind a ≥C4-proven knob. Prior art: ADR-0062's reverted auto-loosen (this narrows *effort*,
  never the acceptance class), `reliability_sensitivity`'s budget-scaling precedent, the design
  cache. Acceptance: fingerprint-validated A/B on the trivial MCB tier, ≥5× token/wall-clock
  reduction, `false_ship` stays 0, over-park not increased, noise floor computed before the sweep.
  Trust-boundary adjacent ⇒ ADR + scoped red-team are part of the definition of done. Identified as
  the top product-alpha blocker by the 2026-08-24 alpha-readiness audit.

- **[arc] Alpha-outsider stoppers — a stranger takes their own project to a merge (issues filed
  2026-08-24)** — the same audit asked what blocks handing Mosaera to a different person, and three
  gaps are tracked:
  **#119** first-time setup —
  **BUILT 2026-08-24; the fresh-machine install by another person is OWNER-OWED and not claimed.**
  Reframed by the owner from "bootstrap" to **the setup wizard itself**, so downstream work can
  assume a configured instance and the whole thing is simulable on a clean VM.
  `mosaera_core/preflight.py` is one origin for "can this instance run anything", read by three
  surfaces — the wizard (`GET /api/preflight`), `mosaera doctor` (the headless VM surface, exits
  non-zero), and a launch that now **refuses** an unconfigured instance by name instead of failing
  downstream. The wizard **probes before it prompts**: a box already running Ollama sees what was
  found and one button. Model choice is a `<Select>` of what the endpoint actually GRANTS — a
  validated key with a typo'd model id is the documented BYOK failure and it surfaced only on the
  first real run. `scripts/dev-up.sh` drops its hardcoded model list (a second origin that lied the
  moment a role was rebound) and delegates. **Presets became an objective POLICY, not a model
  list**: BYOM, so nothing names a model and nothing claims a ranking — routing is on locality and
  price, both facts, while context window is deliberately not an axis because nothing in the API
  surfaces it. **ADR-0016 Amendment 1's owed live no-op detector is discharged**: the escalated role
  is threaded into the re-run and a zero-call escalation is recorded AND surfaced instead of reading
  like "a stronger model tried and could not". Posture/licensing tiers are explicitly out — the core
  edition has none, and the ADR-0046 clamp arc is filed separately.
  **Polish pass 2026-08-25 (walking the whole path end to end, which is what surfaced these — each
  surface had been validated in isolation).** Two DEAD ENDS a stranger hits by default: a failed
  clone was terminal (a starting and a failed intake are both status `draft`, so the Start page
  rendered "Quincy is setting up the repository…" forever, `project.error` was displayed nowhere,
  and nothing re-ran the clone — not even connecting GitLab, the recovery the New-project page
  advertises), now a named failure plus `POST /projects/{id}/intake/retry`; and the wizard's review
  step was read-only, so on a machine with nothing pulled every role read "not resolved", Confirm
  was disabled with no reason, and step 1's "you'll pick on the next screen" pointed at a screen
  with no picker — "I'll choose" was impossible to complete. It now has a real per-role `<Select>`
  over the measured inventory (ADR-0005), and says so honestly when there is nothing to assign.
  Four FALSE STATEMENTS removed: the lede claimed "nothing will run" (the launch guard does not
  enforce that — one `setupConsequence` origin now feeds lede and banner); a probe still running or
  outright FAILED rendered as the finding "Nothing was found on this machine"; a failed
  `/api/preflight` produced no wizard AND no banner, so a broken instance looked healthy; and
  "connect a provider" kept a stale grant, so switching provider after a successful test wrote a
  validated key against the other provider's model — the exact BYOK failure that panel exists to
  prevent. Deferral moved from React state to `localStorage` (it survived only until the next
  reload, which re-took the whole app full-screen). `routes/projects.py` split at the 500-line
  ceiling (`routes/project_reporting.py`), and `FirstRunSetup.tsx` 486 → 141 (`ProbeStep` /
  `ReviewStep` / `ConnectProvider` / `CheckRow`), which is what made room for the picker.
  Live-validated on a clean instance both ways: empty inventory, and a retry that took a terminal
  project to `ready`. **Known divergence left standing:** `lib/models.ts` still spells the presets
  "Local · Free / Balanced / Quality · Cloud" on the Settings page while the wizard uses the
  remapped names — the comment claiming they agree now states the divergence instead.
  **REBUILT as a gated five-screen flow 2026-08-25 ([ADR-0115](adr/ADR-0115-first-run-is-a-gated-flow-resumed-from-facts.md),
  amending [ADR-0040](adr/ADR-0040-first-run-setup-token.md)) — owner-directed.** Setup token ·
  administrator · environment · models · delivery now stand between a fresh install and the
  application. The token gets its OWN screen, so a wrong one is refused where it was typed instead
  of after the operator has also chosen a username and password: `POST /auth/setup/check` validates
  and creates nothing, joins the open bootstrap routes, and **never spends the token** — the spend
  stays inside the request that creates the admin, or ADR-0040's race reopens (pinned by a test that
  fails if it does). It adds no disclosure (`_enforce_setup_token` already runs before
  `validate_credentials`) but it IS unauthenticated and cheap, so it takes the ADR-0051 backoff keyed
  on the **socket peer**, never `X-Forwarded-For` — a forwardable header would let one caller rotate
  into a fresh bucket per guess. **Which screen you see is derived from facts the server already
  exposes**, not a saved cursor, so a reload, a closed tab or a different machine all resume in the
  same place; the exhaustive test walks all 128 fact combinations. Exactly one thing is stored
  (`setup_steps_acked` in `settings.json`): `environment` and `delivery` are optional, and `models`
  is recorded because deriving it from `can_run` alone would put the whole application back behind
  setup the moment a backend went unreachable — a lockout, where the banner is the control that
  exists to report exactly that. The models screen **recommends nothing** (BYOM: unknown hardware,
  possibly cloud-only, one measured binding): it connects first and populates dropdowns only from
  what the machine has or a key grants. The five roles render as a card row carrying the **run
  story's own cast** — role → `AgentSpec.nodes` → the timeline actor and its engraving, a bridge over
  existing data rather than a fourth hand-written name map — and each states a REQUIREMENT: every
  role needs tool calling (all five are `create_agent(tools=…)`), the coder and tester additionally
  write. That corrects `roleNeedsTools`, which claimed only two roles needed tools and was false
  against `ROLE_TOOL_ALLOWLIST`. The preset-based wizard is removed from first run (presets rank on
  locality and price, which the owner ruled out here) and `AuthGate` sheds its ReadyGate and the
  localStorage deferral. Live-validated end to end on a clean instance: wrong token refused on
  screen 1, token unspent by the check, the card row over real models, finish → app, and a reload
  that stays in the app with the banner reporting the degradation. **Not built, and flagged rather
  than folded in:** a browser button that installs software on the host — `preflight.py`,
  `install.sh` and `fresh-machine-check.sh` all state report-only contracts, and an executor would
  hand host execution to anyone who reaches the API. It needs its own ADR and a red-team pass.
  **SETUP MOVED TO THE TERMINAL 2026-08-25 ([ADR-0116](adr/ADR-0116-setup-is-a-terminal-wizard.md),
  superseding [ADR-0115](adr/ADR-0115-first-run-is-a-gated-flow-resumed-from-facts.md) the same day
  and [ADR-0040](adr/ADR-0040-first-run-setup-token.md) on the normal path) — owner-directed.** The
  structural reason: only Postgres is containerised, the API runs on the host, so EVERY install
  already happens at a terminal and a browser cannot install Docker, start Postgres or write `.env`
  even in principle. `mosaera-setup` is a Textual application that installs prerequisites with
  per-item consent, brings up the database, chooses the bind, creates the first admin directly, and
  can uninstall again. `install.sh`'s no-install refusal does not vanish — it MOVES to where consent
  is possible, since a script piped to `sh` cannot prompt at all. **The prerequisite advice was wrong
  in a way that would break a machine:** commands were derived from binary names, so Ubuntu was
  offered `apt-get install -y node` (an amateur packet radio program) and `install -y docker` (not
  the engine), and any unmatched distribution got `curl get.docker.com | sh` for EVERY tool, so
  "install git" ran the Docker installer. `mosaera_core.prereqs` is now one declared table read by
  `doctor`, the wizard and `install.sh`; Docker installs via Docker's own script, the only method
  that brings the compose v2 plugin — a separate package never checked while `docker compose up -d`
  was being run. Also fixed: slow steps ran on the UI loop (frozen screen, no cancel), `sudo`
  deadlocked invisibly under raw mode, nothing timed out (and a SILENT command never even reached a
  per-line deadline), and a re-run re-minted the service token, invalidating live credentials while
  reporting success. Uninstall offers only what the wizard RECORDED installing, demands the word
  REMOVE for anything irreversible, and never removes a system package on the operator's behalf.
  Models are not part of setup at all — they are chosen in the app, per agent.
  **THE ONE-LINER, 2026-08-26 ([ADR-0117](adr/ADR-0117-the-one-liner-installs-uv-and-pins-a-tag.md))
  — owner-directed.** The hand-off ADR-0116 corrected in August was right in shape and broken in
  fact: `install.sh` ended with `uv run --no-sync mosaera-setup` and never ran `uv sync`, so on an
  unsynced clone — every fresh install — it died as `error: Failed to spawn: mosaera-setup`,
  exit 2. Two more defects made a clean box unreachable anyway: the script hard-failed on `docker`
  and `node`, the very tools the wizard exists to install *with consent*, so the component that
  fixes the problem was never reached; and `uv` was required by the script and installable by
  nothing (absent from `PREREQS`), which matters more than it sounds because `uv sync` is also the
  **interpreter** bootstrap. The script now requires one thing (`git`), installs one thing (`uv`,
  user-space, no root, announced, `MOSAERA_NO_BOOTSTRAP=1` to refuse, recorded for uninstall), and
  delegates the rest. Distribution moves to a **read-only public GitHub mirror** and what an
  operator runs becomes a **release tag**, not a branch — so a bug report can name its version, and
  a re-run moves forward deliberately (detached HEAD, and a dirty tree is refused rather than
  moved). **The prerequisite advice was wrong off Fedora**, in both directions this repo already has
  a name for: nothing anywhere distinguished WSL from native Linux (zero hits for
  `WSL_DISTRO_NAME`), so WSL was told to `systemctl enable --now docker` and to "log out and back
  in" — neither of which does anything there; and macOS was offered `brew install git` without
  Homebrew's presence ever being checked. `Platform` grows `wsl` and `brew`, `plan_for` dispatches
  reason-first/platform-second, and `explain.py` + `preflight_host.py` stop carrying their own
  copies of a command the table already owns (three origins for `systemctl`, now one, pinned by a
  test). **ADR-0116's "one table, three readers" claim is corrected, not restated:** `install.sh`
  needs its advice before a clone and before uv exists, so it cannot read the Python table at all —
  the residue collapses to one package name, pinned from Python by a test asserting `git` is `git`
  in every declared family.
  **THE BROWSER SLIMMING LANDED 2026-08-26**, closing ADR-0116's last owed item. `POST /auth/setup`,
  `/auth/setup/check`, `needs_setup_token`, the token mint, `GET /setup/presets`, `GET /setup/state`,
  `PUT /setup/ack/{step}` and `setup_steps_acked` are gone, with nine SPA components and the step
  machine; `setup_gate.py` is now `initial_admin.py` and does only the `MOSAERA_INITIAL_ADMIN_*`
  seed. **CWE-1188 is closed by construction rather than guarded** — a first-admin race needs an
  unauthenticated endpoint that mints an admin, and there is none; the middleware's open set is
  `status` and `login`, neither of which creates anything. An empty instance shows the command
  rather than a login form nothing typed into could ever satisfy. `GET /api/preflight` deliberately
  SURVIVES: the degradation banner polls it inside the authenticated shell for every signed-in user,
  long after setup, so it was never a first-run surface. The `setup_tokens` table and Alembic 0012
  are kept, empty and unread, as the revert hedge; dropping them is a follow-up for after the
  stranger test.
  **OWED, and OWNER-OWED:** the fresh-machine install by another person. The VM matrix (Ubuntu,
  Debian, Fedora, macOS ±Homebrew, WSL2 ±Desktop integration) makes that pass a confirmation rather
  than a discovery, and `test_install_script.py` now drives the installer against a real git remote
  on every CI run — but neither replaces it, and macOS and WSL are **correct in code and unproven in
  the world**. Also owed and explicitly out of scope here: the wizard has no model step, so
  `dev-up.sh`'s WSL Ollama host-gateway handling has no counterpart in it (ADR-0116 §7 puts models
  in the application, not setup) — it belongs to whichever slice first brings model configuration
  into the wizard.
  **#120** delivery where the user
  lives — the wired MR path is GitLab-only and `github.py`'s sole caller is the CLI's `--open-pr`
  (ADR-0001, revisit required); capability = a GitHub PR opened from the Delivery page, or at
  minimum an honest GitLab-required gate at intake instead of a dead end at the finish line.
  **Slice 1 BUILT ([ADR-0112](adr/ADR-0112-two-named-delivery-providers.md)):** the delivery
  provider is derived from `source_repo` by host equality (no column, no migration, no intake
  selector), `GET /api/projects/{id}/delivery/capability` states whether a project can open a
  request at all, and the Delivery page names the provider and withholds the controls that could
  only 400 — criteria 1, 3, 5. Nothing newly succeeds, pinned by a test.
  **Slice 2 BUILT ([ADR-0114](adr/ADR-0114-github-delivery-on-an-app-installation.md)) — criterion 2
  closed, criterion 4 OWED.** A public-GitHub project delivers from the Delivery page on a **GitHub
  App installation token**: minted immediately before each delivery, narrowed to that one repository
  with `contents`+`pull_requests` only, valid an hour, never stored. Its PR state is polled, so the
  project can actually read as *Delivered* — without that, GitHub would have reopened F64's gap.
  **It deliberately does not mirror ADR-0104's Connect:** GitHub documents the setup-URL
  `installation_id` as spoofable, so no value from any redirect is read — the server asks GitHub
  which installation owns the project's own `source_repo`, which removes the question instead of
  answering it, and with it the state/callback/client-secret machinery. Stated limits, shown on the
  page rather than discovered: **public repos only** (`clone.py` cannot authenticate a private
  GitHub clone yet) and **no per-item PRs** (GitLab's are stacked; that is its own slice).
  **OWED (owner, blocks criterion 4 — the live leg):** it will not be marked done on unit tests
  (ADR-0110). (1) register a GitHub App with **Contents: RW** + **Pull requests: RW**, note the app
  id and slug, download the private key PEM; (2) set `MOSAERA_GITHUB_APP_ID` /
  `MOSAERA_GITHUB_APP_PRIVATE_KEY` / `MOSAERA_GITHUB_APP_SLUG`; (3) install it on a **public**
  throwaway repo; (4) create a project on that repo → Delivery → Connect; (5) run → approve → open
  the PR, and record the real PR URL under `engineering-history/`. Note ADR-0104's own GitLab
  round-trip is *also* still OWED, so slice 2 inherits no demonstrated precedent.
  **red-team: done** — 3 rounds pre-merge, 2 FIX-NOW both fixed and pinned by tests: a cached installation id was spent without rechecking it matched the current `source_repo`, and the "endpoint-only" claim was unenforced because the autonomous sweep shares `open_project_mr` (ADR-0114 §8).
  **Slice 3 — the GitHub surface, BUILT 2026-08-28 (presentation + one read-only endpoint; no
  new trust boundary).** Settings gains a **Git** section (`/settings/git`, provider index →
  `/settings/git/:provider`), replacing "Integrations". GitHub gets a real panel: App state, the
  installations it can reach, and Lovable's empty-state shape ("No installations available" →
  *Install on new account / Add account*) in place of the amber warning that used to be the only
  not-installed signal, buried in one project's Delivery card. New `GET /api/github/installations`
  (admin-gated) + `github_app.list_installations`. **ADR-0114's rule is intact:** the listing is a
  display question and nothing it returns is ever spent — delivery still resolves the installation
  from the project's own `source_repo`, pinned by a test that fails if the listing path so much as
  calls `installation_for_repo`.
  **The real defect it closed:** a project's Settings → Integration pane rendered the *GitLab* card
  for every project regardless of forge, so a GitHub-backed project was told to paste a
  `write_repository` token it can never use — the untruth ADR-0112 removed from the Delivery page,
  still live one screen over. The pane now routes on the same `delivery/capability` record the
  Delivery page reads.
  **A second defect, found by running it:** the panel first gated its fetch on
  `github/status.is_admin` (a session fact) while the endpoint enforces `require_admin` (satisfied
  by an admin session *or* an open loopback box). On a dev instance the query never ran and the page
  showed "No installations available" — a true-looking empty state produced by a query that never
  fired (*green-by-vacancy*). Now gated on `isAdmin || !auth_required`, the rule `SettingsPage`
  already uses.
  **GitLab is deliberately untouched** — its card renders verbatim under the new route; the owner is
  **Slice 4 — repository creation ([ADR-0120](adr/ADR-0120-create-a-github-repository-on-a-discarded-user-grant.md)), BUILT 2026-08-28.**
  A project with no repository gets one made for it: authorize on GitHub, and Mosaera creates a
  **public** repo and points the project at it — nothing to paste. The authorization code buys a
  **user** access token (an installation token provably cannot create a repo — checked against
  GitHub's REST docs, not assumed) which is **discarded in the same request**; delivery still uses
  installation tokens only, so ADR-0114 §8's token-routing invariant holds.
  **The repo NAME never crosses the redirect** — it is derived server-side from the project, which
  is ADR-0114 §2's reasoning applied again: a supplied name would decide *which repo on whose
  account* (a slash changes the owner), so the parameter is removed rather than validated. Reuses
  ADR-0104's state (hashed / single-use / TTL / bound, spent *before* any code exchange) on its own
  callback path. **Public-only is enforced in code, not prose** — `clone.py` cannot authenticate a
  private GitHub clone, so a visibility toggle would hand over a repo whose runs never start.
  Credentials are the **same GitHub App's** client id/secret: no second app to register.
  **Two ceiling side-effects, both from the god-file ratchet:** `config/_settings.py` was at 499/500,
  so `role_model_for` + `held_out_ok` moved to `config/_roles.py` as thin delegators (the split that
  module exists to make; no call site changed). `store/_projects.py` now sits at **exactly 500** —
  the next line added there fails CI, so it wants its own cohesive split (`project_cost` +
  `project_metrics` are the obvious pair). Flagged, not done: out of this slice's scope.
  **UNVERIFIED and deliberately not hidden:** whether a GitHub App *user* token is accepted by
  `POST /user/repos`. GitHub's docs name OAuth-app and classic PATs and are silent on App user
  tokens. The callback passes GitHub's own message through verbatim so the live leg settles it; the
  fallback (register an OAuth App) is a config change, not a redesign.
  **red-team: done** — 3 rounds pre-merge, 2 FIX-NOW both fixed and pinned: the "no existing repository" rule lived only in the UI (any admin could repoint a working project at an empty repo), and the installation listing rendered GitHub's first 30 as if complete.
  **Slice 5 — first-run setup ([ADR-0121](adr/ADR-0121-first-run-git-setup-registers-the-app-instead-of-asking-for-it.md)), BUILT 2026-08-28.**
  Connecting a forge is a wizard now, not a list of env vars — one shared shell (step indicator,
  instructions derived from THIS instance, fields, Back/Continue) for both providers.
  **GitHub registers its own App in one click**: the App-manifest flow returns id + slug + private
  key + client id + client secret in a single response (verified against GitHub's REST schema
  before building, after two earlier assumptions in this arc proved wrong), so no credential is
  typed, no PEM touches a clipboard, and ADR-0120's repo creation arrives configured rather than
  needing a second pass. Least privilege is declared IN the manifest — `contents` + `pull_requests`,
  no events — so an over-broad App is never created rather than narrowed later.
  **GitLab is a three-field form** because it has no equivalent; its value is stating the Redirect
  URI **derived from this instance** (a hardcoded one is wrong for every self-hosted install and
  only surfaces later as an opaque OAuth error), plus the scope and Confidential flag. Reuses
  `/gitlab/config` — no new endpoint.
  **Found by a test, not by reading:** `settings_store._ALLOWED_KEYS` is deny-by-default, so the
  five GitHub keys were silently dropped — the wizard reported success and stored nothing, the
  *green-by-vacancy* shape again.
  **red-team: done** — 2 rounds, no FIX-NOW. Residual accepted: with no `MOSAERA_SECRET_KEY`,
  `encrypt_secret` is identity by documented design (the same treatment `gitlab_token` has always
  had) — pre-existing, not introduced and not silently fixed here.
  **OWED:** the live manifest round-trip against github.com, and ADR-0104's GitLab application
  round-trip. **The GitHub manifest round-trip RAN LIVE 2026-08-28** — an app was registered from the wizard, its credentials stored, and the installation listing read real data back (`rengifosec`, USER / ALL REPOS). ADR-0104's GitLab application round-trip is still owed.

  **Slice 6 — create AND push ([ADR-0120](adr/ADR-0120-create-a-github-repository-on-a-discarded-user-grant.md) Amendment 1), BUILT 2026-08-28.**
  Live use found slice 4 half-built in two linked ways. (1) Creation was **unreachable for every
  project that has code**: the precondition was "has no `source_repo`", but a project whose source
  is a local path has a source and no *repository* — exactly the project the feature exists for.
  The rule is now "not already on a forge", which keeps the red-team control (a forge-backed
  project still cannot be repointed) while admitting the case it was written for; the project pane
  no longer dead-ends an unknown provider either, which is why GitHub was missing from project
  settings. (2) **An empty repo is worse than none** — the project's next run would clone nothing —
  so the grant now creates the repo *and pushes the project's existing history into it* before
  `source_repo` is repointed.
  **The ordering is the control:** push, then repoint, never the reverse. A failed push leaves the
  project on its working source and says the repo exists but is empty. Pinned by a call-order test
  and a no-repoint-on-failure test. The push writes only to the remote — no named remote, no
  tracking ref, the operator's own `.git/config` unchanged, proven by a real push at a real bare
  repo. The user token still does its work inside one request and is still never stored.
  **OWED:** the live create-and-push round-trip, and the open question of whether an App user token
  is accepted by `POST /user/repos` — this slice's first real click settles both at once.

  **Slice 7 — local-first projects ([ADR-0123](adr/ADR-0123-a-project-may-start-with-no-upstream.md)), BUILT 2026-08-28.**
  `source_repo` is now **optional**: a project with none gets a working repository initialized on
  the server (`init_project`), one with a source is cloned into the same place and keeps it as the
  upstream. This is what unblocks the whole arc — repository creation only applies to a project not
  yet on a forge, and until now none could exist, so slices 4–6 were untestable by construction.
  **It cost a function, not a migration**, because the model was already the architecture:
  `clone_project` already kept the long-lived working repo at `projects_dir/<id>/repo`,
  `_init_empty` already made the greenfield commit, and `reposhape` already had an `empty` shape
  (ADR-0113). The working path is derived, so **no Alembic revision** (head stays 0035).
  **A hazard found while reading and guarded:** `_clone_into` now refuses a blank source, because
  `Path("")` resolves to the server's **current working directory** and `Path("").exists()` is
  True — a blank source would have cloned whatever directory the API was started in. Same
  cwd-inheritance shape as the 2026-08-10 store loss.
  Publishing now pushes the **working repo** rather than `source_repo`. Two files hit the god-file
  ceiling and were split cohesively: `projects.py` → `backlog_ops.py` (299 lines now), and the new
  tests → `test_repo_local_first.py`.
  **OWED:** create an empty project live, watch intake reach `ready`, then publish it — the same
  click that settles whether GitHub accepts an App user token for `POST /user/repos`.

  **Slice 8 — SETTLED, and corrected ([ADR-0120](adr/ADR-0120-create-a-github-repository-on-a-discarded-user-grant.md) Amendment 2), 2026-08-28.**
  The live click answered the open question: a GitHub App **user token cannot create repositories**
  — `403 Resource not accessible by integration`, GitHub's phrase for "this is an App token and
  Apps may not do this". The documented fallback is now the decision: repository creation uses an
  **OAuth App**, configured separately, with the same authorize shape, state machinery, discarded
  grant, derived name and push-then-repoint ordering. Only the client id/secret differ.
  **The correction that mattered more than the fallback:** ADR-0121's manifest stored the App's
  OAuth pair as this credential, so the wizard produced a configuration that **read as complete and
  provably could not work** — green-by-vacancy in the credential layer. The conversion no longer
  stores that pair, ADR-0121's now-false claim is struck, and repository creation has its own setup
  (`POST /api/github/oauth-app`) with the callback URL and instructions in the panel. The 403 now
  names its own remedy instead of dead-ending.
  **Why the design survived being wrong:** the callback passes GitHub's message through verbatim
  rather than a generic failure, which is what identified the cause on the first attempt and made
  the fix a configuration surface rather than a redesign.
  **OWED:** register the OAuth App, then re-run create-and-push on an empty project.


  supplying its panel shell separately.
  **OWED, unchanged:** the live GitHub App round-trip (criterion 4). This slice is unit-tested only,
  so the surface is polished against a flow whose live leg has still never run.
  **#121** onboarding workflow —
  **BUILT 2026-08-24 ([ADR-0113](adr/ADR-0113-the-oracle-plan-is-chosen-at-onboarding.md), Alembic
  0033); the stranger-test is OWNER-OWED and deliberately not claimed.** `mosaera_core.reposhape`
  measures the clone and states which of `evaluate_oracle`'s four independence legs can vouch,
  reusing the gate's own `authored_suite_asserts_behaviour` rather than counting `test_*` files. The
  surface is a pre-filled CHECKLIST beside the Quincy chat (never a blocking wizard), opening on the
  one row that decides whether a run can conclude. **The operator test command is now reachable from
  the product** — it was wired to `build_graph` and settable only by the CLI's `--test-cmd`, so the
  cheapest independence leg was unusable. Run mode becomes a project default (`RunItemBody.mode`
  goes `| None`, or the column would have been an invisible control) and is named as a DIFFERENT
  axis from ADR-0046's posture, which the issue conflated it with. Every gate reason now carries a
  **remedy** — `lib/remedy.ts`, total over `GateReason` with its knob names checked against
  `GENERAL_KNOBS`, both guarded from Python — and `oracle_unverified`'s is leg-aware off the
  already-recorded `oracle_blocked_by`. `reachability` is finally rendered on the board (served
  since F76/#78, never shown, so it surfaced only as a launch-time 409). Gate untouched; no
  posture-relaxation mechanism. **Not built, and honestly so:** the "what a typical item costs"
  half of the budget row — that number does not exist for a new project, so the card offers a cap
  and says no cost has been measured.
  Sequencing note: #119/#120 are logistics; #121 plus #118
  decide whether a stranger's first day feels magical or broken.

- **[arc] Agents that know what they own — ADR-0110 (accepted 2026-08-23)** — the 2026-08-23
  LedgerCLI session produced **both halves of the team-behaviour question in one run**. Facing an
  acceptance test whose assertion can never pass (`assertNotIn('', content)` on an empty CSV; `'' in
  ''` is `True`), the coder named the contradiction and escalated, and the **Proctor** rewrote it —
  the producer never touched its own bar. Facing an `UnboundLocalError` in code it had just written,
  it concluded *"likely due to Python caching or installation issues"* **twice** (run
  `20260823-220123-d624b9`) and item #126 never delivered. The difference is a **control**, not
  intelligence: the first boundary is encoded three times over (`prompts.py`, a tool-level refusal,
  ADR-0087's contract registry); the second is encoded nowhere.
  **Same blindness as F87**, which spent **291,846 coder tokens** on *"network issues"* while
  validation ran the same suite to 79 passed — so the producer has now narrated two different
  external causes for one missing instrument. Three sequenced slices:
  **S1 environment truth** (a deterministic fact surface on the `_exec.py` probe seam — resolved
  module path, hash, interpreter, `sys.path`; **retires** `_uninstalled_note` rather than adding a
  sibling detector, per [ADR-0085](adr/ADR-0085-oracle-defect-detection-strategy.md) §1);
  **S2 failure-ownership taxonomy** (extends `escalate_arm.py` on
  [ADR-0090](adr/ADR-0090-gate-reason-classification.md)'s one-table pattern, so the escalation
  carries a *who*, not just a *that*); **S3 role context** (the six accountabilities as structured
  context in `agents/prompts.py`, never dialogue).
  **S1 must be MEASURED before S2 is scoped** — comparable-item A/B in F87's shape (coder tokens,
  coder calls, misroute count). The honest failure mode to watch: visible misdiagnosis falls while
  wasted iterations do not. Non-goals, recorded: **no gate relaxation** (autonomy grows on the
  posture axis — [ADR-0046](adr/ADR-0046-posture-and-autonomy-governance.md) — never the gate's
  authority), no agent-to-agent chat (*Not Yet*), no new agents.
  **S1 BUILT + DEPLOYED 2026-08-24; the measurement is OWED and deliberately NOT forced** —
  `tools/repo/_envfacts.py`, attached to a failing probe *and* a failing `run_tests` (the path the
  belief actually formed on), host-side only so it cannot time out or fail, on-failure only.
  `_uninstalled_note` retired into it per ADR-0085 §1. Two follow-ups came from USING it, neither
  visible in the code: it now **emits a firing signal** (a tool's return value reaches no durable
  record, so *"did it fire?"* was unanswerable and the first A/B was unattributable — F83), and it
  **de-duplicates** (a coder probing in circles received 16 near-identical blocks — F84).
  Seven mutants killed across the three commits.
  **The A/B has no population yet:** across every run on 2026-08-24 the block fired **zero times on
  a failing suite** — runs either passed first try or never reached validation. The guided corpus is
  the wrong instrument (broken *graders*, not environment confusion). Stopped rather than spend, per
  [the mutation-veto lesson](engineering-history/mutation-veto-ab-2026-08-11.md). Evidence now
  accrues passively as the product is used. **S2 stays unscoped until it exists.**
  Items: **#111** (S1),
  **#112** (S2),
  **#113** (S3),
  **#114** (the observed defect).

- **[debt] Operator friction — LedgerCLI case study #2 (2026-08-23, F64–F74)** — the console was
  driven toward a finished product by a non-technical operator using **only the UI**
  ([friction log](engineering-history/ledgercli-friction-2026-08-23.md)). The board moved from
  *9 in review · 5 deferred · 1 stuck* to *13 done · 1 in review · 2 to-do*; **delivery and the
  merge were not reached**, so ADR-0102 slice P's finish line ("the LedgerCLI case-study merge
  driven entirely from the Delivery page") is still unmet. The engine's judgement held up
  everywhere — the PM defended the brief and refused to re-scope items that could not comply, the
  escalation asked a real question, the gate refused to call unverified work proven — and the cost
  was all ergonomics: **#93** Deferred is
  a state the engine can assign and the operator cannot leave (F66, FIXED 2026-08-23),
  **#94** review asks for approval without
  showing the change (F68), **#95** raw
  Python reprs in the item sheet (F67),
  **#96** the PM prefill caret trap (F73),
  **#97** cards show the latest run not the
  delivering one (F69), **#98** the
  api-token bit that decides whether a project can finish is invisible (F64). Two engine findings
  are the substantive ones: **#99** a
  backlog can be generated that violates the brief's own written prohibitions — #113 burned 8 runs
  against a contradiction no control caught (F65) — and
  **#101** /
  **#102**, a `.gitignore` costing 1.34M
  tokens and 7 revisions because the reviewer misread the run's own cumulative diff (F70/F71).

- **[debt] Console UI: the Firehose Audit rulings (owner-driven, 2026-08-22, frontend-only, no ADR)** —
  the console led with evidence instead of a verdict and repeated the same fact several times per
  screen. Built: the derived verdict card + proof radar, item-consolidated Runs, the overview trend
  radar, task-title-not-paragraph everywhere, and the redundancy pass (one fact → one render per
  screen; global delivery knobs moved off the project Delivery page into Settings › Autonomy, where
  two editable copies of one stored value became one). Then the **Overview worklist**
  (owner-driven, 2026-08-22/23): the page reported nouns and left the operator to infer the verb, so
  every open item is now bucketed by the ONE intervention it needs (`lib/triage.ts`, a ladder whose
  partition is test-proven), a thrash detector names items failing the identical way, proof became a
  project-wide aggregate over DELIVERED work with independence first and counts carrying visible
  denominators, the server-derived decisions (ADR-0105) moved out of the PM transcript into a
  "Waiting on you" band + the header bell (per project; blocking conditions are never dismissible,
  ADR-0107), and charter constraints render as rows. Remaining, ruled but not built: the Quincy
  summary-bubble placement on history pages, and the drill-down layer the cleanup was the
  prerequisite for. (The Artifacts brief pane was listed here as unbuilt and **already existed** —
  `DocumentsPanel.tsx` has rendered it since `7daf6d9c`, 2026-08-13, before this entry was written.
  Corrected 2026-08-24.) The receipt-backed axes landed as
  [ADR-0109](adr/ADR-0109-project-proof-aggregate.md) (2026-08-23): `GET /projects/{id}/proof`
  aggregates the sealed receipts of DELIVERED runs under five rules — one origin, no synthesis,
  unreadable-is-unknown-and-stays-in-the-population, the source set disclosed so the summary can be
  reconciled by hand, and the denominator is what was measured.

- **[arc] Operator-grade MR management (ADR-0103, owner-approved 2026-08-14)** — a faithful
  multi-line MR body / edit-before-send / labels / squash / branch picker need the GitLab REST
  API (`api` scope), which push-options cannot do. Phases: **1** optional per-project
  `api`-scoped token (`gitlab_api_token`, Alembic 0026, encrypted) + `connectors/gitlab_write.py`
  (create/edit MR, list branches) — trust boundary, red-team DONE (all 4 claims hold); **2** the
  pre-filled editable MR compose Sheet on the Delivery page (push-plain-then-POST when api token,
  else push-options fallback); **3** "open one combined MR" operator action + squash toggle; **4**
  branch v1 (list + prune-merged + `_stacked_target` skips merged predecessors). Deferred:
  arbitrary commit-subset grouping (needs cherry-pick/rebase — absent), branch rename/checkout/
  worktree. Push transport + the autonomous sweep stay `write_repository` throughout.
  - **Git-control trio (owner-requested 2026-08-14, ADR-0103 follow-up, no new ADR)** — closes the
    two deferrals above that turned out cheap. **A1** target-branch picker reads the LOCAL clone
    (`local_branches` in `tools/repo/diff.py`), so it needs no api token and always populates.
    **A2** commit-picker: `commit_list` + `cherry_pick_into_branch` (`tools/repo/cherry.py`) cut a
    fresh branch and cherry-pick the chosen commits; the compose-with-commits `merge` endpoint holds
    the project mutex + 409s on an active run (the pick mutates the shared clone) and aborts cleanly
    on conflict. **A3** single-branch remote delete (`POST …/branches/{branch}/delete`, `mosaera/*`
    only in the UI) + the prune/delete guard now refuses a branch that is the SOURCE *or* stacked
    TARGET of an open item MR (the open-MR-target orphan the ADR-0102 live validation hit). Still
    deferred: rename/checkout/worktree (race the shared clone).
  - **GitLab OAuth "Connect" ([ADR-0104](adr/ADR-0104-gitlab-oauth-connect.md), owner-requested
    2026-08-14, trust boundary)** — provision a project's tokens by authorizing with the configured
    GitLab instead of pasting a PAT. Mint-and-store: exchange the code (scope `api`), mint ONE
    project access token (`write_repository`+`api`) via `POST /projects/:id/access_tokens`, store as
    both `gitlab_token`+`gitlab_api_token`, discard the grant (no per-user table). **Self-hosted
    first** — every endpoint derives from `settings.gitlab_url` (gitlab.com never hardcoded); the
    OAuth app registers on that instance and the Connect UI shows the host. Client secret env OR stored-encrypted (env wins; amended 2026-08-14)
    (`MOSAERA_GITLAB_OAUTH_CLIENT_ID`/`_SECRET`+`MOSAERA_BASE_URL`). New `OAuthState` (Alembic 0027,
    hashed/single-use/TTL/bound to user+project); admin-gated `/api/oauth/gitlab/start` + a pre-auth
    top-level `/oauth/callback` (spent state + live-session re-check, fixed internal redirect).
    Red-team 3 rounds, no FIX-NOW (`docs/engineering-history/redteam-gitlab-oauth-connect-2026-08-14.md`);
    TM-0002 updated. GitHub still deferred ([ADR-0001](adr/ADR-0001-stack-and-architecture.md) — a
    plain OAuth App can't mint a clean per-repo token). **OWED:** the live provider round-trip
    (register the app on `gitlab.rengifo.me`, set the env, connect a project).
    - **One control (Amendment 2, owner-requested 2026-08-18)** — the credential UX was four entry
      points in three visual languages. Consolidated to one GitLab button on the project whose
      label is the state (Configure / Connect / Manage), opening one dialog that carries the
      instructions + the two values; the manual PAT pair moves inside it as a disclosure and the
      New Project token field is gone. **No gate moves** — a member sees read-only status and no
      button, because Connect is a secret write (ADR-0004) the server already refuses. New
      `ui/dialog.tsx` (centered sibling of `ui/sheet.tsx`); project settings panes became
      addressable via `?pane=`, so the OAuth callback and the delivery CTAs land on Integration
      instead of General. The owed live round-trip above now validates both at once.

- **[arc] Quincy as the control surface ([ADR-0105](adr/ADR-0105-chat-as-a-control-surface.md),
  owner-requested 2026-08-19)** — the owner wants work done FROM the PM chat, with the other tabs
  demoted to drill-downs. One slice of the ADR-0045/#31 "Quincy as the single interface" DIRECTION,
  not the arc. **Slice 1 (on staging):** `GET /projects/{id}/decisions` derives what is waiting on a
  human (parked gate · GitLab not connected · MR whose recorded target is gone) — no table, nothing
  to go stale, and listing never rehydrates a run. Quincy may REFERENCE `[[decision:<id>]]` and
  never mint one: the server intersects every reference with the freshly derived set, so an invented
  id renders nothing. Actions carry `{label, kind}` and hand off to the surface that already owns
  the authority; the GitLab setup action opens the SAME dialog as Settings, so **no credential ever
  traverses the chat**. Cards are query-backed and survive a reload (closing the standing
  `PmChangesetCard` TODO). Forced two cohesive splits: `pm_turn.py` out of `projects.py`,
  `pm/_chat_prompt.py` out of `_backlog.py`. **`red-team: done`**
  (`engineering-history/redteam-chat-control-surface-2026-08-19.md`) — 3 FIX-NOW: the stored
  transcript kept the raw `[[decision:]]` markers (a reload showed them), the interactive turn
  derived twice and could block ~40s on an unreachable GitLab, and a pasted credential persisted
  verbatim and was replayed to the model each turn (now redacted, partially). The headline threat
  the design was built around — a model conjuring a credential prompt — held. **OWED:** live
  validation.
  **NOT in slice 1:** backlog editing / run launching / settings from chat, more decision kinds,
  and any generic card registry (Not-Yet until a second use case exists).
  - **Slice 2 (on staging, 2026-08-19)** — prompted by the owner asking Quincy to check git hygiene
    on a live project and getting "I don't have direct access to the repository" four times. Adds a
    **`## Delivery` section to the PM context** (the backlog rows always carried
    `branch`/`mr_url`/`mr_state`/`mr_target`; the renderers discarded them), a **`delivered_no_mr`**
    aggregate decision — which immediately surfaced **six LedgerCLI items and one Ledger Demo item
    delivered with nothing proposing them** — and routes remote-derived branch names through
    `quote_repo_text` (slice 1 interpolated one raw). **Slice 1's network BAN on the chat path
    becomes a ~3s DEADLINE**: the 20s worst case that justified it was never observed (~140ms
    measured against this self-hosted instance) and its real cost was Quincy being blind to a
    decision the panel was showing him — the Round 2 question the slice-1 red team left open. When
    the read does not land the block says **NOT CHECKED** rather than implying a clean repo.
    **Live-validated 2026-08-19** — same question, same project: Quincy went from "I don't have
    direct access to the repository" to naming all six stranded items, the open MR, the real branch
    list and correct MR counts; and on a project with no api token he correctly refused to say
    whether branches were stale. **`red-team: done`**
    (`engineering-history/redteam-delivery-in-pm-context-2026-08-19.md`) — 2 FIX-NOW, the dominant
    one found by the owner: a card that resolves nothing was labelled "Waiting on you", so decisions
    now carry a `blocking`/`standing` tier.
    - ~~**The `[[decision:<id>]]` channel is ON PROBATION (2026-08-19).**~~ — **RETIRED 2026-08-22**
      (ADR-0105 amendment; the strip survives it, see `pm_turn.py`). The kill criterion below fired:
      it never took hold in natural use, and the in-chat cards it pointed at moved to the Overview's
      "Waiting on you" band, so a marker naming a card that no longer exists in the transcript is
      worse than no marker. The strip is NOT optional and stays — Quincy still sees pending
      decisions in context and can still emit the old marker, and it runs BEFORE the message is
      persisted, because the stored transcript is what a reload renders. The probation record is
      kept below because the reasoning is the point: a channel with a kill criterion fixed in
      advance was killed on schedule rather than argued about.

      The original entry, for the record: it had never fired in live
      use. The convention moved out of the system prompt to sit under the ids it refers to (the
      credential prohibition stayed put — standing safety rule, trusted channel), and is now
      measured: a log line per offering turn, an audit event per fire. **Kill criterion fixed in
      advance:** 20 offering turns or one week; still zero ⇒ remove the clause, the regex and the
      validation. The cards are server-derived and unaffected, and the no-minting guarantee does
      not depend on the channel.
      **Tally RESET 2026-08-19** — the context de-duplication below restructured what the
      experiment measures, so the pre-reset turns cannot be carried across the changed baseline.
      Pre-reset data, kept for the record: **3 offering turns, 1 reference — it fired for
      the first time ever**, so the relocation demonstrably changed behaviour and the pre-move
      recommendation to cut it would have been premature. Caveats recorded now rather than later:
      the fire came on a leading question ("show me the decision I need to act on"), while the
      natural phrasing ("is anything waiting on me?") did NOT fire and Quincy answered from the
      delivery block instead, naming item #104's open MR rather than the pending decision. Three
      scripted turns are not evidence of natural use; the count continues under real usage.

- **[debt] The charter posture is decorative** — `free`/`business`/`regulated` is stored
  (`store/_charter.py`), validated and admin-gated on write (`routes/projects.py:307-315`), shown in
  the UI (`CharterSummaryCard.tsx`) and described to Quincy — and **read by no code that changes
  behaviour** (verified by exhaustive grep 2026-08-19; `regulated` on the ledger-demo project
  enforces nothing). Same class as the removed `reviewer_advisory` knob: a control that only exists
  in the surface offering it. Deciding what `regulated` *does* — e.g. force the delivery gate, forbid
  `auto_open_mr` — is an ADR-level design question, so this is tracked rather than patched. Until
  then the honest minimum is to stop presenting it as operative.

- **[arc] Delivery pipeline completion (owner-requested 2026-08-18, ADR-0103 Amendment 2)** —
  "every stuck state has an in-product fix." Landed on `staging` in three commits:
  **(1)** `projects.mr_source` (**Alembic 0029**) — the project MR's source branch is RECORDED, not
  guessed. Found live: project MR !4 sourced from `mosaera/item-102` while the guard protected
  `projects.branch`, so the branch a live MR depended on was protected by nothing. Same defect
  0028 fixed for item MRs, one level up. Forced a cohesive split of `models.py` (at the 500 ceiling)
  into `models_attachments.py`.
  **(2)** MR **close/reopen** (`state_event`, item + project, member-available like `retarget` —
  closing destroys nothing and reopen undoes it): the product could previously only ever OPEN an MR.
  Plus: every REST read moves off the `write_repository` push token onto the `api` token — the poll
  and the MR-URL fallback were spending a token whose scope cannot make those calls, which is HOW
  items got stranded with a branch, `mr_state = "opened"` and no URL; and the operator's chosen
  target is now applied BEFORE the empty-diff refusal, which previously made that state unrescuable.
  **(3)** `split_backlog_item` / `merge_backlog_items` get the delete guard (the row is the record
  branch protection reads; they were two more doors to the same orphaning); `?force=` re-reads a
  wrongly-recorded `merged` (the state that makes a branch prunable); a merge request deleted in
  GitLab is forgotten on **two** facts (MR 404 **and** project 200 — GitLab 404s for *unauthorized*
  too, so one fact would let a token that lost access strip protection).
  **Live-validated** 2026-08-18 on `app.mosaera.dev` (0029 backfilled `mr_source` from MR !4's own
  JSON; the delete of `mosaera/item-102` now refuses naming the project MR; close→reopen→close
  round-tripped against GitLab; `?force=` backfilled two stale `mr_target`s). That validation found
  the `mr.reopend` audit-name typo (`08b4e30`). **`red-team: done`** —
  `docs/engineering-history/redteam-delivery-pipeline-2026-08-18.md`: 3 FIX-NOW (all fixed), the
  dominant one self-inflicted (the phantom-MR fix created a new stranded state).
  Explicitly OUT of scope, still open: clone re-clone/reconcile for a diverged or missing project
  clone, and a stuck-project-mutex release — each is a new operator power over shared state.

- **[arc] Delivery spine (ADR-0102, owner-approved 2026-08-13)** — make the git/GitLab last
  mile true → complete → operable. Slices, in order: **T** gated-actions truth-up + MR token
  posture (policies — red-team: pending) · **D** base-drift fail-closed before the item-branch
  cut · **O** operable item MRs (manual open endpoint, `mr_state` per item via Alembic 0025,
  MR-URL fallback; `routes/projects.py` at 489 ⇒ route extraction) · **H** delivered-but-
  unpushed readiness state · **P** the **Delivery page** (the operator's git-delivery
  management surface). Finish line: the LedgerCLI case-study merge driven entirely from the
  Delivery page. Out of scope: GitHub wiring (the `delivery.py` outcome layer is the seam),
  workspace GC (existing [debt]), webhooks (poll stays). Pre-existing loose end seen while
  editing: branch `fix/audit-clean-db-error` is pushed with no open MR.

- **ADR-0101 (2026-08-13): run interaction modes** — ask / accept / auto, operator-switchable
  mid-run; gates redefined as direction / escalation / convergence / delivery. Engine+API mode
  plumbing and the web mode-switcher/gate-dock land with it (demo-readiness arc). Counsel
  (out-of-band PM channel) recorded as DIRECTION, deferred. Park after-action ("why it
  stopped" + Send to Quincy) landed 2026-08-13.

- **THE SEQUENCE from here (2026-08-11) — decided, in order.** Recorded because it was agreed in
  conversation and conversation is not a durable artifact.
  **Landed on `staging` tonight:** slices 1 + 2.1, the escalation no-op fix, ADR-0099 (undeclared
  destruction), the control-liveness audit, the security-chain positive control + `never-scanned`
  cause recording, the critic probe, and the evidence-store fix (`4e61c6c`).
  **The measurement baseline** is [`engineering-history/corpus-baseline-2026-08-11.md`](engineering-history/corpus-baseline-2026-08-11.md)
  — 125 runs on one commit: **31% over-park, 0 false ships**.
  1. **Record which oracle leg refused — DONE 2026-08-11.** `graph/_oracle_legs.py` computes the
     verdict and the per-leg record in one evaluation, so the record cannot drift from the decision.
     `blocked_by` names the refusing term; it reaches the live payload, committed state, the
     receipt, and the scorecard (via the ADR-0078 park-capture seam in `bench/harness.py`).
  2. **A/B the mutation veto — DONE 2026-08-11, NULL RESULT, default unchanged.**
     ([record](engineering-history/mutation-veto-ab-2026-08-11.md).) 250 runs. Over-park **39 → 38**
     — 0.14 standard errors, i.e. nothing. **The experiment was underpowered and provably so in
     advance:** the effect was known from arm A to be ~7 runs (5.6pp) and the binomial SE at n=125
     is 5.8pp, so the noise floor was ~15 runs. One division would have shown that before spending
     5.5 GPU-hours. A paired design (re-run only the refused runs, or fix seeds across arms) is the
     fix; an unpaired 125-vs-125 cannot see a 7-run effect.
     **Both recorded predictions failed** (over-park 31%→26%: actually 30.4%; false_ship stays 0:
     one appeared, though it carried `mutation_caught=True` so the veto could not have caught it).
     **What IS established, needing no statistics:** the veto is deterministic given a proven
     `False` — 0 such runs delivered in arm A, **8 delivered in arm B, all 8 grader-passing**. Its
     cost is real; its benefit stays unmeasured (0 false ships in arm A means no veto *could* show a
     true positive). Safety control stays ON under that asymmetry.
     **Incidental:** sanctioned test edits fire on 21/125 runs, so ADR-0087's backstop is
     load-bearing — 6 arm-B runs still park on it, `sanctioned=True, mutation_raw=None`, **all 6
     over-parks**. Unexamined, and the most promising remaining lead.
  3. **THE OVER-PARK CAUSE, FOUND 2026-08-11** —
     [attribution](engineering-history/over-park-attribution-2026-08-11.md). **26 of 38 over-parks
     are runs whose OWN tests failed while the hidden grader passed**, and **16 of 16** of those
     authored ≥1 test that the case's correct `reference/` solution fails. The honesty machinery
     works; its input is wrong. The oracle arc explains 3 of 38 — a sideshow that cost two sweeps.
     **[ADR-0062](adr/ADR-0062-proctor-faithfulness-detector.md) already documented this mechanism**
     (2026-07-19) and **forbids the obvious fix**: deterministic auto-loosening was built,
     red-teamed and REVERTED (a loosened assertion widens the acceptance class → false ship; STOP
     rule tripped). **Do not rebuild it in any disguise.** Its untried lever (MR-D) is being
     measured now: route the TESTER role to a stronger, *different* model — config only, since
     `tester_model == coder_model` today. Enriched 6-case probe, power computed before running.
     Also recorded: `overstrict_static` has ~11% recall against ground truth (4 of 250 runs) — a
     detector that is silent, not wrong.
     **MR-D MEASURED 2026-08-11 and REFUTED**
     ([record](engineering-history/tester-model-probe-2026-08-11.md), ADR-0062 Amendment 1). 30
     runs: pooled over-strictness **+4%**, inside the +21% noise floor, against a pre-registered
     ≥50% reduction. Delivery 55%→40%, capability 91.0→88.8, false ships 0. **The heterogeneity is
     the finding** — 4 cases improved 52–65%, MCB-22 got 3× WORSE (5.60→17.00). A stronger model is
     a better Proctor on most cases and badly worse on at least one; the average cancels. Default
     stays `qwen3-coder:30b`. **The dominant over-park cause is therefore still open.**
     **Method note, third instance in one day:** at 20/30 runs this read **−51%** and was reported
     as encouraging; the last case moved it to +4%. Partial reads of the ordered corpus have now
     been wrong every time they were taken.
     **Owed before the next Proctor experiment:** record the authored suite SIZE on the card —
     `overstrict_vs_ref` is a count, so "wrote more tests" and "wrote worse tests" are currently
     inseparable.
     **Next lead:** 5 sole-cause `critic_vetoed` over-parks — the critic is alive
     (positive-controlled 08-10) but may not be calibrated, and it is the remaining named lever.
  4. **Slice 4 (MODIFY) — MERGED 2026-08-11.** Red team done (R2 confirmed + fixed: a bare-name
     collision handed the Proctor an unrelated test). **MCB-28 measured**
     ([record](engineering-history/mcb28-slice4-measurement-2026-08-11.md)): on the runs where the
     Proctor complies, `tests_tampered` / `validation_failed` / `claim_behavioral_failed` **all
     vanish** and every claim is satisfied — the deadlock breaks, observed for the first time.
     Compliance 0/5 on the default tester, 2/5 on a larger one (suggestive only at n=5).
     **⚠ CORPUS DISCONTINUITY:** this merge took `--all` from **25 to 26 cases** (125 → 130 runs),
     because `available_cases()` globs the directory. Corpus-wide rates from before it are not
     comparable to sweeps after it; per-case comparisons are.
  5. **THE CRITIC VETOES CORRECT WORK — 9 firings, 9 wrong, across 260 runs.** 8 of 9 quote a
     PREMISE sentence ("crashes on the first malformed op", "the existing test asserts the OLD
     unrounded result") — the state the item exists to change, which a correct fix necessarily
     falsifies. Structural cause: an unmatched sentence mints material with `oracle_kind: none` →
     disposition `unbound` → **the gate discards it** ("intake's job") **but `unbound` is inside the
     critic's veto jurisdiction**, so a model gates on evidence the deterministic layer refused to
     gate on. Third recurrence of the class (MCB-03, MCB-13, MCB-28); `_PREMISE` already carries
     near-miss patterns for all eight, so extending it is STOP-rule territory. ~~**This is the last blocker on MCB-28 and the current top priority.**~~ **CLOSED 2026-08-11 by
     ADR-0100** — `unbound` removed from the critic's residual jurisdiction, closing the class by
     construction; MCB-28 then delivered `clean_deliver` with zero gate reasons. Corrected
     2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`.
  9. **OVER-PARK REDUCTION — branch `research/over-park-reduction` (2026-08-12).** Baseline
     47/130 (36.2%) attributed as a PORTFOLIO of six populations, not one cause
     ([ledger](research/over-park-reduction-ledger.md)). **P1 LANDED, measured on the four
     refactor cases (n=20/arm): delivered 7→18, over-park 8→2, false ships 0** — the engine was
     grading its own scaffold's frozen snapshot as delivered source (E1), and the "short
     orchestrator" contract had no number (ADR-0082's named gap; the ratified
     `structural.body_statements=5` is now the bench default, `bench/_clauses.py`). E1 alone was
     measured to false-ship and reverted same-day; the pair lands together. Remaining
     populations: P2 validation_failed (17, quoted-example assertions designed), P3 SQL
     independence (5, needs ADR), P4 mutation-blocked (7, extend #62), P5 Proctor compliance
     (5, owner model-tier call), P6 reviewer-only (5). Honest ceiling ~11–15% without P5.
  8. **Slice 3 (attribution) — LAST, and currently undemonstrable.** Its rule only fires when the
     system would otherwise escalate to a larger model, and the escalation ladder is empty (the
     configured model is not installed). **It cannot fire on the bench as configured.** It needs
     either an installed escalation model or deliberate fault injection before it can be shown to
     work at all. Do not mark it done on unit tests.
  - **Slice 5 (REFACTOR) stays blocked** — [ADR-0085](adr/ADR-0085-oracle-defect-detection-strategy.md) §1
    freezes the deterministic layer against semantic detectors.

- **FOUND + FIXED 2026-08-08 — Layer 2 has NEVER been eligible, because it reads a blank field**
  ([ADR-0078](adr/ADR-0078-terminal-gate-visibility.md) amended — its **fourth** residual).
  Driving the mechanism rather than reading it: **2,049 stored scorecards, 544 honest parks, Layer 2
  eligible ZERO times.** `gate_node` interrupts before its only returns, so a run that parks and is
  never resumed commits nothing it computed — `final["gate_decision"]` is blank exactly where a
  judgement about the park must look. Its own decline said *"no blocking gate reason"* while the
  scorecard beside it read `gate_reasons=['claim_structural_failed']`.
  **ADR-0078 (2026-08-02) already documented this root cause** and fixed the measurement reads; it
  listed three residuals and Layer 2 — which predated it by ten days — was not among them, though it
  is the only one gating a mechanism that can **ship unattended**. *(This was reported as undocumented
  before checking. It is the fourth re-derivation of documented prior art in this project's record,
  and the second today.)*
  **The writer-side fix was rejected**: putting the decision into state would show the FROZEN
  ADR-0069 classifier the captured `iteration_limit` and silently move the clean-conclusion headline
  — ADR-0078's own load-bearing constraint, with two tests guarding it. Instead `RunOutcome.terminal_state`
  composes the captured terminating facts over `final`; the classifier keeps `final`. `reliability.py`:
  **0 changed lines**. The same capture repairs ADR-0090's `unsatisfied_claim_kinds`, which had been
  reading `{}` on parked cards since it shipped that morning.
  **Post-fix, n=10:** the decline now names the true blocker and the kinds field carries
  `{'ast_transformation_contract': 3}`. Still 0 conversions — those parks were structural, which
  ADR-0092 deliberately does not rescue, so the deny path is confirmed live. **The first attempt was
  underpowered by design** (cases picked on "reasons now admissible", which selects for exactly the
  structural parks that are not rescuable — ~10% of runs produce a convertible park, computed after
  the fact rather than before). Re-targeted on cases with no structural claims. New instrument:
  `mosaera-layer2-report` reads every scorecard ever written and renders the four-cell matrix —
  rescued/right, rescued/wrong, parked/right, parked/wrong — and **refuses to print a bare zero**:
  0 false ships over a handful of conversions bounds the true rate near 50%, not 0.
  **Corpus finding worth carrying:** of the **264** parks that recorded a reason (285 more are
  measurement-blind, pre-ADR-0078), **92 carry the class-1 shape and the hidden grader passed on 91**
  — correct work the system discarded, and the population this mechanism exists for.
- **SHIPPED 2026-08-08 — #68 MR2: the
  claim reason splits by evidence class ([ADR-0092](adr/ADR-0092-claim-reason-split.md)).**
  `unsatisfied_claim` → `claim_behavioral_failed` (`shortfall`) / `claim_structural_failed`
  (`objection`) / `claim_integrity_failed` (`tamper`). **The Layer-2 converter is unblocked on the
  dominant over-park shape** — the F62 gap is closed. Two re-scopings made this smaller and safer
  than ADR-0090 predicted. **The mandatory replay analysis was not needed:** the stall breaker
  compares fingerprints *within a run only*, so a split changes the hash value and not the equality
  relation. **The real hazard was suppression**, which ADR-0090 floated and this ADR refuses:
  emitting FEWER reasons is the only thing that can empty `reasons` and flip a park into a **ship**
  through `_resolve`'s positive allowlist. So the split never suppresses, deny-preservation is
  **provable** rather than empirical, and the proof ships as `test_gate_monotonicity.py` — an
  exhaustive cross-product over every gate input × the failed-class powerset, asserting the
  surjection. Core partitions oracle kinds into classes (`packages/policies` may not import core, and
  mirroring `ORACLE_KINDS` there would have recreated ADR-0090's defect at a new seam); the flat id
  list is unchanged so the receipt seal is byte-for-byte. **Red team, 3 rounds, and R3 broke this
  ADR's own plan:** the plan proposed fingerprinting reason CLASSES to stop the split losing stall
  trips — refuted twice over (it doesn't fix that case, and where it differs it makes the breaker
  *more* aggressive, contradicting ADR-0069's explicit guardrail), reverted, and **ADR-0069 left
  untouched**. R1 no finding; R2 one ACCEPTED residual (an `unevaluable` structural claim emits no
  reason, so a park can convert with the AST shape unproven — pre-existing, now reachable); R3
  replayed all 299 stored cards with **0 admissibility changes**. A second self-inflicted FIX-NOW
  during implementation: the first draft's no-classes fallback emitted the *most* permissive class,
  which is not a deny-by-default. **Eligibility is not conversion** — `disposition_gap_close` stays
  default OFF with zero production conversions ever; whether Layer 2 converts these, and with what
  mutation outcome, is the next measurement. Still open: the ESCALATE arm's own class tuple (gated on
  MR3's stale-`gate_decision` defect).
- **DEFERRED 2026-08-09 — the mutation gate does not discriminate; the sweep was stopped at 58% by
  owner decision** ([record](engineering-history/layer2-mutation-parity-2026-08-09.md)).
  112 runs · 25 parks · 13 eligible · **0 converted · 0 false ships**.
  - **The grader probe answered the question it was built for, in the direction that matters.** In
    **5 of 5** cases where both checks produced a verdict, the **hidden human answer key survived
    the mutation check exactly as the model's authored test did** — spread across **four distinct
    cases** (MCB-03/05/08/13), checked specifically because eligibility was concentrated. Zero cases
    where the grader caught what the authored test missed. So the dominant refusal — *"the authored
    test does not catch a mutation"* — is **not** "the model writes weak tests". The gate's second
    pillar is not separating rubber stamps from real oracles.
  - **The false-ship rate is STILL unbounded — the third consecutive attempt to bound it.** Zero
    conversions ⇒ the rule of three bounds nothing. Before a fourth attempt, fix the denominator:
    **MCB-05 alone produced 8 of the 13 eligible parks**, so any rate off that sample is
    unrepresentative.
  - **ADR-0094's widening worked:** 6 wrong deliveries reached the gate (the WRONG column, empty
    across 193 prior runs) and all 6 were refused. Necessary but NOT sufficient — a
    refuse-everything mechanism scores identically, and with 0 conversions the data is still
    consistent with exactly that.
  - **F84's measurement came back EMPTY, and that is a result:** 0 scanner no-verdicts in 112 runs
    against 17% (33/193) in the morning sweep. Transient, not a standing defect. A failed
    prediction, recorded rather than dropped.
  - **Why deferring is reasonable, not avoidance:** slices 1–4 delivered four deterministic oracles
    that owe nothing to mutation, and slices 6–8 are likely to produce the reference-level and
    structural machinery that makes designing a mutation *replacement* cheaper than it would be
    today. Designing it now on 5 data points would repeat the premature move this session already
    made twice. **Slice 5 stays BLOCKED** — diff-scoped mutation is its proposed oracle.
  - **Data preserved:** the 112 cards are durable but separable only by mtime window, so the record
    pins the baseline commit (`4bcaa77`), the window start (`1786317156`) and a re-runnable
    analysis script (`scripts/experiments/layer2_probe_report.py`).
- **SHIPPED 2026-08-09 — verb-arc SLICE 4 (MODIFY): a behaviour change must know who it breaks
  ([ADR-0097](adr/ADR-0097-consumer-impact-modify.md)).** Stacked on slice 1
  (`worktree-slice4-modify`) — it reuses the non-use reference walk and shares its files.
  - **The defect:** a MODIFY item deadlocks or launders. The test asserting the OLD behaviour fails,
    the gate sees `validation_failed` — **indistinguishable from "the code is wrong"** — so the run
    grinds to the cap against a test it may not touch, or the coder rewrites the contract that
    judges it. Measured: `Change \`load_config\` to return …` mints `acceptance_test`, whose oracle
    is `tests_passed` VERBATIM. MODIFY minted not *nothing* but a claim that cannot tell *"the test
    failed"* from *"the test was supposed to fail"*.
  - **The design INVERTS slice 1.** A MODIFY verb is how ordinary work is described, so the ORACLE
    is the discriminator, not the pattern: *did anything already depend on this symbol?* Consumers
    with no test among them → `impact_unassessed`. `_REMOVAL` had to be narrow only because
    `non_use_proven` could not make that distinction; here over-matching is harmless by
    construction, which is the better property.
  - **A planning assumption was measured and REVERSED.** The plan said "no new bench case — MCB
    already has MODIFY-shaped cases", justified by a grep claiming 19 of 25 briefs. Both wrong: the
    grep counted prose. Of the 14 real modify-verb sentences, **not one is a behaviour-change item**
    — "persist the change" (a noun), "after your change:" (a discourse marker), "Do not change any
    observable behaviour" (a refactor's PRESERVATION clause, the inverse claim), `update_user` (an
    API name). The pattern mints **0 of 372** real claims, which is correct. **MCB-28 added** — the
    corpus had no MODIFY item, exactly as it had no SUBTRACT item before MCB-27.
  - **Red team: R1 clean, R3 clean, R2 CONFIRMED AND FIXED** — a symbol MOVED to a new file read as
    "new code" and its consumers went unassessed (a false `satisfied`, the only unsafe direction).
    Fixed by asking the better question: a pre-existing CONSUMER is itself proof the behaviour could
    be depended on. A second self-inflicted defect was caught before the red team reached it — the
    filter was first written file-level, calling a brand-new function in an existing file a
    modification.
  - **Not Layer-2 convertible**, pinned with the ADR-0094 knob ON: Layer 2 verifies with a
    BEHAVIOURAL test, the very evidence a behaviour change invalidates.
  - **Owed:** MCB-28 executed (needs the sandbox; queued behind the sweep) and the ADR-0087 wiring —
    the amendment path can now key on a claim instead of freeform operator text.
- **SHIPPED 2026-08-09 — verb-arc SLICE 1 (SUBTRACT) lands: a removal now has an oracle
  ([ADR-0095](adr/ADR-0095-non-use-oracle-subtract.md)).** The first sliced item to move off zero,
  and the first work this session that is *on the roadmap* — Layer 2 (F83/F84/F85) appears **zero
  times** in `verb-arc.md`, is gated on `mode == "autonomous"` **and** a default-OFF knob, and has
  never shipped anything in production.
  - **The deadlock was reproduced before anything was built:** every removal phrasing classified
    `('none', True)` — a MATERIAL claim with NO oracle, unsatisfiable by construction — while
    `delete_file` sat admin-opt-in and off, so the coder could not do the work either. A removal has
    **no behavioural signature**: absence cannot be exercised by a test, and a green suite proves
    only that what remains still works.
  - **1.1/1.2** a `non_use` oracle kind + `nonuse.py`, deterministic reference enumeration (no model
    call, no sandbox), tri-state in the `structural_spec` shape — downgrade-only, `None` never
    vouches. **1.3** `delete_file` only, git untracking deferred (closes verb-arc open question 1).
    **1.4** `removal_unproven`, its own `removal` evidence class, `objection`, PROOF-BEARING.
    **1.5** MCB-27 — the corpus's first subtract case.
  - **Unprovable is FAILED, not `unevaluable`** — the one deliberate divergence from every other
    oracle kind. `unevaluable` is right for a claim about behaviour (absent evidence is not an
    objection) and **wrong for a claim of absence**, where the requirement is literally *removal
    without a non-use proof cannot ship*.
  - **It cannot be Layer-2 converted, by construction.** `claim_structural_failed` is the bucket
    ADR-0094 widened yesterday; an unproven removal landing there would have become auto-ship-
    eligible, and Layer 2 verifies with a BEHAVIOURAL test + mutation, which says nothing about
    whether the removed thing is still referenced. Pinned with the widening knob explicitly ON.
  - **Red team (1 pass): R1 no finding** (monotonicity sweep — downgrade-only holds); **R2 no
    finding** (18/18 reasons classified); **R3 CONFIRMED and FIXED** — `getattr(m, "legacy_export")`
    names its target as a STRING, so the AST pass vouched for a removal a live caller still used. A
    false vouch is the ONLY unsafe direction this oracle has. Fixed with an exact-match string pass
    returning `None`; exact and not substring, because treating a docstring mention as a caller
    would make it refuse nearly everything.
  - **Over-match measured, not assumed:** a bare verb search produced **5 false positives** across
    the 27 shipped briefs (`delete` naming a CLI verb, a dict method, a payload action — all
    features being BUILT). Narrowed to a leading imperative / explicit passive: **0 of 361 real
    claims** now mint `non_use`.
  - **Four guards caught incomplete wiring** and each was a real gap: the proof-bearing registry
    (whose error names the `validation_not_attempted`-unprotected-for-six-days precedent), the
    termination-reason branch, the operator's plain-English sentence, and memory's re-declared
    vocabulary.
  - **VALIDATED 2026-08-10 — and the first run exposed a defect in the oracle itself.** MCB-27
    over-parked **2/2** with the hidden grader PASSING: a test asserting the symbol is gone
    (`from pkg import gone` inside `pytest.raises(ImportError)`) is an `ast.ImportFrom` like any
    other, so **the test that proves a removal was the thing that refuted it** — this slice's own
    grader makes that exact assertion. Fixed by scoping the walk to the production tree
    ([ADR-0095](adr/ADR-0095-non-use-oracle-subtract.md) Amendment 1); 5 of the 6 new tests fail
    against the unfixed oracle. **MCB-27 then delivered `clean_deliver` with an EMPTY gate**, and
    7/7 offline controls confirm `removal_unproven` still fires on a live production caller, a
    symbol never removed, a dynamic string reference, and a tests-only tree. Both directions
    proven.
  - **Still owed:** item 88 and LedgerCLI item 4 replayed LIVE (needs a deploy). Expected outcome
    is a **park naming the capability**, not a delivery — git untracking was scoped out.
- **SHIPPED 2026-08-09 — verb-arc SLICE 2.1: the probe now says when it fell short, and the
  shortfall is counted (ADR-0059 amendment).** Second sliced item off zero, on its own branch
  (`worktree-slice2-exec-ceiling`, based on staging — file-domains are disjoint from slice 1, so
  independent MRs rather than a stack).
  - **Slice 2's premise did not hold.** Its goal is *"close the largest MEASURED harness gap"* — and
    it was not measured. Of four ways `sandbox_exec` falls short, **none reached a durable record**:
    `emit_activity` writes to the ephemeral LangGraph stream, so no checkpoint and no scorecard.
    *"Does the 30 s / 4 KB ceiling actually bind?"* had no answer.
  - **One was a correctness bug, not telemetry.** A **timed-out probe returned its partial output
    with nothing saying so** — `outcome.ok` was False and the return path ignored it — so the coder
    could read a half-finished probe as the complete answer and conclude the opposite of the truth.
    Now stated FIRST, with the partial output still shown (it is evidence, just labelled).
  - **NO ceiling was raised and NO knob added — deliberately, and this is a scope reduction from the
    approved plan.** The plan called for four configurable ceilings to enable an A/B. That is
    speculative machinery: if the corpus shows nothing binds, the answer is no raise; if something
    binds, changing a constant on evidence is a one-line diff. Raising a ceiling nobody measured
    would have been **F83's mistake for the third time this week**.
  - **Containment untouched** — `readonly_work=True`, `-B`, network-off and the fail-closed
    `SandboxViolation` all verified structurally. `sandbox_exec` extracted to `tools/repo/_exec.py`
    for the god-file guard (behaviour-preserving; the same split `_read`/`_scratch`/`_activity` had)
    rather than shaving pre-existing comments to make room.
  - **Red team (1 pass): no findings.** R1 containment + all four ceiling values unchanged; R2 each
    count is emitted before its STOP return with nothing between, so counting cannot weaken a
    budget; R3 the marker leaks no path/host/argv; R4 no `packages/policies` reader — advisory only.
  - **A test found a documented weakness by accident:** writing "different" probes as `print(0)`,
    `print(1)`, … made the repeat guard fire 20 times, because `fingerprint` STRIPS DIGITS. That is
    red-team #55's finding — cosmetic digit variation evades the repeat guard, which is precisely
    why the hard TOTAL session budget is the load-bearing bound. Now pinned on purpose.
  - **Owed:** the corpus measurement. Honest coverage limit — counts are pinned in `test_node`, so a
    run that hand-raises from `capture` to `supervise` records nothing. That UNDER-counts, biasing
    toward "no raise needed": the conservative wrong answer, not the dangerous one.
- **AUDITED + CLOSED 2026-08-09 — F85 part 2: the leak audit is complete, and the second
  contaminant was worse-shaped than the first.** Exactly three things write into a judged
  workspace: the answer key (`grade.py`, fixed), the case **seed** (legitimate), and the
  **reference solution** (`faithfulness.py`). Both parallel harnesses (`guided_cli`,
  `govbench/live`) grade LAST and run nothing on the tree after; `report.py`/`suite.py` write to
  output dirs. No pre-delivery leak exists — workspaces are seed clones, and `grader/`+`reference/`
  live outside agent containment.
  - **`overstrict_vs_reference` overlays the CORRECT SOLUTION over the delivered code and never
    restores it.** It was safe only because it sits at line 178 of a dict literal while the Layer-2
    attempt sits at line 150 — **safety by evaluation order**. Layer 2 avoided judging reference
    code by luck of placement; anything added after that point would read a tree in which the agent
    appears to have written a flawless solution, and convert it.
  - **Its stated justification was false.** *"The workspace is discarded immediately after"* —
    measured: **1,941 workspaces on disk, 1,863 still carrying a leaked grader.** Nothing is
    discarded, and none of this was recoverable from the excuse.
  - **Fixed as a mechanism, not a comment:** the overlay writes a `_MCB_POISONED` sentinel BEFORE
    running anything (so a mid-measurement crash still leaves the tree labelled), and
    `assert_judgeable` REFUSES a poisoned tree. Unlike the answer key this cannot be cleaned up —
    the delivered work is gone, overwritten — so refusing is the only honest response. Pinned by a
    test that runs the overlay FIRST and asserts the attempt declines.
  - **The grader-vs-authored diagnostic is built** (`bench/grader_probe.py`): re-runs the SAME
    mutation check on the SAME changed lines with the hidden grader as the suite, strictly AFTER
    the real verdict, purging the key in a `finally`. It reuses the verdict's own `source`/`changed`
    rather than recomputing — one origin. Pinned structurally so it can never reach the verdict:
    the grader is the independent judge, and a judge that also decides makes the false-ship rate
    unmeasurable by construction. That IS what F85 was.
  - Answers on the next sweep: **does the gate discriminate** (clean), **why the scanner is
    unavailable 17%** (F84), and **grader vs authored** — one run, three questions.
- **RETRACTED + FIXED 2026-08-09 — F85: the bench was handing Layer 2 the answer key, so every
  Layer-2 safety number ever measured is contaminated.** Found mid-sweep while building the
  grader-vs-authored comparison. `grade()` copies the hidden acceptance suite to
  `<workspace>/_mcb_grader/` and never removes it, and **grading runs BEFORE the Layer-2 attempt**.
  Confirmed in a live workspace from the running sweep: `_mcb_grader/test_acceptance.py` sitting
  beside `tests/`. Two leaks: the green step runs `pytest` at the workspace root with only
  `--ignore=.mosaera`, so it **collected the answer key**; and the tester authors with repo tools
  that can **read** the tree, so its "independent" test could be copied from the key beside it.
  - **The signature was unmistakable once looked for:** **6 of 7 grader-WRONG deliveries failed the
    green step and 0 of 6 grader-RIGHT ones did** — a perfect separation produced by an authored
    test the same cards show is a rubber stamp 4 times in 7.
  - **RETRACTION.** The mid-sweep report of *"7 of 7 wrong deliveries refused, 0 false ships"* is
    **withdrawn**. It is an artifact. The eligibility counts and the mutation results (the 9
    rubber-stamp findings) are unaffected — only the GREEN step was contaminated.
  - **It biased toward SAFE, which is the dangerous direction.** Production Layer 2 has no answer
    key, so the bench granted the mechanism an oracle the real system will never have — while that
    bench was the evidence for switching it on. ADR-0094's pre-registered condemning outcome could
    not have fired.
  - **Fixed:** `_purge_grader` removes the suite before ANY Layer-2 step and **fails closed** — an
    unpurgeable key declines the attempt rather than measuring, because a measurement taken with
    the key present reads as a safe result. `GRADER_DIR` now has one origin, imported not repeated.
  - **The widened sweep was STOPPED at 42%** rather than run to completion: every further minute
    produced data that could not answer the question it was launched for.
  - Open: the same leak may affect other bench consumers that run the delivered tree after grading.
- **INSTRUMENTED 2026-08-09 — F84: a 17% scanner-availability rate is the largest single source of
  discarded correct work, and nothing recorded why.** Found while diagnosing the biggest waste
  bucket during the widened sweep. `security_unverified` means a scan was EXPECTED and produced **no
  verdict** — absence of evidence, not a finding; `security_findings` was raised **zero** times in
  193 runs. It fires on **33 of 193 runs (17%)**, of which the hidden grader passed **29**, and it is
  the **only** reason disqualifying **25** parks from Layer-2 class 2.
  - **A CORRECTION to ADR-0094 and to what was reported here.** The claim *"security_unverified is
    never the sole blocker, so relaxing it unlocks exactly zero runs — dead on data"* was computed
    under **class-1** rules, where `validation_failed` is itself disqualifying. **Class 2 admits
    `validation_failed` as a `shortfall` — that is its entire premise** — so for class 2
    `security_unverified` IS the sole blocker, on 25 parks (21 correct work). The reasoning was
    wrong; **ADR-0094's decision is unaffected**, because the structural bucket was chosen for being
    the only *mixed* one. Corrected in the ADR and in `eligibility.py` rather than left standing.
  - **Deny-by-default on absent security evidence (ADR-0076) is NOT in question and is untouched.**
    The defect is that the evidence is absent 17% of the time. Fixing availability removes the
    blocker without relaxing Sentinel's veto — which remains the wrong move.
  - **Instrumented, not fixed — deliberately.** `run_one` collapsed **four** causes into one
    `ran=False`: a sandbox exception, a timeout, a bad exit code, and `incomplete` (semgrep's
    `errors[]` non-empty, so **one unparseable file voids the whole repo's verdict**). Cause 4 is
    the most suspicious given agent-written code and `--max-target-bytes 0`, but there is no
    evidence for it, and **naming an unmeasured cause is the defect F83 committed and then repeated
    inside its own fix**. `run_one_with_cause` records it; `run_one` delegates so the two cannot
    disagree about what counts as a verdict.
  - **Proved inert:** `status` is computed exactly as before across all five paths, pinned by
    `test_scan_cause.py` — the load-bearing test, since `scan.py` produces a security verdict.
  - Next: decompose the 17% by cause on a sweep **after** the widened one finishes (they contend for
    Docker and Ollama). The fix follows the measurement; it is not designed yet.
- **MEASURED 2026-08-09 — the 193-run sweep: F83's fix is CONFIRMED with power; the false-ship rate
  is still unmeasured, and the matrix has an EMPTY COLUMN.** All 24 cases ×8, 13.9 h, isolated by
  mtime against `b408fb4`. 96 clean deliveries · 74 honest parks · 21 thrash parks · 1 crash.
  **74 parks → 13 eligible → 13 attempted → 1 converted.**
  - **The pre-registered prediction is confirmed, and this one IS powered.** Inconclusive mutation
    checks fell from **16/16 (100%) pre-F83 to 3/13 (23%)** — Fisher exact **p = 1.4e-05**. The
    oracle now returns a real verdict on 10 of 13 attempts (9 SURVIVED, 1 caught) where it
    previously returned none, ever. That is the defect F83 named, measured.
  - **The headline is still unanswered.** **1 conversion, 0 false ships.** Rule of three puts the
    95% upper bound at 3/1 = **300%** — it bounds nothing. One conversion is not a rate, and
    `disposition_gap_close` stays default OFF.
  - **The empty column is the real finding.** All 13 eligible parks were on work the hidden grader
    **PASSED**. Zero were on wrong work. So the gate has **never once been handed a wrong delivery
    to refuse**, and its 12 refusals cannot be scored as correct — there was nothing wrong to catch.
    Measured discrimination is currently **undefined**, not good: on this record it is a mechanism
    that says no to almost everything, and 12 of 13 times that no discarded correct work.
  - **Eligibility, not the oracle, is the binding constraint** — 13 of 74 parks (18%). The turn-aways:
    19× gate reasons outside the class allowlist (`security_unverified`), 19× core reasons beyond
    `oracle_unverified` (`claim_*`), 13× `coder_escalated` (a hand-raise routes to the ESCALATE arm),
    8× the suite was not green, 2× the held-out critic vetoed. Widening this is the only way the
    false-ship question gets an answer, and it is a scope decision, not a measurement.
  - **A defect the result exposed, fixed:** the single conversion — the only unattended ship in the
    entire record — carried an **empty `layer2_source`**. The audited-files capture had been added
    to the DECLINE path only, leaving the one verdict that ships code as the least auditable card
    written. Now instrumented on both paths and pinned by a test.
- **MEASURED 2026-08-08 — F83's pre-registered sweep: the oracle asked its first real question, and
  the headline number is UNRESOLVED at n=2.** MCB-06 ×12 + MCB-07 ×8 with `--layer2`, isolated to
  cards written after the F83 commit (the `--since` filter is date-granular and could not separate
  the same day's earlier sweep — that filter has now misled this project three times).
  **20 runs → 6 honest parks → 2 eligible → 2 attempted → 0 converted.**
  - **The mechanism is confirmed.** MCB-07's attempt returned `mutation_caught=False` — a mutant was
    **generated and survived**. That is the first real mutation *verdict* on these cases; every prior
    attempt returned `None`. It fired on precisely the diagnosed case class (the authored files are
    `test_off_by_one_bug.py` / `test_pagination_bug_fix.py`). The operators reach the shape that
    motivated F83.
  - **That decline is correct, not wrongful.** `unverified` + `grader_passed=True` means the code
    happened to be right *and* the independent test does not prove it. Deny-by-default is the right
    answer to insufficient evidence; it is **not** the equivalent-mutant wrongful decline R2 covers.
  - **The false-ship question is NOT answered.** Zero conversions ⇒ the rule of three bounds nothing.
    n=2 attempts cannot test the pre-registered prediction. It remains open, and
    `disposition_gap_close` stays default OFF.
  - **Unexplained and flagged:** eligibility collapsed to 2 of 6 parks (was 15 of 19). The new
    non-eligible reasons are `security_unverified` and `reviewer_requested_changes` sitting outside
    the class allowlist. Not attributable to F83 — different run mix, n=20 — but it is what starved
    the sample, and it is the binding constraint on ever measuring the false-ship rate.
  - **A defect the sweep exposed in F83 itself, fixed:** `not_measured` printed *"no mutable
    construct in the change"* for all four causes of a `None` (no tests, nothing mutable, no runnable
    execution, or the check raised). An unmeasured cause asserted in the record whose only job is
    separating causes — F83's own defect, one level up. `no_verdict_reason` now asks the AST. The
    existing D3 test disproved the old string **on its own fixture**. MCB-06's one `not_measured`
    was written by the pre-fix code and its workspace is reaped, so **its stated cause is
    unverifiable** — which is why cards now record `layer2_source`, the files the check judged.
- **SHIPPED 2026-08-08 — F83: Layer 2 refused 15 of 15 correct deliveries because its oracle had
  no question to ask ([ADR-0093](adr/ADR-0093-mutation-operator-sufficiency.md)).** With F81's decline
  reason finally recorded, the 40-run sweep read **15 eligible, 15 attempted, 0 converted, every one
  on grader-PASSING work** — and **7 of 8** reasons were *"the mutation check was inconclusive"*, not
  *"the authored test is a rubber stamp"*. `mutation: {'inconclusive': 8}`: zero survived, zero
  caught. Reproduced by hand — the delivered fix was `page * per_page` → `(page - 1) * per_page`, and
  the three operators (return→`None`, flip a comparison, delete a bare call) match **nothing** on that
  line. **The gate was spending silence as a refusal.** Fixed by two single-substitution operator
  kinds (`arith`, `const`), arid-context suppression, and `not_measured` splitting from `unverified`
  — it still declines, so nothing new ships from the split, but a coverage gap stops reading as a
  failed test. Operator choice is evidence-led, not taste: arithmetic is one of Offutt's five
  *sufficient* operators (99.5% coverage retained) with the second-lowest equivalence rate; ABS (47%
  equivalent) and UOI (24%) were **rejected**, as were the 4-way AOR cross-product (31% duplication)
  and the six-way CRCR (57%). **Red team, 3 rounds: R1 no finding; R2 CONFIRMED and FIXED** — two of
  the five swaps (`x - 0` → `x + 0`, `x ** 1` → `x * 1`) produced provably *equivalent* mutants, which
  in a binary ship veto are guaranteed wrongful declines, now suppressed by identity element (`x * 1`
  → `x / 1` deliberately kept: int→float is observable); **R3 ACCEPTED** — fuzzy called-name
  suppression can silence a user-defined `range()`, Google flags the same unsoundness, and the cost is
  a missed question, never a false ship. **Recorded honestly: this WIDENS a ship channel.** An
  inconclusive check always declined; a verdict-bearing one can convert, so **a false ship is
  reachable for the first time**. Pre-registered next measurement: MCB-06 ×12 + MCB-07 ×8 with
  `--layer2` — expect inconclusives to fall, and watch the false-ship cell. `disposition_gap_close`
  stays default OFF until it reads clean.
- **ANSWERED 2026-08-08 — F81/#84: the
  constant failed-claim set has TWO causes, and the second was not what anyone was looking for**
  ([record](engineering-history/claim-constancy-2026-08-08.md)). ADR-0090 deferred *"19 of 23 cases
  emit a byte-identical failed-claim id set"* as a minting bug. **It is not a bug in minting.**
  **(a) Within a version:** the id→kind partition is a pure function of the brief *and* all three
  behavioural kinds resolve to `state["tests_passed"]` **verbatim** — so a case's behavioural ids
  fail together or not at all. **18 of 24 MCB cases mint no structural claim at all**, so their
  failed set is driven purely by shared booleans. Every apparent anomaly resolves once behavioural,
  integrity and structural are treated as three independent channels. **(b) Across versions — the
  new finding:** the claim id space is **not stable**. Commit `5bcae6e` (2026-08-03) rewrote the
  sentence splitter (its own message: *"MCB-03: 16 claims → 9"*) and halved it, so MCB-06/21/22's
  stored cards cite ids **no current brief can mint** (`task-c37` on a case minting 21).
  `models_claims.py` documents `(item_id, claim_id)` as *"the cross-run key"* — **it is false** across
  that boundary. Latent, since the only reader is single-run scoped; it becomes live the moment
  anyone builds the cross-run analysis that docstring invites, and it is a concrete instance of the
  missing corpus/version identity on the benchmark. **Self-check performed rather than assumed:**
  ADR-0090's 118-card measurement spans the boundary, and on single-version data post-`5bcae6e` it
  is **stronger** — 88% (n=50) vs 30% (n=54). **Net effect: ADR-0090's MR2 argument is upgraded from
  a correlation to a proof**, pinned by `test_claim_constancy.py`, which fails if a behavioural kind
  ever gains a per-claim oracle. **No production code changed.** The corollary — on 18 of 24 cases
  the ADR-0079 claims apparatus contributes **zero** information to the gate — is filed as its own
  successor, not folded in here.
- **SHIPPED 2026-08-08 — F80: an operator's acceptance bar could be replaced by a sentence about
  replacing it ([ADR-0091](adr/ADR-0091-clarification-proposal-kind.md)).** Found while scoping
  ADR-0090's MR2. `clarification.proposals` has ONE consumer, which writes an accepted proposal into
  `backlog_items.acceptance` **verbatim** — the contract two producers were written against and
  state explicitly. The ESCALATE arm, added later, writes *instructions to a human* into the same
  field (*"Amend the acceptance criteria so tests/x.py can pass as written."*), and the card renders
  every proposal as a button labelled with its text. **One click destroyed the bar**, and the next
  run minted every ENTAILED claim from that sentence. `escalate_arm` is ON live, so this was
  reachable in production; it is reproduced end to end by a test that failed on the real arm driving
  the real route. **ADR-0090's defect one layer out** — a later feature landing on a contract nobody
  had written down, every test green. Fixed by making the channel declare `proposal_kind`
  (`acceptance` | `direction`) as a **required argument with no default**, refusing an index for
  anything else, and treating a **missing** discriminator as `direction` so every pre-existing row
  is refused rather than trusted. The arm also gains the operator position the card never had —
  **"the bar stands — the code is wrong"** — which leaves the acceptance untouched and *records* the
  affirmation, because the arm re-fires each sweep and asking every sweep is pressure, not a
  question. mypy caught a fourth mirror of the contract during implementation, which is the shape
  working. **Still open (companion gaps, not closed):** an acceptance change leaves **no versioned
  record** (four store writers overwrite in place, the resolve route emits no audit event, and the
  `"why"` is discarded unread — so *"what bar was run R held to"* is unanswerable; needs its own ADR,
  a new model module since `models.py` is at 500/500, and Alembic 0025), and a lowered bar still
  inflates `delivered_items` / `calls_per_delivered_item` on the card captioned *"Deterministic-first
  discipline"* while the number that would contradict it is bench-only.
- **Program:** Correctness **and** the change verbs. **Primary goal:** close v1.0 **Gate 2 —
  `false_ship` ≈ 0** vs the hidden grader, and drive **over-park** down.
- **Current bottleneck — RESTATED 2026-08-08, because the named one measured clean.** The section
  below has said for weeks that the correctness oracle is *"the load-bearing gap."* The 2026-08-08
  sweep measured **`false_ship` 0/72**. Gate 2 is still not *passed* (at n=72 the 95% upper bound is
  ~5%, and a rate is only a result when the distribution it bounds is named — ADR-0061 gate-2
  amendment), but it is no longer the worst number we have. **Over-park is 36.1%** — roughly 3× any
  other defect rate, up from 30% — and it was not the stated focus. Two bottlenecks now, named
  honestly:
  1. **Over-park** — 36.1%. **The #68 framing was wrong and is now corrected
     ([ADR-0090](adr/ADR-0090-gate-reason-classification.md), MR1 shipped 2026-08-08).** #68 asked a
     Gate-2 question — *may the disposition's independent re-verification establish an unsatisfied
     claim?* — and that question is **unanswerable as posed**: `unsatisfied_claim` is ONE reason
     string over three evidence classes with opposite correct dispositions. For the behavioural
     oracle kinds the "bound claim's oracle" is `state["tests_passed"]` **verbatim**, so a failure
     restates `validation_failed` — a reason both arms already admit; for
     `ast_transformation_contract` it is genuinely independent; for `tests_unmodified` it IS the
     tamper fact. **Measured over 2,055 stored scorecards, no new runs** — that corpus was destroyed
     2026-08-10 ([record](engineering-history/evidence-store-loss-2026-08-10.md)), so the split below
     is **recorded, not re-derivable**: of 118 cards carrying the
     reason, the `∧ validation_failed` group is **86% grader-PASS (n=63)** and the `∧ ¬` group is
     **69% grader-FAIL (n=55)**. And in **19 of the 23** cases that emit it, the failed-id set is
     byte-identical on every run — *a signal that does not vary with the run is not measuring the
     run* (a separate finding about claim **minting**, not resolved by the ADR).
     **MR1 shipped and is behaviour-neutral by construction** (pinned by a test): gate reasons are
     now CLASSIFIED beside the `GateReason` Literal, both arms derive their membership from the
     class rather than each holding a list, the private cross-module import is gone, a totality test
     fails if a new reason arrives unclassified, and the scorecard records the failed-claim
     `oracle_kind` so MR2's argument rests on a direct read instead of a proxy. **Over-park is
     unchanged: 36.1% before, 36.1% after.** Still open: **MR2** (the reason split + the admission
     matrix — needs a stall-fingerprint replay analysis, since the breaker fingerprints
     `sorted(set(reasons))`, plus ~3 red-team rounds and a non-leading ask, because every proposal
     the ESCALATE arm offers today lowers the bar and nothing records that it moved) and **MR3** (the
     arm's predicate is evaluated at two points against *three* states of `gate_decision` — absent,
     **stale**, real — blocked on extracting the block out of `nodes_plan.py` at 499/500).
  2. **The engine can only ADD** — no change verb except addition has an oracle. `_amendment.py`
     records it as the deadlock; item 88 and LedgerCLI item 4 cost ~7M tokens against it and neither
     shipped. Until 2026-08-08 **no wave named this at all**. →
     #82, design in
     [`design/verb-arc.md`](design/verb-arc.md).
- **STANDING BASELINE (2026-08-08, n=72 at engine 0.6.0): 90.3% clean-conclusion · false_ship 0/72
  (95% upper bound ~5%) · over-park 36.1% (26/72) · delivery 13/24 cases · 0 crashes · mean capability
  91.** Outcomes: 39 `clean_deliver` · 26 `honest_park` · 7 `thrash_park` · 0 `false_ship` · 0 `crash`.
  Cost 11.97M tokens / $1.71 / 1,220 calls. Per capability: greenfield 78 · bug-fix 87 · feature 97 ·
  refactor 93 · robustness 94. **Read honestly: clean-conclusion is flat within noise (−1.4pt, no seed
  control anywhere in the bench, temperature 0.1–0.2 per role), over-park moved the wrong way (+6pt),
  and roughly fifteen changes since the prior baseline bought no measured reliability** — which the
  pre-registration predicted, because the cycle's work was workflow-shaped and MCB exercises no
  operator, gate or amendment path. **The one result worth carrying: greenfield 78 is the *worst*
  capability**, below refactor and robustness. Every capability we score well on is brownfield-shaped
  — an oracle already exists to lean on. Greenfield is the one phase where the apparatus must be
  *created* before anything can be verified, and it is the phase a non-technical operator starts in.
- **The accepted reliability baseline has drifted DOWN across three measurements and was never
  restated:** `#43` records *"accepted by owner (2026-07-22): 94.4%"* → 2026-08-05: 91.7% →
  2026-08-08: 90.3%. The arc still reads as accepted. Treat 94.4% as historical, not as the bar.
- **PRIOR BASELINE (2026-08-05, n=72 at `c83d0be`): 91.7% clean-conclusion · false_ship 1.4%
  (1/72, 95% upper bound ~7.5%) · delivery 56.9% · 0 crashes · mean capability 89.5.** Retires the
  2026-08-04 figure (87.5% / 6.9% / 50%), which was taken BEFORE the vacuous-vouch fix: that 6.9%
  was **our defect**, not a capability gap — `check_structural_compliance` vouched on zero executed
  predicates and shipped five runs. MCB-05/15 now park **6/6**, confirming it. **Gate 2 still does
  NOT pass** under the restated wording, for two reasons the old wording hid: the bound is far from
  zero at this n, and the one remaining false ship (**MCB-18**) is a *no-op coder run* certified by
  a pre-existing suite — `standing_suite_is_independent_oracle` used as a sufficiency oracle when it
  is only a relevance heuristic, so a suite written before the task existed cannot fail for new
  behaviour. `reviewer_unknown` was a passenger (33/35 deliveries got a real APPROVE). **And the
  larger defect is now over-park: CORRECTED to 18 of 60 runs (30%), not the 5.6% first reported** —
  the original count included only `thrash_park`s, so the 14 over-parks that stopped *promptly*
  filed as `honest_park` and were never counted (honest about stopping, wrong about the work). 18 of
  25 parks had a passing hidden grader. `parked` and `grader_passed` were both already on every
  card and nothing crossed them — the ADR-0081 shape again, now closed by the standing `Fidelity`
  dimension. Up to 10 of the 18 fall in Layer 2's two convertible classes (`disposition_gap_close`,
  built + red-teamed, **default OFF pending exactly this measurement**); 4 are `stalled:plan`, which
  both predicates exclude *by construction, not by evidence*. **MEASURED 2026-08-05 (18 runs) and the
  answer was that the lever is switched off:** `unsatisfied_claim` (ADR-0079 Wave 2, 2026-08-02) is
  absent from `_GIVE_UP_ALLOWED_REASONS` (ADR-0075, 2026-07-23), so **Layer-2 class 2 cannot fire on
  the dominant over-park shape** — 7 of the 18, reproduced live on three cases. A feature landed on
  top of a deny-by-default allowlist and narrowed a measured converter to nothing, tests green
  throughout: #76's measurement no longer describes the engine. Unblocking it is a **Gate-2 question,
  not an edit** (may the disposition's independent re-verification establish an unsatisfied claim?) →
  ADR + red team. `disposition_gap_close` stays **default OFF** — zero conversions is not safety
  evidence. Record:
  [engineering-history/over-park-layer2-2026-08-05.md](engineering-history/over-park-layer2-2026-08-05.md).
  Prior record:
  [engineering-history/rebaseline-2026-08-05.md](engineering-history/rebaseline-2026-08-05.md).
- **DRIVEN AS OPERATOR — 2026-08-06 SUPERSEDES the 2026-08-05 result below. READ THIS FIRST.**
  The same greenfield project (LedgerCLI) was driven to **completion**: all three slices delivered
  (`c61a68e` guided, `0cd9f49` + `1294030` **autonomous**), on the 13th run — the previous 12 were
  cancelled. The 2026-08-05 paragraph that follows says *"0 items delivered"*; that is **no longer
  the state**, and it is kept only for the diagnosis it contains.
  - **The bottleneck moved.** It is no longer "can the operator path deliver". It was
    **#65 (F63)** — a delivered test cannot
    be legitimately amended, so an item that *changes behaviour* deadlocks. LedgerCLI hit it at item
    four: a five-line deletion took three runs and ~4M tokens and never shipped, with every control
    behaving correctly. **BUILT 2026-08-07** ([ADR-0087](adr/ADR-0087-test-contracts-and-renegotiation.md)
    §5 escalation half + §6): at the escalation gate the operator may authorize amending the
    specific blocking test(s); the **Proctor** — never the coder — rewrites them once, and the
    result lands in `proctor_edits` under the existing content pin. Knob `amendment_gate`,
    **default OFF**; red-teamed 3 rounds, 2 FIX-NOW. `#66`'s weakening measure
    (`assertion_profile`) landed with it and is what bounds the amendment within a file.
    **MEASURED LIVE 2026-08-07 — item #87 DELIVERED** on run `20260807-143934-8a8639`, clean gate
    (`action: deliver`, `reasons: []`, 35 passed, reviewer APPROVE, `oracle_verified: true`) after
    six attempts and ~5M tokens. Every designed property held in state: the operator authorized a
    SCOPE (3 node ids, server-intersected with the blocking set), `give_up_reason` stayed EMPTY (the
    F63 fix — the arm no longer ignores the answer), the **Proctor** wrote the content and the coder
    never touched the path, the result landed in `proctor_edits` so `tampered_paths` came back `[]`
    with `tampered_integrity` unchanged, the one-shot licence was consumed (`pending_amendment: 0`),
    and the assertion profile confirmed no collateral weakening. **Still open in ADR-0087:** §3's impossibility proof only — ~~the contract/ownership registry
    (§1–§4)~~ **SHIPPED 2026-08-07** (migration `0024_test_contracts`, `persist.py`; corrected
    2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`), for which the human's
    authorization currently stands in — and the registry now has its strongest argument yet (F67:
    six of nine claims "satisfied" by one shared fact, with no criterion→test attribution).

    Three blockers were cleared to get there, none of them the amendment: the planner's context
    window (`ollama_num_ctx` 16384 → 32768 — the prompt hit 16374 with 10 tokens of headroom and
    `done_reason='length'`), the F39 attribution work that made that visible in one run, and two new
    findings — **F65** (a human-approved Proctor edit of a delivered test has no sanctioning path,
    and the resulting tamper silently disqualifies the amendment gate) and **F66** (the offer's
    `criterion` is empty). Both in the friction log.
  - **Completion is not correctness.** All three slices delivered and
    #67 (F57) still shipped — `status`
    ignores months, and the authored tests never mention one. Every control passed on its own terms.
  - **Read before planning:**
    [lessons-2026-08-06](engineering-history/lessons-2026-08-06-first-project-end-to-end.md) (what it
    means + what to build) ·
    [run ledger](engineering-history/ledgercli-run-ledger-2026-08-06.md) (every run, cost, milestones)
    · [friction log](engineering-history/ledgercli-friction-log-2026-08-05.md) (F0–F63, each finding).
    **Load-bearing findings are now tracked issues #65–#70** — the log is a record, not a backlog.
  - **The models are not the constraint.** 0 corruption in 6 seeded-bad-oracle runs; the producer
    diagnoses broken bars and raises its hand. Every blocker was upstream (the bar) or downstream
    (a control, a gate, a screen).

- **DRIVEN AS OPERATOR (2026-08-05, `#53`) — the benchmark measures a path the product does not
  ship by default.** *(Superseded above; the delivery counts here are stale.)* A greenfield project
  (LedgerCLI) was driven end-to-end through the web UI:
  charter → backlog → runs. **Two runs, ~932,000 tokens, 0 items delivered — and `Vera`/`Rook`
  never executed in either.** The budget was consumed by authoring and six operator send-backs
  before verification began. That is not a Gate-2 result: `false_ship` is measured on runs that
  *reach* the gate, and MCB runs **autonomously** — no write gates, no operator send-backs, no
  interactive re-scoping. **The shipped default (`guided`) is therefore an unmeasured path**, and
  the failure it exhibits is invisible to every instrument we have. This is the `#68` shape one
  layer out: govbench grades the system that produces the brief; nothing grades the system that
  *executes under an operator*. **Gate 2's wording is not wrong — its scope was unstated**, now
  corrected in the gate table below.
  **What the run DID establish, and it is the good news:** the acceptance suite is a real
  discriminating oracle. Reconstructed verbatim and executed outside Mosaera, the Proctor-authored
  test **fails on the buggy implementation and passes on the corrected one, one identifier apart**
  (`except (ValueError, TypeError)` does not catch `decimal.InvalidOperation`, so a charter
  constraint — *"never print a traceback"* — was violated and the suite caught it). Test-first,
  the protected-suite mechanism, and honest parking all worked; the closing record read *"Nothing
  was delivered because the required proof never existed — that is recorded, not dressed up."*
  **The oracle is not the constraint on this path; reaching it is.** Root cause of both
  cancellations was a contradiction between two generated artifacts — the PLAN instructed a
  duplicate package, the DESIGN said none was needed, nothing reconciled them, and the same
  correction was issued **five times in one run** and then **reverted by the coder itself**.
  Encoding the rule as a charter constraint did **not** fix it (six violations in run 2): semantic
  constraints propagate, structural ones do not, because the per-run plan is the operative
  instruction at file-writing time. Full record + 31 findings:
  [engineering-history/ledgercli-friction-log-2026-08-05.md](engineering-history/ledgercli-friction-log-2026-08-05.md).
- **IN FLIGHT — the governance instrument (`packages/core/mosaera_core/govbench/`, issue #68).** MCB
  grades the coder on a *good* brief; nothing graded the system that produces the brief, which is
  how a standing decision sat inert for its whole life with unit tests green. Five pre-registered
  cases (`G-01`..`G-05`) scored on **Detected / Asked / Compounded**, deliberately in `make test`
  (no model, no Docker, seconds) because an opt-in control is a control that rots. `Asked` is
  precision AND recall — `G-03` must stay silent, so over-asking can fail. Governance dimensions
  carry `bucket="governance"` and are **not** weighted into MCB's `overall`: the frozen suite stays
  comparable (asserted: `available_cases() == 24`). The pre-registration caught two broken cases of
  mine on the first run. **Both arms now built** ([ADR-0083](adr/ADR-0083-governance-benchmark.md)):
  the expensive arm (`python -m mosaera_core.govbench.live`, opt-in) runs `G-01` on two arms that
  differ by *exactly* the operator's reply, which is what turns "it should have asked" into a
  measured claim — if the unasked arm scores the same, asking bought nothing. It grades parked runs
  too, so an over-park (grader passed, run parked) is visible rather than absorbed. **First sweeps
  run 2026-08-05** ([record](engineering-history/govbench-first-sweeps-2026-08-05.md)): G-01 at n=3
  per arm gives raw 0.48 / resolved 0.67, **overlapping ranges — `asking_paid: false`, not proven**;
  G-05 is 1.00 three times. Asking trends positive and is not yet claimable. Two findings came free:
  a **live over-park** (an asked run scored **1.00 on every hidden assertion and PARKED** with
  `oracle_unverified` — the first *direct* instance, where the re-baseline could only infer it), and
  **variance concentrated on the undecidable brief** (G-01 spans 0.00–1.00; G-05 does not move) — an
  undecidable brief produces an *unstable* answer, not merely a wrong one. Three of the first
  sweep's "false ships" were defects in graders written for this project, in the over-strict direction; that base
  rate belongs beside any governance number.
- **SHIPPED 2026-08-07 — intake asks whether an item is REACHABLE (ADR-0089, F76,
  #78).** A third deterministic axis beside
  checkability and decidability: can the engine's toolset actually BUILD this? Item 88 was checkable,
  decidable and impossible — five runs, ~2.9M tokens. **The root cause was that the capability
  boundary lived as prose inside a prompt**; it is now DATA that the PM prompt renders from and the
  check matches against, so the next unreachable class is closed by naming a capability rather than
  adding a regex. Ships **default OFF** with an inert-when-off test; `govbench` gained
  `expect_reachability` and **precision** is the number that decides whether it may ship on. First
  real content behind #6's "capability profiles", which had been one annotation line since ADR-0047.
- **DIRECTION — the environment arc (persistent project workbench + the deploy layer).** Researched
  and owner-reviewed over four rounds 2026-08-07, then **parked behind run reliability** on the
  owner's call. The finding worth carrying: Mosaera covers plan→test well, release partially
  (an MR, a human merges), and **nothing after** — and it has **no environment concept at all**,
  which is why a deploy layer is currently not designable rather than merely unbuilt. The reviewed
  design — an ADR settling environments/artifacts/deploy authority, plus a HUMAN-SURFACE-ONLY
  per-project workbench (own clone, isolated bridge network, authenticated dev-server preview, file
  browser, admin-gated terminal), with the rule that **the workbench is never an evidence source** —
  is preserved in [`design/environment-arc.md`](design/environment-arc.md) so it is not re-derived.
  **Not authorizing:** needs a tracked issue and an accepted ADR first. Also corrected there: the
  git gap is narrower than "the agent has no git" — `_stage_all` runs `git add -A`, which stages
  deletions.
- **SHIPPED 2026-08-07 — the invisible-control class closed, and the ratchet made to ratchet
  (#79,
  #80,
  #81).** **#79:** the F71 fix had covered
  one function and left seven — three states that were one empty tuple are now three sentences, via
  ONE classifier whose predicate is its `.paths` and whose reason is its `.reason`, so they cannot
  drift (the `deny_finalizes` trick, third use). **Writing the per-branch tests found a new defect:**
  the offer was computed without checking `tester_enabled` while the consumption requires it, so a
  tester-disabled run let an operator tick tests and then discarded the answer — F70/F71's
  offer-vs-consumption shape, third variant. **#80:** `hygiene_unavailable` was declared, populated
  and read by nobody while TM-0001 claimed it was "a distinct, warned, recorded outcome";
  `hygiene_status` now carries ADR-0076's tri-state to the panel, and "no Python changed" is finally
  distinguishable from "linted clean". Informational by choice — blocking would be a new control
  needing an ADR. **#81:** `GRANDFATHERED` had names but no sizes, so a listed file could grow
  forever and the guard only fired when you FIXED one. Sizes recorded; `scripts/` scanned; tests get
  a 1500 ceiling instead of an exemption (`test_api.py` is **5702**). **It caught its own author
  within minutes** — growing `client.ts` failed the new check, so the gate contract was split to
  `api/gate.ts` (1199 → 1070) rather than raising the number.
- **SHIPPED 2026-08-07 — the codebase audit: a new guard, three HIGH fixes, and a leanness result.**
  Rather than keep finding the same defect shapes one live run at a time, two read-only sweeps went
  looking for the rest. **New guard:** `check_state_keys.py` (wired into `make lint`, now six)
  fails any production `state.get("X")` naming a key `RunState` does not declare — LangGraph drops
  those silently (ADR-0026), which is how F66 shipped. Run red it flagged exactly three reads and
  **zero false positives** across 374 files. **Three HIGH fixes, none found by a run:** the gate
  reported security `"clean"` on the two branches that never enter `scan_node` (F77 — **this
  TIGHTENS a gate**, expect plan-unworkable stops to park on `security_unverified` now);
  `run_diagnosis` recorded an empty vouch on *every* live run (F78); `operator_edits` never reached
  the raw-bytes tamper guard (F79 — F71's defect at the third origin). **Leanness is good news:**
  ruff dead-code rules clean, no orphaned modules across 496 files, all 72 knobs genuinely read,
  `gap_fill` fully gone. `scan_node` extracted to its own module, taking `nodes_review.py` from the
  500 ceiling to 475. Release-record check hardened (`--strict`) and given the tests it never had;
  **the version is deliberately NOT bumped** — 0.6.1 is gated on item 88 + a benchmark, per the
  runbook. Open: #79 (the silent-refusal
  cluster), #80,
  #81.
- **CONFIRMED LIVE 2026-08-07 — the amendment path completes end to end** (run
  `20260807-223112-c21240`, item 88, 5th drive). `amended_tests` populated, `amendment_refusals: {}`,
  **`tampered_paths: []`**, `tests_baseline` re-pinned, and `tests_tampered` gone from the gate
  reasons — the state that failed on the previous run. **The operator refused half the offer, which
  is the more important result:** of two blocking tests only the self-referential one (F72) was
  legitimately amendable; `test_egg_info_files_not_tracked` correctly encodes the acceptance
  criterion and fails because the engine **has no tool that can untrack a file**. Authorizing it
  would have used a human signature to weaken a bar to fit a capability gap. **New finding F76
  (#78):** intake asks whether a criterion
  is *checkable* and *decidable*, never whether it is **reachable** by the engine's actual toolset —
  so an unreachable item burns whole runs and then mis-presents as a test problem at the escalation
  gate. **The test-contract registry remains unexercised** (records on delivery; five attempts, five
  distinct blockers, zero rows).
- **SHIPPED 2026-08-07 — §5 covers both origins its own offer accepts
  (#76, F71).** Measured live minutes
  after #75 made the offer fire: the operator authorized, the Proctor wrote the content, and the run
  ended `incomplete` on a tamper verdict with `proctor_edits: {}`. **The offer and the consumption
  disagreed about what may be amended** — `blocking_protected_tests` offers a baselined path OR one
  the Proctor authored this run, and every consumption mechanism handled only `integrity_baseline`.
  So **#87's success does not generalise**: it happened to take the inherited path, all 15 existing
  tests snapshot the file into that baseline first, and §5 was non-functional for half its own
  surface through three rounds of red team. Fixed by covering both origins and recording the result
  in **both** hash spaces. Red team round 1 of 3 clean; **rounds 2–3 outstanding**.
  **The class this closes:** F61's button, F65's vanished offer, F69's placeholder, F71's silent
  refusal — four in one day, one shape: *a control that offers or declines invisibly*. Every refusal
  now records its reason and shows it. Still open: #77
  (F72, the Proctor authoring a self-referential suite-runner test — which also produced a FALSE
  diagnosis blaming the filesystem). **Both graph god-files are now at the ceiling**
  (`nodes_plan.py` 499, `nodes_review.py` 500) — the next change to either must extract.
- **SHIPPED 2026-08-07 — the amendment gate gets evidence on the branch it fires on
  (#75, F70).** A coder hand-raise routes
  `implement → capture → supervise` and never touches `test`, so the only writer of `test_output`
  never ran and the offer was withheld — on exactly the branch where the producer is saying a
  protected test blocks it. Measured live twice on LedgerCLI item 88. The fix reuses evidence that
  already existed: `run_tests` takes no arguments and runs the engine's resolved plan in the
  sandbox, so the producer chooses only WHEN — its output is now pinned to `workspace.evidence_hash()`
  and persisted into a declared channel, failing closed if the tree moved. **Process finding
  larger than the defect:** ADR-0087 already recorded this residual verbatim and CLAUDE.md already
  said *"the stop works, the ask does not"* — it was re-derived anyway, the third instance of the
  F62/F58 failure. Writing a residual down is not sufficient; it needs an issue and a test.
  Red team 1 pass: **1 FIX-NOW** (the SHIPPING close-the-gap arm had inherited the fallback through
  a shared helper), 1 ACCEPT, 1 pre-existing. Still open: §3's impossibility proof.
- **AMEND-TESTS VALIDATED LIVE 2026-08-21 — run `20260821-225529-5cd3fb`, LedgerCLI #113.** The
  loop the whole arc was for, end to end: the operator answers, the Proctor acts, the run continues.
  `amend_tests` rendered **disabled with 0 of 6 tests ticked** (the R2 defect: before the fix it was
  clickable and ENDED the run while promising it continues), stayed disabled with 6 ticked and no
  note, and enabled only with both — the note being the amendment's recorded reason. Clicking it
  returned `status=running`, and the trace shows `supervise -> plan -> design -> author_tests ->
  write_file -> implement`: the Proctor re-authored the six stale tests coder-blind and the run
  carried on. Honest alternatives throughout — `send_back` and `stop_honestly` both declared
  `end_run`, so amending was the only option that could continue, and the machinery said so.
  **The affirmation held**: having answered "the bar stands" on the earlier clarification, the arm
  declined to re-ask (`bar affirmed for ...`) rather than nagging, and `acceptance` was never
  touched by any of it.
  **Two findings from the run.** The producer CONFABULATED a constraint — *"the system prevents
  re-editing files that have already been modified in this session"* — which does not exist anywhere
  in the tool layer, and the escalation relayed that fabrication as an operator-facing reason (the
  `claim_text`-asserts-a-conclusion shape, now with a second instance; recorded, not fixed here).
  And R3's accepted finding that `escalate-arm.suppressed` was reused for the already-answered case
  proved to be the COMMON rendering, not a rare one — "withheld a question from you" for a question
  the operator had answered. Split into `escalate-arm.affirmed`, muted: asking once is a question,
  asking every sweep is pressure.
- **THE AUDIT'S CRITICAL — CLOSED 2026-08-22 ([ADR-0108](adr/ADR-0108-evidence-describes-a-tree.md)).**
  A stale `security_status="clean"` vouched at the gate for a tree the scanner never saw and
  produced `reasons==[]` / `action=deliver` — it SHIPPED. ADR-0106 pinned one channel
  (`tests_passed`); ADR-0107 closed only the ABSENT case. **Absent suppressed a question; stale
  delivered.** Writers now stamp `security_tree`/`review_tree`, `graph/_freshness.py` owns the one
  comparison, and `security_stale`/`reviewer_stale` are classed `not_run` so the ADR-0107 ask still
  fires (pinned — an unclassified reason would have silently re-suppressed it).
  **Proven, not asserted:** the regression was RED before the fix and green after, driven through
  real LangGraph channels and the real `scan_node` so the contestable step — that iteration 1's
  verdict is still in state at the second gate — is *observed* rather than assumed by a fixture.
  **Two findings about our own instruments, both worth more than the fix.** (1) Measure-first was
  attempted and is IMPOSSIBLE from stored data: the stamp was never recorded, and `audit_events`
  node rows exist for only **6 of 131 runs**, so even the upper bound had no sample. A first cut
  reported "50% at risk" by flagging `scan -> review -> gate` — the normal path. That number was
  pure instrument artifact, the second such today. (2) Mutation testing caught a gap in the new
  test file itself: blanking the writer's stamp left every assertion passing, because an empty
  stamp reads as not-fresh and parks. Safe direction, but it would park EVERY run and nothing
  noticed — a control that can only reach one outcome is a constant, whichever outcome that is.
  Fixed by adding the fresh polarity; both mutations now killed.
  **Correction on the record:** the plan-unworkable edge is NOT the dangerous one (nothing writes
  after `test_node` there, so its verdicts are stale-but-accurate). The give-up-after-post-scan-write
  edge is. My first analysis had this backwards.
  **~~Honest limit inherited: 300 sorted paths~~ — SUPERSEDED, and the framing was the defect.**
  ~~The pin is now unbounded (`limit=None`, `c2c1ed8e`); ADR-0106's is still capped.~~ **STALE
  AGAIN — `f0666bfa` moved BOTH pins onto `evidence_hash`, and this line sat unchanged through the
  commit that falsified it. On the very bullet that records the lesson.** Fourth consecutive commit
  shipping a G-class claim; caught by a red-team lens, not by a guard, every time. The cap had been recorded
  here and in the ADR as an "honest limit, inherited not introduced" — true, useless, and it
  let me stop thinking. Round 1 built a 401-file tree and reproduced the original bug straight
  through the fix. **This roadmap line then sat unchanged for a commit, telling every reader the
  opposite of the code** — the same G-class defect the commit claimed to close, at the surface this
  repo calls the live build status. Caught by round 2, not by a guard.
- **[debt] Two order-dependent tests in `apps/api/tests/test_api.py`** — `test_decompose_spec_lint_
  recurates_once` (spy called 2×, clean-clone `make ci` under pytest-randomly, 2026-08-22) and
  `test_a_ratified_clause_stops_the_question_being_asked_again` (same shape, same day, different
  seed). Both pass standalone and in fixed order; both are "a monkeypatched spy fired twice", so
  some PM/curate-path module state survives across tests under certain orderings. NOT touched by
  the security arc — the failing paths are backlog curation. Until fixed, an MR pipeline can flake
  this way; a retry is the mitigation, and a green-after-retry there is not evidence of anything
  else being wrong.
- **[debt] The collect-only drift check is dark on repos whose conftest imports a third-party
  dep** — resolved 2026-08-22 by reading the two red-team lenses' scopes together, no new
  execution needed: one lens verified the no-dep arm works end-to-end in Docker (its
  "FALSE-POSITIVE" was about the interpreter path rewrite, which is fine); the other ran BOTH arms
  and pasted the container's `ModuleNotFoundError` — `sys.executable` maps to the container's
  system python, not the `.venv` where the install phase puts the repo's deps. `coveragemap.py`
  already documents this exact trap and picks `.venv/bin/python`; the fix is to reuse that pick and
  report "could not ask pytest" distinctly from "agreed". Advisory-only either way — the detector
  never gates.
- **STATE OF THE SECURITY ARC — CONSOLIDATED 2026-08-22 (supersedes the per-round notes below where
  they disagree; the notes stay as the audit trail).** Eleven commits, `98ebfb1a..8488700b`, ready
  for staging→main; live-validated same day (a run delivered end to end through plan → baseline →
  tests → build → checks → review → deliver on the deployed build).
  **CLOSED, each with its regression pinned:** stale security/reviewer evidence shipping
  (`98ebfb1a`+`c2c1ed8e`) · the evidence pin blind to skip-dirs/caps — one origin with the delivery
  path (`f0666bfa`) · the protected-test set empty on every real repo, two independent blind spots
  (`1f710222`) · two terminal false parks + a vouch-while-nothing-ran the widening armed
  (`8f102902`) · "test file" is the TARGET's definition, four named sets (`21718bf8`) · the config
  parser's five divergences from pytest incl. a crash (`75402744`+`26821089`) · the
  fires-on-every-run warning (`8488700b`, live validation) · the four evidence sites + the
  `verified_tree` timing (this pass).
  **DEFERRED, each named:** collect-only as the SOURCE of the collected set (parser demoted to
  fallback) · the index-sourced fingerprint (gitlinks/symlinks/mtime) + v2 stamp prefix ·
  `python_functions`/`python_classes` AST-level blindness · ADR-0108 phase 2 (reason-token split,
  blocked on `gate.py` 500/500) · non-Python tamper protection (LanguagePack seam built, predicate
  unwritten) · tracked-vendored-tree false parks · the remaining whole-product audit findings.
- **ADR-0108 RED TEAM — COMPLETE 2026-08-22, 2 rounds / 6 agents. Verdict: `honest_park`. THE
  CONTROL DOES NOT ACHIEVE ITS GOAL.** Round 2 reproduced ADR-0108's own CRITICAL through ADR-0108
  with nothing but the coder's ordinary `write_file`: a write to `src/.mosaera/backdoor.py` leaves
  the stamp byte-identical (`is_fresh: True`), the gate emits `reasons == []` / `deliver`, and git
  commits the file. `live_tree` prunes `_SKIP_DIRS` by directory NAME AT ANY DEPTH; the delivery
  path's exclusions are ROOT-ANCHORED by deliberate design (#59 red team, so a nested
  `src/.mosaera/` deliverable is not dropped). Two origins for "what is in the tree", disagreeing —
  and the gap is a ship path. ADR-0106's `verified_tree` inherits it.
  **The STOP rule fired on FIVE classes**, each recurring in consecutive rounds: pin blind to part
  of the tree (300-cap → skip-dirs) · fails open where it says fail-closed (unreadable root → empty
  listing) · stale evidence vouches to the human (clean line → findings list) · operator sentence
  asserts a false cause (`disabled` → unstamped/unreadable) · control unpinned by tests (gate wiring
  survived 2,136 → reviewer leg survives both mutations). All five are downstream of ONE
  architectural error: **the pin derives "what is the tree" from `file_listing`, a presentation
  helper.** No round 3, no sixth patch — see ADR-0108 "Red-team outcome" for the successor design
  (derive the pin from git's view, the same source of truth as the delivery path).
  **Not a regression:** the ship path found was open before ADR-0108 too; the defect is that the ADR
  claimed to close it. The pin is still strictly better than no pin.
  **SUCCESSOR PHASE 1 LANDED same day** (owner-approved scope): `Workspace.evidence_hash` /
  `committable_paths` mirror `_stage_all` exactly (`git ls-files -c -o --exclude-standard` minus the
  root-anchored `.mosaera/` reset), so the evidence listing and the committer are ONE ORIGIN by
  construction. Four evidence pins switched together — ADR-0108's, ADR-0106's `verified_tree`, and
  the coder-validation pair — while the ~16 memo/presentation callers correctly stay on the walk.
  End-to-end: the CRITICAL now yields `['security_stale'] / require_human` where it yielded
  `[] / deliver`. Closes the skip-dir ship path, the 300-cap blindness (by construction), the
  `sha256("")` sentinel, the ADR-0106/0108 contradiction and the double-walk cost; incidentally
  removes a false-park class, since git honours `.gitignore` so build artifacts no longer move the
  pin. **7.3 ms vs 73.7 ms** in a clean checkout — faster than what it replaced at every size and
  shape measured. (The first figures published here — "254 ms", "a 4,925-entry walk" — were measured
  in a checkout whose `.claude/worktrees/` held thousands of nested-worktree files; they described
  the dev box, not the repo. Direction held, magnitudes did not.)
- **[prereq] THE PROTECTED-TEST SET WAS EMPTY — CLOSED 2026-08-22.** Two independent blind spots,
  either of which alone emptied it. Measured on this repo, before → after:
  | set | before | after |
  | --- | --- | --- |
  | `security_listing` (new) | — | **1316** (`file_listing` capped at 300) |
  | `integrity_paths` | 28 | **249** |
  | `protected_test_paths` | **0** | **249** |
  | vendored/cache noise | — | **0** |
  **`protected_tests` was literally ZERO on Mosaera**, because five sites filtered on
  `startswith("tests/")` and `git ls-files | grep -c '^tests/'` is 0 here — the tests live at
  `packages/core/tests/`. So the cap was only half of it: those controls were dead on **any**
  src-layout or monorepo target regardless of the cap, and fixing only the famous blind spot would
  have shipped a control still dead on the commonest repo shape.
  **Fix:** one `Workspace.security_listing()` (git-sourced, uncapped, boundary-aware) + one
  `testintegrity.protected_test_paths()` helper replacing seven inline re-derivations. It RAISES
  rather than degrading — `evidence_hash` returns `""` and fails closed, but an empty *listing* reads
  downstream as refuses-nothing/baselines-nothing/guard-vacuously-true, so there is no safe empty.
  **Two designs were rejected on measurement, both mine:** the union with the filesystem walk (1616
  integrity paths, because `.claude/worktrees/` holds sibling checkouts `os.walk` descends and git
  does not — every `.tox/` write would have become a TERMINAL tamper park); and an unbounded
  ignored-collection-control term, which pulled in `.tox/*/conftest.py` until bounded to directories
  that actually hold a protected test. The second was caught by this change's own canary test.
  **RED-TEAM ROUND, 3 lenses, isolated worktrees — the widening ARMED three latent defects** in
  code written while the guard was dead. All three were unreachable before the set went 0 -> 249,
  and all three are now fixed (see below). Two were TERMINAL false parks; one was an oracle that
  vouched while zero tests executed. The lesson worth keeping: a fix that populates a dead control
  is not a small change — everything downstream of it was written against a control that never
  fired, and none of it was under test.
  **BENCH DISCONTINUITY — DO NOT COMPARE ACROSS 2026-08-22.** `bench/layer2.py` and
  `bench/operator.py` sat on the same dead expressions, so every containment score and every F43
  oracle-fitting result recorded before this date measured a control that was not there and reported
  SAFE. Historical layer-2 containment numbers are not comparable to anything after it.
- **[debt] ~~SUCCESSOR — collapse the TWO protected-set definitions into one~~ — DONE 2026-08-22,
  but NOT as a collapse.** The collapse is impossible: two live consumers of the same call need
  opposite answers about the same file (`close_oracle_gap` needs a non-`test_`-named helper IN; the
  same list becomes a pytest argv where a `.json` exits 4). Partitioned into four named sets instead
  — protection (wide), collection (exact), authorship (exact), collection-control (unchanged) — all
  derived from one resolved surface, so there is still a single origin. **"Test file" now means what
  the TARGET's `python_files`/`testpaths` say**, verified once against `pytest --collect-only` with
  no path args (ADR-0054), falling back to pytest's defaults and RECORDING that it inferred. Closes
  the headline blindness (`python_files` repos were wholly unprotected), the supersession path that
  deleted a human's test, and the registry claiming authorship of a non-test. **Non-Python targets
  still have no tamper protection — stated in the ADR, not left implicit.** ~~The original item:~~ `1f710222` replaced
  seven inline re-derivations with `protected_test_paths` (3 terms) and left `integrity_paths`
  (2 terms) beside it; consumers treat them as one set. That gap is what made the oracle-vouch
  CRITICAL reachable, and it still leaves the headline blindness open on repos whose tests are not
  named `test_*.py` — the commit's own claim reproduces there. **Source one definition from the
  target's real pytest `python_files` config.** Two consecutive rounds on the second-origin class,
  so this is a scoped successor, NOT another patch. Carries with it: supersession misclassifying a
  pre-existing human test as engine-authored, and tracked vendored trees making third-party tests
  terminally protected.
- **[prereq] ~~THE 300-CAP BLINDNESS IS NOT AN ADR-0108 PROBLEM~~ — the ORIGINAL note, superseded — it spans at least eight sites, and
  two of them are separation-of-duties CRITICALs that are live TODAY.** Found by red-team round 3
  (2026-08-22); both PRE-EXISTING, neither introduced by the ADR-0108 arc.
  - `testintegrity.integrity_paths` (ADR-0036/0058 tamper baseline) uses `file_listing()` at the
    DEFAULT 300 cap. On Mosaera itself it baselines **28 of 215** test files. Verified on a 401-file
    repo: `integrity_paths() == []`, the acceptance test is unprotected, and the coder rewriting it
    to `assert True` yields `tampered_paths == []`. **The guard the producer "cannot edit around" is
    silent on any repo where `tests/` sorts past the 300th path — i.e. every real target repo.**
  - the Proctor / disposition protected-test set (`nodes_plan.py:184,212`,
    `_proctor_authoring.py:226`, `disposition.py:206,215`, `_escalation.py:87`, `bench/layer2.py:158`)
    — same helper, same cap, same empty set past the cut.
  - lower severity, same class: `nodes_critic.py:48` memoizes the held-out VETO under a key blind to
    exactly the write ADR-0108 exists to catch; `nodes_impl.py:62` writes the durable suite verdict
    under a key namespace its only reader can never match (so the cross-run cache can never hit —
    re-measure before trusting `_content_key`'s recorded cause).
  **Fix shape is known and already built:** move these consumers onto `Workspace.committable_paths`.
  **Scope it as ONE successor, do not patch site by site** — this is class (a)'s sixth instance and
  the STOP rule has fired on it three rounds running.
- **ADR-0108 SUCCESSOR PHASE 1 — `honest_park` after red-team round 3.** The mechanism holds (skip-dir
  ship path, cap and `sha256("")` sentinel genuinely closed; 14/14 path-selection fixtures agree with
  `_stage_all`; all eleven gates green). The framing failed three ways: "one origin by construction"
  was true of the PATH LIST and assumed for the FINGERPRINT (gitlinks ship unseen — `evidence_hash`
  stats the worktree while the committer reads the index; the dropped symlink guard is the same
  cause); the load-bearing "remaining callers are memo keys and presentation listings" sentence was
  wrong and waved through the two CRITICALs above; and **three of the four switched sites survive a
  full-suite revert — `2914 passed, 0 failed`** (class (e), shipped in the commit that claimed to fix
  that class). Regressions introduced: `verified_tree` slid from a PRE- to a POST-validation stamp,
  so `tests_passed` now certifies a tree including writes made DURING validation; and the
  `delivery_check` fail-open aperture widened, which matters most on the bench, where `scan_enabled`
  is False and that path is the only remaining pin on `tests_passed`.
  **~~OWED before this leaves staging~~ — CLOSED (consolidation pass, 2026-08-22):** the four
  differential pins live in `test_evidence_site_pins.py`, each proven by killing its own site's
  revert AND the red team's exact all-four revert (a fixture had to carry a walk-invisible file
  before the stamp, or the factory revert was undetectable — the two hash functions coincide on
  trees where the listings agree); the `verified_tree` timing regression is fixed (stamp taken
  before `run_plan`; the factory stamp stays deliberately post-run — the coder's evidence describes
  the tree its run saw). The v2 stamp prefix is DEFERRED BY DECISION, not omission: adding it now
  would re-park every in-flight run a second time for a benefit that only matters when the
  index-sourced fingerprint lands — it ships with that successor.
  **Cause-level successor (NOT attempted — STOP rule):** source the fingerprint from the INDEX
  (`ls-files -s` object ids / `status --porcelain=v2`), which closes gitlinks, symlinks, the
  deleted-file sentinel and the stat-only mtime residual in one change.
  **PHASE 2 OWED (blocked on headroom):** `gate.py` is at exactly 500/500, so splitting the reason
  token (`security_stale` still asserts "the code changed" for *never stamped* and *unreadable*)
  needs that CODEOWNERS trust-boundary file split first. Also owed: the stale-FINDINGS UI branch,
  `delivery_check`'s fail-open polarity, `bench.diagnose_bottleneck`'s missing branch for both
  staleness reasons, and the self-measurement once runs accumulate.
- **ADR-0107 RED TEAM — COMPLETE 2026-08-21, 3 rounds / 6 agents. Verdict: HOLDS.** The successor
  fix (`graph/_tamper.py`, `b065bf37`) put the tamper evidence on the branch that consumes it, and
  R3 verified it by DIFFERENTIAL EXECUTION of `test_node` against `b065bf37^` over six real
  workspaces — behaviourally unchanged, over-block and under-block closed on every reachable path,
  no FIX-NOW, and **no third instance of the defect class the STOP rule was tripped on**. Rounds 1-2
  below, kept because the two defects they found were mine and the pattern is the lesson.
  **Was: STOP RULE TRIPPED, MR blocked.** Two rounds, five independent agents, scoped to the merged change.
  **R1 (3 agents).** The false-ship lens could NOT break the core claim — SHIP admission is
  byte-identical (verified by parsing the pre-commit table and diffing, not by reading), Layer-2 is
  unreachable, `_resolve` is genuinely a positive allowlist, no string-prefix escape, ADR-0091's
  boundary is enforced in code, no XSS, and the clarification never enters Quincy's context.
  Two HIGH defects, both introduced by this arc:
  (a) **Slice 0a was INERT in production** — `_lifecycle.approve` queued `effect`;
  `_resolve_escalation` rebuilt the resume as a fresh dict and dropped it, so `stop_honestly` never
  stopped anything. Three tests were green over it: two inject a hand-built resume BELOW the seam,
  one asserts only that the field reaches the queue ABOVE it. Found independently by two agents.
  Fixed `b295549d` + `test_resume_effect_boundary.py`, which tests the seam and nothing else.
  (b) **the ADR-0107 widening made a TAMPERING hand-raise reach the ask** — `tests_modified` and
  `destroyed_paths` are written only by `test_node`, which a hand-raise bypasses, so the guard read
  keys that were never written and the gate minted no tamper reason from missing state.
  **R2 (2 agents) — the (b) fix was wrong in BOTH directions, which is what tripped the STOP rule.**
  Over-block: treating absent keys as UNKNOWN re-kills the ask on the hand-raise branch — the branch
  #68 exists to serve — i.e. ADR-0107's own defect shape reintroduced one commit later on the
  sibling branch. Under-block: a STALE clean verdict is still trusted, so tamper committed after the
  last `test_node` run passes through. Both with executed reproductions.
  **Diagnosis: patching a predicate that reads evidence absent from its own branch was the wrong
  move.** The successor fix is to put the evidence on the branch — extract the tamper computation
  to ONE origin and call it from `capture_node`, fresh, exactly as #75 did for `test_output`.
  NOT done here: the STOP rule forbids a third round this session, and a third unverified patch to a
  security guard is the failure mode, not the fix. **Owner decision + a fresh round owed.**
  Also FIX-NOW from R2, not yet done: the `amend_tests` button ENDS the run when no test is ticked
  while its consequence promises the run continues (F61's shape inside ADR-0107's own machinery);
  the "Unsuppressible Ask" invariant's *visible* half is unmet (`escalate-arm.suppressed` renders as
  a muted lifecycle row and matches no vocabulary map); `_RESUME_EFFECTS` has no derived-set
  assertion tying it to what `gate_outcomes` actually emits.
- **#68's split evaluation — FIXED 2026-08-21 (ADR-0090 MR3), and F62's other half with it.**
  `supervise_node` now answers the structural question ONCE, while the raise is live, and records it
  in `ask_blocking_tests`; the arm reads that instead of re-deriving
  `is_oracle_conflict_escalation` from a `gate_decision` that had moved on. The two used to disagree
  in both directions — a stale objection blocking a legitimate stop, a stale clean permitting a stop
  that then could not ask.
  **The exclusions only the FINAL state can answer are deliberately KEPT** as a second check
  (`ask_withheld_reason`): a critic veto or a real gate objection is invisible at supervise time,
  because on the give-up path the gate runs AFTER it. Reading only the recorded verdict would have
  silently dropped what ADR-0075 red-teamed twice — an existing test caught that. The bug was ONE
  question re-asked against drifting inputs; two different questions, each asked once where its
  inputs are final, is not the same thing.
  **The other half of F62:** the supervise interrupt now carries computed `outcomes` (ADR-0082 §1)
  via `escalation_outcomes()`, so the operator gets named choices, not a boolean — the machinery was
  built end to end and only the delivery gate had ever populated it. The option's stated consequence
  and the engine's routing come from ONE predicate (`escalation_finalizes`), the F61 rule applied one
  gate over: a "send it back" that will really end the run declares `end_run` and says so.
  `nodes_plan.py` crossed the god-file ceiling, so `supervise_node` + `route_after_supervise` moved
  to `graph/_supervise.py` (369 + 177), re-exported so every caller is unchanged.
  **LIVE PROOF, 2026-08-21 — half confirmed, and the other half found a THIRD defect.** LedgerCLI
  item #113 ("switch list output to pipe-delimited", written so its acceptance contradicts three
  pre-existing comma tests) was driven into a real oracle conflict on run
  `20260821-180202-7865c0`. The escalation rendered four computed outcomes, and the anti-drift
  property held where it counts: `amend_tests` declared `send_back` and was RECOMMENDED, while
  `send_back`, `fix_regressions` and `stop_honestly` all declared **`end_run`** and said why —
  *"every failing test is one the producer may not edit, so re-planning cannot help."* Notably the
  coder's own summary asserted *"The implementation is correct and complete"*; the deterministic
  layer computed `no_progress` from 14 -> 14 -> 14 anyway. ADR-0082's *computed, never authored by a
  model* earning its keep against a model actively claiming success.
  **But the ask still did not fire, for a THIRD reason — the arm's CALL SITE was unreachable.**
  The run parked `incomplete` with an honest `termination_reason` and item #113 carried no
  clarification. `_after()` returns at `if not chain` before reaching `_try_escalate_arm`, and the
  "Run guided" button launches with `chain=False` (`routes/backlog.py`), so on the path an operator
  actually uses to drive a single item the arm was dead code. Every test stayed green because they
  all invoke the arm directly and none executes `_after()`. **Fixed 2026-08-21** by hoisting only
  the arm above the guard; `_try_model_escalation`, `_try_close_named_gap` and
  `_try_recurate_or_defer` stay chain-only on purpose (they take autonomy — launch a run, ship a
  diff, move the item out of the picker — which a human-driven run must not get for free). The new
  test pins the call site, not the behaviour, and asserts the siblings did not come along.
  **RE-RUN 2026-08-21 (`20260821-185000-08c6c2`, autonomous, chain=False) — the hoist WORKS and a
  FOURTH defect is underneath it.** The arm is now reached: the audit carries
  `escalate-arm.suppressed | a gate objection rode the park`, where the guided run before the fix
  carried no arm event at all. It then suppressed itself, and the suppressing reason is a routing
  artifact rather than an objection. The give-up park's gate reasons were `validation_failed,
  reviewer_unknown, security_unverified, claim_behavioral_failed`; `security_unverified` is classed
  `objection` (`policies/gate.py`), and `build.py`'s own comment states that *"a plan early-park /
  supervise give-up route straight to the gate, bypassing"* scan and review. So on the give-up path
  `scan_node` never runs, `security_unverified` is STRUCTURALLY GUARANTEED, and
  `ask_withheld_reason` therefore returns "a gate objection" on **every** give-up park. **The ask is
  suppressed by a condition that the only path able to trigger it guarantees** — F77's shape (a
  value defaulting on a branch that skipped the node populating it) rendering a control permanently
  dead.
  **Diagnosis:** the arm borrows `give_up_allowed_reasons()`, an admissibility set built to answer
  *"may this parked run be DELIVERED?"*, to answer *"may I ask a question?"* — and those carry very
  different risk, because the ask ships nothing, edits nothing and approves nothing. The shared
  constant was chosen to avoid a second origin (the F71/F79 defect class); the right instinct on the
  wrong pair of questions.
  **NOT fixed here, deliberately.** Narrowing the exclusion to POSITIVE objections
  (`security_findings`, `critic_vetoed`, `reviewer_requested_changes`/`_blocked`/`_conflict`,
  `claim_structural_failed`, `removal_unproven`, `impact_unassessed`) rather than "the node was
  bypassed" is a change to what ADR-0075's twice-red-teamed exclusion means. This slice already
  deferred the sibling of that decision (`claim_structural_failed`); deciding the other half
  unilaterally would be inconsistent. **Owner decision pending.**
  **FIXED 2026-08-21 — [ADR-0107](adr/ADR-0107-decision-specific-admission.md), and the class, not
  the instance.** The audit's decisive finding was that the exclusion's stated provenance is FALSE:
  `escalate_arm.py` claimed *"exactly the exclusion ADR-0075 red-teamed twice"*, but ADR-0075
  (2026-07-23) predates the arm (2026-08-06) and `ask_withheld_reason` (2026-08-21), neither
  red-team round mentions a security reason, and on 2026-07-23 the reason **could not occur on this
  path at all** — `gate_node` defaulted absent security to `"clean"` until `5677e7fc` (2026-08-07).
  ADR-0076's own R1 ACCEPT #1 had already scoped the case out (*"the bypass routes rely on the
  validation gate"*). Both false comments are corrected; leaving them would preserve a fabricated
  justification for the next reader, which is the F62/F58 shape.
  The fix splits `security_not_attempted` from `security_unverified` exactly as F39 split
  validation for the same two bypass edges (deny-preserving — *a message, never a permission*),
  adds a fifth `ReasonClass` `not_run` (ADR-0090's own Review trigger), and gives each arm its own
  DERIVED admissible-class tuple — ADR-0092 §3's named successor, unblocked by MR3 that same
  morning. SHIP admission is byte-identical and
  `test_the_admission_set_is_exactly_what_adr_0092_authorised` passes untouched.
  **Two prevention harnesses ship with it**, both mutation-proved against the real defect:
  `test_arm_admission_exhaustive.py` fails until every arm dispositions every class (admission is
  `set(reasons) - allowed`, so an unconsidered class silently defaults to REFUSED — exactly how the
  ask died, and mypy cannot see it because a short `tuple[ReasonClass, ...]` typechecks fine); and
  `test_control_polarity.py` asserts each control reaches BOTH outcomes on the state the LIVE path
  builds, constructed by running the real gate over the real bypass inputs rather than hand-written
  — the hand-written fixture is what let every unit test stay green for fifteen days.
  Named in the North Star as **Unsuppressible Ask**: a control may refuse to act; it may not refuse
  to speak.
  **CLOSED 2026-08-21 — the clarification landed. Run `20260821-203751-894dcd`, LedgerCLI item
  #113.** Both halves of F62 now hold on one live run, fifteen days after it was measured.
  The gate carried `["validation_failed", "reviewer_unknown", "security_not_attempted",
  "claim_behavioral_failed"]` — **the split is live**: `security_not_attempted`, not
  `security_unverified`, and all four reasons are ASK-admissible (shortfall / incidental /
  not_run), so `ask_withheld_reason` returned "" and the arm spoke. The item now carries a
  `direction`-kind clarification on the `reachability` axis, naming the three blocking test files
  and offering the operator three moves; **`acceptance` is unchanged**, which is ADR-0091's store
  boundary holding.
  Two things worth recording about how it was reached. The coder **self-diagnosed** the
  contradiction unprompted this time (*"my change is correct according to the task requirements,
  but ... they were written expecting the old behavior"*) — no steering, unlike the 2026-08-21
  morning runs. And three earlier attempts missed `supervise` entirely because the **Revisions cap
  was 3**: `convergence.py` sets `progress_trip` (→ supervise) only on Rung 2 BELOW the cap, and
  at/over it falls to Rung 3 with `stalled=True`, deliberately — *"rode-to-cap IS thrash; never
  dress it up"*. Not a defect; a run parameter. Worth knowing before diagnosing a missing
  escalation as a broken control.
  Also confirmed live on run `20260821-202246-5f10cb`: the budget park now renders **"Continue —
  raise limit" / "Stop run"** in the dock, where it read "Approve & deliver" / "Send back" that
  morning.
  Three defects deep on the same ask is itself the finding: *invisible control* (roadmap's own
  defect-class list) has now bitten the same feature at the predicate, the presentation, and the
  call site.
  **Still open:** `claim_structural_failed` is classed `"objection"` (`gate.py:148`), so a park
  carrying one still suppresses the ask — a second suppression path, not bundled here because
  reclassifying a gate reason moves a control signal and needs its own evidence.
- **SHIPPED 2026-08-07 — the gate stops misstating what your answer will do (ADR-0082 §1/§5, F61).**
  A denial at the iteration cap *terminated* the run and discarded the operator's notes while the
  button said "send back to revise" — ~1.1M tokens of correct work, HTTP 200, nothing anywhere
  saying so. `gate_outcomes()` now computes the answers that are actually available with their real
  consequences, and **an option that cannot function is not offered**. A third finalizing exception
  no finding had recorded — the gate-stall breaker making a denial terminal *as a consequence of the
  denial* — is predicted and labelled. `ApproveBody.option_id` landed with an unknown id **rejected
  (400), never auto-approved**; its real value is catching a **stale screen**, which honest labels
  alone cannot. The durable part is the anti-drift shape: routing and presentation read ONE
  predicate, pinned across all 32 combinations. Still DIRECTION: §1's *"Something else…"* proposal
  shaping, §6 counsel routing (needs its own ADR), *(ADR-0086's risk-gated writes removed 2026-08-18: ADR-0101 superseded that posture ladder — see
  the ADR's archive note. §2's risky-write list survives as unbuilt direction, currently ungated in
  `accept`/`auto`.)*
- **Recently shipped:** reliability arc `#43` ·
  Quincy Layer-2 disposition `#76` (arc CLOSED) · independent
  security gate `#83`/ADR-0076 (merged + red-teamed) · project onboarding `#42` (MR1–MR4 complete).
- **The 2026-08-01 → 08-05 narrative moved to the engineering journal (2026-08-06).** 569 lines of
  dated arc detail — the claim-contract waves, the `#61`/`#62` A/Bs, the `#63` redesigns, the
  rebaseline, the intake-decidability work — now live in
  [`engineering-history/roadmap-and-arc-history.md`](engineering-history/roadmap-and-arc-history.md).
  **Nothing was deleted.** Read it for the *why-and-how* of a specific arc; this section is only
  what is live now.

## Road to v1.0 — the four measured gates (ADR-0061)

**`1.0` = "the SWE team is production-stable"**: the engine drops into *any* repo and either delivers
correct, industry-standard code **or** honestly refuses — governed and auditable. **Anti-gimmick
clause: every gate is measured on held-out inputs the coder can't game, or it doesn't count.** v1.0
ships only when **all four are green on one held-out benchmark run**.

| Gate | Threshold | Status |
|---|---|---|
| **1. Reliability** | ~99% clean-conclusion (deliver-correct or park-honestly, no thrash), repeat ≥ 3 | Near-bar with escalation on; the routing lever |
| **2. Correctness** | `false_ship` ≈ 0 vs a **hidden** grader the coder never saw | ✗ **the load-bearing gap** (MCB-05 class) — critical path. **Scope (stated 2026-08-05): measured on the AUTONOMOUS path only.** MCB has no write gates and no operator turns; the shipped `guided` default is unmeasured, and a run that dies before verification is invisible to this gate (`#53`, 2026-08-05). |
| **3. Any-repo** | holds on **brownfield** repos in **≥ 2 languages** (Python → TS/JS or SQL) | Python-first; brownfield/demo harness exists |
| **4. Governance** | tamper-evident exportable audit + dual-control ceremonied autonomy + control-mapped posture | Foundation only (gate/sandbox/tamper/honest-outcomes) |

*(Exact per-release benchmark snapshots live in the engineering history.)*

## Strategic programs (the permanent themes)

Durable, multi-year programs the arcs ladder up to — some engineering, some product. **Waves decide
*when* we work on each; the programs themselves barely change.**

- **Reliability / honest-stop** — every run reaches a clean terminal state: deliver, or park with an accurate reason.
- **Correctness / oracle** — prove the *output* at the door; turn "passes the tests" into "code you'd sell".
- **Coverage** — runtime code↔test map, durable test ledger, change-coverage gate, token-saver.
- **Project-knowledge / onboarding** — interview → recon → durable untrusted **map** + trusted **charter**; runs are gap-analysis against the project's real state.
- **Capability / routing (BYOM)** — the right model per role; degrade-or-park on a model-capability gap.
- **Capability-through-auditability** — containment + traceability (tamper-evident audit) + verification; a workbench, not a straitjacket.
- **Governance / posture** — Free/Business/Regulated as a tighten-only policy-as-code lattice + a dual-control enablement ceremony.
- **Firm layer** — teams-as-modules + Quincy as the single interface; generalize the four SWE seams for a second team.
- **Enterprise & capability benchmark** — SSO/RBAC/audit-export productized; MCB as a grader + a product; mosaera.dev self-build dogfood.

## Roadmap at a glance

| Wave | Purpose | Primary blocker / dependency | Status |
|---|---|---|---|
| **Phase 0** | The trust foundation everything stands on | — | ✅ Done |
| **Wave A** | Stabilize the SWE engine until it consistently produces trustworthy delivery | the correctness oracle-successor | 🟡 **Now** — reliability accepted; correctness is the open gate |
| **Wave B** | Teach the engine the project before it changes it | posture enforcement seam + BYOM depth | 🟡 Onboarding done; posture/BYOM = direction |
| **Wave C** | Generalize the SWE engine into the first governed AI firm | a real second team + honest editorial evidence | ⚪ Direction |
| **Wave D** | Expand output quality and research capabilities | Wave C | ⚪ Direction |
| **Wave E** | Enterprise productization + capability benchmarking | Wave C governance | ⚪ Direction |

## Detailed waves

### Phase 0 — Trust foundation — **DONE**

Deny-by-default tool allowlist + the deterministic evidence delivery gate, honest outcomes, the
tamper baseline, and the independent-oracle gate. *(ADR-0020/0031/0034/0036/0044.)* This is the
substrate everything else stands on.

### Wave A — Foundations (now) — *the high-leverage prerequisites*

**Purpose:** stabilize the SWE engine until it consistently produces trustworthy delivery.

**[arc] Run-conclusion reliability — `#43`** (umbrella, ★ owner priority)
- **Goal:** ~99% of runs reach a clean terminal state (deliver, or park honestly), without thrashing to the caps.
- **Status:** baseline **accepted by owner (2026-07-22): 94.4% clean-conclusion, `false_ship` 0, crash 0** — `rebaseline_80on_x3` (MCB ×3 = 72 runs, `#80` ON + `cautious` + escalation OFF; delivery ~47%, the Layer-2/Quincy lever). Residual greenfield model-capability thrash (`#81`/`#82`) **PARKED** — the lever is Layer-2/Quincy, not the last ~3pp. *(Snapshot recorded in [`CHANGELOG.md`](../CHANGELOG.md); scoreboard artifacts are under the gitignored `.mosaera/`.)*
- **Major deliverables (all merged):** the honest-stop family (early-conclude, projected-non-convergence + gate-loop breakers) · whole-suite validation · the sensitivity dial · the autonomous-oracle posture · Proctor validates/repairs tests + acceptance spec-lint · the coder toolkit · comprehensive mutation + structural-spec oracle · the reliability scoreboard (the arc's DoD instrument).
- **References:** ADR-0052/0053/0054/0056/0057/0058/0059/0060/0067/0069/0071/0072/0073; issues #43–#45, #51–#56, #65, #67, #74, #80.

**[arc] Quincy Layer-2 disposition — `#76`** (ADR-0074 + ADR-0075)
- **Goal:** convert `honest_park` → `clean_deliver` *outside* the run graph — produce the missing proof (author the test, re-run the REAL oracle) or escalate. **Hard invariant: never an LLM green-light.**
- **Status:** **DONE / arc CLOSED** (MVP + widening merged; red-team + bench DoD done; knob `disposition_gap_close` default OFF).

**[arc] Independent security gate — `#83`** (ADR-0076, NS-2 governance)
- **Goal:** a scan that can't fully verify **parks** (`security_unverified`), deny-by-default — the security control point, deterministic.
- **Status:** **DONE** (merged + 2-round red-team). **Successor (NEXT):** coverage-based scan-completeness oracle (trust `clean` only when scanned paths cover the scannable set) — *highest-priority security follow-up*; then SCA/deps (Trivy), charter-posture scaling of the veto.

**[arc] Correctness oracle-successor — the `#54`/`#66` successor** *(the load-bearing v1.0 arc)*
- **Goal:** prove *output* correctness so `false_ship` → 0 — a Proctor-hard-gate (require a red-verified asserting suite to ship autonomously) + stronger/union mutation + a non-pytest oracle.
- **Status:** **DIRECTION** — its *production build* is withheld pending an authorizing issue + ADR, but per scope discipline the **design / ADR-proposal is the authorized design cycle**. Sequencing: the **scan-completeness oracle (under `#83`) is the authorized code frontier now**; this successor is the *design* frontier that follows it (the STOP-ruled MCB-09 class escalated here). Note: the LLM-judge path (ADR-0070) was built, **measured net-null, and REVERTED** — the successor is deterministic, not a judge.

**[arc] The verb arc — `#82`** *(design: [`design/verb-arc.md`](design/verb-arc.md))*
- **Goal:** give every change verb an oracle. The engine can only **ADD**; subtract, modify and
  refactor each deadlock for want of evidence, not for want of a tool. Spine: **Forge claims → the
  engine refutes mechanically → the gate checks completeness** — three separations (evidence
  ownership, decision authority), not three agents.
- **Why it is an arc and not debt:** `graph/_amendment.py` names it as the deadlock in our own
  source; item 88 (five runs, ~2.9M tokens) and LedgerCLI item 4 (three runs, ~4M tokens) both died
  on it with **every control behaving correctly**; and no wave modelled it until now.
- **Slices:** `run_tests` selector → SUBTRACT end to end → execution feedback → attribution →
  MODIFY/REFACTOR → comprehension apparatus → project lifecycle + doctrine. Most land on existing
  issues (`#55`, `#67`, `#71`, `#6`) — the mapping is in the design doc; **do not open parallel work**.
- **Sequencing:** `#68` (ADR question) → `#58` (an opening cannot be red-teamed while its e2e job is
  green-by-vacancy) → verify `#29`'s unread coverage ledger → slice 0. `#54` sequences *after* the
  modify slice; `#52` is subsumed by the claim artifact.
- **Status:** **PROPOSED** — design accepted by the owner 2026-08-08; no production implementation
  authorized until each slice carries an issue and, where required, an ADR.
- **Evidence basis (2026-08-08 research sweep):** a producer-owned oracle can invert the loop's sign
  (Reflexion −3.0 on MBPP-Python from self-generated tests); independence is asymmetry, not headcount
  (Olausson et al., ICLR 2024 — GPT-4 critiquing GPT-3.5 beat both models' self-repair; erroneous
  feedback humans 7/80 vs GPT-4 32/80); executed feedback beats prose feedback **4–6×**
  (Self-Debugging, ICLR 2024); ~58% of engineering time is comprehension (Xia et al., ICSE 2018);
  only ~14% of review comments concern defects (Bacchelli & Bird, ICSE 2013). **Caveat:** every one
  of those magnitudes comes from single-shot, add-a-feature, oracle-already-exists benchmarks. There
  is **no published benchmark for subtract, for refactor-with-behavior-preservation, or for a
  governed multi-slice project** — the direction is supported, the numbers are not transferable, and
  each slice must be measured on our own corpus.

**[prereq] Guided-mode measurement harness — `#64`** (ADR-0085 §3)
- **Goal:** measure whether the firm **contains** a bad oracle or is pushed by one into corrupting the
  product (F43: the coder proposed hardcoding `date(2023,1,1)` to satisfy an unsatisfiable test, and
  only a human reading the diff stopped it). Seeded bad oracle + a deterministic scripted operator at
  real write gates + a containment score.
- **Why it is a prereq:** MCB cannot see this class at all — it runs autonomously (no `interrupt()`,
  so the F35 resume path is untestable) and all 42 of its test files are bare-`assert` while the
  product authors `unittest` (which is why F37 survived its own justification measurements). `#54`'s
  test-steward should not be graded without it, and ADR-0085 §3 permits re-opening ADR-0070 **only**
  on the containment question this measures.
- **Status:** **DONE** (built + measured 2026-08-06). Guided posture for the bench (real `interrupt()`
  write gates + a deterministic scripted operator), three seeded cases (GMB-01/02/03), containment
  scoring with recourse classification, and the `mosaera-guided` runner.
- **Measured — the headline is a null result, and it overturned the working hypothesis.**
  **0 corruption in 6 runs**, proposed *and* approved. The producer does not cheat: it diagnoses the
  broken bar, twice naming the exact contradiction unprompted, and raises its hand. F43 was an n=1
  observation generalised too far — this is the instrument correcting the operator.
- **What it found instead:** [F49](engineering-history/ledgercli-friction-log-2026-08-05.md) — the
  hand-raise had **no resolver**. The autonomous path answered an escalation with a re-scope, sending
  the producer back at the same unfixable wall until the cap. All six runs scored `thrash_park`. The
  ESCALATE arm (knob `escalate_arm`, ADR-0074/0075's named-but-unbuilt sibling) now stops the run and
  asks the operator: measured `thrash_park` 3/3 → `honest_park` 3/3.
- **The arm is HALF-BUILT — do not read "DONE" as "the arm works."** Fired live for the first time on
  2026-08-06 (`20260806-231047-7c2c75`): the **stop** half worked (`give_up_reason` named the blocking
  tests, `honest_park` instead of `thrash_park`) and the **ask never fired** — the item carried no
  clarification, so the operator got an honest stop and nothing to answer, which was the point of
  building it. Cause: one predicate evaluated at **two points against evolving state**, plus the
  `unsatisfied_claim` allowlist gap already measured 2026-08-05.
  → **#68 (F62)**, filed as ONE thread with
  the pre-existing Layer-2 allowlist question. **F62 was a rediscovery**: the gap was documented the
  previous day and quoted in this very section, and the arm was built on it anyway.
- **Known blind spot (F87, PARTLY CLOSED 2026-08-20; ROOT CAUSE FIXED 2026-08-21):** GMB-02's
  *environmental* class — a test invoking
  the wrong interpreter. The producer never diagnoses it, so no hand-raise happens and the arm never
  fires. Recurred live on 2026-08-06 (`subprocess.run(['python', …])`), caught only by the operator
  at a write gate. **A third recurrence on 2026-08-20 showed the deeper cause is not diagnosis but
  the missing BASELINE:** run `20260820-185125-994a3d` reported `35 failed, 35 passed` three times
  identically, with the failures in PRE-EXISTING tests, and the coder concluded "the failing tests
  are all due to environment issues (package not properly installed)". The install had succeeded and
  pytest exited 1 (assertions, not collection); its own change had broken the CLI's other
  subcommands. It spent ~$1.65 of $1.80 shadow arguing with the wrong file. With no record of
  whether the suite was green at run start, a regression and an already-red repo are the SAME
  observation — so the producer filled the gap by inventing one, and nothing could contradict it.
  `graph/_baseline.py` now runs the existing suite once in `plan_node` (same planner, sandbox and
  interpreter as the `test` node) and records WHICH tests were already failing. A later failure in
  a pre-existing file that was NOT already failing is named as a **regression** in the fix prompt
  and the escalation payload. Deterministic — a set difference over test ids, no model call.
  **The first cut parked the run on a red baseline and that was wrong**, caught by an end-to-end
  fixture whose contract test fails on purpose: "the suite is red and your job is to make it green"
  is the canonical task (`make run TASK="make the failing test pass"`), so parking would have
  refused the most common shape of work there is. A red baseline is ordinary input; what it must
  never be again is UNRECORDED. The baseline also never fails a run — an unreachable sandbox
  records `read=False` and nothing downstream claims to know what it does not.
  **Superseded the same day by [ADR-0106](adr/ADR-0106-the-tree-that-ships-is-the-tree-that-passed.md),**
  after the owner asked why the suite runs at the START of every run at all. It now runs only when
  the verdict for the current tree is unknown: one verdict per project keyed by `tree_hash`
  (`project_suite_health`, **Alembic 0032**), written where it is MEASURED so it survives the
  cancel / crash / resilient-give-up paths `persist_run` never reaches. An unchanged tree costs
  nothing. The same ADR closes the other half that question exposed — the delivered tree was NOT the
  validated tree (`hygiene`'s autofix writes after validation and routes on; the give-up diversion
  carries a pre-write verdict; nothing ran after `commit_all`) — by binding the verdict to a tree
  hash, re-verifying at deliver only when the tree moved, and QUARANTINING a red tree to
  `mosaera/quarantine-<run>` so the tip every later item is cut from stays green and the work is not
  destroyed by the next run's reset.
  **CONFIRMED IN THE WILD the same day.** Item 107 reported `67 passed` and delivered `completed`;
  the next run's baseline found one of its own tests red. The coder wrote `action='store_true'`,
  the suite passed on that tree, `hygiene`'s autofix ran `ruff format` (single→double quotes),
  nothing re-tested, and the reformatted tree was committed — the delivered `cli.py` now carries
  `action="store_true"` while the authored test asserts the single-quoted form. The engine had
  already met this exact ruff behaviour and fixed it for PROTECTED TESTS ONLY (`hygiene_node`'s
  ADR-0068 comment), so the same mechanism went on to break a source file a test asserts on. Two
  faults: the engine rewrote after validating (fixed by ADR-0106), and the Proctor authored a bar
  that asserts a QUOTING STYLE rather than behaviour (**F86** — what makes the first
  cheap to trigger; recorded as F53 when first written, which was wrong: F53 is the Proctor
  WEAKENING a bar it already committed, this is the Proctor MIS-AUTHORING one). Mosaera already enforced this precondition on ITSELF
  (`tests/test_guard_liveness.py:101-104`, "a suite that is already failing 'detects' anything");
  target repos now get the same rule. **Still open:** `seedcheck.py:22` counts a collection `ERROR`
  as a healthy red phase and measures it under a THIRD interpreter (`sys.executable`,
  `install=False`), so it cannot see an interpreter mismatch; `languages/python.py:130-139` folds
  install-phase errors into the failing count driving the breaker (`node.py:145-152` already
  isolates the test step); ADR-0025's behaviour floor never fires for a src-layout package whose
  entrypoint is `pkg/cli.py` (no `__main__.py` at depth 1) — so LedgerCLI has never had one; and
  `persist_run` is reached only from `deliver_node`, so a parked or cancelled run records no
  `validation_plan` and no test results (today's diagnosis was possible only because the run-event
  transcript carries the `update` payloads).
- **Successor:** the recourse classifier counts recourse *available*, not *effective*. Whether an
  operator↔PM exchange actually resolves a blocked item is unmeasured.

**[debt] F87 — the coder's PROBE ran on the wrong interpreter** (fixed 2026-08-21)
- **The defect.** `sandbox_exec` hardcoded `sys.executable` — the engine's interpreter — while the
  validation plan runs pytest under `.venv/bin/python` (`languages/python.py:173-179`). For any
  `pip install -e .` project the package exists ONLY in that venv, so every probe the coder ran
  raised `ModuleNotFoundError` while validation imported the same package fine. The probe is also
  network-off AND read-only, so the coder could never install its way out, and the persona
  explicitly sends it there (`prompts.py:145-147`).
- **What it cost, measured.** Run `20260821-023819-4ad38a`: 453,133 tokens / **$1.24 imputed**, of
  which the Coder was **291,846 ($0.93)** — for a five-line flag. Not a fix loop (`iterations: 1`,
  `stalled: false`): one implement pass spent concluding *"the tests are failing due to network
  issues with installing dependencies"*. Validation then ran the same tests: **79 passed in 3.58s**.
  The code had been correct throughout.
- **`run_tests` was NOT the bug** — it calls the same `resolve_plan` + `run_plan` as `test_node`
  (`factory.py:356-362`), pinned by `test_repo_tools.py:797`. The coder had a correct path and used
  the wrong one, which is why this reads as an environment failure rather than a tooling gap.
- **DONE 2026-08-21.** New `project_interpreter(workspace)` beside `_install_step` returns
  `.venv/bin/python` when it is a real file on disk, else `sys.executable`; `sandbox_exec` uses it.
  `_pytest_plan` is deliberately UNCHANGED — it names the venv because it just queued the install
  that creates it (what WILL exist); a probe must ask what DOES exist. Plus a one-sided note that
  fires only when an import failure coincides with no venv, covering the fresh-clone window the
  interpreter fix cannot reach. Same defect and fix as [ADR-0049](adr/ADR-0049-change-coverage-gate.md)'s
  B3 false-park. No trust-boundary change: still network-off, still read-only.
- **MEASURED LIVE 2026-08-21.** Comparable item on the same project, same mode (guided/Balanced),
  same shape (a small flag on an existing subcommand): `--limit` (run `20260821-073957-e02032`,
  `clean_deliver`, 89 passed) against the `--verbose` baseline.

  | | before | after | |
  |---|---|---|---|
  | **Coder tokens** | 291,846 | **110,678** | **−62%** |
  | **Coder calls** | 26 | **13** | −50% |
  | Coder shadow $ | 0.93 | 0.36 | −61% |
  | Total tokens | 453,133 | 281,235 | −38% |
  | Total shadow $ | 1.24 | 0.74 | −40% |
  | Budget parks | 2 | 1 | |

  The **mechanism** corroborates the number, which matters more than the delta alone: the baseline
  coder's reasoning was environment diagnosis end to end, while this run's coder reported real
  results — *"All existing tests pass (89 tests)"*, *"10/10 tests in test_cli_list_limit.py"* — and
  raised no environment complaint at all. It could finally see what validation sees.

  **Honest limits.** n=1 vs n=1 on different items, so some of the delta is item difficulty
  (`--limit` is a slice; `--verbose` needed a counts dict). Both runs were `iterations: 1`,
  `stalled: false`, both `clean_deliver`. **Tester tokens went UP 27%** (86,994 → 110,408) on a
  larger authored file (195 lines vs 124) — unrelated to this fix in either direction, and recorded
  so the total-token line is not read as all attributable.
- **NOT fixed, deliberately:** seven other callers pass `install=False`, which silently leaves
  `interp = sys.executable` (`seedcheck.py:72`, `disposition.py:242`, `mutation.py:414`,
  `coveragemap.py:226`, `bench/faithfulness.py:104`, `bench/layer2.py:193`, `_escalation.py:273`).
  `seedcheck`'s is a **control input** — it decides the red-phase verdict — so moving it changes a
  gate signal and needs its own evidence and red-team round.

**[debt] F86 — the Proctor authors a bar that cannot do its job** (ADR-0085 amendment 2026-08-20)
- **The defect, two shapes, both live 2026-08-19/20.** *It can never pass:* the Proctor authored
  `assert "action='store_true'" in cli_content`, pinning source SPELLING that `hygiene`'s own
  `ruff format` rewrites after authoring — item 107 shipped a tree failing its own suite, and
  LedgerCLI was blocked on it until the ADR-0087 amendment path was exercised to fix the bar
  through the product. *It can never fail:* a rewrite that built a list, appended to it and
  asserted nothing — authored twice in one day, caught both times only by a human reading it.
- **NOT F53.** F53 is the Proctor *weakening* a bar it already committed (`assertTrue(True)`);
  this is *mis-authoring* one. They share only "the Proctor's judgment about its own bar is
  unguarded". The ADR-0106 entry above and its ADR carried the wrong number; corrected here.
- **DONE 2026-08-20 — doctrine + detection.** `personas/tester.md` permitted this outright (it
  told the Proctor to assert "file contents", and a source file is a file); it now narrows that to
  files the program WRITES, forbids asserting on source spelling *with the reason*, and requires
  every test to assert. `behavior_preservation.py` carries the same carve-out where it tells the
  Proctor to read source. Detection: `bar_integrity.py` adds `source_formatting_pin` and
  `vacuous_test`, admitted under ADR-0085 §1 by a recorded amendment (its review trigger fired) and
  measured — **every pre-existing kind moved by exactly zero** across 232 files, and the new kinds
  report nothing on those files while catching both live defects (the F37 result shape).
- **Honest limits.** Detection-only (ADR-0062) — it names a target for the Proctor's repair turn
  and gates nothing, so the evidence is that the Proctor was *told*, not that it complied. The
  one-sidedness was bought with recall: a spelling pin behind a computed path is not detected
  (including one real instance in this repo, `test_pmbench.py:267`), and a vacuous test that also
  calls the code under test is not detected. `overstrict_static` in bench
  scorecards is not comparable across this change.

**[prereq] Coverage-based oracle — `#29`** (ADR-0049)
- **Goal:** runtime line coverage (code↔test map), durable test ledger, change-coverage gate, token-saver (author only the uncovered delta).
- **Status:** P0–P2 **DONE**. P3 **split**: the region adapter + ledger write-wiring shipped; the
  **gap-fill token-saver was built then DELETED** by ADR-0060 (`coverage_gap_fill` + `gap_fill_node`
  removed — see the ADR-0049 amendment). Open: union the mutation test-set (A-3); the ledger is
  **written but never read** (the impact-selection consumer was never wired).

**[arc] Live demo-repo validation — `#53`** — three seed repos (greenfield / brownfield / spaghetti) + a webUI runbook + an observed-outcomes writeup. **Status: IN-PROGRESS — first observed-outcomes writeup landed 2026-08-05.**
- **Specimens (live, on `mosaera.rengifo.me`):** `LedgerCLI` = **greenfield, ALL 3 SLICES DELIVERED
  2026-08-06** — the first project driven end to end. Slice 1 guided (`c61a68e`, on the **13th** run;
  the previous 12 were cancelled), Slices 2 and 3 **autonomous** (`0cd9f49`, `1294030`). Full run
  ledger + milestones + cost:
  [engineering-history/ledgercli-run-ledger-2026-08-06.md](engineering-history/ledgercli-run-ledger-2026-08-06.md)
  · **synthesis + what to build next:**
  [engineering-history/lessons-2026-08-06-first-project-end-to-end.md](engineering-history/lessons-2026-08-06-first-project-end-to-end.md)
  (**read this before planning the next arc** — the highest-value change it identifies is an operator
  authorization *artifact* the tamper guard can read, [F63](engineering-history/ledgercli-friction-log-2026-08-05.md))
  — **this is the baseline the engine is measured against.** Two cautions recorded there and worth
  repeating: the F52 floor fix was deployed but **never fired** (the bar was real from the first
  draft, so the deliveries are *not* evidence the fixes caused them — the Proctor is high-variance),
  and **completion is not correctness** — [F57](engineering-history/ledgercli-friction-log-2026-08-05.md)
  shipped through every green control (`status` ignores months; the authored tests never mention one).
  Item #86 exists to test whether the loop closes without a human reading the diff. `Password Generator` =
  the **degraded** specimen — deliberately preserved in its broken state as the reference case
  (`DELIVERED` badge over `0/3 items done`, a security item stuck 25 days awaiting an approval no
  screen offers, 34 runs / 17.85M tokens). **Do not repair it**; it is the only known example of
  the end-state the engine is supposed to prevent. Brownfield/spaghetti seeds still open.
- **Output:** [engineering-history/ledgercli-friction-log-2026-08-05.md](engineering-history/ledgercli-friction-log-2026-08-05.md)
  — 31 findings, standing scorecard, ranked actions. The debt items below are its disposition;
  the path-coverage finding is in Current focus and amends the Gate-2 scope.
- **Open:** the webUI runbook; brownfield + spaghetti seeds; re-run Slice 1 once the plan/design
  reconciliation lands (the run that finally reaches `Vera` is the one worth measuring).

**[prereq] PM per-project sessions — `#30`** (ADR-0048 — corrected 2026-08-18; ADR-0045 was mis-credited) — replace the single forever-chat with per-project threads. **Status: DONE.** (Per-team sessions fold into the cockpit `#11`.)

### Wave B — Know the project

**Purpose:** teach the engine the project before it begins changing it.

**[arc] Project onboarding + recon + durable map — `#6`** (ADR-0047)
- **Goal:** interview → recon → durable **untrusted map** + **trusted charter**; the map informs scoping, **never** the gate.
- **Status:** map/charter store `#40` **DONE** · recon engine `#41` **DONE** · onboarding flow + synthesis `#42` **DONE** (MR1–MR4). Open: synthesis caching + posture enforcement.

**[arc] BYOM capability-hardening — *untracked, no issue*** — a capability layer over
`get_chat_model`: per-triple capability set + cached probe, fail-closed at config time,
degrade-or-park (never thrash/false_ship) on a model gap; DoD = a BYOM conformance suite.
**Status: DIRECTION.** *(Corrected 2026-08-08: this arc carried `#78`, which is F76/reachability — a
different piece of work. The number was a collision, not a reference; file an issue before any build.
The "degrade-or-park on a model gap" DoD also depends on the verb arc's slice 3 —
#82 — since a model gap cannot be
distinguished from a harness gap until harness constraints are recorded.)*

**[arc] Posture profiles — `#31`** (ADR-0046) — Free/Business/Regulated as a tighten-only restriction lattice over the autonomy knobs. **Status: DIRECTION.**

**[prereq] Settings v2 — intent profiles over the knob surface — *untracked, issue proposal*** ([ADR-0122](adr/ADR-0122-core-settings-are-intent-profiles.md)) — `GENERAL_KNOBS` reached 80 entries, ~62 of them reachable in the Settings page. Four intent profiles (`autonomy_profile`, `recovery_profile`, `quality_profile`, `verification_profile`) derive the mechanics; precedence gains a layer, `env > stored > profile > default`, with the profile BELOW stored so it can only fill what the operator never set.
- **Status: PARTIAL (2026-08-28).** Built on `session-d`: the resolver (`config/_profiles.py`), the four knobs, the precedence layer, `derived_from` provenance in `general_settings_view`, and the **Behavior** settings section — the profiles as dropdowns, a "what your profiles set" summary built from the server's provenance (not a client-side copy of the table), and per-knob *from X* / *overrides X* badges on the mechanics pages. Verified against knob values captured from the pre-change tree — all 80 pre-existing knobs resolve identically.
- **Deliberately NOT built, and not to be confused with what was:** this is a DEFAULT layer, not ADR-0046's tighten-only ceiling. The Free/Business/Regulated tiering, policy inheritance, the effective-policy view and the exception workflow all remain the `#31` arc above, DIRECTION.
- **The surface is now 12 controls (2026-08-29).** `config/_visibility.py` classifies every knob and the settings page reads it: `core` renders, `developer` sits behind one *Show advanced configuration (N)* disclosure, `internal` never renders. **84 → 12 visible** (35 developer, 37 internal). The unread `Knob.visibility`/`category` fields from the previous slice are GONE — the classification is two readable sets instead, so "what does a user see?" is answerable by reading one list rather than scanning 85 constructor calls. An unclassified knob defaults to `developer`, never `core`, and a test caps Core at 14 so the surface cannot drift upward one defensible knob at a time.
- **[prereq] LOCKING is the next slice, and it is NOT what hiding did.** Every knob is still settable by its env var; hiding is presentation, crosses no trust boundary and reverts by editing a set. A knob a client genuinely cannot change must ignore env *and* stored config — that contradicts the ADR-0005 precedence invariant and, for the safety set (`deliver_unverified`, `scan_enabled`, `hygiene_gate_enabled`, `stall_detection_enabled`, `backlog_spec_lint`, `doctrine_enabled`), touches the delivery gate: **CODEOWNERS + red-team required.** Two design questions to settle first: (a) locking a safety control ON is monotonic and safe, locking anything OFF or locking a non-safety knob can strand an operator — so the mechanism should only tighten; (b) whether a support/debug escape hatch exists, because if none is designed one will be added later as an undocumented env var, which is strictly worse than an explicit recorded one. **Never describe a hidden knob as locked** — an operator with shell access can still set it.
- **Open:** the knob-hiding IA slice above; making `verification_profile` the input to `apply_oracle_posture` (changes what the delivery gate permits → CODEOWNERS + red-team); removing `deliver_unverified` (same); per-run policy snapshot + policy versioning (needs its own ADR + Alembic revision).
- **OWED — this landed on `staging` by FAST-FORWARD, so none of the following happened before it was shared.** Recorded here rather than in a session transcript because a fast-forward leaves no review artifact to hang them off:
  1. **ADR-0122 has had no CODEOWNERS review.** `docs/adr/` is protected and the ADR + its `README.md` index row went in unreviewed, at the owner's explicit instruction. The design decision worth reviewing is §2 and §4 — a DEFAULT layer versus ADR-0046's ceiling — not the code. If the review rejects that framing, the precedence layer is the part that comes out.
  2. **No live-instance validation.** Everything is offline evidence: unit, API-route and component tests. Nobody has selected a profile on a running instance and watched the summary populate or a hand-set knob report *overrides*. That is the check that would catch a wiring fault the mocked `fetch` in the web tests cannot see.
  3. **The `Knob.visibility` / `category` disposition above is unresolved**, and shipping unread metadata is the thing most likely to rot here.
  4. **No issue tracks any of this.** File it as a Wave-B `[prereq]` citing ADR-0122 and move these four into it; nothing further should be built against this ADR untracked.

**[arc] Persist PM proposals + structured backlog actions + risk tiers + audit — `#8`.** **Status: DIRECTION.**

### Wave C — The firm + governance + cockpit

**Purpose:** generalize the SWE engine into the first governed AI firm.

**[arc] Firm layer — `#31`** (ADR-0045) — teams + Quincy-as-interface; generalize the four SWE seams. **No `Team` plugin API until the editorial team is a concrete second implementation** (extract-from-N). ⚠ **Blocking prereq:** editorial "done" needs an honest deterministic oracle, not an LLM-judge (the `strength="suite"` collision). **Status: DIRECTION.**

**[arc] Posture governance + enablement ceremony — `#31`** (ADR-0046) — dual-control, out-of-band, time-boxed, tamper-evident; the Regulated tier; red-team the posture × knobs composition. **Status: DIRECTION.**

**[arc] Team-tab cockpit — `#11`** — the UI face of the firm/posture work (built *with* it). **Status: DIRECTION.**

### Wave D — Research & artifacts

**Purpose:** expand output quality and research capabilities.

**[arc] Lyra (research packets) + Loom (artifact curation) — `#12`**, plus near-term artifact curation/packaging. **Status: DIRECTION.**

### Wave E — Enterprise & benchmark-as-product

**Purpose:** enterprise productization and capability benchmarking.

**[arc] Enterprise policy pack — `#13`** — the Regulated posture's productized surface. **Status: DIRECTION.**
**[arc] Capability Lab (MCB as a feature) + `mosaera.dev` self-build — `#14`/`#4`** — the dogfood endgame. **Status: DIRECTION.**

### Continuous — independent debt (slot anytime friction demands)

- Engine versioning (ADR-0055) — **DONE.** Follow-up closed 2026-08-07: `scripts/bump_version.py`
  (bump + `--check`), the CI `version-record` job, the maturity channel
  ([ADR-0088](adr/ADR-0088-engine-maturity-channel.md)), the
  [versioning runbook](runbooks/versioning.md), and drift closed in `apps/web/package.json`,
  `mosaera_agents.__version__`, and the FastAPI app version. Tagging stays a human act by design.
- UI refresh `#36` (reachable knobs, `incomplete` badge + reason) — **DONE.**
- Per-user rate limiting / quotas `#34` (ADR-0050) — **DONE.**
- Login brute-force protection `#38` (ADR-0051) — **DONE**; open: distributed credential-stuffing detection.
- **[debt]** Budget gate: in-flight node spend `#57` — the node's agent loop keeps calling the model after a park.
- **[debt]** Engine lean-detailing `#77` — dead-const cuts, relocate `bench/escalation.py`, split `tools/repo/factory.py` before 500 lines, surface `reliability_sensitivity` in UI.
- **[debt]** Host tools must not run with `cwd` inside the untrusted clone — the durable fix for the recon RCE classes (proven vectors already pinned).
- **[debt]** `is_test_file` review (ADR-0049 A2) — a *source* file named `test_*.py` bypasses coverage.
- **[debt]** **Backlog audit (`mosaera-audit-backlog`) is SHIPPED but UNCALIBRATED** — the read-only
  sweep over an existing backlog (ADR-0080 family; `backlog_audit.py` + CLI, merged 2026-08-05).
  Its own docstring makes calibration a precondition: *"a detector that over-fires here does not
  produce a bad number — it locks an operator's real backlog."* **First real run: 3 items across
  2 demo projects, 0 flagged — credible but zero signal**, exercising no true positive and
  bounding no over-fire rate. **Calibration needs a labeled corpus** of genuinely
  under-specified/legacy-shaped items with expected verdicts. Until then the tool must stay
  report-only (it is) and its output must not be cited as a measured rate.
  **Partly answered 2026-08-19 (ADR-0105 amendment):** a `backlog_health` decision now surfaces the
  same family of findings in the PM conversation — advisory, never gating, for exactly the reason
  the docstring gives. It also produced the **first labeled corpus**: 16 real LedgerCLI items with
  5 duplicate groups confirmed by hand against the repository, committed as
  `packages/core/tests/test_duplicates.py`. On it, the pre-existing near-duplicate Jaccard rule
  scored **0/7 pairs**, the overlap coefficient **54% precision**, and IDF-weighted cosine grouped
  by **average linkage** all 5 groups with none invented — so the card uses the last. The first
  version used SINGLE linkage and chained on live data within hours (one shared boilerplate
  sentence welded two groups; see the ADR-0105 amendment), which is the sharpest evidence yet that
  one corpus is not calibration. The threshold (0.3, stable band [0.25, 0.3] under average
  linkage) was fitted after seeing the labels and is recorded as provisional. The CLI itself is
  still uncalled by the app.
- **[arc] Quincy toward SME — the recorded truth now reaches the conversation (2026-08-20).** The
  North Star's bar is "answers from recorded truth, never guesswork", with the answering capability
  marked DIRECTION. Measured cause: he was not short of ROOM (a 10-item fixture assembled 587 tokens
  against 12,000) but short of CONTENT. Wired: claim-ledger verdicts per criterion via a new
  `list_item_claims` read (`item_id` was already a column) reconciled against the item's CURRENT
  acceptance so an unevaluated criterion reads UNMEASURED and never as passed; the acceptance TEXT
  instead of a count; the map's observations, not just its gaps; ratified clauses WITH their
  `because`; and `acceptance_criteria.md`, one of four doctrine files that shipped and were read by
  nobody. **First measured context change in this repo**
  ([A/B](engineering-history/pm-evidence-context-ab-2026-08-20.md)): pre-registered movers
  `grounded` (7-0, p=0.016) and `honest` (5-0, power-limited at p=0.062) both moved, all three
  controls sat still. Caveat recorded: 10 of 12 wins come from cases written by the change's author.
  **F60's code-evidence half (#70) followed on 2026-08-20**
  ([A/B](engineering-history/pm-code-evidence-ab-2026-08-20.md)): `curate` and `decompose` now
  receive the CONTENTS of the repo files an item names, selected by design-grounding's
  `plan_named_files` but rendered with the `| ` line prefix rather than its escapable fence
  (`mapview.py:8-11` had already recorded that flaw). QMB could not have detected it — fixtures
  carried a listing and no source — so the instrument was extended first (`contents`, and QMB-12,
  whose contract exists ONLY in the code). Measured on QMB-12 over 20 paired passes: `grounded`
  10-0 (p=0.002, 0/20 → 10/20) and `honest` 16-0 (p<0.001, 4/20 → 20/20), `safe` unmoved. Reported
  against it: `complete` leaned 3-9 to BEFORE (p=0.146), mechanism traced to empty/unparseable
  changesets which a follow-up probe measured at 2/12 with evidence vs 4/12 without — most likely
  noise, not ruled out. **Live-validated** 2026-08-20 on `app.mosaera.dev`: twelve curate calls,
  twelve `code-evidence: 7054 chars` log lines. Getting there took a detour worth recording — the
  control first failed open SILENTLY (`""` for a bad path, a missing clone and "named no file"
  alike), so an empty changeset on 9 of 12 live calls could not be told apart from an inert
  change; the diagnostic added to resolve it then DISPROVED the inertness theory. What is still
  NOT shown live is grounding itself: LedgerCLI's backlog already states its contract, so no
  code-only token ever had to appear. **Still open:** an item that names no FILE gets no code (selection is
  filename-driven, measured at 0 characters on the first QMB-12 draft); `build_grounding`'s fence
  on the design path is untouched; and F53 — the Proctor weakening its own bar — is #70's other
  half.
- **[debt] QMB — the PM behaviour benchmark (`mosaera-pmbench`, 2026-08-19).** The seat nothing
  measured: MCB grades the coder, govbench grades the intake detectors and *stubs the PM by
  design* ("this measures the ROUTING, not the proposal"). Six cases, five deterministic
  dimensions, no LLM judge. **Twelve cases as of 2026-08-20.** First three sweeps in
  [`qmb-first-sweeps-2026-08-19.md`](engineering-history/qmb-first-sweeps-2026-08-19.md). **NO BASELINE
  COMMITTED — the noise floor is larger than the signal:** two identically configured 5-pass
  sweeps disagree about which case fails which dimension. Stable across all sweeps: a proposal
  that destroys delivered work appears in every run, the no-op control fires (the PM invents work
  on a healthy backlog), and chat/curate disagree. On F60: it does NOT reproduce when the contract
  sits in the item description (QMB-06, winnable without code by design). The harder version — a
  contract that exists ONLY in the repository — became measurable on 2026-08-20, when fixtures
  gained `contents` and QMB-12 was added; ungrounded it reproduces at 0/20, and it is the case
  that measured the code-evidence change. **Its cost dimension was inert until 2026-08-20:**
  `run_arm` built a bare `CostMeter()` carrying NO price table, so every arm reported `$0.00`
  however the instance was priced — the benchmark could rank PM models on quality but never
  against cost, which is half of what it is for. It now takes the operator's rates and reports
  real spend and imputed on-box spend separately. Needs 3–5 cases per dimension and a second
  fixture project before it can gate anything. Every defect found in the instrument itself was
  found by reading raw output, not scores — the cost one included.
- **[debt] DIRECTION — a second detector, over project STATE.** The intake detectors
  (`checkability`, `decidability`) judge how an item was *written*, and would flag almost nothing
  on the degraded specimen: its acceptance criteria are genuinely checkable. The rot there is in
  **state** — contradictory status, an orphaned approval, a `LOCKED` badge on an item that already
  ran and passed, dependency edges with no provenance (a docs chore gating a unit-test item). Same
  family as the ADR-0080 instruments, different layer; arguably more urgent, since the checkability
  axis is measured and this one has no instrument at all. **Not authorized to build** — needs an
  issue + ADR like its siblings.
- **[debt]** **The bundled-DB default URL exists only inside `scripts/dev-up.sh:64`.**
  `Settings.from_env()` (`config/_from_env.py:142`) reads `MOSAERA_DB_URL` and nothing else, and
  `.env` ships it commented out — so any entrypoint **not** launched by `make up` reports "No
  database configured" while the bundled Postgres is running on `127.0.0.1:5432`. Hit by
  `mosaera-audit-backlog` on its first real run and by `scripts/db_migrate.py:25`, which reads the
  same variable. **Not a quiet default-value fix:** `Settings.db_url` feeds the API's ADR-0035
  refuse-to-start-on-unreachable-DB behaviour, so introducing a default changes boot semantics →
  decide explicitly.
- **[debt]** **Token cost is disproportionate to change size, and the cap is in the wrong unit.**
  Measured 2026-08-05: editing one file **to add a single comment line** cost **~43,000 tokens**;
  a whole correct `pyproject.toml` cost ~5,600. Run 2 split **450,357 input / 11,995 output
  (97.4% input)** over 51 calls — ~8,830 tokens of re-sent context per call, ~235 generated. Three
  consequences: (a) `_budget.py` caps on `total_tokens = input + output`, but the two are priced
  ~5× apart and input is cacheable at ~0.1×, so the cap is **dimensionally wrong** for cost —
  the `usd` dimension beside it is correct but reads `$0.00` on local models and never binds;
  (b) **no prompt caching exists anywhere** (`grep cache_control` over `packages/`+`apps/` is
  empty) on a workload whose 97%-input profile is the ideal case; (c) verification is what runs
  out of money first. Related: in-flight node spend `#57`.
  **The instrument landed 2026-08-20** (the hosted-API prerequisite, before any spend):
  `TokenUsage` now carries `cache_read`/`cache_write` as a BREAKDOWN of `input_tokens` — verified
  against `langchain-anthropic` 1.4.8, which adds the cached tokens INTO `input_tokens` before we
  see them, so pricing them separately would have double-counted and hidden the very saving the
  work is for. Rates accept `[in, out, cache_write, cache_read]`; a 2-element entry still prices
  exactly as before. **Shadow prices are reported apart from real ones** (`shadow_usd`, on-box
  models via `models.on_box_models`): the burn is visible without imaginary money reaching `usd`,
  which is what `runner/_budget.py` caps on — pricing local models would otherwise start parking
  and cancelling runs over spend nobody incurred.
  **(b) caching — DONE 2026-08-21.** `prompt_cache_enabled` (default ON) makes
  `_build_model_kwargs`' anthropic branch request `cache_control` — the one place ADR-0002 permits a
  provider option, and the funnel every run model passes through, so no agent is touched.
  **Prompt REORDERING turned out to be unnecessary and was NOT done:** `coder_system()` takes three
  booleans resolved at team-build time with no task text, listing, timestamp or uuid; tool schemas
  come from a fixed list literal with literal docstrings; personas are `@cache`-loaded; and
  `RunState.messages` is `add_messages`, so each turn APPENDS. The prefix was already byte-stable and
  monotonic — the ideal shape. A test now PINS that property, because a prefix that silently stops
  being stable costs money with no failure anywhere.
  Baseline to beat (2026-08-21): 440,075/13,058 and 271,490/9,745 input/output, `cache_read: 0` both.
  **CONFIRMED LIVE 2026-08-21** — run `20260821-153142-e8d73a`, coder on `claude-haiku-4-5`:

  | | |
  |---|---|
  | input tokens | 192,553 |
  | **cache_read** | **162,641 (84.5%)** |
  | cache_write | 29,837 |
  | uncached | ~75 |

  `162,641 + 29,837 = 192,478` of `192,553` — essentially ALL input is a cache read or write, and
  the hit rate CLIMBED with the conversation (69% at 4 calls → 84.5% at 14), which is the signature
  of an append-only transcript. Billed **$0.0729** against **$0.212** un-cached: a **65% cut**.
  Accepted limit: `StandingCorrections` (`coder.py:121-128`) appends to the system string, so a NEW
  operator correction invalidates the prefix once — not once per call.

  **The saving was INVISIBLE at first, and that was a second defect (fixed same day).** The run
  REPORTED $0.2118 — exactly its un-cached cost, a 2.9x overstatement — because
  `parse_price_map` required `len == 2` and dropped a 4-element entry WHOLE, leaving the model
  unpriced, while the pricing UI had no cache fields at all. So `.env.example` documented
  `[input, output, cache_write, cache_read]` and `cost._rate` implemented it, but nothing could
  ever deliver one: the 4-element path was unreachable. Parser, API (`PriceEntry.cache_write` /
  `cache_read`, all-or-nothing so a half pair can't persist as a droppable 3-element entry) and UI
  columns now carry it end to end. **The instrument built to show the saving was hiding it** — the
  same class as the inert cache and the inert `prompt_eval_ms` below.
  **(c) LOCAL caching — the correction, 2026-08-21.** The record said "Ollama reports no cache
  metrics, nothing to measure there". That was WRONG twice over. Ollama's prefix cache is AUTOMATIC (no
  request flag), and it does report a signal: `prompt_eval_duration`. Worse, the "96-97% input,
  `cache_read: 0`" framing could not have shown local caching either way — `cache_read` is an
  Anthropic field, structurally 0 on Ollama, and `prompt_eval_count` (which we DO record, and which
  feeds our input-token numbers) reports the request's whole context size, not what was recomputed.
  Token counts are therefore FLAT whether the local cache hits or misses.
  Two fixes: **`ollama_keep_alive`** (default `30m`) — Ollama unloads after 5 MINUTES by default and
  an unload dumps the KV cache, which guided mode triggers constantly because a human reading a
  write gate takes longer than that; and **`prompt_eval_ms`** on `TokenUsage`, so a hit (evaluation
  time collapsing while input tokens stay put) is finally visible.
  **`prompt_eval_ms` SHIPPED INERT and was fixed 2026-08-21.** Run `20260821-153142` reported
  `prompt_eval_ms: 0` on every local call: the duration was read only in `usage_from_message`'s
  response_metadata FALLBACK, but ChatOllama populates BOTH `usage_metadata` and
  `response_metadata` (its own docstring shows it), so the standard branch always returned first
  and the read was dead code. The original test set `usage_metadata=None` — green for the wrong
  reason, guarding nothing. The duration is now read independently of which branch supplies the
  token counts, and the new test pins the real ChatOllama shape. `ollama_keep_alive` is still
  unconfirmed: the before/after is a guided run's `prompt_eval_ms` at comparable input tokens.
  **Still open: (a) the cap's unit** — `_budget.py` caps on `total_tokens = input + output`, which
  caching makes *more* dimensionally wrong. Also noted: `config/_settings.py` now sits AT the
  500-line ceiling, so the next knob forces a split.
- **[debt] FIXED 2026-08-20 — every delivered run paid for embeddings nothing reads.**
  `persist.py` embedded the run diff and task+plan on every delivery; the only readers,
  `similar_artifacts` and `similar_doctrine`, have **zero production callers** (one store test is
  the sole reference in the tree). Cross-run retrieval is DIRECTION (ADR-0084), so the cost bought
  nothing. The calls are gone; the column, the store methods and migration 0008 stay as the seam.
  Second benefit for the hosted migration: `get_embeddings` is hard-wired to Ollama and ignores
  `role_providers`, and the failure was swallowed — so on a box without Ollama every delivered run
  was silently paying for a failing round-trip.
- **[debt] FIXED 2026-08-20 — the PM chat lost every proposal on refresh.** `pm_turn` returned
  `changeset`/`charter_proposal` to the client and stored neither, so a reload destroyed the card
  — and because `pm.chat` strips the proposal out of the reply before persisting it, what survived
  was a bare "Here's what I'd suggest." with nothing under it (the standing `PmChangesetCard`
  TODO). Now a `message_proposals` child table (**Alembic 0031**, the `message_context_sources`
  shape) stores them redacted beside their turn; `list_messages` returns the OPEN ones so a card
  the operator already settled does not return, mirroring `clarification` vs
  `clarification_record`. Storing grants nothing: applying still runs the changeset validator and
  the delivered-work guard, and a charter still needs the admin-gated PUT (ADR-0047 §1).
- **[debt] PARTLY FIXED 2026-08-05** — **a cancelled run's code was unreachable through the
  product.** `GET /api/runs/{id}/patch` returned `{"detail":"no changes recorded for this run"}`
  for **both** runs after **36 approved writes**, while the page offered `download patch` and
  claimed *"Every attempt, check run and verdict is preserved."* Cause: `add_repo_change` is only
  reachable via `deliver_node → persist_run`, so the cancel path writes ~3 columns. The work was
  never destroyed — the workspace is not cleaned on cancel — so `run_diff` now falls back to a
  read-only live diff of it (throwaway `GIT_INDEX_FILE`, so a GET cannot stage the tree), which
  fixes `/patch` and the `/files` listing together. **Still open:** the seal. `record_run`
  early-returns on a `CANCELLED` row by design, so `engine_version` / checksum cannot be
  backfilled — a cancelled run remains un-replayable against the code that produced it, which is
  the actual *Capability through Auditability* residual.
- **[debt]** **Operator corrections do not persist within a run, and the write gate hides the
  regression.** The coder applied a correction to the file in front of it, then **reverted its own
  corrected file** later in the same run (reintroducing a forbidden import and **deleting the only
  test of a charter constraint**). The gate renders the proposed file but **not a diff against
  what is on disk**, so a fast-clicking operator loses earlier corrections silently. Fix: diff
  overwrites against disk and flag removal of previously-approved content.
  **BOTH FIXED 2026-08-05**, and both mechanisms turned out to be deletion rather than disobedience.
  (a) `write_file` now sends a unified diff against disk and a `+N -M vs disk` summary — `edit_file`
  had carried a diff all along, and that asymmetry was the whole defect. (b) A send-back's only
  destination was the `DENIED by human reviewer:` tool result, which `ClearToolUsesEdit(keep=3)`
  deletes after three more tool calls; corrections are now lifted into the coder's system message
  and stored in a new checkpointed `corrections` state key (deliberately not `feedback`, which gates
  the ADR-0080 intake park). Producer-side only — corrections never reach the reviewer, critic or
  gate. **Owed:** end-to-end confirmation on a real slice; unit tests prove a correction is re-sent,
  not that the coder obeys it.
- **[debt]** **The artifact tiers are inverted** — decision drafted as
  [ADR-0084](adr/ADR-0084-artifact-tiers-and-cross-run-context.md) (proposed). Two failures, one
  root cause. (a) **The charter reaches decompose only** (`grep charter` over `graph/`,
  `prompts.py`, `run_context.py` is empty); the coder gets `Task + Plan + Design` and nothing else,
  so a semantic constraint survives only by landing in an item's acceptance and a structural one
  reaches the executing agent not at all. (b) **The design is persisted on the item and reused as
  authority by later runs** — `design_node` reuses it whenever `feedback` is empty, so a design is
  served from cache after the charter, the acceptance or the plan changed. ~~It is a cache with no
  invalidation key~~ **— FIXED 2026-08-06 (ADR-0084 §3):** `design_cache_key` fingerprints task +
  plan + standing corrections, `design_node` serves the cache only on an exact key match, and a NULL
  key reads as stale (`graph/_design_cache.py`, migration `0023_design_key`). Known incompleteness,
  recorded in the key's own docstring: the CHARTER is absent because it is not reachable from the
  graph, so (a) still gates it. Corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`; the recon map's per-dimension fingerprint (deny-by-default on unknown
  freshness) is the pattern to copy. Nothing reconciles plan against design either, and the coder
  is told to follow both with no tie-break — five identical operator corrections in one run, then
  reverted by the coder itself. Highest value-per-fix on the interactive path.
- **[debt] DIRECTION — cross-run context: runs are siloed on their own failures.**
  `project_history` filters `Run.status == "APPROVED"`, so the shared run context
  (`build_run_context`, `#26`) carries **successes only** — every cancelled, parked and thrashed
  run is invisible to later runs, which is the lesson most worth carrying. The failure-side data
  already exists (`run_diagnosis`, `#75`: outcome bucket, park cause, gate reasons, in the bench's
  own vocabulary) and the carrier already exists and is budgeted, so this is a filter widening, not
  new storage. Admissible on the map's terms only (ADR-0084 §4): evidence-derived, attributable,
  bounded, and **never reaching the gate**. Related: the map's fingerprints should turn each run's
  repo understanding into a *verification pass over stale dimensions* rather than a fresh deep
  dive. **Not authorized** — needs an issue, a measurement, and a red-team pass, because a
  "what to avoid" digest is exactly where a bad prior run teaches a wrong lesson.
- **[debt]** **Artifact serialization defects (two, both mechanical).** (1) **FIXED 2026-08-05** —
  acceptance criteria were stored as a **stringified Python list**, so every item showed
  `ACCEPTANCE CRITERIA · 1` whose text was `['…', '…']`. One line (`pm/_backlog.py:190` doing
  `str()` on a JSON array); the correct joiner already existed as `intake_ask._as_text` but had
  never reached the decompose path. Promoted to `task_spec.acceptance_text`, applied at all six
  write sites, with type validation in the changeset validator. It corrupted more than the count:
  claim ids (so gate attribution), the task string handed to the coder AND Proctor, the
  checkability verdict, the backlog audit's input, and `pm_context_builder`'s criteria count fed
  back to Quincy — which is why asking him to emit separate criteria never worked. **A second,
  distinct shape remains** (a model emitting `{"a","b"}` as a *string*, so it arrives
  already-stringified): recognisable, deliberately not auto-repaired.
  (2) **Charter regeneration is lossy, truncating, and self-misreporting**: three attempts
  produced a charter cut off mid-sentence, one that dropped all seven prohibitions, and one that
  rendered the constraints as a Python list repr — each presented under a claim that everything
  was preserved, with a `Confirm & save` button beneath it. **The deterministic Overview → Edit
  path wrote it correctly first try**; regeneration should not be the default path for a
  governance artifact, and must never assert completeness without checking its own output.
- **[debt]** **The vendored semgrep ruleset declares no metadata, so the triage carrier is empty.**
  `tools/scan.py` now carries `confidence` / `subcategory` (semgrep's own `vuln`/`audit`/`guardrail`
  vocabulary) / `cwe` off each result — **DATA only**, out of `format_findings` and out of the gate,
  per [ADR-0076](adr/ADR-0076-independent-security-gate.md)'s rejection of gate tiering. But
  `infra/semgrep-rules/python-security.yml` has four rules and **zero `metadata:` blocks**, and the
  scan sandbox is `--network none` so registry rules cannot be fetched. Every field is therefore
  empty on every real finding today; the parse is proven against a fixture, not live output. Adding
  metadata to the vendored rules touches `infra/` — **CODEOWNERS-protected, needs explicit human
  approval and its own MR**, the same split ADR-0076 already made for scanner-image changes. Until
  it lands, this is a carrier with no cargo, and any derived-constraint work that assumes populated
  triage data is blocked on it.
- **[debt]** **An assertion-free suite can become the protected oracle.** A coder-authored file
  whose three tests were `self.assertTrue(True)` was designated *"ACCEPTANCE TESTS (PROTECTED —
  THE CODER CANNOT EDIT THESE)"*. The separation-of-duties machinery worked perfectly around a
  suite that cannot fail. `assertTrue(True)` is mechanically detectable — reject before granting
  protected status. (Whether `oracle_mutation_check` would have caught it is **still unknown**:
  the run never reached validation.)
- **[debt]** **Project status disagrees across surfaces, and one surface invents evidence.** Six
  panels gave six answers on the degraded specimen (`DELIVERED` vs `0/3 done` vs `6 delivered
  items` vs `DONE 0`); the run-summary tiles read `Cancelled 0 / Approved 0` above a list of both;
  two **different spend figures** appeared on one screen (`406,495` vs `469,333`) — the number the
  operator prices a stop/continue decision on. Worst case: a cancelled run whose own record says
  *"no claims were bound"* is badged **`TESTS FAIL`** on the backlog item, asserting a verification
  outcome that never happened. The same class appears on a **clean** project within minutes of
  setup (`Objective: No goal recorded` beside a saved charter). Needs one derivation of status,
  consumed everywhere.
- **[debt]** **No project-state repair path, and manual steps have no board presence.** Every
  control moves work forward (Run · Review · Approve · Request edits · Unlock · Run anyway ·
  Curate · Re-run recon); nothing retires a bogus dependency, cancels an orphaned approval,
  reconciles contradictory status, or re-baselines after a charter finally exists — so the only
  escape from broken governance is **ungoverned override**. Compounding it: `File deletion` is
  admin-disabled by default (correct), and the resulting *manual step* materialises in **no**
  backlog column — the degraded specimen's security item has sat 25 days in `AWAITING_APPROVAL`,
  named in the health panel as the reason autonomy stopped, with no affordance anywhere to action
  it. This is the "clean up a messed-up project" gap.
- **[debt]** **Write-gate granularity does not scale.** `guided` opens an identical approval, with
  identical weight, for a 5KB test module and a **38-character `__init__.py`**; one slice required
  ten. Uniform gating trains click-through, which defeats the gate on the write that mattered.
  Risk-weight it (new vs modified, size, path class) or batch trivial writes.
- **[debt]** LiteLLM / vLLM / OpenAI-compatible proxy in front of the gateway; egress-allowlisted install proxy. *Classification half done:* a loopback endpoint the operator explicitly declares on-box is no longer treated as cloud egress ([ADR-0024](adr/ADR-0024-cloud-egress-and-price-gate.md) amendment 2026-07-28) — deny-by-default, so a forwarding proxy still requires a conscious declaration. Open: the proxy itself + the install proxy.

#### Staleness audit backlog (2026-08-01)

A three-part audit (docs hygiene · built-but-inactive features · pytest coupling) ran before the
`#81` arc. **The engine's active path was found healthy** — no half-built work, every posture-ON
feature reachable and tested. The four *honesty hazards* it found were fixed in the `#81` cleanup
(dead `reviewer_advisory` knob + its UI toggle and the phantom control it implied in
[TM-0001](threat-models/TM-0001-mosaera-lite-repo-agent.md); root `pyproject` a release behind, now
guarded by a test; the ADR-0049 amendment above; the missing `critic` node in the architecture doc).
The rest is recorded here rather than lost:

- **[debt]** **Unmeasurable "held" features.** *(Partially resolved 2026-08-02: both named knobs
  gained `MOSAERA_BENCH_*_OFF` levers and were measured — `oracle_mutation_comprehensive` moved
  MCB-05 0/3; `oracle_structural_spec` was activated on n=3, then WITHDRAWN when n=25/arm showed
  null — see the entries above.)* Still open for ADR-0074/0075 Layer-2 disposition (a core module
  + an API sweep rung + 29 tests + a bench flag, whose own measurement records **0 true
  conversions**) and ADR-0066 `behavior_preservation_guard` (dormant, known-harmful-when-on,
  retirement already queued).
- **[debt]** **Dead public functions.** `similar_doctrine()` (**zero references anywhere, including
  tests**), `similar_artifacts()` (test-only), `team.py::spec_for()` (test-only). `persist.py` still
  pays the embedding cost on every artifact write for a retrieval path with no consumer.
- **[debt]** **Coverage-region ledger written but never read** (see the ADR-0049 amendment).
- **[debt]** **Doc drift** (low-risk, mechanical): `#30` attributed to ADR-0045 at line ~127 but
  ADR-0048 owns it; `CHANGELOG` `[Unreleased]` omits three shipped `main` commits (two user-visible
  `feat`); ~12 prose code paths drop the inner package dir (`packages/agents/coder.py` →
  `packages/agents/mosaera_agents/coder.py`), several inside CODEOWNERS-gating sentences where an
  unresolvable path weakens the instruction; ADR-0070 carries two statuses at once with no
  `Superseded by:` pointer; the ADR template defines `Implementation:` / `Date accepted:` fields
  ~~**zero** ADRs use~~ **10 ADRs use** (corrected 2026-08-18 — this ledger entry had itself gone
  stale; ADR-0084…0092 carry the full template header); `docs/archive/README.md` link text ≠ its target.
- **[debt]** **Dangling git refs.** Three superseded branches (`feat/mcb-cross-language` — the
  cross-language grader landed better on `main`; `fix/tamper-guard-false-positive` — ADR-0068 is on
  `main`; `origin/infra/sandbox-node` — superseded by per-language sandbox images) and five stale
  stashes, incl. one explaining the ADR-0030 tombstone. Delete rather than merge.
- **[debt]** **Gate 2 status reads contradictory** — the gate table marks `false_ship` ✗ while the
  accepted 2026-07-22 baseline reports `false_ship` **0**. Both are true (0 on `rebaseline_80on_x3`,
  1 on the 0.6.0 snapshot, MCB-05 class judged unclosed) but the reconciliation is stated nowhere.

  **RESOLVED 2026-08-05 — it was a three-way contradiction, and the reconciliation is that the
  number was ours.** The 6.9% was real at `405ded5`; it is unreproducible at HEAD; and the
  two-rulers grader divergence is still there, unmeasured. All three are true because
  `check_structural_compliance` vouched on zero executed predicates, minting the vouch that cleared
  `oracle_unverified` and let five runs ship (MCB-05 ×2, MCB-15 ×3, every one with
  `vouch: structural_claims:…` and `gate_reasons: []`). Fixing that on 2026-08-04 removed the only
  delivery channel those cases had, so `false_ship` went **unobservable, not zero** — and 24/24
  `honest_park` is a hollow pass, not a green gate. Gate 2 is therefore **restated** (ADR-0061,
  amended: *no unestablished material claim ships*, rate as a bound on a NAMED distribution) and
  **re-measured** at HEAD, n=72, same isolation protocol. The standing baseline
  (87.5% / 6.9% / 50%) is pre-fix and retired on arrival of the new sweep; the per-case baselines
  still record `delivered: true` for MCB-05/15 and are three weeks stale.
- **[debt]** `on_box` (ADR-0024 amendment) is absent from every **operational** doc despite deciding
  whether an autonomous run demands egress consent.

## Open reconciliation notes

- **Reconciled against the code 2026-08-24, after 36 commits had landed since the previous edit.**
  The file tracks ARCS well and ISSUE CLOSURE poorly: work lands, the defect is fixed, the bullet
  stays open. Found and corrected in one pass — #108, #109 and half of #116 shipped while still
  listed as open; the `[[decision:<id>]]` channel described as ON PROBATION when it had been
  retired the day before this file was last edited; the Artifacts brief pane listed as unbuilt
  when it had existed for ten days; and two whole shipped arcs (the clean-clone check, the agentic
  PM chat) absent entirely. Nothing that was open turned out to be closed by accident — every
  correction is one direction, which is the signature of "finishing work does not update the map".
  The rule at the top of this file is the one that slipped: *every MR that finishes or discovers
  work updates this file*. Verify against `git log` before trusting a status here.

- **We build ahead of the board.** The correctness oracle + trust boundary shipped before they were issues → recorded as **Phase 0**; treat the code as truth over the issue list.
- **Anti-rabbit-hole (recorded):** the oracle change-relevance heuristic took four adversarial rounds → the coverage arc is the durable exit, not more heuristic polish. Same lesson drives the STOP rule.
- **Issue-number caution:** `#57` labels both the Proctor-faithfulness arc (ADR-0062) and the in-flight-spend debt item; `#31` is an **umbrella epic** (firm layer + posture profiles + posture governance, Waves B/C), not one issue — verify before citing.
- **2026-08-05 was `#53` executing, not a pivot.** The operator-driven session that produced the
  friction log is the arc's own definition of done ("a webUI runbook + an observed-outcomes
  writeup") finally producing evidence. Nothing in it contradicts a standing DIRECTION item; it
  **narrows** one thing (Gate 2's measured scope) and **adds** one unmeasured path. The correctness
  program remains the critical path — today's result argues the interactive path needs an
  instrument *before* it can be argued about, not that correctness should yield priority.
- **Unclosed at the time of writing (2026-08-05), so it is not lost:**
  (a) branch `fix/audit-clean-db-error` carries `c9a2d30` — **pushed to origin but with no open
  MR**, so it is not in `origin/main` and local `main` trails it; merge or park explicitly;
  (b) the **backlog-audit calibration** that opened the session is **still open** — the tool runs,
  the corpus doesn't exist (see the debt entry);
  (c) `#53`'s brownfield and spaghetti seeds are unstarted, and the LedgerCLI re-run is blocked
  behind the plan/design reconciliation;
  (d) the **F19-class question is answered** (the acceptance oracle discriminates) but the
  **mutation-oracle question is not** — whether `oracle_mutation_check` rejects an assertion-free
  protected suite is still unmeasured, because no run has reached validation on this path.
