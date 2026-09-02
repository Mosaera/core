# ADR-0085: Oracle defects — the deterministic layer is frozen, and judgment is bought with memory before models

- Status: proposed
- Implementation: **§1 (the freeze) is IN FORCE and has been applied; §3's INSTRUMENT shipped; §3's
  oracle review and §2 are not-started** — ~~"§2/§3 not-started"~~ **corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`):
  that contradicted the sub-bullet below it and the roadmap's `#64` entry (DONE, built + measured
  2026-08-06, `mosaera-guided` runner). §3 names the instrument as its own prerequisite, so an
  instrument that shipped is §3 partially built.
  - **§1 has governed real work since 2026-08-06.** The F52 fix (the assertion floor accepting
    `self.assertTrue(True)` while rejecting `assert True`) was built explicitly to comply with it:
    the rule applied was the one the bare-`assert` branch already used, extended to the call syntax —
    *no new detector class*. Commit `870ee7f`; measured zero verdict deltas across 173 real test
    files. Recorded here because "proposed / not-started" understated a policy that is already
    binding decisions, which is exactly the staleness the 2026-08-06 doc pass was correcting.
  - **§3's instrument shipped** as `#64` (guided-mode harness), measured **0 corruption in 6 runs**,
    and produced F49's ESCALATE arm — itself half-built, see
    #68.
  - Ratifying the status is a **decision for the owner**, deliberately not taken during a docs pass.
- Date accepted:
- Owners: @rengi
- Related issue / MR: operator session 2026-08-06 (LedgerCLI live runs, findings F36–F44 in
  [the friction log](../engineering-history/ledgercli-friction-log-2026-08-05.md))
- Supersedes / Superseded by: — (constrains future work under [ADR-0062](ADR-0062-proctor-faithfulness-detector.md);
  re-opens the question [ADR-0070](ADR-0070-independent-spec-review.md) closed, on narrower terms)
- Related threat model: [TM-0001](../threat-models/TM-0001-mosaera-lite-repo-agent.md) (the oracle-authoring trust surface)
- Review trigger: a sixth semantic detector class is proposed, or a measurement shows oracle review changes a containment outcome
- Amended by: [ADR-0093](ADR-0093-mutation-operator-sufficiency.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

**Decision summary:** Stop adding case-specific semantic detectors for oracle defects. The
deterministic layer is **frozen** to structural, one-sided facts. Semantic judgment about whether a
test is *right* is bought first with **durable correction memory** (cheap, untried, and the only lever
with recurrence evidence behind it), and only then — if a specific containment measurement justifies
it — with an independent model review. Two things stay non-negotiable: the delivery gate remains
deterministic, and no model may relax a protected test.

## Context

Two accretion strategies for "the Proctor authored a bad test" now have measured null results, from
opposite directions.

**The deterministic direction (ADR-0062, this session).** `faithfulness.py` grew five hardcoded
detection classes plus hint-word lists (`_OUTPUT_HINTS`, `_SOURCE_HINTS`, `_EXIT_ATTRS`);
`roundtrip.py` added a sixth with `_MIN_COMPONENTS = 2`. F37 fixed a genuine blindness (the module
walked `ast.Assert` alone and could not see `unittest`, which this product's charter mandates) and
was measured properly: findings byte-identical across all 42 MCB corpus files, 12 new tests. **On the
product's own authored suites it reports zero.** The fix was correct and changed nothing, because the
next defect did not match the pattern. Each class is a photograph of a defect we already saw.

**The model direction (ADR-0070).** A held-out, coder-blind, naming-only spec review of the authored
tests — structurally the strongest version of "have an independent agent review the Proctor" —
measured with DeepSeek-R1:32B: **0 park→ship conversions in 15 ON runs**, a mild regression where it
acted. Reverted the next day. Its lesson was that a faithful test is not sufficient; correct code
parks for deeper reasons.

**What neither measured, and what the 2026-08-06 live runs showed.** ADR-0070's A/B scored
*throughput* — does correct code ship — on the autonomous MCB bench. The failure that actually
occurred is *containment*:

- The Proctor authored `self.assertIn("2023-01-01", content)` for a command run with no `--date`.
  Unsatisfiable by any correct implementation (F44).
- The coder, correctly forbidden from editing the protected test, proposed replacing
  `date.today()` with `date(2023, 1, 1)` — commented *"For test purposes"* — which would date every
  user's expense 2023-01-01 forever, and would have turned the suite green (F43).
- It was stopped by a human reading the diff. No detector fired; no agent objected.

This is a different question from ADR-0070's. It is not "does correct code ship", it is "can a wrong
oracle push a correct producer into corrupting the product". The bench could not have seen it: it
runs autonomously (no write gates), and all 42 of its test files are bare-`assert` while the product
authors `unittest`. That is the [F35](../engineering-history/ledgercli-friction-log-2026-08-05.md)
lesson recurring — *the instrument cannot see the defect the product has*.

**The recurrence evidence.** Across three consecutive live runs the same defects reappeared: the
closed-file `tempfile` write (twice), the unsupplied date pin (three times), the `src.` import prefix
(repeatedly). Six operator corrections issued during one run did not survive it. Nothing carries a
lesson from one run to the next.

## Decision

### 1. The deterministic layer is frozen to structural, one-sided facts

`faithfulness.py` and `roundtrip.py` keep what they have and **gain no new semantic detection
classes**. A new deterministic check is admissible only if it is *structural* — decidable from the
shape of the code without interpreting the spec — and one-sided in the safe direction. The existing
structural checks are the model: does this file assert anything at all (`tests_assert_real`), was a
protected/baselined path modified (the tamper guard), did the suite go red before implementation
(`tests_red_verified`).

"Is this assertion faithful to the spec?" is **not** structural and no further deterministic answer
to it will be built. Concretely, **F44 is not to be implemented as a detector** — a seventh rule for
a standalone unsupplied pin is the same accretion, and the eighth defect will not match it either.

*Why this is a decision and not a preference:* every semantic class costs permanent maintenance,
appears in two consumers with different gating, and is scored against the corpus that motivated it.
The F37 result is the measurement — a correct fix with no effect on real output.

#### Amendment, 2026-08-20 — the review trigger fired, and two checks were admitted

The trigger above ("a sixth semantic detector class is proposed") fired. Two checks were proposed,
argued against the §1 test, and **admitted** — recorded here rather than merged quietly, because the
freeze only means anything if a proposal has to answer it.

**What prompted it.** Two live defects on 2026-08-19/20, both in Proctor-authored bars:

- `assert "action='store_true'" in cli_content` — pins the SPELLING of source code. `hygiene` runs
  `ruff format` over delivered source *after* the tests are authored, so the quotes it pins are
  rewritten out from under it. Item 107 reported 67 passed, delivered `completed`, and shipped a
  tree failing its own suite ([ADR-0106](ADR-0106-the-tree-that-ships-is-the-tree-that-passed.md)).
- A rewrite that built a list, appended to it, and asserted nothing — twice in one day, caught both
  times only by a human reading the test.

**Why they pass the §1 test.** Both are *structural*: decidable from the shape of the code, with no
reading of the spec. Critically, the first is unsatisfiable against **the engine's own pipeline**,
not against a judgement about what the task meant — a mechanical fact about Mosaera, in the same
category as the tamper guard §1 already names as a model. The second is not a new class at all: it
is `authored_suite_asserts_behaviour`'s existing rule asked per FUNCTION instead of per SUITE (that
check is true if *any* test asserts, so a vacuous test carried by its siblings is invisible to it).
That is the F52 precedent this ADR already blessed — the rule that existed, applied at a new scope.

**The measurement** (the discipline F52 set: 173 files, zero verdict deltas). Detector run across
the MCB corpus (46 grader files) and the product's own suites (186 files), before and after:

| kind | MCB before → after | product before → after |
|---|---|---|
| `exact_output_equality` | 1 → 1 | 3 → 3 |
| `source_formatting_pin` | 0 → 0 | 0 → 0 |
| `vacuous_test` | 0 → 0 | 0 → 0 |

**Every pre-existing kind moved by exactly zero**, which is the safety claim: the new predicates are
deliberately kept out of `_derived_vars`' `src_names`, so `present` — and therefore the
`contradiction` and `source_introspection` counts — cannot shift. And the new kinds add nothing on
232 real files while catching both live defects — the same shape as the F37 result this ADR calls
its measurement: *a correct fix with no effect on real output*.

**One-sidedness was bought by narrowing, and the first cut did not have it.** The initial predicates
produced 8 findings on the product's suites, of which 7 were false positives in two classes — tests
asserting on a `.py` file the code under test had *written* (legitimate behaviour), and the "does
not raise" idiom (`persist(ctx, m)  # no store -> no-op`), which is a weak bar but a real one. Both
are now excluded structurally: a source path must be written LITERALLY in the test (a path composed
from a fixture is unresolvable, so the check stays silent), and a bare call statement counts as an
assertion of "does not raise". The module docstring's original claim that a vacuous test "can never
fail" was wrong for that idiom and has been corrected.

The 8th finding was a **true positive** — `test_pmbench.py:267` asserts an exact source line of
`projects.py` and carries a comment conceding the coupling — and it was given up deliberately. It
survived only through an inconsistency: a literal path flowing through a local (`source = "…py"`)
bypassed the literal rule, which would equally have re-admitted `tmp_path / p`. Making the rule
consistent — one unresolvable name anywhere in the receiver and the check is silent — costs that
detection. Silence when unsure is what §1 asks for, and a rule with a hole in it is not one-sided.

**Consequences accepted.**

- The checks live in `bar_integrity.py`, not `faithfulness.py`. The split is the ADR boundary made
  visible — the five frozen classes there, the two admitted here — and it was forced anyway:
  `faithfulness.py` and `oraclecheck.py` are both at the god-file ceiling. No measured code moved.
- `overstrict_static` (`bench/faithfulness.py`, a bare `len()`) can now count these kinds, so bench
  scorecards from before this change are **not comparable** to later ones on that field.
- Detection-only stands ([ADR-0062](ADR-0062-proctor-faithfulness-detector.md)): the findings reach
  the Proctor's coder-blind repair turn and the critic's hint, and gate nothing.
- The narrowing costs real recall — a spelling pin behind a computed path goes undetected, and one
  real instance in this repo's own suite (`test_pmbench.py:267`) is knowingly not reported. That is
  the intended direction of the trade.
- **This does not reopen the freeze.** It resolves one trigger. The prose in §1 stands, including
  that F44 is not to be implemented as a detector.

### 2. Correction memory before model review

The untried lever with direct recurrence evidence is durability, not intelligence. An operator
correction, and a defect the run already hit, must survive into the next run for the same project —
the cross-run context ADR-0084 designs and nothing yet builds. This is ordered **first** because it
is cheap (no model call), it attacks recurrence rather than any single defect class, and its evidence
is measured rather than assumed: the same three defects recurred across three runs.

### 3. Oracle review re-opens only as a containment question, with a falsifiable measurement

ADR-0070's revert stands as the prior. It is **not** re-litigated on throughput. It may be re-opened
only for the containment claim it did not test, and only with a measurement that could fail:

> On a corpus containing an unsatisfiable authored test, does independent oracle review reduce the
> rate at which the producer proposes a product-corrupting diff (F43), versus the human-driven
> baseline?

The measurement needs a guided-mode instrument with write gates and `unittest` suites — the bench
today has neither, which is itself the finding. **Building the instrument is the prerequisite work**;
proposing the reviewer before it exists would repeat ADR-0070's actual error, which was measuring a
mechanism whose wiring was silently inert until someone logged the raw output.

If it is built, it inherits ADR-0070's constraints unchanged: held-out model (≠ coder), coder-blind
(runs before an implementation exists, so a test can never be fitted to failing code), naming-only
(the engine names, the Proctor edits), echo-injection hardened, and bounded by the assertion floor
and pre-impl red-verify so a "repair" that guts a test is not excused.

### 4. Two invariants this ADR does not touch

- **Deterministic Final Authority.** The delivery gate stays deterministic. Measured again on
  2026-08-06: a model returned `reviewer_verdict: APPROVE` and the gate refused with four earned
  reasons. Nothing here lets a model green-light.
- **No model relaxes a protected test.** Review may *name* a conflict; only the Proctor edits, only
  coder-blind. A reviewer that can see failing code and loosen the oracle is the false-ship path
  ADR-0062 red-teamed and reverted.

## Options considered

**Keep adding deterministic classes (status quo).** Rejected: measured null on F37, and the cost is
permanent. It also produces a false sense of coverage — five named classes read as "over-strictness is
handled" when the product's own suites match none of them.

**Rebuild ADR-0070's spec review now.** Rejected as premature, not as wrong. Its throughput result is
real evidence against, and the containment case that motivates re-opening cannot currently be
measured. Building it now would mean asserting an outcome we have no instrument for.

**Better Proctor persona prompting alone.** Rejected as insufficient, on evidence: the persona
*already* forbids pinning incidental detail the spec leaves open — `faithfulness.py`'s own docstring
quotes that instruction — and the Proctor pinned anyway in three consecutive runs. The coder was
likewise instructed to escalate rather than work around a test; it escalated correctly once, then
reached for the hardcode after a re-plan returned it to the same wall. Prompting is necessary,
already present, and demonstrably not sufficient at the current model tier. Worth re-measuring on a
stronger model rather than assumed in either direction.

**A stronger model everywhere.** Not rejected, but out of scope and not a substitute: ADR-0070's null
was produced *with* a strong reasoner.

## Security implications

Unchanged trust boundary. The oracle-authoring surface (TM-0001) keeps its existing controls: the
coder cannot edit protected tests, the Proctor's repair is coder-blind, the tamper guard is anchored
to a checkpointed integrity baseline (ADR-0068 / F35), and the gate is deterministic. This ADR
*narrows* what may be added there — a frozen deterministic layer and a review path that can only
name, never clear — so it removes no control.

The residual risk it does **not** close is F43: a wrong oracle can still push a correct producer
toward corrupting the product, and today only a human reading the diff catches it. Recorded as
accepted-and-open rather than mitigated, because claiming otherwise would be the dressing-up this
repo prohibits.

## Operational implications

- F44 is closed as **will-not-implement-as-a-detector**, not as fixed. The defect is real; the
  response moves to §2/§3.
- The guided-mode instrument in §3 is tracked as **`#64`** (`[prereq]`, opened 2026-08-06). It shares
  the deterministic-scripted-operator machinery with `#59` and is the missing evaluator for `#54`'s
  test-steward — whose stated risk ("a steward that edits a test to pass failing code is just gaming
  with extra steps") is precisely what the harness scores.
- Cost is a live constraint on §3: the 2026-08-06 run exhausted its 750k-token budget and needed a
  raise, with the coder at 634k. A per-file review pass adds a round trip per authored test, and
  convergence — not per-call cost — is what kills these runs.

## Consequences

**Good.** The detector surface stops growing on cases rather than principles. The next oracle defect
is answered by memory or by an independently measured control, not by a sixth regex. Both prior null
results are recorded as evidence instead of being quietly re-litigated.

**Bad / accepted.** No new detection lands immediately, so the F43 class stays open and
human-dependent in the interim. §2 and §3 are sequenced work, not a fix available today. If the
guided-mode instrument is never built, §3 stays permanently parked — which is the honest outcome, not
a silent lapse.

**Reversible?** Yes. §1 is a policy on future additions and removes nothing; §3 states the evidence
that would re-open ADR-0070's question. A measurement showing containment benefit reverses the
ordering without unwinding anything built.
