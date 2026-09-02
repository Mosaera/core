# ADR-0124: A trivial item should not pay for ceremony it cannot use

**Status: PROPOSED — WINNER MEASURED (Approach B); awaiting the owner's approval to stage.** Both are built,
tested and benchmarked on branches (`exp/lane-classifier`, `exp/engine-oracle`), both default OFF,
neither is on staging. This ADR exists to make the choice, not to record one already made.

## Context

Every run executes the full spine regardless of size. Measured on the trivial tier: **44.3 coder
calls, 68% over-park**, and 16 node visits against moderate's 12. On LedgerCLI, "Switch list output
to pipe-delimited" took 8 attempts for 0 deliveries; "Remove unused imports" 3 attempts, 120
minutes, 0 deliveries; a *feature* slice took 7 minutes.

Two things were established before designing anything, and both narrowed the solution space:

1. **The spine is not the cost.** Trivial runs visit four more nodes than moderate ones; the Coder
   is 73.2% of trivial spend. #118's original framing — collapse plan+design to save round trips —
   attacks ~2.3% of tokens and, by cutting the Coder's budget, would raise the over-park its own
   acceptance criterion forbids.
2. **The Proctor is the ceremony that actually hurts.** For an item with no behavioural surface the
   Proctor *cannot red-verify by construction*, so it authors either a vacuous test or a test about
   something else. That is the direct cause of the protected-test deadlock: **19 of 92 LedgerCLI
   runs, 26.9% of all non-deliveries** (#127).

## The constraint that shaped both designs

ADR-0062 built a deterministic auto-loosen, red-teamed it, and **reverted it wholesale**, with the
standing rule *"do not rebuild it in any disguise"*. The boundary is directional: the engine may not
mechanically **widen** the acceptance class. Detection, naming targets, judgement-based repair and
veto-only checks all survived; the one mechanism that could make *more* ship did not.

Naively skipping `author_tests` for a trivial item lands on the wrong side of that line — removing
the oracle is a widening move, whatever the motive. Both approaches below are built so that they do
not.

The sanctioned precedent is `scaffold_if_refactor` (ADR-0066/0072): where a model-authored oracle
does not fit, **the engine authors a deterministic one**, returning `[]` deny-by-default when it
cannot.

## Shared: a deterministic classifier

`mosaera_core/task_scale.py`. Certifies an item as non-behavioural and scoped to one existing file.
No model call. Deny-by-default: an unrecognised shape, a behaviour verb outside the matched phrase,
a plan naming no real repo file, or more than one file all fall back to the full spine.

**Arming reads the trusted task only.** `scaffold_if_refactor` records a live failure (MCB-11) where
a detector armed on the PM's lossy paraphrase planted an unmeetable bar on a feature task. The plan
is consulted only for a scope that is **re-measured after the fact** — `diff_within_scope` and
`added_lines_within_budget` in `capture_node`. The classifier predicts; the engine measures; a wrong
prediction costs the run its lane, never its correctness.

## Option A — the reduced lane (`exp/lane-classifier`)

`plan → implement`, skipping design and the authoring pass. The oracle comes from the gate's
**existing `standing_suite` leg**, which already requires baselined tests that assert something real
*and reference the changed module*. No standing suite that vouches ⇒ `oracle_verified` False ⇒
`oracle_unverified` ⇒ the run parks, exactly as today.

## Option B — the engine-authored oracle (`exp/engine-oracle`)

Every node still runs. `scaffold_if_inert` writes the acceptance test itself — the module still
imports, and its public surface is byte-identical to the pre-change snapshot (taken by AST, never by
import, because authoring runs outside the sandbox). The Proctor's model call is replaced, not
skipped, so everything reading `authored_tests` keeps working: coder file protection, the tamper
guard, the amendment path, mutation targeting, critic input.

B **adds** an assertion that did not exist. It can only ever refuse more — directionally opposite to
ADR-0062's reverted MR.

## Measured

Real graph, real nodes, real routing, fake models (`test_lane_ceremony_bench.py`):

| stage | baseline | A | B |
|---|---|---|---|
| plan | 1 | 1 | 1 |
| design | 1 | **0** | 1 |
| author_tests | 1 | **0** | **0** |

A behavioural item (`"Add a --quiet flag"`) is still designed on both branches with the knobs ON.

`packages/policies` is **byte-identical on both branches**, pinned by a test that inspects the gate's
source for lane tokens. A lane that cannot reach the gate with a new verdict cannot have widened the
acceptance class — provable rather than arguable.

## Red-team

**A-1 · FIX-NOW-if-A-is-chosen — the false trivial.** "Fix the comment handling" matches `comment`,
strips to "Fix the handling", trips no behaviour verb, and is certified. If the coder's change is
one file and under the line cap it ships on `standing_suite` alone — a *behavioural* change verified
only by "the existing suite still passes". The size cap bounds the blast radius and the standing
suite must reference the changed module, but the acceptance class for that run is genuinely weaker
than baseline. **B is immune**: its oracle pins the public surface, so a behavioural change that
alters it fails.

**A-2 · ACCEPT (documented).** The lane is decided once, on the first plan. A `supervise` re-scope
returns to `plan` with new feedback but keeps the lane. The task text does not change on that path,
so the certification still describes the item — but it is an assumption, not an enforcement.

**B-1 · FIX-NOW-if-B-is-chosen — the module path may not import.** `src/report.py` becomes
`src.report`, which only imports if the repo is laid out that way. In a src-layout repo the authored
oracle fails for reasons unrelated to the change, and **every reduced-lane run parks**. Authoring
cannot verify importability without executing code, which it must not do. Needs a layout probe
(`__init__.py` / `pyproject` packages) before authoring, or the scaffold must decline.

**B-2 · FALSE-POSITIVE.** Snapshotting an unparseable file would freeze the breakage into the bar —
already declined, with a test.

**Not triggered:** the STOP rule. A-1 and B-1 are different defect classes.

## Decision

**Deferred to the owner.** The honest summary: **A is cheaper, B is safer.** A removes two model
stages and leans on an oracle that may not exist for a given repo; B removes one and manufactures an
oracle that directly checks the claim the item is making. A-1 has no clean fix inside A's design —
the classifier is heuristic on the accept side by construction. B-1 is a bounded engineering problem
with a known shape.

## Consequences

Whichever is chosen: it ships default OFF and unmeasured, the full suite runs before staging, and
the chosen branch carries a `red-team: pending` marker until its FIX-NOW is closed. The other branch
should be deleted rather than left as a second half-built lane.

Neither approach touches the delivery gate, the tamper guard, or `packages/policies`.


## A/B RESULTS — measured 2026-08-29 (n=3 per cell)

**First, why not the full MCB suite.** Measured before booking any GPU: **0 of the original 26 cases
arm the classifier**, even under a generous upper bound that pretends every path a brief mentions
exists. A full-suite A/B would have been null by construction — both arms byte-identical — at ~156
runs and ~8 GPU-hours for two identical numbers. MCB's "trivial" tier means *small feature*, not
*no behaviour change*; the corpus has never contained this shape. Three cases were authored to
close that gap (MCB-30 comment, MCB-31 docstring, MCB-32 version bump).

`MCB-31` is a deliberate control the classifier **declines** — its brief quotes the old docstring
and the quoted word is a behaviour verb. Deny-by-default fires and the lane changes nothing. The
brief was not reworded to flatter the tool.

### Approach A — measured, and the result is split

| | MCB-30 (comment) | MCB-32 (version bump) |
|---|---|---|
| baseline calls / tokens | 47 / 294k | 39 / 211k |
| **A** calls / tokens | **34 / 163k** | **27 / 64k** |
| baseline Fidelity | 33 | 67 |
| **A** Fidelity | **67** | **0** |

On MCB-30 A is unambiguously better: **28% fewer calls, 44% fewer tokens, and delivery doubled.**

On MCB-32 A is **3× cheaper and delivers nothing.** All three runs: `oracle_unverified`,
`over_park: True`, and — the damning part — **`grader_passed: True`**. Correct work, refused.

The cause is one leg: `standing_suite` read **True** on MCB-30 and **False** on MCB-32, on two cases
whose seeds differ by a single constant. A's entire oracle rests on that leg, and it is not stable
across changes that look equivalent. This is red-team finding **A-1 manifesting as a false PARK
rather than the false TRIVIAL that was predicted** — the prediction named the wrong direction, and
only the A/B found the real one.

### Approach B — NOT COMPARABLE; the arm is invalid

Fidelity 0 on both cases, but the diagnosis is different and disqualifies the run rather than the
design: `verified: True` (the engine-authored oracle DID vouch via `standing_suite`), while the gate
recorded **`validation_not_attempted`, `reviewer_unknown`, `security_not_attempted`**. Validation
never executed. That is a defect in how the scaffold was wired into `author_tests_node`, not
evidence about whether an engine-authored oracle works.

**B's numbers must not be read as a comparison.** Its idea is untested. Reporting them as a loss for
B would be the "green by vacancy" error one level up — treating a broken harness as a result.

### Honest state

- **A is measured** and shows a real, split trade: large wins where `standing_suite` vouches, total
  over-park where it does not.
- **B is unmeasured** pending a wiring fix.
- Neither is ready for staging. A's dependency on `standing_suite` is now a measured fragility, not
  a hypothetical.
- n=3 per cell on 2 cases. Enough to see a 33→67 and a 67→0, nowhere near enough to bound a rate.


## FINAL RESULT — 2026-08-29. Winner: **Approach B**.

Re-measured after two defects found *by* the A/B were fixed. n=3 per cell, 3 runs per case per arm.

### The two clean cases

| | baseline | A (reduced lane) | **B (engine oracle)** |
|---|---|---|---|
| **MCB-30** comment | 47 calls · 294k · Fid **33** | 24 · 53k · Fid 100 | **19 · 50k · Fid 100** |
| **MCB-33** docstring | 33 calls · 108k · Fid 100 | 29 · 79k · Fid 100 | **19 · 50k · Fid 100** |

Both approaches deliver where baseline over-parks. **B is cheaper on both and identical on both** —
19 calls / 50k tokens regardless of case — while A varies (24–29 calls, 53–79k). Against baseline,
B is **−60% calls and −83% tokens on MCB-30**, with Capability 100/100 and delivery 33 → 100.

### The control behaves

MCB-31, which the classifier **declines**, runs full-spine numbers with the knobs ON on both
branches (A: 41 calls/203k; B: 35/193k) — indistinguishable from baseline. A lane that quietly
cheapened real work is the failure mode both designs existed to avoid, and neither does.

### MCB-32 is confounded, and the confounder is a PRE-EXISTING ENGINE DEFECT

Both approaches score Fidelity 0 on the version bump, and **neither approach causes it**.

`change_is_covered` (`coveragemap.py:130-155`, via `standing_suite_is_independent_oracle`
`oraclecheck.py:465-471`) requires a changed line to have executed under a **test-function**
dynamic context. `__version__ = "1.4.0"` is executable but runs at **import** time, so it can never
be covered by any test. MCB-30's comment escapes only by accident — a comment produces no
executable line, so the intersection is empty and the check passes trivially.

The gate therefore **credits a change it provably cannot verify (a comment) and refuses one the
standing suite genuinely does verify (a version bump)**. It affects every module-level constant,
`__all__`, dataclass default, decorator and import in any repo — reviewer APPROVE, critic 3/3
SUPPORTED, grader 2/2 passed, and the run still parks.

**Filed as its own defect. It is independent of #118 and should not gate this decision.**

### Two defects the A/B found in the candidates themselves

1. **The scope check counted the engine's own oracle against the coder.** B authors
   `tests/test_inert_<module>.py`; `diff_within_scope` read it as a change outside the certified
   scope, so every B run parked before reaching `test`. Fixed — the certified scope bounds the
   CODER's change; `authored_tests`/`proctor_edits` are excluded, and the line budget counts only
   the certified files' hunks. **B's entire first arm was invalid because of this**, and reporting
   it as a loss would have been green-by-vacancy one level up.
2. **A new knob read unconditionally crashed 11 tests** that build partial fake settings. Now
   `getattr(..., False)` — deny-by-default, so a missing knob means FULL SPINE, never a cheaper lane.

### Why B wins on architecture as well as numbers

- **A's oracle is borrowed; B's is manufactured.** A depends on the `standing_suite` leg vouching.
  That leg proved unstable across two cases differing by one line — the very defect above. B does
  not depend on it.
- **A-1 (the false trivial) is real and unfixable inside A.** "Fix the comment handling" certifies,
  and A would ship it verified only by "the existing suite still passes". B is immune: its oracle
  pins the public surface, so a behavioural change that alters it fails.
- **B keeps every node**, so coder file protection, the tamper guard, the amendment path (#127),
  mutation targeting and critic input all keep working unchanged. A skips two nodes and must argue
  each of those is unaffected.
- **B only ever ADDS an assertion** — directionally opposite to ADR-0062's reverted widening.

### Honest limits

- Two clean cases, n=3. Enough to see 33 → 100 and a consistent 19/50k; nowhere near a bounded rate.
- B-1 from the red-team is **still open**: `src/report.py` → `src.report` assumes a flat layout. The
  bench cases are flat, so this A/B did not exercise it. A src-layout repo would park every lane
  run. **This is B's FIX-NOW before staging.**
- MCB-32 remains unresolved for both, pending the coverage defect.
- The full suite passes on B (3768 passed, 135 skipped, 0 failed) with all four gates green.
