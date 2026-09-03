# ADR-0052: Already-satisfied tasks conclude early and honestly (they don't thrash, and they don't auto-deliver)

- Status: accepted
- Date: 2026-07-17
- Owners: Mosaera core
- Related issue: #44 (child of the #43 run-reliability arc; sibling #45 validation-scope)
- Related threat model: TM-0001 (the delivery gate / oracle)

## Context

The #43 arc's target: ~99% of runs reach a clean terminal state — deliver, or park honestly with an
accurate reason — **without looping or thrashing**.

A live run (`20260717-190701`, proctor ON) thrashed to a park: the task was **already satisfied** before
any implementation, so the Proctor's acceptance suite passed on the untouched tree
(`oraclecheck.authored_suite_is_red` → `False`). The engine had no first-class response — it kept hunting
a red it could never get (~13 files), the planner emitted a degenerate plan, and the run gave up via
`supervise` **mislabeled "beyond what I can complete."** The conclusion was honest but far too late and
wrong-reasoned: 138 calls / 1.2M tokens to reach a park that should have been an immediate, correctly
reasoned conclusion.

## Decision

When the Proctor's suite is **green pre-impl** (`tests_red_verified is False`) AND makes a real assertion
in a **non-skipped** test (`tests_assert_real is True`), set `RunState.already_satisfied`. Treat it as a
**hint that the task may already be done — enough to conclude early and honestly, but NOT enough to
auto-deliver.** Concretely:

1. **Don't give up on a satisfiable run** (`route_after_capture`): with `already_satisfied` set, don't
   divert to the supervisor on a *degraded-plan* `escalate_reason` — route to the normal `test → … → gate`
   path so the run concludes at the gate with an accurate reason instead of the "beyond what I can
   complete" give-up. A **genuine coder hand-raise still wins**: `blocked_reason` OR a coder-originated
   `coder_escalated` both route to `supervise` (see red-team F-routing below).
2. **Conclude honestly, do NOT auto-deliver.** The gate is unchanged: a green-pre-impl suite is not an
   independent oracle, so `oracle_unverified` fires and the autonomous policy **parks** (guided: a human
   decides; autonomous: honest `incomplete`). The only change is the *reason*: `_termination_reason` and
   the report say **"appears already satisfied — confirm the acceptance is met (green pre-impl)"** instead
   of the inaccurate generic "the passing tests are the coder's own." This lands the run in the scoreboard's
   `honest_park` bucket — a clean, honest conclusion.

The engine never ships work it cannot independently confirm. The win is *early + honest*, not *auto-delivered*.

## Options considered

- **Auto-deliver the tester's green tests (REJECTED after red-team).** The original cut of #44 suppressed
  `oracle_unverified` behind a `changed_files(diff) ⊆ authored_tests` guard and auto-delivered a tests-only
  diff. The red-team (below) proved this **false-completes** genuinely-unmet tasks — the same false-success
  class as #45, on the conclusion side. A *safe positive* auto-deliver would need requirement-linkage
  evidence that the green-pre-impl signal structurally cannot provide.
- **Complete with no MR (REJECTED).** Same false-completion problem — it still marks an unmet task done.
- **Honest early-conclude (CHOSEN).** Keeps the anti-thrash win, adds no ship path, cannot false-complete.

## Red-team disposition (definition-of-done gate — the gate/oracle is a trust boundary)

Three refute agents, one round; the STOP rule tripped on the false-completion class → escalated to this
design change rather than patching variants. Findings and disposition:

- **False-completion class — `already_satisfied` can't prove the suite pertains to the task**
  (wrong-target green: tests pre-existing behaviour; skip/xfail green: collects-but-never-runs → exit 0):
  **FIX-NOW via this redesign** — dropping the auto-deliver removes the harm (the run now parks for a
  human). Plus a deterministic hardening: `authored_suite_asserts_behaviour` now excludes
  skip/xfail-decorated tests, so an all-skipped suite no longer clears the assertion floor.
- **Subset-guard leaks — `changed_files` under-reports vs `git add -A`** (`__pycache__`/renames/chmod ship
  invisibly, so "can never ship a source change" was false): **MOOT** — the subset guard is removed with
  the auto-deliver.
- **Routing swallowed a genuine coder escalate** — the anti-thrash override dropped *every*
  `escalate_reason`, not just the degraded-plan one: **FIX-NOW** — `capture_node` marks
  `coder_escalated`; `route_after_capture` respects it (a real hand-raise reaches the supervisor).
- **Vacuous "real-looking" assertions slip the floor:** **ACCEPT** — the honest-conclude means a
  human confirms, so the label is a hint, not a claim; the floor stays best-effort.
- **Coder tampers the Proctor suite / source-change-parks / path-format / deletions:** **FALSE-POSITIVE**
  — the tamper baseline + the (now-removed but re-verified) subset logic held.

## Security implications

Strengthened vs the original cut: this ships **nothing** on the already-satisfied path — it only relabels
a park. Deny-by-default is fully intact (no gate reason is suppressed). Residual: the honest label may
over- or under-trigger (a green-pre-impl suite that misses the requirement still reads "appears already
satisfied") — but it is a *hint for a human*, never an unattended delivery, so it cannot false-complete.

## Operational implications

No migration; the durable status is unchanged (`incomplete` with the honest reason in autonomous, a
human park in guided). Opt-in by construction: the signal only exists when the tester (Proctor) is
enabled (`tester_enabled`, default OFF).

## Consequences

- **Good:** an already-done task self-terminates in one spine pass, correctly reasoned, far from any
  ceiling — the #43 target — and it can never false-complete.
- **Follow-up (#44 successor, ~~deferred~~ DELIVERED by ADR-0056 — `#51`, 2026-07-18; corrected 2026-08-18, `docs/audits/adr-corpus-review-2026-08-18.md`):** the supporting thrash-reducers — bound the Proctor's
  red-hunt, trip the breaker early on a degenerate/repeated plan, and benchmark-seed hygiene.
