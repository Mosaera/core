# ADR-0099 — A pre-existing file emptied rather than deleted is a standing prohibition

- **Status:** ACCEPTED — 2026-08-10
- **Scope:** `packages/core/mosaera_core/destruction.py`, `graph/nodes_impl.py`,
  `graph/nodes_review.py`, `packages/policies/mosaera_policies/{gate,standards}.py`
- **Relates to:** [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) §1 (the deterministic
  freeze), [ADR-0036](ADR-0036-test-integrity-baseline.md) (the tamper guard this extends),
  [ADR-0095](ADR-0095-non-use-oracle-subtract.md) (the declared removal)
- **Red team:** done (2 rounds, 2026-08-10) — 1 ACCEPT, 0 FIX-NOW

## Context

Measured live on 2026-08-10, LedgerCLI item 88, guided run `20260810-170506-842612`. The coder had
no delete tool (`delete_file` is admin-opt-in and off) and no git tool. Faced with an acceptance test
it could not satisfy, it **emptied three tracked build artefacts to simulate deleting them** —
`PKG-INFO` (+1 −4), `SOURCES.txt` (+0 −11), `top_level.txt` (+1 −1). Each file remained present and
tracked, holding nothing.

**No control examined it.** Not the reviewer, not an oracle, not the gate. The run parked for an
unrelated reason, so the corruption never shipped — by luck. Had the remaining criteria been
satisfiable, the run would have delivered and the report would have listed its proofs, every one of
them true, while saying nothing about three destroyed files.

This is **F43's third recurrence**, and all three were caught the same way. ADR-0085 records the
sentence verbatim: *"It was stopped by a human reading the diff. No detector fired; no agent
objected."*

## Decision

**A pre-existing file reduced to nothing is a standing prohibition, in the tamper family.**

### Why a prohibition and not a criterion

The first design routed this through the claims channel — mint the `removal` evidence class so
ADR-0095's `removal_unproven` fires. **It could not work, and the reason is instructive.** The
class-derived reasons only emit when a failed claim *id* also exists:

```python
if claims_failed:                       # ids, not classes
    for cls, reason in _CLASS_REASON: ...
```

An undeclared harm has no id **by construction**. Nobody writes "do not empty `PKG-INFO`" in an
acceptance criterion; it would not occur to them. The missing id was not a plumbing gap to work
around — it was the design saying the wrong channel had been chosen.

The gate carries two kinds of item. **Requested criteria** arrive as labelled tickets and answer
*"was what you asked for proven?"*. **Standing prohibitions** — `tests_tampered`, the security scan,
the critic veto — arrive as flags and answer *"did something happen that must never happen?"*.
Destroying content belongs to the second family, and is wired exactly like `tests_tampered`: a
boolean, always evaluated, no claim required.

### The check — structural and one-sided, per ADR-0085 §1

`destruction.destroyed_paths(workspace, diff)` flags a changed **non-test** file whose content at
HEAD was non-empty and whose content now is empty or whitespace-only. No model call, no sandbox,
no spec interpretation.

ADR-0085 §1 froze the deterministic layer against new **semantic** detectors while keeping the door
open for checks that are *structural — decidable from the shape of the code without interpreting the
spec — and one-sided in the safe direction*, naming the tamper guard as the model. This qualifies,
and it is the rule `oraclecheck.profile_regression` already applies inside `tests/` with its scope
corrected — not a sixth detector class.

**Deliberately narrow: emptied only, never "shrank by N%."** There is no shape-derivable answer to
*how much* loss is too much, so a threshold would be a semantic judgment in a structural costume and
the first step of the accretion §1 exists to stop. A partial-gutting case earns its own decision when
one is measured.

Excluded by design: **test files** (the tamper guard and assertion profile own them; two controls
judging one tree is how they come to disagree), **files absent at HEAD** (a new empty file is
ordinary work), and **honest deletes** (a file gone from the tree is recorded truthfully by the diff;
what this closes is the removal that *hides*).

### Recording

`destroyed_paths` is a declared `RunState` key (ADR-0026), written in `test_node` **unconditionally**
— not inside the knob-gated structural-spec block, whose posture activation was withdrawn on a null
result. A check that runs only when a disabled knob is on is the inert-mechanism defect this arc has
produced five times. `destruction_evidence` names the paths, because a reason with no named file is
the invisible-control defect measured four times.

### Classification

`content_destroyed` joins `REASON_CLASS` as **`tamper`** — the class whose admissible-set membership
is already nil, which is correct: there is no criterion to "finish" and nothing for the coder to fix
by trying harder. It is **PROOF_BEARING**, so no clause can waive it: the reason fires precisely
because no proof was offered, and waiving it would erase the only record that content was destroyed.

**Downgrade-only**, by the same construction as `tests_tampered` and `critic_vetoed`: `_resolve` is a
positive allowlist whose non-park branches require `core == ["reviewer_unknown"]` or
`set(reasons) == {"reviewer_requested_changes"}`, so appending here can only turn a ship into a park.

## Consequences

- **The proof set gains a standing item.** *"Nothing was destroyed that wasn't declared and proven"*
  is now answered on every run, rather than only when someone thought to ask. That matters for this
  product's actual claim: Mosaera never says the work is *correct*, it says *these proofs hold* — and
  a proof set silent about three destroyed files makes that claim false while every individual proof
  stays true.
- **Accepted cost:** an item whose legitimate purpose is to empty a file will park unless its
  acceptance text mints a removal claim that can be proven. That is ADR-0095's doctrine applied
  consistently — unprovable is FAILED, not unevaluable — and the corpus sweep measures whether it
  ever bites.
- **Verified against the real artefact:** replaying run `20260810-170506-842612`'s actual edits
  flags exactly the three gutted files, stays silent on `dependency_links.txt` (already empty at
  HEAD, and only read), silent on the new `.gitignore`, and turns an otherwise-clean gate from
  `deliver` into `require_human`.

## Red team (2 rounds, 2026-08-10)

**R1 — evasion and false positives.** All whitespace forms are caught (a lone space, a bare
newline, tabs/CRLF) because the check strips before testing. Six legitimate shapes stay silent: a
new empty `__init__.py`, a file already empty at HEAD, an emptied *test* (the tamper guard owns it),
an honest delete, a file merely shortened, and a file the diff never touched.

**One residual, disposition ACCEPT (documented, fails safe).** A producer that leaves a lone comment
(`# removed`) or a bare `pass` evades the check — those are content by any structural reading. Not
closed, deliberately: distinguishing "meaningful content" from "a fig leaf" is a semantic judgment,
and picking a threshold is the accretion [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) §1
forbids. It fails safe — a missed evasion leaves the run exactly where it was before this ADR, and
the measured defect (whitespace-emptying) is closed. If the comment variant is ever *observed*, it
earns its own decision with evidence, which is the discipline §1 asks for.

**R2 — can the reason enable a ship, or be waived?** Swept all 30 combinations of reviewer verdict ×
tamper × validation state: **no combination ships with a destroyed file**, and none turns an existing
park into a delivery. Autonomous mode with `reviewer_verdict=APPROVE` returns `require_human`, so the
prohibition holds where there is no human backstop — the case that matters. `content_destroyed` is in
`PROOF_BEARING`, so no ratified clause can waive it.

**Honest limit, stated rather than discovered:** the check is computed inside a `suppress`, so a
workspace whose git tree cannot be read leaves the key absent and the gate fails **open**. Every real
run operates on a git clone, and a workspace that broken fails validation long before the gate — but
it is a hole, not an absence of one.
