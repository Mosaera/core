# ADR-0072: Structural-spec oracle — verify a refactor met the requested SHAPE (#80)

- Status: accepted, **posture activation WITHDRAWN 2026-08-02** — the mechanism ships and is
  correct, but it is NOT in the autonomous posture and the knob is default OFF. The successor
  landed the same day (the relative measure replaced the unsound `max_body`) and the expiring risk
  acceptance is RETIRED; then the activation itself was withdrawn on a null n=25/arm A/B.
  **Read §Amendment 3 first — it supersedes the activation described in §Amendment 1.**
  (**red-team DONE — 3 rounds, 2 FIX-NOW fixed pre-merge, 1 ACCEPT**; see §Red-team of the successor)
- Date: 2026-07-21
- Owners: Mosaera core
- Related issue: #80 (the MCB-05 false_ship class) — a sibling of #74/ADR-0071 (comprehensive
  mutation), feeding #76 (the Quincy disposition harness).
- Related threat model: TM-0001 (the delivery-gate evidence surface — same boundary it feeds via
  `oracle_verified`).
- Red-team: **required** (it feeds `oracle_verified` at the delivery gate) — **DONE**, 3 rounds; see §Red-team of the successor.

> ## Amendment 3 (2026-08-02, later still) — the posture activation is WITHDRAWN
>
> **§Amendment 1 below says the posture was ACTIVATED and sets an expiry review for 2026-11-02.
> That activation was withdrawn the same day. There is no live accept and no pending review.**
> Recorded here 2026-08-18 by the doc-accuracy pass
> (`docs/audits/adr-corpus-review-2026-08-18.md`); until then the withdrawal existed only in code.
>
> The activation rested on an n=3 result (MCB-05 3/3 `false_ship` → 3/3 `honest_park`) that **did
> not replicate**. A frozen n=25/arm interleaved A/B (100 runs) showed no effect: MCB-05 ON 21/25
> vs OFF 23/25 `false_ship` (Fisher p=0.667), MCB-15 ON 25/25 vs OFF 24/25 (p=1.0), **pooled
> p=1.0**. The safety half DID hold — 0 false-parks across all 100 runs (95% upper bound ~3%),
> superseding the earlier 0-of-20-references bound.
>
> So the oracle is **safe and ineffective on the current model tier**: it would pay a gate
> dependency for a measured-zero benefit. What stays: the knob (default OFF), the pure
> `evaluate_structural_spec`, and the bench OFF-lever. What goes: membership in
> `apply_oracle_posture` — `oracle_structural_spec` appears nowhere in
> `packages/core/mosaera_core/config/_posture.py`.
>
> **Re-test condition:** once acceptance claims are first-class and the check has a real contract
> to score against. Full record: `docs/engineering-history/structural-oracle-ab-2026-08-02.md`;
> the standing note is at `config/_posture.py:101-111` and `config/_settings.py:361-364`.
>
> **This also reads on Amendment 2's efficacy tables below** — the n=3 figures there are the
> result this A/B refuted. Amendment 2's *soundness* argument (a ratio against the function's own
> pre-refactor body beats a fixed integer) is untouched and still stands.

> ## Amendment 2 (2026-08-02, later) — the accept is RETIRED; the successor landed
>
> **The expiring risk acceptance below is CLOSED, ahead of its 2026-11-02 review.** The unsound
> `max_body` constant is gone from the bare-"handful" path; the shape is now measured **relatively,
> against the function's own pre-refactor body** (the diff's old side, read from `HEAD`).
>
> **Why one ratio can do what no integer could.** Measured on the two refactor cases' known-correct
> references:
>
> | case | orchestrator statements | ratio | loops |
> |---|---|---|---|
> | MCB-05 `checkout_total` | 8 → **4** | 50% | 1 → **0** |
> | MCB-15 `parse_log_line` | 8 → **3** | 38% | 1 → **0** |
>
> ...against a delivered-but-wrong shape that keeps the work inline: **7 of 8 (88%)**. A single
> dimensionless ratio (`2/3`, deliberately loose — the error to avoid is a FALSE PARK) separates
> both references from that, where no absolute could separate MCB-05's ≤6 from MCB-15's ≤7. The
> constant is now **dimensionless and case-independent**, which is exactly the property whose
> absence made the old one unsound.
>
> **Plus a genuinely constant-free rule.** Both references go from one loop to zero: *"extract into
> helpers"* means the ITERATION moves out. An orchestrator that shrank but kept its loop kept the
> work it was asked to delegate — a failure no statement count can express. The two rules cover
> different shapes: the ratio catches "still too long", the loop rule catches "didn't actually
> extract".
>
> **Deny-by-default preserved.** No pre-refactor body — a greenfield task, a brand-new module, an
> unparseable original — means **no baseline, no claim**: the relative check is inert rather than
> judging against an invented number. An EXPLICIT `<= N statements` ask in a brief is still checked
> as stated; the brief named a real constraint, we are not guessing one.
>
> **Measured:** 0 false-parks across all 20 known-correct references; engagement still confined to
> the 2 refactor cases. `test_the_unsound_body_check_is_still_the_load_bearing_one` — written to
> fail the moment a sound replacement landed — **fired, and has been replaced** by
> `test_the_relative_measure_replaced_the_unsound_constant`, which asserts the same shape is caught
> *and* that the reason never cites a guessed constant.
>
> **Measured on both refactor cases (×3 per arm, `MOSAERA_BENCH_STRUCTURAL_SPEC_OFF` as the lever):**
>
> | | MCB-05 ON | MCB-15 ON | MCB-15 OFF |
> |---|---|---|---|
> | `false_ship` | **0/3** | **0/3** | **1/3** |
> | `clean_deliver` | 0/3 | 0/3 | 2/3 |
> | Governance (mean) | 100 | **83** | 67 |
> | overall (mean) | 94 | 91 | 90 |
>
> MCB-05 converts exactly as the unsound version did (3/3 `false_ship` → 3/3 `honest_park`), so the
> Gate 2 result is preserved with the constant removed. **And the oracle prevents a false ship on
> MCB-15 too** — a case the absolute check was never shown to help. Governance, the dimension that
> scores whether the gate made the RIGHT call, improves 67 → 83.
>
> **The cost, stated plainly: delivery on MCB-15 went 2/3 → 0/3, and one of the three ON parks
> scored Governance 50 — it refused code the hidden grader passes.** That is a false park. It is
> the SAFE direction (an honest park, never a bad ship) and it is what a stricter shape gate buys,
> but it is a real cost and not noise-free at n=3. The `2/3` ratio is deliberately the loose end of
> the defensible range for exactly this reason; if the false-park rate proves higher on a wider
> sweep, loosen it further or gate the loop rule rather than accept the delivery hit.
>
> ### Red-team of the successor — DONE (3 rounds, 2 FIX-NOW, 1 ACCEPT)
>
> Scoped to the successor (the relative measure), not the codebase.
>
> **R1 — nesting hides the body. FIX-NOW, fixed.** Wrapping the work in `if True:` made a
> 9-statement body read as ONE top-level statement: 11% of the original → passed. **ADR-0072's
> FIRST red-team already found this** ("trivially defeated by one level of nesting") against the
> absolute check; its disposition dropped that check, so no mitigation was written and the
> relative measure inherited the hole. Fixed by counting statements IN FULL (nested included),
> self-consistently on both sides: the dodge now reads 111% and is caught. Counting in full also
> gives correct refactors MORE headroom — the references fall to 25% / 23% of their originals,
> versus 50% / 38% top-level.
>
> **R2 — baseline evasion. ACCEPT (documented).** Relocating the target to a new module leaves no
> `HEAD` blob, so the check has no baseline and goes inert; a bad shape then ships. This is the
> deny-by-default contract, and the alternative — park whenever there is no baseline — would
> false-park every greenfield task, which is strictly worse. The evasion returns to the
> **pre-oracle baseline** and opens no NEW false-ship channel; it also requires deliberately
> moving the function, which is a visible, unusual change. Pinned by a test so the behaviour is a
> recorded decision rather than an accident.
>
> **R3 — false-park generator. FIX-NOW, fixed.** On a SMALL original the `<= 2/3` bound is
> *unsatisfiable*: an orchestrator delegating to N helpers needs at least N+1 statements, so a
> correct 3-statement orchestrator was parked whenever the original was ≤5 statements. Fixed with
> a floor **derived from the brief's own helper count** — not another guessed constant — which can
> only ever make the check more permissive. Verified it does not disarm the oracle: once the
> original is large enough for the ask to be satisfiable, bad shapes are still caught.
>
> **STOP rule: not triggered.** Three distinct defect classes (count evasion, baseline evasion,
> false park); none recurred. 0 false-parks across all 20 known-correct references after the fixes.
>
> The expiry, the review date and the ratchet tests below served their purpose and are retained as
> the record of how the accept was carried and closed.
>
> ## Amendment (2026-08-02) — posture ACTIVATED as a bounded, expiring accept
>
> **This is a risk acceptance, not a fix. It must not become permanent by default.**
>
> **Measured (MCB-05, 3 arms x 3 runs, controlled):**
>
> | Arm | `false_ship` | Outcome | Overall |
> |---|---|---|---|
> | both oracles OFF | **3/3** | `false_ship` | 74-77 |
> | comprehensive mutation (ADR-0071) | **3/3** | `false_ship` | 74-77 |
> | **structural spec (this ADR)** | **0/3** | `honest_park` x3, Governance 100 | **90-94** |
>
> MCB-05 is the Gate 2 blocker — **48/91 (52.7%)** of all recorded runs false-ship. This oracle
> converts it 3/3 with the overall score RISING, so it is not parking indiscriminately. Comprehensive
> mutation moved it 0/3, consistent with §Context: nothing to mutate, the behaviour is correct.
>
> **What is unsound, stated plainly.** The catch rests on `max_body`, the statement count this ADR's
> own red-team called *provably unsound* and whose disposition was **"DEFER the soft body-length
> check"** — a disposition **recorded but never implemented**. Verified 2026-08-02: MCB-05 and MCB-15
> use near-identical brief language and **both extract `max_body=6`**, yet the bench grades them <=6
> and <=7. No fixed integer satisfies both. A correctly-shaped but verbose refactor can be
> false-parked, and `test_the_unsound_body_check_is_still_the_load_bearing_one` pins that this — not
> the sound helper-count rule — is what actually converts MCB-05.
>
> **Why shipping it anyway is defensible.** The error direction is the safe one: the check is
> downgrade-only at the gate, so it can only ever turn a ship into an honest park, never manufacture
> a false ship. And the blast radius is measured, not assumed:
>
> - constraints are extracted on **2 of 22** bench cases (the two refactor briefs); the oracle is
>   inert everywhere else (deny-by-default `None`);
> - **0 of 20** known-correct `reference/` implementations are false-parked.
>
> Both bounds are pinned by tests (`test_structural_spec_blast_radius_is_bounded`,
> `test_structural_spec_never_false_parks_a_known_correct_reference`), so the residual **cannot widen
> silently** — a change that broadens the heuristic fails CI instead.
>
> **EXPIRY — review by 2026-11-02, or at the v1.0 release-readiness review, whichever is first.**
> At that review the accept must be either retired (successor landed), re-justified with fresh
> measurement, or withdrawn (`oracle_structural_spec=False` in `_posture.py`). Re-measure any time
> with `MOSAERA_BENCH_STRUCTURAL_SPEC_OFF=1`.
>
> ### Successor — a RELATIVE measure, no magic constant
>
> The root defect is trying to turn "a handful of statements" into a fixed integer read out of prose.
> That is not resolvable by better brief-extraction (the deterministic cousin of the ADR-0070
> LLM-judge dead end). The sound successor measures the orchestrator **against its own pre-refactor
> self**, using evidence the engine already holds — the diff's OLD side:
>
> - *"short orchestrator"* becomes **shorter than what it replaced** (a ratio, e.g. body <= ~40% of
>   the original, or <= helpers + k) rather than <= 6;
> - optionally, a **delegation fraction** — how much of the original body now sits behind helpers.
>
> Both are brief-independent, deterministic, model-agnostic, and grounded in durable evidence rather
> than a number scraped from English. When that lands,
> `test_the_unsound_body_check_is_still_the_load_bearing_one` should begin FAILING — that is the
> designed signal that this accept can be retired.


## Context

The delivery oracle credits a green run when an independent suite vouches, and the refactor oracle
(behaviour-preservation golden-master) additionally proves a refactor changed no output. But a
refactor task can carry a **structural** acceptance criterion — *"refactor `checkout_total` into a
short orchestrator that delegates to ≥ 3 helpers"* — that has **no behavioural signature**. The
delivered code can be perfectly behaviour-preserving (the refactor oracle vouches, the suite is
green) yet miss the requested *shape*.

Measured, deterministically, on MCB-05 (15/15 runs, both surviving workspaces): the engine ships a
behaviour-preserving refactor that delegates to 3–4 helpers but leaves a **7–8-statement
orchestrator** (the `if member:` branch inline), failing the one structural check
(`len(fn.body) ≤ 6`) → impl 88 = 7/8 → **false_ship**. This is a **different class** from the
executed-but-unasserted false_ship #74 targets: there is nothing to mutate, the behaviour is correct.

## Decision — a deterministic structural check for refactor tasks (Layer-1 floor)

Add `oracle_structural_spec` (default OFF; posture HELD). When on, on a green run:

1. **Extract** the structural asks from the task brief (`structural_spec.extract_structural_constraints`):
   explicit numbers deterministically (`delegates to ≥ N helpers`, `no more than N statements`), a soft
   `short orchestrator` / `a handful of statements` → a body bound `_HANDFUL` (= 6, `len(fn.body)` — the
   same AST idiom a structural test uses). No structural intent → `None` (no effect).
2. **Check** the delivered target function's AST against the constraints
   (`check_structural_compliance`): body length ≤ bound, delegation to ≥ N module-level helpers.
3. **Downgrade, deny-by-default:** a *stated-but-unmet* constraint returns `False` →
   `structural_spec_ok=False` → `oracle_verified` is downgraded in `gate_node` (ANDed exactly like
   `mutation_ok`) → the run **parks honestly** with the named gap. Absent, unverifiable, or a parse
   fault → `None` → no effect (never downgrades, never vouches).

This is the **Layer-1 floor** of the #80 two-layer plan: it can only ever *downgrade* — a `False`
turns a would-be ship into a park, so it can never manufacture a false_ship. It moves MCB-05
false_ship → **honest_park**. The Phase-2 iterate that converts that park → a verified deliver
(feed the coder the named gap, retry, re-run the **same** gate) is a separate change; the gate stays
the sole ship-authority so the loop can only ever produce a gate-verified ship or an honest park.

- **Deterministic, judge-independent, $0.** Pure AST + regex extraction. No LLM, no sandbox. New
  `structural_spec.py`; wired in `nodes_impl` (compute, memoized by tree hash) → `nodes_review`
  (downgrade). No `packages/policies`/`gate.py` edit — it feeds the existing `oracle_verified` AND.

## Rejected

- **LLM spec-interpretation of the structural bar.** The extraction is narrow (structural
  constraints, not correctness judgment) and deterministic; the #66 measurement killed LLM-judge
  oracles, so the check stays code.
- **A generic "materially decomposed" heuristic only.** It would pass MCB-05 (7 stmts is a big drop
  from the seed) and miss the class. The check reads the *stated* asks so it catches a real shortfall.
- **Activating it in the posture now.** Held — a stricter gate parks more (over-park risk below);
  measured first, mirroring #60/#74.

## Consequences

- Knob `oracle_structural_spec` (default OFF; posture HELD). New RunState `structural_spec_ok:
  bool | None`. No migration.
- **What it fixes:** the structural-spec false_ship (a correct refactor that misses the requested
  shape) — false_ship → honest_park.
- **Honest limits / the measured dial:** the soft `_HANDFUL` bound risks **over-parking** a genuinely
  good refactor (trading false_ship for a *false-park* — still honest, but costs delivery). This is
  the safe direction (never a false ship) but real, and is exactly why activation is HELD until the
  A/B quantifies over-park across the refactor cases + the clean suite. Requires a **named** target
  function; an un-named or multi-function refactor → `None` (deny-by-default, no downgrade).

## Measurement + red-team (DONE 2026-07-21)

**A/B (target):** MCB-05 x5 OFF=false_ship 5/5 vs ON=honest_park 5/5 — a clean, deterministic flip
(the outcome it was built for). **A/B (over-park):** MCB-15 x5 — ON parked a correct impl=100 delivery
(clean_deliver 4→3), a **confirmed over-park**; the no-ask controls (MCB-13/14) were a true no-op.

**Red-team (3 lenses, all reproduced against the live module):**
- *Crash/hang:* soundness SOLID — deny-by-default holds at the wiring, no spurious ship possible, no
  ReDoS. Two module-contract breaks **FIXED**: `except (SyntaxError, ValueError, RecursionError)` around
  `ast.parse`; a digit-cap in `_num` (a >4300-digit token no longer raises). Regression-tested.
- *False-park:* the soft `len(fn.body)` bound is **provably unsound** — MCB-05 grades ≤6, MCB-15 grades
  ≤7 for IDENTICAL "a handful" language, so no fixed `_HANDFUL` satisfies both; plus over-extraction
  (`_MAX_BODY` harvests "N lines" from non-body clauses; `_SOFT_BODY` fires on descriptive prose).
- *False-vouch:* the body check is **trivially defeated by one level of nesting** (`if cart: …` →
  `len(fn.body)=3`), class-method targets are silently skipped, and a same-named decoy in an
  earlier-ordered changed file masks the real miss (trust-boundary gaming).

**Disposition (STOP-rule tripped — 3 lenses, one class):** the `len(fn.body)` "short orchestrator" check
is unsound in BOTH directions. **DEFER the soft body-length check** (drop `_SOFT_BODY`/`_HANDFUL`);
**keep only a hardened helper-count check** (explicit `min_helpers`, recurse into `ClassDef`, count
`self.x()` delegation, worst-verdict-across-files). **MCB-05 → DEFER (residual):** its only failing
criterion is the fuzzy body-length whose bar is indistinguishable from MCB-15's from the brief — the
deterministic cousin of #66's LLM-judge dead-end; not resolvable by brief-extraction. **Bench-consistency
note:** MCB-05 (≤6) vs MCB-15 (≤7) grade identical asks differently — flag for review.

**OWNER DECISION (2026-07-21):** for the reliability-first goal (over-parking is *free* for
clean-conclusion — a park is clean), **keep #80 as-built** (do NOT reduce to the sound helper-count-only
version) and run it **ON for reliability-mode via the knob** — it converts MCB-05 false_ship →
honest_park (~92%→~97% on the suite); the over-park costs delivery, not conclusion. The default stays
**OFF** and it is **NOT posture-activated** (delivery-mode runs are unaffected). The soundness debt above
(soft-body: gameable + over-parks) is real but **deferred to Layer-2 (#76) / oracle-precision at
maturity**. The residual-thrash arcs #81/#82 are **parked**.

## Live-drive finding (#53 backlog sweep, 2026-07-21) — trigger-seam false positive, FIX-NOW

The #53 greenfield backlog drive (`docs/demos/observed-outcomes.md`) surfaced a false positive in
the oracle's *trigger* seam, `is_behavior_preserving` (`behavior_preservation.py`, ADR-0066): the
pattern `(same|identical)\s+(observable\s+)?(behaviou?r|output|result)s?` matched Quincy's natural
feature-acceptance phrase *"piping via stdin produces the **same output** as the command line"* — an
**input-path consistency** clause, not a preservation-vs-baseline promise. The misfire classified a
"create CLI entry point" feature task as a refactor, authored `test_decomposition_happened` against
it (an impossible bar for a feature), and honest-parked a working implementation. Fail direction was
safe (over-park, deny-by-default held; no false ship possible through this seam).

**Fix (FIX-NOW — no planned successor kills this class):** the bare pattern now carries a
`(?!\s+as\b)` negative lookahead, and a companion pattern re-admits only **baseline referents**
("same output as *before* / *it did* / *the original|existing|current|old|previous|unrefactored*").
Regression cases cover both directions, including the literal #53 phrase. The successor spec-lint at
Quincy's decompose boundary (#54) reduces exposure but does not remove this class — acceptance text
from any source still reaches the classifier — hence fix-now, not defer.

**Red-team scope card** (oracle domain → red-team-required): target = this pattern change only;
budget 1 round — (a) craft natural feature-acceptance phrases that still trip the classifier,
(b) craft refactor briefs the tightened patterns now miss. Marker: **red-team: done** (1 round,
2026-07-22, executed against the live module; 34 phrases + 100KB pathology probes):

- **FIX-NOW (fixed + re-verified):** the optional plural backtracked past the lookahead —
  `s?(?!\s+as\b)` let *"same resultS as /v1/users"* (the #53 shape, pluralized) still fire. The
  guard now covers the plural (`(?!s?\s+as\b)s?`); regression cases added. Riding along (the plural
  fix would otherwise unmask two false negatives): baseline referents widened with
  `prior|legacy|pre[- ]?refactor\w*`.
- **DEFER-TO-#54:** bare-pattern false positives on non-comparative consistency/idempotency/
  determinism clauses ("running the command twice must produce the same output", "identical results
  across runs") — pre-existing class this fix never claimed; the decompose-boundary spec-lint (#54)
  flags classifier collisions on non-refactor items.
- **ACCEPT (deny-by-default, soft degradation):** comparative baselines outside the referent list
  ("same output as it currently does", "as today", "as main") stay unmatched — a missed refactor
  loses guidance injection only; no ship-path effect.
- **Pathology: none** — adversarial 100KB inputs complete in single-digit ms.

**Class closed at the ARMING seam too (2026-07-23).** A second live instance (bench MCB-11, the
2026-07-22 deep dive): the scaffold's arming call scanned `task + plan + design`, so even when the
TRUSTED brief did not match any pattern (MCB-11's symbol-scoped "keep the existing `+`/`-` behaviour
unchanged" — the backticked operators block the match), the PM's lossy paraphrase ("keep the existing
behaviour unchanged") DID match and armed the scaffold on a feature task — planting the protected
`test_decomposition_happened` bar and double-trapping a hidden-grader-correct run. The smoking gun:
the same run's task-only meta flag (`behavior_preservation_detected: false`) disagreed with the
arming. Fix: `scaffold_if_refactor` now arms from `is_behavior_preserving(task)` ONLY — the
paraphrase is never consulted (the detector's own ADR-0066 contract, "an EXPLICIT clause in the
trusted spec", now enforced at the seam). Regression tests pin both directions (paraphrase never
arms; a real refactor brief still arms task-only; MCB-11's brief is a task-only negative case).
