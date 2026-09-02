# ADR-0073: Acceptance spec-lint at the decompose boundary (#54 slice 0)

- Status: accepted
- Date: 2026-07-22
- Owners: Mosaera core / api
- Related issue: #54 (the wrong-test thrash lever) — this is its cheapest, non-trust-boundary
  first slice; test-modify authority is the Proctor's, already BUILT + red-teamed in ADR-0058
  (which also rejected a separate steward role), and is not touched here.
- Related threat model: none — the trust surface is unchanged (see §Trust).
- Red-team: **not required** — no oracle/gate/policies/test-protection touch; lint output flows
  only through the already-validated deny-by-default changeset applier.

## Context

The #53 live backlog drive (`docs/demos/observed-outcomes.md`) measured the engine concluding
honestly 3/3 while the *specs* were defective 2/3: Quincy's decompose invented an exact return
tuple (`(1, ['too short (len < 8)'])`) that the Proctor pinned tamper-protected tests to — the
coder's more-correct behaviour could never satisfy it → 35 min / 1.3M tokens of thrash; and it
emitted a near-duplicate "add tests" item that parked `already satisfied`. Acceptance text flows
**verbatim** into the run task (`_launch.py`) and into the Proctor's authoring, so a bad
acceptance is an immovable wall the coder is (correctly) forbidden to move. #54's stated
confound — escalations recording $0 — was resolved separately (unpriced `claude-sonnet-5` +
missing tester ladder; config-fixed 2026-07-22).

## Decision

A deterministic **acceptance spec-lint** runs once at the end of `run_decompose`, gated by
`backlog_spec_lint` (default **ON**). Division of labor:

1. **Deterministic detect** — `mosaera_core/spec_lint.py` (pure, no I/O, no LLM; the
   `behavior_preservation.py`/`progress.py` pure-checker precedent). Three rules, precision over
   recall, `todo` items only:
   - **R1 exact-value over-specification**: literal tuple-with-list return shapes, backticked
     exact literals after returns/prints/outputs, exact-output code fences.
   - **R2 refactor-classifier collision**: the item's acceptance trips
     `preservation_matches()` (a new read-only accessor on `behavior_preservation.py` sharing
     `_PRESERVE_PATTERNS`, so it can never drift from `is_behavior_preserving`) — the phrase
     class that armed the ADR-0072 structural oracle against a feature task in #53.
   - **R3 near-duplicate items**: pairwise token-set Jaccard ≥ 0.5 over normalized
     title+acceptance (reuses `progress.normalize`).
2. **LLM disposition** — findings render (`curate_instruction`) into ONE bounded
   `curate_backlog` pass ("fix ONLY what genuinely needs fixing … propose nothing else"); the
   same proven seam the resilient-sweep recuration uses. One shot, no loop.
3. **Deterministic apply** — the existing deny-by-default `apply_backlog_changeset` validates
   the proposed ops wholesale; a rejection (or any failure) keeps the as-authored backlog.
   A lint bug can never break backlog generation.

Prevention side: one doctrine sentence in `_DECOMPOSE_SYSTEM` (acceptance states observable
behaviour; no invented exact strings/tuples/formats; no preservation phrasing on non-refactor
items; no item another item's acceptance already covers).

**Default ON** (owner decision): detection is free; the pass is one PM call only when findings
exist — against a defect class that provably costs a full run's budget. The bench cannot measure
it (decompose isn't in the bench path); validation is the live demo drive.

## Trust

Unchanged. The lint proposes nothing itself; every mutation goes through the same validated
changeset applier any curate call uses. `behavior_preservation.py` gains a read-only accessor
only (`is_behavior_preserving` behavior untouched — parity-tested). No gate, oracle, policies,
or test-protection edits.

## Consequences / limits

- Regex detection is precision-first: an unflagged bad acceptance still reaches the run (the
  honest-stop family remains the backstop); a false flag costs one sentence the curator may
  ignore.
- The re-curate pass uses the same (possibly weak) PM model — it may fix imperfectly; the
  one-shot bound caps the cost either way. Findings that remain are a log line only (audit
  events are run-scoped; a project-scoped trail is logged debt).
- Chat/curate-applied changesets are NOT linted (a human is already in that loop) — follow-up.
- Successors: the #54 wrong-test functions (the Proctor's coder-blind repair, ADR-0058 — not a
  new role) and the #76 Quincy disposition harness (ADR-0074/0075 — supersede the wrong engine
  test post-park, re-verify, ship) consume the same failure class downstream.

## Validation-drive follow-up (2026-07-22) — R4 + retry-on-empty

The slice-0 live drive surfaced two adjacent defect classes, both closed same-day:

- **R4 `no_behaviour`** (new lint rule): existence-only acceptance ("the file exists and can
  be imported without error") — a scaffolding item with nothing a test can independently
  assert can never earn oracle credit under the autonomous posture, so the sweep can only
  defer it (and recuration just spawns another untestable sibling — observed live). Fires
  only when EVERY sentence is existence-only (one behavioural sentence suppresses it —
  precision-first, same posture as R1–R3). Plus a `_DECOMPOSE_SYSTEM` doctrine sentence
  (no scaffolding-only items; fold scaffolding into the first item that uses it).
  Residual: recuration-created items bypass the lint (it runs at decompose only).
- **Retry-on-empty in `robust_invoke`** (`packages/agents/retry.py` — cross-module
  robustness note, recorded here because the failure poisons the same decompose boundary):
  local models intermittently return a fully EMPTY reply (measured: gpt-oss:20b on the
  second consecutive long call; prompt-independent by A/B), and only exceptions retried —
  decompose silently collapsed to its single-item fallback ("Implement the brief", empty
  acceptance: the worst possible spec, invisible unless inspected). Empty replies (no text
  AND no tool calls) now retry on the transient backoff schedule; a persistent empty is
  returned, never raised, so every caller's existing fallback still works.
