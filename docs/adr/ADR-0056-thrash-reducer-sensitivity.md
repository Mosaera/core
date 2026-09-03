# ADR-0056: Thrash reducer + a model-strength sensitivity dial (#51, run-reliability arc #43)

- Status: accepted
- Date: 2026-07-18
- Owners: Mosaera core
- Related issue: #51 (thrash reducer, the #44-successor) — arc #43; sibling #52 (oracle) blocked-by this
- Related threat model: — (graph routing + budgets + an agent bound + a bench-measurement fix; no
  trust-surface change — the gate/oracle/policy allowlist is untouched)

## Context

The #43 arc wants runs to reach a clean terminal state **without looping or thrashing toward the
iteration/escalation/recursion caps** — "self-stop before hitting any ceilings." Two live findings and one
measurement gap motivated this:

1. **A degenerate plan thrashes late.** When the planner produces no grounded plan (`plan_is_fallback`),
   the run today burns design+implement, then two `plan → supervise → re-scope → plan` cycles, and only at
   `escalations > max_escalations` does `supervise` set `stalled` → **thrash_park** — far too late and
   wrong-reasoned (ADR-0052 saw the 138-call/1.2M-token version of this).
2. **The Proctor's red-hunt is unbounded.** On an already-satisfied task the tester writes ~a dozen test
   files chasing a red it can never obtain, bounded only at the 15 model-call ceiling — pure waste.
3. **The scoreboard's `iteration_limit` trigger is dead in the autonomous bench.** The gate's
   `iteration_limit` reason is appended only inside a gate visit that then *parks* and is never resumed, so
   it never commits to `final`; a reviewer-revise loop that rode to the cap mis-buckets as `honest_park`.

Owner steer: keep **honest+clean conclusions AND a high delivery rate**, and **scale that balance to model
strength** — a strong model gets more rope (tries harder → delivers more), a weak model self-stops early
(parks honestly, cheaply). Delivery is mostly the model's job; the engine's job is to spend the right
amount of effort for the model it's given.

## Decision

Five changes, all deterministic and outside the trust boundary.

### 1. A model-strength **sensitivity dial** (the governing lever)
A user-declared knob `reliability_sensitivity` (dropdown `cautious | balanced | persistent`, default
`balanced`). Model strength is not stored anywhere (a role is just `(provider, model)`), so it is
*declared*, not inferred. `apply_reliability_sensitivity(settings)` (`graph/build.py`) scales **every**
self-stop budget at once via `dataclasses.replace` at the top of `build_graph` (mirroring
`bench/escalation.py::escalate_role`) — the one seam every budget derives from (`max_iterations`,
`max_escalations` via RunContext; `stall_limit` read live; the tester step-limit baked into the agent):

| budget | cautious | balanced (default) | persistent |
|---|---|---|---|
| `max_iterations` | `min(cfg,2)` | `cfg` (3) | `min(ceiling, max(cfg,6))` |
| `max_escalations` | 0 | `cfg` (1) | `max(cfg,2)` |
| `stall_limit` | `min(cfg,2)` | `cfg` (3) | `max(cfg,4)` |
| `tester_step_limit` | `min(cfg,8)` | `cfg` (15) | `max(cfg,20)` |
| `plan_stall_limit` | 1 | 2 | 3 |

`balanced` is **identity** (returns the same object — provable zero regression). Every target is a
`min`/`max` floor/ceiling (not a relative step), so the transform is **idempotent** — it is applied both in
`build_graph` and in `recursion_limit_for` (which must size the LangGraph limit off the *scaled*
`max_escalations`, or `persistent` overflows it into a `GraphRecursionError` instead of a park). All scaling
stays within the hard `max_iterations_ceiling` (`min(configured, ceiling)`), so a future posture (ADR-0046)
composes on top.

### 2. A plan-level no-progress breaker → **honest EARLY park**
`plan_node` fingerprints each plan under a new `"plan"` stall-kind: a fallback plan (counts at its first
occurrence) or one identical to the last is no-progress. After `plan_stall_limit` such attempts it sets a
new **declared** state key `plan_unworkable_reason` and a new `route_after_plan` sends it **straight to the
gate, before design/implement** — skipping the coder cycle and the `supervise` give-up. Because `plan_node`
never sets `stalled`, the run lands in **`honest_park`** (clean), carrying an accurate reason
("couldn't form a workable plan … after N attempts — needs clarification") surfaced in `_termination_reason`
+ the report. A genuine coder hand-raise still reaches `supervise` (it's `coder_escalated`, detected
post-implement — the ADR-0052 override in `route_after_capture` is untouched). `route_after_gate` also
finalizes (never re-plans) when `plan_unworkable_reason` is set, for the resolved/guided drive.

This is the honest bucketing, not metric-gaming: a planner that recognizes it can't form a workable plan and
stops *promptly* with an accurate reason is the textbook `honest_park` ("stopped promptly on an accurate
reason"), the opposite of grinding to the breaker. `balanced`'s `plan_stall_limit=2` intercepts the
supervise give-up (which fires at plan attempt 2 when `max_escalations=1`).

### 3. Bound the Proctor red-hunt
A `tester_file_cap` (default 10) wires the stock `ToolCallLimitMiddleware(tool_name="write_file",
exit_behavior="continue")` into `build_tester_agent` — it blocks further test-file writes past the cap so
the loop winds down. `"continue"` not `"end"` (the latter raises on a parallel/batched tool call). Bounds
cost, not correctness; a legit acceptance suite is 1–4 files.

### 4. Classifier measurement fix
`classify_outcome` gains a `max_iterations` kwarg and buckets a park at `final["iteration"] >= max_iterations`
as `thrash_park` (the committed `iteration` counter is reliable even when the gate reason isn't). Bench-only
(`bench/cli.py` threads the effective cap); no gate/policy touch.

### 5. Bench-seed disk teardown (minor)
`run_case` drops the per-run seed repo (`shutil.rmtree`) after the run — it's consumed only by the clone +
report metadata; the grader/scorecard read the workspace. Left unbounded, `home/bench/seed/*` accumulated a
copy per run.

## Options considered

- **Scale every budget at one `Settings`-derivation seam (chosen)** vs. sprinkling `* sensitivity` at each
  of ~8 consumption sites. The seam localizes the change, keeps it out of the per-node hot paths, and reuses
  the `escalate_role` precedent. It also composes with a future posture clamp.
- **Auto-derive the sensitivity default from the coder's provider** (local→cautious, cloud→persistent via
  `provider_is_local`). Rejected for v1: the same knob value would produce different budgets depending on an
  unrelated BYOM setting (surprising, hard to test deterministically), and local-vs-cloud is a weak strength
  proxy. Kept a literal `balanced` default; a provider-aware default is a clean follow-up.
- **Trip the existing `stalled` breaker for a degenerate plan** (thrash_park, just earlier) vs. routing to an
  honest early park (chosen). The plan-breaker is a *prompt* stop on a definitive "can't plan," not a grind
  to the breaker — `honest_park` is the truthful bucket, and it converts the old late thrash into a clean
  conclusion where it is legitimately clean.
- **A red-aware Proctor early-stop** (run the suite mid-authoring, stop once green) vs. a deterministic
  file-count cap (chosen). The cap needs no sandbox runs mid-authoring and bounds the actual waste.

## Security implications

None. No edit to `packages/policies`, the gate, the oracle, or auth. The sensitivity dial only *tightens or
loosens self-stop budgets within the existing hard ceiling* — deny-by-default is intact (a weak/unknown
sensitivity self-stops *earlier*, never ships more). The plan-breaker ships nothing (it parks). The classifier
fix is pure measurement. Repo content still never widens the trust surface.

## Operational implications

`reliability_sensitivity`, `plan_stall_limit`, and `tester_file_cap` are new `GENERAL_KNOBS` — the Settings
page ~~renders the sensitivity dropdown automatically (no UI code)~~ — **corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`): it does NOT. `apps/web/src/components/settings/KnobForm.tsx` renders hand-declared `FieldSpec`/`KnobGroup` lists and `apps/web/src` contains zero occurrences of "sensitivity", so the knob is settable by env var only and surfacing it is open UI work (roadmap debt `#77`). Also `MOSAERA_TESTER_FILE_CAP` is absent from `.env.example`, unlike the other two; env vars `MOSAERA_RELIABILITY_SENSITIVITY`
/ `MOSAERA_PLAN_STALL_LIMIT` / `MOSAERA_TESTER_FILE_CAP` documented in `.env.example`. No migration. Default
`balanced` = today's budgets, so existing deployments are unchanged until an operator opts in.

**Honest caveat:** the sensitivity's `max_iterations` scaling is a no-op in the *bench* (the harness passes
an explicit per-case `max_iterations`, which `build_graph` prefers over `settings.max_iterations`); the
escalation/stall/tester/plan_stall scaling do apply. The iteration-axis rope manifests on real API runs.

## Consequences

- **Good:** a degenerate/repeated plan self-stops early + honestly (`thrash_park` → `honest_park`, saving a
  coder cycle + a supervise round); the Proctor stops its runaway; the scoreboard now catches ride-to-cap
  thrash; and operators tune the thrash↔delivery trade-off to their model with one dial.
- **Neutral:** `balanced` is not *literally* zero-change — the always-on plan-breaker converts the
  degenerate-plan terminal at every level (delivery rate unchanged; those runs never delivered). It only
  fires on a fallback/identical plan, never a healthy one.
- **Follow-up:** a provider-aware sensitivity default; re-baseline `mosaera-bench --all --compare` (repeat=3)
  to confirm the default rate holds and the plan-thrash cases convert. #52 (the oracle gap) is next and is
  blocked-by this (a Proctor-hard-gate mechanism there depends on this red-hunt bound).
