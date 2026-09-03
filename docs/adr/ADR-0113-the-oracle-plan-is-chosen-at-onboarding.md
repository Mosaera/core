# ADR-0113: A project's ORACLE PLAN is chosen at onboarding, and a park names the knob that unblocks it

- Status: accepted
- Implementation: shipped
- Date accepted: 2026-08-24
- Owners: Alejandro Rengifo
- Related issue / MR: #121 (the alpha-outsider onboarding stopper); #108 (the park reason was recorded and not rendered — this is the other half); #78 (F76, the reachability axis)
- Supersedes / Superseded by: — (**amends** [ADR-0047](ADR-0047-project-onboarding-and-the-durable-map.md): the interview now settles the oracle plan, not only goal/constraints/posture)
- Related: [ADR-0046](ADR-0046-posture-and-autonomy-governance.md) (posture is a restriction lattice — the INITIAL choice is in scope here, no relaxation mechanism is), [ADR-0012](ADR-0012-cohesive-team-supervision.md) / [ADR-0101](ADR-0101-run-interaction-modes.md) (the run-mode vocabulary this makes a project-level default), [ADR-0005](ADR-0005-config-in-ui-settings.md) (enumerables are dropdowns; env > stored > default), [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (an operator test command is worth `strength="suite"`), [ADR-0090](ADR-0090-gate-reason-classification.md) (the reason vocabulary this attaches remedies to)
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) (an operator-supplied test command is now settable from the web and executed in the sandbox), [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (a project-scoped route writes a deployment-global config knob)
- Review trigger: `evaluate_oracle` gains a fifth independence leg, or a per-project settings overlay is introduced

**Decision summary:** A project records the choices that decide whether its runs can conclude —
default run mode, an operator test command, and (via the deployment-global knob) whether the Proctor
authors the acceptance test — and the product states, before the first run, which of the delivery
gate's four independence legs can vouch for that repository. Every gate reason additionally carries
a **remedy**: the knob or action that unblocks it. No gate authority changes, and no posture
relaxation mechanism is introduced.

## Context

The 2026-08-24 alpha-readiness audit asked what blocks handing Mosaera to someone who is not its
owner. A newcomer's project is almost always **greenfield**, which is both the regime the corpus
measures worst and one whose default terminal state is a **park** rather than a delivery. The
mechanism is `evaluate_oracle` (`graph/_oracle_legs.py`):

```
verified = (tester_vouched or standing_suite or test_cmd or structural_vouch)
           and mutation_ok and structural_ok
```

On a fresh repository every disjunct is false: there is no standing suite, `tester_enabled` is OFF
by default, `structural_vouch` is earned per-item, and **`test_cmd` was unreachable from the
product** — `RunSubmit.test_cmd` reached `build_graph`, but only the CLI's `--test-cmd` could set
it. So a newcomer writes code, watches a green suite, and gets `oracle_unverified`.

Three separate things made that unrecoverable without the owner in the room:

1. **Nothing stated the repo's shape or its consequence** before the first run.
2. **`#108` fixed the recording of park reasons and not the remedy.** The run page names what was
   missing and nothing about what supplies it — for a reader who has not read the ADRs, a diagnosis
   with no action is the same dead end as no diagnosis.
3. **The intake lint already existed and one axis was invisible.** `reachability` (F76, #78) has
   been computed and served on every backlog row since it shipped and was never rendered, so "the
   engine has no tool for this work" surfaced only as a 409 *after* the operator committed to a
   run. Item 88 cost five runs and ~2.9M tokens to that silence.

## Decision

### 1. The repo's shape is MEASURED, and the measurement reuses the gate's own predicate

`mosaera_core.reposhape` classifies a clone as `empty` / `greenfield` / `sources_no_suite` /
`standing_suite`, from the validation planner (`detect_validation_plan`) and
`authored_suite_asserts_behaviour` — **the same predicate `standing_suite_is_independent_oracle`
requires**. Counting `test_*` files would have been easier and would have told the operator a suite
exists that the gate then refuses to credit; `sources_no_suite` is a distinct shape precisely
because "your tests assert nothing" and "you have no tests" have the same consequence and different
words. Pure, deterministic, no sandbox, no model — it runs on the interactive path.

It never claims the suite *passes*: that requires executing it, which is recon's `tests` dimension.

### 2. The onboarding surface is a pre-filled CHECKLIST, not a blocking wizard

The card sits beside the Quincy chat rather than in front of it, arrives pre-filled with the
detected recommendation, and is savable in one click. Only the row that actually decides whether a
run can conclude — the oracle plan — is open by default; run mode, posture and budget sit collapsed
at safe defaults with their answers legible in the summary line.

This is a deliberate design decision and not a layout preference. The published evidence on
activation is consistent in three directions: a blocking multi-step wizard suppresses reaching first
value; steps not required to reach it should be deferred rather than made faster; and a form of
empty fields is where people stop. It is also the shape Devin's repo setup converged on — detect,
propose as approvable cards, then build.

### 3. Run mode becomes a project-level DEFAULT, distinct from posture

`projects.default_run_mode` (one of `RUN_MODES`) seeds the launch control and is still overridable
per run. `RunItemBody.mode` becomes `Literal[...] | None`, because a hard `"guided"` default made
the stored value unreachable through the only path the UI calls — a column nothing reads is an
invisible control, which is a defect class this repo has now measured six times.

**Run mode is not posture, and the flow says so.** The issue that requested this work used
"posture" for `guided/autonomous/high_assurance` (ADR-0012's run modes); ADR-0046's posture is
`free/business/regulated`, a governance declaration on a restriction lattice. Both are set here, on
separate rows, named as separate axes. An operator who believes they are one thing will set one
expecting the other.

**Graduated autonomy is the default.** The card opens on `guided` and the operator opts up. That is
the trusted onboarding shape and it is also the only direction ADR-0046's lattice permits.

### 4. The operator test command becomes reachable

`projects.test_cmd` is threaded onto the `RunSubmit` a backlog-item launch builds. `resolve_plan`
already treats an operator-named command as `strength="suite"` (ADR-0034) — the operator asserted
what "validated" means for their repository. This closes the one independence leg that existed in
the engine and could not be selected from the product.

### 5. Three authorities in one body, gated separately

`PUT /projects/{id}/setup` spans governance (`posture`, admin, and **only on a real change** — the
ADR-0047 amendment's rule), deployment-global config (`tester_enabled`, admin, written through the
same `coerce_general_patch` + `write_settings` path `/settings/general` uses), and per-project
operator intent (run mode, test command, budgets — a member's job). Every field is None-sentinelled:
omitted means leave alone, so a partial save can never exercise an authority the operator did not
intend to use.

**The Proctor knob is deployment-global and the UI says so in those words.** There is no per-project
settings overlay and #121's scope forbids inventing one; the honest resolution is to write the real
knob and label its reach, not to imply a per-project setting that does not exist.

### 6. Every gate reason carries a remedy, and the oracle's remedy is LEG-AWARE

`apps/web/src/lib/remedy.ts` is total over `mosaera_policies.gate.GateReason`, pinned from Python
(`test_gate_reason_coverage.py`) for the reason that file already records: a TS enumeration of a
Python vocabulary is a second origin by construction. Two properties are load-bearing:

- **A remedy that names a knob must name a real `GENERAL_KNOBS` field**, guarded. "Turn on X" where
  X does not exist is worse than silence — the operator goes looking, fails, and stops trusting the
  next sentence too.
- **`oracle_unverified` is one token over three situations.** `diagnosis.oracle_blocked_by`
  (`independence` / `mutation` / `structural`) has been recorded on every run since #60 and never
  rendered. A generic sentence sends an operator to flip the Proctor when the Proctor was already
  on and the mutation check is what refused.

**A tamper reason gets an action and deliberately no knob.** There is no setting that makes "the run
edited the tests it was judged by" acceptable, and offering one would train the operator to click
past the most serious park the engine emits.

## Options considered

- **A per-project settings overlay** so the Proctor could be set per project. Rejected — it is a new
  config seam beside `GENERAL_KNOBS`, explicitly out of #121's scope, and the scatter ADR-0046 was
  written about. Writing the global knob and labelling its reach is honest; a shadow copy is not.
- **A modal setup wizard at project creation.** Rejected — see §2. It also cannot work: intake
  clones in the background, so at creation time there is no repo to measure.
- **Putting the remedy table in `packages/policies` beside `REASON_CLASS`.** Rejected — a remedy is
  operator guidance, not a gate input, and the trust boundary should not grow a surface that no
  control reads. It lives in the copy deck and is guarded from Python.
- **Recommending, but not writing, the Proctor knob** (link into Settings instead). Rejected by the
  owner: sending someone out of the product to copy a value back is a measured activation killer,
  and the recommendation only ever turns verification ON.
- **Collapsing run mode and posture into one control**, as the issue's wording implied. Rejected —
  §3. They are different authorities over different questions.
- **A ninth recon dimension for repo shape.** Rejected — recon needs a sandbox and is asynchronous;
  this must answer on the interactive path.
- **Rendering remedies on the delivery receipt too.** Rejected for now — the receipt records what an
  approval priced, and it does not carry `oracle_blocked_by`, so it could only show the generic
  sentence. A receipt is history; the diagnosis panel is where the next step belongs.

## Security implications

- **An operator-supplied `test_cmd` is now settable from the web** and executed in the run sandbox.
  It is operator-authored and therefore trusted in the same sense the charter is (ADR-0047 §1), it
  runs network-off under the standard sandbox constraints, and the write is not a privileged one —
  but the *reachable surface* is new (it was CLI-only). TM-0001 records it.
- **A project-scoped route writes deployment-global config.** `tester_enabled` is admin-gated
  identically to `/settings/general` and goes through the same coercion, so no new authority is
  created — but the route's blast radius is wider than its path suggests. TM-0002 records it.
- **No gate authority changes.** The shape, the plan and the remedies are descriptive. The oracle
  disjunction, the mutation floor and the delivery gate are untouched, and the recommendation can
  only turn verification ON.
- **No posture relaxation mechanism.** The initial posture choice is in scope per ADR-0046 §7; a
  change still requires an admin, is audited, and the lattice is unmodified.

## Red-team (scoped, 1 round — 2026-08-24)

Trust-boundary-adjacent by CLAUDE.md's rule (it writes the ADR-0046 posture, feeds an oracle leg,
and adds an admin-gated write path), so a scoped pass was run against **this change**, not the
codebase. Two findings, both FIX-NOW, both fixed and regression-pinned; one accepted gap.

1. **Host-path infoleak in the honest-unavailable reason (FIX-NOW, fixed).**
   `open_project_workspace` raises `project clone not found at <absolute host path>`, and
   `_shape_payload` interpolated the exception into the operator-facing `reason` — handing the
   server's filesystem layout to any authenticated caller, on the ordinary *first* read of every
   new project. The state is what the reader needs; the exception is not. Pinned by
   `test_the_unavailable_reason_does_not_leak_the_host_path`.

2. **The audit line is dropped exactly when it matters (FIX-NOW on the CLAIM, gap ACCEPTED).**
   `AuditEvent.run_id` is a NOT NULL foreign key to `runs` and `project_activity` reads through
   that join, so a setup answered on a project with **no runs yet** — the normal case — records
   nothing. This is inherited rather than introduced (`put_charter`'s audit has the identical shape
   and hole, on the same governance field), and closing it needs a project-anchorable audit row: a
   migration on a shared table, which is its own change. **Disposition: ACCEPT, documented, and the
   claim corrected** — the docstring and the TM-0002 row now say the record is absent in that case
   instead of implying it exists. The deny-side controls (admin gate, change-only posture check,
   None-sentinelled fields) are the whole of the defence there, and the threat model says so.

Checked and NOT findings: `test_cmd` is `shlex.split` into argv with no shell, is length-bounded at
the store, and grants a member no capability they lacked (they could already launch runs that
execute agent-chosen commands in the same sandbox); a member re-sending the default posture creates
a charter row at the value already in force and cannot erase an existing goal/constraints
(`upsert_charter` leaves omitted fields alone); the posture change-detection compares against the
EFFECTIVE posture, so accepting the pre-filled card is not a governance act.

**Verdict: `clean_deliver` on the trust-boundary surface, with finding 2 accepted and filed.** One
round, not three: the change adds no new authority — every write reuses an existing gate and an
existing validated path — so the STOP-rule budget is spent on the surfaces that do.

## Operational implications

- **Alembic 0033** adds three nullable/server-defaulted columns to `projects`. An existing project
  keeps today's behaviour exactly: `guided`, no test command, an unanswered card.
- The card collapses to a one-line summary once answered (`setup_completed_at`) and does not nag.
- Rollback is the migration's `downgrade` plus removing the router mount; nothing else depends on
  the columns.

## Consequences

- A newcomer learns before their first run that a greenfield repository parks by default and what
  supplies the missing vouch. That is the #121 capability.
- `reachability` is finally visible on the board, which was a pure rendering gap over data the
  server has always sent.
- **Owner-owed and deliberately not claimed:** #121's criterion 5 — a stranger who has not read the
  docs creating a project and reaching a first evidence-backed outcome — cannot be satisfied by the
  author of the flow. It needs a person who has not seen this code.
- **The budget row offers a CAP and states that no per-item cost has been measured**, because for a
  new project none has. The issue's capability text asked for "a budget preset and what a typical
  item costs at it"; the second half is a number that does not exist for a fresh project, and
  inventing it would be the first thing a newcomer ever read from us. Follow-up: a deployment-wide
  measured per-item cost, priced at the selected tier, would be an honest answer and is not built.
