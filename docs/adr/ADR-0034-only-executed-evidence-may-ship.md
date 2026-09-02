# ADR-0034: Only EXECUTED evidence may ship — narrow the reviewer-silence backstop, and stop calling a machine's decision a human's

- Status: accepted
- Date: 2026-07-14
- Owners: Alejandro Rengifo
- Narrows: [ADR-0031](ADR-0031-deliver-on-silence-with-deterministic-validation.md) (deliver on reviewer silence), [ADR-0029](ADR-0029-reviewer-as-veto.md) (reviewer-as-veto)
- Corrects the verdict semantics of: [ADR-0028](ADR-0028-reviewer-verdict-recovery.md)
- Extends: [ADR-0032](ADR-0032-adding-a-languagepack.md) (a pack now also declares its plan's `strength`)
- Related: [ADR-0006](ADR-0006-durable-transcript-and-honest-outcomes.md) (honest outcomes), [ADR-0025](ADR-0025-behaviour-smoke-gate.md)
- Related threat model: docs/threat-models/TM-0001
- Completed by: [ADR-0044](ADR-0044-oracle-make-real.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

ADR-0031 changed what an unparseable reviewer verdict *means*. Before it, `UNKNOWN`
**parked** — the failure direction was false-park. After it, `UNKNOWN` + `tests_passed is
True` **delivers** — the failure direction is false-ship. That was a deliberate, measured
trade (the local reviewer emits no verdict on ~75% of correct MCB-21 runs, and false-parks
throw away working deliverables).

The problem is that four mechanisms around it were designed under the *old* direction and
were never re-audited against the new one. Together they let an autonomous run ship on
nothing:

1. **`tests_passed is True` is not one claim.** ADR-0031's own docstring justifies the
   backstop as resting on "the executed test suite AND the independent behaviour-smoke
   floor". That is true only for pytest repos. For a **testless** repo `PythonPack`
   produces `_scripts_plan` — `compileall`, whose own reason string says *"syntax check
   only"*. `config-data` is a JSON/TOML parse; `static-site` is an HTML well-formedness
   check; a Node repo with a `tsconfig` but no test script only runs `tsc --noEmit`. On all
   of these, "green" means **it parses**. Combined with a silent reviewer, autonomous mode
   auto-delivered behaviourally unvalidated code — and testless repos are the *common*
   case for the script-shaped tasks the product targets.

2. **A conflicting verdict was indistinguishable from silence.** `parse_reviewer_verdict`
   returned `UNKNOWN` both when it found *no* verdict and when it found *two different*
   ones. Post-ADR-0031 those mean opposite things. A reviewer that genuinely emits
   `VERDICT: REQUEST_CHANGES` while *quoting* a `VERDICT: APPROVE` it read in the repo (or
   in the coder's diff, or in echoed test output) produced two tokens → `UNKNOWN` → silence
   → backstop → **ship**. A real veto laundered into a delivery. It was also irrecoverable:
   `clarify_verdict` *appends* to the same text, so a third verdict cannot disambiguate.

3. **`deliver_unverified` composed with the backstop into zero evidence.** The flag coerces
   `tests_passed: None → True` at `nodes_impl.py` — *upstream* of the gate — and
   `evaluate_gate` never received `validation_unverified`. So the flag's `True` (meaning
   "no validator exists") satisfied the backstop's `tests_passed is True` (meaning
   "validation passed"). Reviewer silence + this flag = an autonomous ship with **no
   validator and no reviewer**. The flag's documented contract says the opposite: *"the
   reviewer still gates acceptance"*.

4. **The audit trail blamed the operator for it.** `human_override` was computed as
   `approved and reasons`, guarded by the comment *"an autonomous approve only ever happens
   with empty reasons"*. ADR-0031 falsified that premise: the silence-approve has
   `reasons == ["reviewer_unknown"]`. So **every autonomous silence-ship** was recorded, and
   rendered in the UI, as *"Human override: yes — a human approved delivery despite the
   reasons above."* The riskiest class of autonomous delivery was attributed to a person.

A fifth, smaller defect: `evaluate_gate(autonomous=True).action` and `autonomous_resolution`
were two policy surfaces for one decision, and ADR-0031 only taught the runner about the
backstop — so `action` reported `require_human` for cases the runner shipped.

## Decision

**1. Silence may only ever be overridden by EXECUTED evidence.** `ValidationPlan` gains
`strength` — `"suite"` (a real test suite executed) / `"shallow"` (it only proves the code
parses) / `"none"` (nothing executed) — **declared by the LanguagePack that builds the
plan**, because the pack is the only thing that knows. The gate does not guess from
`project_type` (that list would drift with every new language; ADR-0032 exists precisely to
stop that). The backstop now requires:

```python
core == ["reviewer_unknown"] and tests_passed is True and strength == "suite"
```

The default is `"unknown"`, which is not `"suite"` — so a pack that forgets to declare
**parks** instead of shipping. Deny-by-default. `strength` is carried on `GateDecision` (not
merely used to compute it) because the serialized interrupt payload is all that
`autonomous_resolution` and the human gate panel ever see.

**2. A conflicting verdict is not silence.** `parse_reviewer_verdict` returns a distinct
`CONFLICT`, which becomes its own gate reason `reviewer_conflict`. It can never satisfy
`core == ["reviewer_unknown"]`, so it always parks: if we cannot tell whether the reviewer
approved or objected, a human decides. `clarify_verdict` no longer fires on it (a third
appended verdict cannot disambiguate two).

**3. `deliver_unverified` reaches the gate.** `evaluate_gate` takes
`validation_unverified`, which forces `strength = "none"`. Silence can no longer ship it; a
reviewer **APPROVE** still can — which is exactly the contract the flag always claimed.

**4. `human_override` reflects who actually decided.** The runner stamps
`actor: "autonomous"` on its auto-approve and `actor: "human"` on a resume that came from a
person answering the parked gate; `ApprovalDecision` carries it. `human_override` is now
`approved and reasons and actor == "human"`. An unmarked resume reads `"unknown"` and is
**never** branded a human override — we under-claim rather than blame a person for a
decision we cannot attribute. The report gained the honest counterpart: an autonomous
approval over blocking reasons now says *"Autonomous delivery: the runner approved this over
the reasons above — no human decided it"*, and prints the validation strength in plain words.

**5. One policy surface.** `evaluate_gate`'s `action` and `autonomous_resolution` both route
through a single `_resolve(reasons, tests_passed, strength)`, so they cannot drift again.

## Consequences

- **Autonomous runs on testless repos now park for a human instead of shipping.** This is
  the intended correction and it is not free: MCB Autonomy/Governance scores will drop on
  the shallow-validation cases, and the baselines need a re-run. A drop there is the
  benchmark finally telling the truth — those runs were shipping on a syntax check.
- Autonomous delivery on repos with a **real suite** is unchanged. ADR-0031's actual target
  (MCB-21, a multi-module CLI package *with tests*) still delivers on reviewer silence. The
  fix is a narrowing, not a revert: reverting ADR-0031 would restore the ~75% false-park
  rate that made autonomous mode unusable on local models.
- `GateDecision.as_dict()` grows a 7th key; the serialized `gate_decision` KV row and the
  SPA's parser grow `validation_strength`. Old persisted rows lack it → `"unknown"` → they
  simply never satisfy the backstop, which is the safe reading.
- Several existing tests **inverted**. Every inversion is a *strengthening*: fewer
  autonomous approvals, more parks. Notably `test_parse_reviewer_verdict` had a case
  asserting that `"VERDICT: APPROVE … on second thought VERDICT: REQUEST_CHANGES"` →
  `UNKNOWN`. That test encoded the vulnerability.

## What this does NOT fix

The underlying epistemic problem stands: for a repo whose only tests are the **coder's
own**, `strength == "suite"` still means "the author's tests pass". A thin or
self-serving suite still clears the bar. This ADR removes the cases where the bar was
*nothing at all*; it does not create an independent oracle. That remains the tester
(Proctor, off by default) and the open work in ADR-0027's arc — *"a false-positive-ship
needs a better ORACLE, not a bigger coder"*. Relatedly, the coder can still delete or weaken
a **pre-existing** test and pass its own suite (the tamper baseline covers only
tester-authored files) — tracked separately, not closed here.

## Amendment (2026-08-19) — a reviewer that QUOTES a verdict no longer parks the run

`reviewer_conflict` exists because two different `VERDICT:` tokens mean we cannot tell what the
reviewer said, and collapsing that into `UNKNOWN` would let a real veto be laundered into a ship.
That reasoning stands. What it did not account for is the reviewer quoting **itself into a
conflict**: reasoning models echo the diff, quoted source and test output into fenced blocks, and an
echoed `VERDICT:` line there read as a second, conflicting verdict. A genuine review could park a
run for quoting the thing it was reviewing.

The critic was hardened against this exact class on 2026-07-19 (strip fences before scanning, plus a
persona line forbidding the echo). The reviewer got neither — found by an agent-wide prompt review
on 2026-08-19.

`parse_reviewer_verdict` reads the raw text first. On **two or more** verdicts it re-reads with
fenced blocks stripped, and adopts a surviving single verdict **only when that verdict is not
`APPROVE`**:

- a genuine objection alongside an echoed `VERDICT: APPROVE` → the objection (was: `CONFLICT`);
- a reviewer that fenced its **only** verdict → parses exactly as before;
- a genuine two-verdict conflict in prose → still `CONFLICT`, still parks;
- no verdict → still `UNKNOWN`.

**The never-toward-`APPROVE` rule is the load-bearing half, and this amendment's first version did
not have it.** That version scanned the fence-stripped text *first* and accepted whatever single
verdict survived, on the claim that "the only behaviour that changes is the intended one". A red
team disproved the claim by running it: a reviewer that fenced its genuine `REQUEST_CHANGES` while
untrusted prose carried `VERDICT: APPROVE` parsed as **`APPROVE`** — a park converted into an
autonomous ship, which is the precise laundering the `reviewer_conflict` reason exists to prevent.

Which of two verdicts is the echo is **undecidable** — the reviewer may fence its own verdict as
readily as a quotation — so the parse may only guess in the direction that cannot ship. A wrongly
parked approval costs a human one click; a wrongly shipped one bypasses the only human control
there is. The consequence is accepted deliberately: the spurious park this amendment set out to
remove is only removed in the objection direction. The prompt also now carries the anti-echo
sentence its sibling has had for a month — but the strip is the control; the sentence is not.

