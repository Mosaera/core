# Brief-checkability analysis — every MCB claim, classified

**Date:** 2026-08-02 · **No ADR** (analysis; design input for the claim-contract ADR drafts).
Method: every material claim in all 24 MCB briefs annotated by hand — class, whether a
deterministic oracle *kind* exists for it, and whether the engine *binds* one today.

**Classes:** EB explicit-behavioral · ES explicit-structural · EN explicit-non-functional ·
RD repository-derived · AM ambiguous · UC uncheckable-without-clarification.

**Oracle kinds that exist in the engine today:** acceptance tests (Proctor/pytest/vitest/SQL
assertions, counted per #81) · validation pipeline (two-phase install→test) · **tamper guard**
(`tests_tampered` — "fix the implementation, not the tests" is already deterministically enforced)
· structural AST check (`evaluate_structural_spec` — engages only "short orchestrator + ≥N
helpers" phrasing) · static-site/config well-formedness parse · `spec_lint` (backlog-time).

## Per-case verdicts

| Case | Kind | Material claims (class) | Covered today | Verdict |
|---|---|---|---|---|
| MCB-01 | python-cli | commands/persistence/ids/error-exits (EB) · own tests (EN) · "dependency-free where reasonable" (AM) | EB+EN yes | CHECKABLE |
| MCB-02 | static-site | files exist+linked, nav/anchor/id pairing, h1/sections/footer (ES/EB) · "real content", "semantic", "clean CSS" (AM/UC) | parse-level only | PARTIALLY |
| MCB-03 | python | suite passes (EB) · fix-impl-not-tests (RD→tamper) · API unchanged (ES) · no 3rd-party (EN) | EB+RD yes; ES implicit | CHECKABLE |
| MCB-04 | python | search behavior + add/list regression (EB) · "follow existing conventions" (RD/AM) | EB yes | CHECKABLE |
| MCB-05 | python | behavior identical (EB) · short orchestrator ≥3 helpers (ES) · "well-named" (UC-soft) | EB yes; **ES bound today** | CHECKABLE |
| MCB-06 | python | ConfigError ×4 modes, import path, valid-config passthrough (EB) | yes | CHECKABLE |
| MCB-07 | python | slice spec w/ examples (EB) · tamper (RD) · API unchanged (ES) | yes | CHECKABLE |
| MCB-08 | python | canonical numerals w/ reference values (EB) · tamper (RD) | yes | CHECKABLE |
| MCB-09 | python | merge semantics incl. touching (EB) · tamper (RD) | yes | CHECKABLE |
| MCB-10 | python | delete/items behavior + regression (EB) · "existing style" (RD/AM) | EB yes | CHECKABLE |
| MCB-11 | python | precedence/associativity/float-div (EB) · "extend, don't reinvent" (RD/AM) | EB yes | CHECKABLE |
| MCB-12 | python | :param matching semantics (EB) · "match segment-by-segment" (ES directive) | EB yes; ES unbound | CHECKABLE |
| MCB-13 | python | behavior unchanged (EB) · **data-driven bands + exactly one `if`** (ES) | EB yes; **ES unbound** | PARTIALLY |
| MCB-14 | python | behavior unchanged (EB) · **one shared helper both call, no inline dup** (ES) | EB yes; **ES unbound** | PARTIALLY |
| MCB-15 | python | behavior identical (EB) · short orchestrator ≥3 helpers (ES) | EB yes; **ES bound today** | CHECKABLE |
| MCB-16 | python | robustness rules + empty-set shape (EB) | yes | CHECKABLE |
| MCB-17 | python | TableError cases incl. 1-based line no. (EB) | yes | CHECKABLE |
| MCB-18 | python | atomicity, `errors` attr w/ per-op index, no-mutation (EB) | yes | CHECKABLE |
| MCB-19 | python | inclusive weekday count (EB) · tamper (RD) | yes | CHECKABLE |
| MCB-20 | python | `--json` anywhere, text path unchanged (EB) · "fit in" (RD/AM) | EB yes | CHECKABLE |
| MCB-21 | python-cli | tag/find behavior (EB) · own tests (EN) · **keep `cli`/`store`/`model` layout — extend, don't collapse** (ES) | EB+EN yes; **ES unbound** | PARTIALLY |
| MCB-22 | python-cli | program/assignment semantics (EB) · own tests (EN) · **keep 4-module layout** (ES) | EB+EN yes; **ES unbound** | PARTIALLY |
| MCB-23 | node-cli | commands/persistence (EB) · `tsc --noEmit` clean, tests wired to `npm test` (EN) | EB yes (counts fixed by #81); EN partial | CHECKABLE |
| MCB-26 | sql | applies cleanly, constraints enforced (EB) · `.sql` tests under `tests/` (EN) | yes (countable post-#81) | CHECKABLE |

## The numbers

- **Cases whose material claims are ALL coverable by an oracle kind that exists today: 19/24.**
  The 5 PARTIALLY cases (02, 13, 14, 21, 22) each fail on exactly one **explicit-structural**
  claim that today has no bound oracle.
- **Explicit-structural claims appear in 8/24 briefs** (02, 05, 12, 13, 14, 15, 21, 22).
  The current extractor binds **2** (05, 15 — the "short orchestrator + N helpers" phrasing).
  The other six are *different transformation verbs*: data-driven/single-`if` (13), extract-shared-
  helper/deduplicate (14), module-layout preservation (21, 22), segment-wise matching (12),
  DOM-level structure (02). **A small transformation-contract vocabulary raises structural
  engagement from 2/24 to 8/24 — the ceiling question is answered: 8, not 2.**
- **"Fix the implementation, not the tests" (6 bugfix cases) is already a bound oracle** — the
  tamper guard. This is the existence proof for REPOSITORY_INVARIANT provenance: a claim the
  brief states, the repo enforces deterministically, and no model certifies.
- **AM/UC claims occur in ~9 briefs but are material in at most one** (MCB-02's "real content").
  Everything else ("clean", "well-named", "where reasonable", "follow conventions") is
  quality-soft: a reviewer signal, not a gate claim.
- **Zero briefs are UNDER-SPECIFIED at the material level.** Expected — MCB briefs were authored
  to be benchmarkable. **This sample is biased exactly where the product question lives**: real
  operator asks will carry far more AM/UC material claims, which is what the intake clarification
  path is for. The bench needs an under-specified-brief case class before intake can be measured.

## The uncomfortable observation (feeds ADR-1 directly)

MCB-05/15's ES claim is *bound today* — and the n=25 A/B still false-shipped 84–100% with the
oracle ON. The AST check passes shapes the hidden grader rejects: **two readers of the same claim
text disagree about what it means.** Claim coverage is necessary but not sufficient; the claim
must have **one binding** — a single predicate evaluated identically by the gate and by whatever
grades it. An ADR-1 claim artifact therefore carries the *predicate*, not just the text, and the
grader must consume the same predicate. (This also explains why "add an oracle per defect class"
kept failing: each new oracle re-interpreted the brief independently.)

## What this means for the claim schema (ADR-1 inputs)

- Provenance labels observed in the wild: ENTAILED (dominant), REPOSITORY_INVARIANT (tamper
  guard, layout keep-working clauses), quality-soft AM/UC (must be representable but non-gating).
- Oracle-kind vocabulary actually needed now: `acceptance_test`, `validation_exit`,
  `tests_unmodified` (tamper), `ast_transformation_contract` (6 verbs cover all 8 ES claims),
  `wellformedness_parse`. Nothing exotic.
- Every PARTIALLY case becomes CHECKABLE with the transformation-contract vocabulary — **no MCB
  case requires clarification**, so intake-interrupt value cannot be demonstrated on this suite
  (needs the new case class above).

## Addendum (same day): the vocabulary claim is now MEASURED, not asserted

`scripts/experiments/claim_predicates_stage0.py` — offline, zero model calls, pre-registered
(references must PASS, seeds/synthesized-wrong-shapes must FAIL). **18/18 expectations met**
across all four unbound contracts (`data_driven_single_if` on MCB-13, `extract_shared_helper` on
MCB-14, `layout_preserved` on MCB-21/22 + synthesized collapses, `dom_contract` on MCB-02
good/broken pages) plus a re-validation of the two bound ones (MCB-05/15 via the existing
`evaluate_structural_spec`). One harness bug found and fixed en route, disclosed: the first run
checked reference *directories* instead of the overlay-applied tree (references store only changed
files) and false-parked MCB-21's reference — the same harness-bug class probe-stage0 had. The
predicate itself was correct. Caveat unchanged: passing references and seeds is necessary, not
sufficient — these predicates have not yet been run against model-*delivered* wrong shapes, and
MCB-05/15's history shows delivered shapes are where interpretations diverge. That divergence is
precisely what ADR-0079's single-binding rule exists to close: under it the grader consumes the
same predicate, so gate/grader disagreement becomes structurally impossible rather than merely
unlikely.
