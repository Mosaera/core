# ADR-0071: Comprehensive mutation — verify EVERY changed behaviour, not just the first (#74)

- Status: accepted (mechanism built behind a knob; **posture activation HELD pending measurement**)
- Date: 2026-07-21
- Owners: Mosaera core
- Related issue: #74 (deterministic per-behaviour gate) — the twice-deferred `catches-some ≠
  enforces-all` successor escalated by #52 (ADR-0057) and #54 (ADR-0058), and now by the #66
  measurement (ADR-0070, which proved the LLM-judge oracle path does not crack this).
- Related threat model: TM-0001 (the delivery-gate evidence surface — same boundary as the mutation
  check it extends, ADR-0049/#39).
- Red-team: **required** (it feeds `oracle_verified` at the delivery gate). To be run as the DoD gate.

## Context

The delivery oracle credits a green run when an INDEPENDENT suite vouches for it. The mutation check
(ADR-0049/#39) is the "can this suite actually FAIL bad code" measure: mutate the delivered source, run
the suite, require it to go RED. But it makes **one** mutation per changed file and returns `True` on
the **first** catch. So a change with *multiple* behaviours can have a SECOND region the suite executes
but never asserts — a single mutation lands on the first (caught) construct and never probes the second.
That surviving-but-unprobed region is the **executed-but-unasserted false_ship** (the MCB-09 class the
#52 red-team named and deferred to "the dynamic per-repaired-test / Proctor-hard-gate successor").

The #66 measurement (ADR-0070) then established that the LLM-judge route to this problem is a dead end
on these models. So the successor is **deterministic**.

## Decision — mutate every eligible construct, require the suite to catch all

Add `oracle_mutation_comprehensive` (default OFF; needs `oracle_mutation_check`). When on, the mutation
check mutates **every eligible construct in each file's changed region** — one mutant per construct,
across the three existing operators (value-returning `return X` → `return None`; first comparison
operator flipped; a bare side-effecting call deleted → `pass`) — and requires the suite to catch **all**
of them. Any survivor = a delivered behaviour the suite executes but never asserts → the run is
downgraded (the same `oracle_verified` downgrade the single check already produces).

- **Deterministic, judge-independent, $0-ish.** Pure AST mutation + the existing sandboxed test run.
  No LLM. Extends `_mutate_source`/`suite_catches_a_mutation` (moved to a new `mutation.py` module to
  keep `oraclecheck` under the god-file ceiling; re-exported for the call site + tests).
- **Bounded.** A `_MUTATION_CAP` (20) caps total mutants per run (each mutant runs the suite once). A
  change exceeding the cap has its first `cap` constructs checked — strictly more than the single
  baseline, never fewer.
- **Fail-closed + downgrade-only.** The FIRST survivor (across all files and mutants) returns `False`;
  an early catch never masks a later rubber stamp. Each mutant is reverted byte-for-byte in a `finally`.
  A `False` can only ever turn a would-be ship into a park — it can never create a ship, so it cannot
  manufacture a false_ship. `None` (inconclusive) never downgrades.

## Rejected

- **Per-requirement red-verify from the spec.** "Every requirement has a covering test" needs a
  machine-readable requirement list, which is exactly the LLM-judgment the #66 measurement proved
  unreliable. Mutation verifies what the code DOES without enumerating requirements.
- **The LLM-judge oracle (Phase A/B, ADR-0070).** Measured net-null-to-negative; reverted.
- **Activating it in the posture now.** Held — a stricter gate PARKS MORE (see Consequences); it is
  measured first, mirroring `behavior_preservation_guard` (#60) and the #66 discipline.

## Consequences

- Knob `oracle_mutation_comprehensive` (default OFF; posture HELD). No new RunState, no migration.
  `oraclecheck.py` 496 → 334 lines (mutation logic extracted to `mutation.py`).
- **What it fixes:** the executed-but-unasserted false_ship (a second unasserted changed region).
- **Honest limits:**
  - It does **not** catch a **dropped requirement** whose code is simply absent — there is nothing to
    mutate. That class needs requirement enumeration (out of scope).
  - **It parks more.** An *equivalent mutant* (a mutation that genuinely does not change behaviour)
    survives → a false park of correct code. That is the safety/throughput trade; it is in the safe
    direction (never a false ship), bounded by the must-change operators + the cap, but real. This is
    exactly why the posture activation is HELD until an A/B quantifies the extra parks against the
    false_ship reduction.
- **Cost:** up to `cap` extra sandboxed suite runs on a green iteration (memoised by tree hash, off the
  iteration loop). Opt-in.

## Red-team (done 2026-07-21, 2 refute-agents: false-vouch/enumeration + revert/corruption/resource)

**Verdict: revert/corruption REFUTED (sound); false-vouch found 1 HIGH + 2 MED — all FIXED.** All were
one theme: comparisons (boundary logic) were the least-probed construct.

- **HIGH — FIXED (enumeration gap → silent false vouch).** `_mutate_nth`'s combined transformer used a
  bare `return node` in `visit_Return`/`visit_Expr` (no `generic_visit`), so `NodeTransformer` never
  descended into their children — a comparison nested in a return value (`return {"big": n > 100}`) or
  in a bare call was **unreachable and never enumerated**, so its rubber stamp survived unprobed and the
  check returned `True`. This directly defeated the ADR's headline (the exact MCB-09 class). Fix: every
  visitor ends with `generic_visit`; `st["done"]` still bounds it to one mutation per call. Tested
  (a compare in a return / in a bare call is now enumerated).
- **MED — FIXED (return-biased cap → compares starved).** `_all_mutations` enumerated ALL returns before
  ANY compare, so a change with ≥cap returns spent the whole budget on returns and never probed a
  comparison. Fix: enumerate each kind up to the cap, then **interleave by index across kinds**
  (return[0], compare[0], noop[0], return[1], …) so the cap is construct-fair. Tested.
- **MED — FIXED (cross-file budget starvation → early catch masks a later survivor).** The budget was
  one global counter consumed first-file-first: a caught-heavy file that sorts first could starve a
  later changed file's survivor into a `True` vouch (making comprehensive WORSE than single). Fix:
  **round-robin the schedule by mutant index across files** (every file's baseline before any file's
  breadth) + **fail-safe to `None` on truncation** (a truncated all-caught run is inconclusive, never a
  vouch). So the "never masks a later rubber stamp / never weaker than single" guarantees now hold.
- **REFUTED:** byte-revert is sound on every path (original bytes captured once pre-write; each mutant
  `try: write_text … finally: write_bytes(original_bytes)`; the survivor `return False` runs after the
  finally); `None` cannot launder a survivor (a survivor is green → immediate `return False`); the cost
  is bounded by the cap + tree-hash memo. Residuals: a `finally`-write OS-failure (LOW, pre-existing,
  amplified) and a `None`-not-memoised recompute in `nodes_impl` (LOW, pre-existing).

## Measurement (DoD) — RUN 2026-08-02: null; posture stays OFF

> ~~(DoD, still to run)~~ **The A/B ran.** Recorded 2026-08-18 (`docs/audits/adr-corpus-review-2026-08-18.md`); until then this section read "still to run". **Result: null** — `oracle_mutation_comprehensive` moved MCB-05 **0/3**, no conversion of the false_ship class it was built for. Posture activation stays HELD, the knob stays default OFF; the mechanism, the `mutation.py` extraction and the red-team fixes all stand. Consistent with §Context: on MCB-05 there is nothing to mutate — the miss is structural, which is ADR-0072's class. Note the knob has **no** `MOSAERA_BENCH_*_OFF` lever, unlike `oracle_structural_spec`; A/Bs must set `MOSAERA_ORACLE_MUTATION_COMPREHENSIVE` directly.

The originally-planned scope, retained for the record:

An A/B (`MOSAERA_ORACLE_MUTATION_COMPREHENSIVE` on vs off) on the false_ship cases (MCB-05/09) + a
delivery check (MCB-01/02/16), to quantify `false_ship`↓ vs the extra parks BEFORE the posture activates
it — the measure-first discipline (#60/#66).

## Amendment (2026-08-03, owner-ratified): the AND stands — survivors are the to-do list

The #60 vouch A/B (engineering-history/refactor-vouch-ab-2026-08-03.md) surfaced the
collision: a detected pure refactor with a satisfied delta-proving structural claim AND a
green differential golden-master still parks when a comprehensive mutation SURVIVES. The
owner ratified keeping the conjunction unconditional, on this insight: **the mutation check
and the differential test share the same blind spot** — a surviving mutant names an input
region no test AND no generated equivalence input reaches, i.e. it points at the hole in the
equivalence proof rather than contradicting it. Superseding it would discard a free, precise
map of the proof's gaps.

Consequences: (1) no gate change — the evidence rises to meet the bar, never the reverse;
(2) the named successor lever is **mutation-guided differential inputs** (the scaffold
consumes the survivor list to generate inputs that REACH those branches — killing the mutant
strengthens the equivalence proof and the vouch stands on it); (3) meanwhile the park is a
PRICED, NAMED residual: the gate payload carries the three-line receipt (shape proven /
equivalence sampled / unproven branch survives) and a human approval ships it with
`human_override` + the residual on record — the operator is the supersession mechanism,
per-decision, audited.

Status note (2026-08-03, #63): the receipt is now DURABLE and rendered — `oracle_residual` +
`tests_mutation_caught` commit into `gate_state`, persist writes a JSON `receipt` decision
row, and the shared ReceiptCard shows the residual at the live gate, the run evidence tab,
and the durable commit page ("approving accepts this residual on record").
