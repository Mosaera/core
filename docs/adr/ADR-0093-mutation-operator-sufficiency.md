# ADR-0093 — The mutation oracle gets a sufficient operator set, and "could not ask" stops meaning "failed"

- **Status:** accepted
- **Date:** 2026-08-08
- **Amends:** [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) (operator scope), [ADR-0074](ADR-0074-layer2-park-to-ship-disposition.md) / [ADR-0075](ADR-0075-engine-blocked-give-up-conversion.md) (the Layer-2 verdict vocabulary)
- **Scope:** `packages/core/mosaera_core/mutation.py`, `disposition.py`, `bench/layer2_report.py`
- **Invariants:** *Evidence-Gated Advancement*, *Deterministic Final Authority*, *Honest Parking*

## Context

Layer 2 converts an honest park into an unattended ship. Measured over 40 runs on 2026-08-08 it
declined **15 of 15** attempts — every one on code the hidden grader said was **correct**. With the
decline reason recorded (#84), **7 of 8** read *"the mutation check was inconclusive"*, not *"the
authored test is a rubber stamp"*.

Reproduced by hand: the delivered fix was `start = page * per_page` → `(page - 1) * per_page`. The
three operators (return→`None`, flip the first comparison, delete a bare call) generate **zero
mutants** on that line. No mutant ⇒ no verdict ⇒ decline. The oracle was not failing the work; it had
no question to ask, and the gate spent that silence as a refusal.

## Decision

**D1 — two operator kinds, single-substitution.**
`arith` (`+`↔`-`, `*`↔`/`, `//`→`/`, `%`→`/`, `**`→`*`) and `const` (one `+1` per numeric literal).
Not the 4-way AOR cross-product (31% duplication) and not the six-way CRCR (**57% duplication, the
worst of any operator studied**). We need *availability* — one killable mutant — not an exhaustive
probe, and in this gate every extra mutant is another independent chance to draw an equivalent one
and refuse correct work.

Evidence, converging from four directions: arithmetic replacement is one of Offutt's five sufficient
operators (TOSEM 1996 — 5 operators retain **99.5%** of full mutation coverage), has the
second-lowest equivalence rate of the five (**5%** under Yao et al.'s 6-person-month manual analysis,
ICSE 2014; 1% under Trivial Compiler Equivalence, ICSE 2015), ships in Google's production
mutagenesis across 10 languages, and is a default in every mainstream Python tool. Constant ±1 is
*not* sufficient-set, but is in the Major set that reaches **73% real-fault coupling over 357 real
faults** (Just et al., FSE 2014). **ABS (47% equivalent) and UOI (24%) are rejected** — Google
dropped ABS explicitly.

**D2 — suppress arid contexts** (Google's published rules): literals in `sleep`/`timeout`/`deadline`/
`retry`/`backoff`/`range`/`reserve` arguments, and default argument values. Perturbing `sleep(100)`
alters speed, not behaviour — no reasonable test kills it, so it is a *manufactured survivor*. This
class is what took Google's mutant productivity from **15% → 89%**; without it, D1 becomes a
wrongful-decline generator.

**D3 — `not_measured` is a distinct verdict** from `unverified`. It **still declines**: deny-by-default
is correct when the ship authority is a machine. Only the *record* changes, so nothing new ships from
D3. But *"the oracle could not ask"* and *"a real check said no"* imply opposite fixes, and conflating
them is what made an operator gap read for two hours as weak authored tests.

**D4 (red team R2) — identity-preserving swaps are suppressed.** `x - 0` → `x + 0` and `x ** 1` →
`x * 1` compute the same answer. An equivalent mutant is unkillable; in a *continuous* mutation score
that is a small bias, but in a **binary ship veto** it is a guaranteed wrongful decline. Suppression
is by identity element per operator — `x * 1` → `x / 1` is deliberately kept, because in Python that
turns an int into a float, which a test can observe.

## Rejected

- **Coverage as a substitute when mutation cannot run.** Coverage proves a line executed, not that the
  test would fail if the line were wrong — precisely the rubber stamp this gate exists to catch. It is
  the one change considered here that could produce a **false ship**.
- **Making a survivor non-blocking** (Google's advisory model). Our fallback for a decline *is* a park,
  and a park *is* human review — we already have Google's behaviour on the unattended path.
- **ABS, UOI, the AOR cross-product, the CRCR six-way.**

## Consequences, stated honestly

**This change opens a ship channel that could not open before.** An inconclusive check always declined;
a verdict-bearing check can convert. That is a widening, not a hardening, whatever the growing operator
count suggests. A false ship becomes *reachable* for the first time, and the pre-registered re-run of
MCB-06 ×12 + MCB-07 ×8 is the measurement that will say whether it happens.

**No published industrial deployment uses a deterministic mutation verdict as a ship authority** —
Google's is a non-blocking suggestion to a human reviewer. Ours is a machine gate, so deny-by-default
on ambiguity is right, but it means every equivalent mutant is a wrongful decline, and the literature
puts those at **8–25% and undecidable**. **This fix reduces inconclusives and increases wrongful
declines.** Both move toward waste, never toward a false ship. The research does not endorse this
architecture; it bounds it.

Two findings we are **not** acting on, recorded because they bound what this buys: **27% of real
faults couple to no mutant at all**, and **40%** of coverage-neutral fault-revealing tests kill zero
additional mutants (Just et al.). Mutation silence never implies test inadequacy — which is precisely
why D3 exists.

## Red team (3 rounds, F83 scope)

- **R1 — trivial-kill conversion.** No finding. Every generated mutant on the constructed cases was
  behavioural; single-substitution holds (4 mutants on a 3-site line, each one substitution).
- **R2 — equivalent-mutant wrongful decline.** **CONFIRMED, FIXED (D4).** Two of the five swaps
  produced provably equivalent mutants. Pinned by `test_identity_preserving_swaps_are_suppressed`.
- **R3 — arid suppression as an attack surface.** **ACCEPT, documented.** Suppression is by fuzzy
  called-name, so a user-defined `range()` and a genuine `retry(3)` are both silenced. Google flags
  the same unsoundness in their own rules. The cost is a *missed question* (`not_measured`, which
  declines), never a false ship, and D3 is what makes that cost visible instead of silent.

Verdict: no round produced a second finding in the same defect class; the STOP rule was not reached.
