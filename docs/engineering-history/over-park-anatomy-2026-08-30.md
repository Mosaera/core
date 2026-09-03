# The anatomy of over-park — the 0.6.3 sweep (2026-08-30)

150 runs, 30 cases × 5, `MOSAERA_ORACLE_RECORD_ALL_LEGS=1`, engine at `f671797b`.
Store: `/home/rengi/mosaera-sweep/v063/` (explicit `MOSAERA_HOME`, outside the live tree).

**Every over-park in this document is a tree the hidden grader passed 100%.** Each one is correct
work our own gates refused. That is what makes the assertions below evidence rather than suspicion.

## Headline — the arc did not move the number

Like-for-like on the 25 cases shared with the stored baseline, n=125 per side:

| | 0.6.3 | baseline |
|---|---|---|
| delivery | 62.4% | 56.8% |
| over-park | **32.0%** | **31.2%** |
| false_ship | 0 | 0 |
| crashes | 0 | — |

Over-park is unchanged. The delivery difference is ~1.3 standard errors on unpaired arms — noise,
not a win. The result worth keeping is **0 false ships in 150 runs**: nothing this arc did weakened
the safety property.

## The taxonomy (55 over-parks)

| mechanism | n | share | standing suite vouched |
|---|---|---|---|
| **Bar refused** — an authored assertion failed correct code | 26 | 47.3% | **24/26** |
| **No oracle** — nothing could vouch | 17 | 30.9% | **1/17** |
| Tamper — coder edited tests | 6 | 10.9% | 5/6 |
| Structural claim — no test involved | 2 | 3.6% | 2/2 |
| Validation failed, assertion uncaptured | 2 | 3.6% | 0/2 |
| Reviewer / critic | 2 | 3.6% | 1/2 |

The two dominant mechanisms are **opposites** — the bar is too strict, or there is no bar at all.
78% between them, and they need opposite fixes. That is why no single "over-park fix" was ever going
to work.

**The standing suite separates them almost perfectly**: 24/26 vouched in the too-strict bucket,
1/17 in the no-oracle bucket. It is a free classifier for which failure you are looking at, and it
only became visible because `oracle_record_all_legs` stopped the OR short-circuiting past it.

## Where it concentrates

| capability | n | delivery | over-park |
|---|---|---|---|
| robustness | 20 | 95% | 5% |
| refactor | 20 | 80% | 20% |
| feature | 35 | 71% | 29% |
| bug-fix | 25 | 48% | 44% |
| non-behavioural | 20 | 45% | 55% |
| **greenfield** | **20** | **10%** | **65%** |

Over-park is concentrated, not diffuse: MCB-02 over-parks 5/5, MCB-26 5/5, MCB-19 4/5, while nine
cases never over-park at all.

## What the refusing assertions actually said

All 26 read individually. Classified by hand, because the regex classifier built for this fires on
4.2% of them (see *Instrument trust* below).

**1. The Proctor's own test code is defective — 8 (31%)**

```
NameError: name 're' is not defined                       # missing import
assert "<!DOCTYPE html>" in content.lower()               # UNSATISFIABLE by construction
assert len(open_tags) == 0                                # hand-rolled parser counts <meta> unclosed
PosixPath('style.css').exists()                           # relative path, non-hermetic
python -m journal add  -> returncode 1, ModuleNotFoundError # wrong invocation context
```

Note how few are catchable by exception class. The unsatisfiable DOCTYPE comparison, the broken tag
parser and the relative path all raise `AssertionError` like any honest failure.

**2. Invented incidental detail the Coder invented differently — 5 (19%)**

Exact stdout, output ordering, and `Expected exactly 3 files, but found 4` — broken by a `README.md`
the task never forbade. Two equally valid choices; the bar refuses because they differ.

**3. Our own scaffold's decomposition bar — 4 (15%)** — see below.

**4. Wrong computed expected value — 3 (12%)** — e.g. `mean == 3.125` where the answer is 2.875.

**5. Encoded the OLD buggy behaviour — 3 (12%)**

```
assert current_result == 4   # This is wrong - should be 5
E  assert 5 == 4
```

MCB-19's brief says the implementation *undercounts by one* and must be fixed. The Proctor read the
repo to ground its imports, absorbed the bug as the contract, and asserted the buggy value — with a
comment admitting it was wrong. This is the **misguidance effect**: shown buggy code, a model
mistakes the bug for intent. Our Proctor is coder-blind but **not bug-blind**.

**6. Invented a requirement absent from the spec — 2 (8%)** · **7. Float exact-equality — 1 (4%)**

## The structural finding

> **The Proctor's output is the only artifact in the system that nothing verifies.**

The Coder's work faces review, critic, security scan, mutation testing, coverage, structural claims
and a deterministic gate. The Proctor's faces an assertion floor and red-verification.

**And red-verification cannot distinguish a broken test from an unbuilt feature.** A test with a
`NameError` fails. A test with an unsatisfiable assertion fails. Both are "red", indistinguishable
from "red because the feature does not exist yet". The one gate on the Proctor passes defective tests
by construction.

## A defect we own: the decomposition bar

`refactor_scaffold.py` emits, as its red phase:

```python
def test_decomposition_happened():
    assert _module_level_functions(_real) > _module_level_functions(_frozen)
```

The premise — *"a real refactor adds module-level helpers"* — is false. A correct refactor may extract
into a method, nest a helper, move code to another module, or simplify without extracting.

Worse, it fires on tasks that are not decompositions at all. The scaffold arms on
`is_behavior_preserving(task)`, and a version bump *is* behaviour-preserving — so MCB-30 and MCB-32
received a decomposition bar for work that decomposes nothing, producing `assert 2 > 2` four times.

**Arming is not the bug.** "Behaviour-preserving" and "is a decomposition" are different predicates,
and the scaffold treats the first as implying the second.

## Configuration note that changes an earlier reading

`reduced_lane` and `inert_oracle_scaffold` both default `False` and are **not** in
`apply_oracle_posture`. This sweep therefore ran with **ADR-0124's lane OFF**.

MCB-30/31/32/33's poor showing is consequently *not* a verdict on ADR-0124 — those cases were
measured without the mechanism built for them. An earlier draft of this analysis claimed ADR-0124's
delivery figure "did not survive"; that claim compared a lane-ON measurement against a lane-OFF
sweep and is withdrawn. What the sweep does show is a real defect in the **default** configuration:
with the inert lane off, the refactor scaffold takes over and plants an unmeetable bar.

## Instrument trust — three corrections earned in one day

1. The shipped over-strictness detector fires on **4.2%** of the runs it was built for, versus 2.8%
   on clean deliveries — no signal, against a claimed 30% recall measured on a self-labelled corpus.
   It checks exception-message pins and type-name strings; the real failures are broken helper code,
   invented details, and wrong expected values.
2. The first `BAR` gate-reason set used for this analysis counted 6 `tests_tampered` runs as
   over-strictness. Different mechanism; corrected above.
3. A misguidance hypothesis derived from MCB-19 predicted bug-fix would over-park most. **Falsified**
   — bug-fix sits mid-pack at 44%; greenfield is the problem at 65%. The mechanism is real and
   visible in MCB-19; it is not the driver.

The new instrument explains **75%** of the bucket (27 of 36 pre-correction); the blind runs are
dominated by `tests_tampered`, where no assertion failed at all.

## What follows

Ordered by leverage, and each attacks a class measured above rather than a class imagined:

1. **Stop planting the decomposition bar on non-decompositions.** Deterministic, entirely ours,
   15% of the dominant bucket. Deny-by-default: when the scaffold cannot confirm the task requests
   decomposition, it declines and the Proctor authors as usual — the contract the module already
   states for every other uncertainty.
2. **Ask on standing-suite disagreement.** Measured 31/34 = 91% precision on the trigger "authored
   bar refused AND standing suite vouched". Ships nothing; converts a silent, mislabelled park into
   a question. Not a widening of the acceptance class (ADR-0062) because nothing advances on it.
3. **Fix the contract before both parties invent it.** Greenfield is 65% over-park because the
   Proctor and Coder independently invent file layout, output format and ordering. The design stage
   should commit to those and both should work from them.
4. **The no-oracle bucket (31%) needs its own fix** — concentrated in MCB-26/30/32, and ADR-0124
   territory rather than an over-strictness problem.

The false-vouch rate behind item 2 is **3/97 (3.1%)**, not the 0/48 an interim read suggested. And
the corpus contains only 7 incorrect trees in 150 runs, so that rate is weakly tested — the case
where a standing suite vouches for subtly wrong work is barely represented here. Item 2 is safe
because it only *asks*; the failure mode of a wrong ask is a wasted review, not a false ship.

---

## FIX 1 LANDED — the decomposition bar (validated)

`scaffold_if_refactor` now requires `requests_restructuring(task)` in addition to
`is_behavior_preserving(task)`. When the trusted task does not ask for the code's structure to
change, the scaffold declines and the Proctor authors as usual — the deny-by-default contract the
module already states for every other uncertainty.

Declining is the correct refusal rather than emitting the differential test alone: without a red
phase the golden-master is GREEN on an empty diff, which would trade a false park for a false ship.

A bare "refactor" still arms it. The predicate is a **conjunction** with the preservation check, so
adding signals can only bring it closer to today's behaviour and never arms more than today did.

### Measured, n=5 per case

| case | before (0.6.3 sweep) | after | `_module_level_functions` in output |
|---|---|---|---|
| MCB-30 comment fix | 1/5 delivered, 4 over-park | **5/5 delivered, 0** | gone |
| MCB-32 version bump | 1/5 delivered, 4 over-park | **4/5 delivered, 1** | gone |
| MCB-14 real refactor (control) | 5/5 delivered, 0 | 3/3 delivered, 0 | gone |

Pooled on the two affected cases: 2/10 → 9/10 delivered, Fisher exact two-sided **p = 0.005**.
The control is unaffected, so this is not "fixed by deleting a working control".

Unpaired — "before" comes from the sweep — but nothing changed between the arms except this guard.

### A green-by-vacancy near-miss worth recording

The first version of the tests passed a `None` workspace to `scaffold_if_refactor`. It raised, the
function's bare `except Exception` swallowed it, `[]` came back, and **all 13 tests passed with the
guard deleted**. The suite proved nothing.

The fix was a fixture that can genuinely author (a root-level module plus a test importing it with
literal inputs) plus an explicit control — `test_the_fixture_really_can_author__otherwise_everything_
below_is_vacuous` — asserting the scaffold DOES author on a decomposition brief, so a `[]` elsewhere
means the guard refused rather than the scaffold merely failing. With the guard removed, 3 tests now
fail.

This is the sixth defect class in `mosaera-defect-classes` (green-by-vacancy) reproduced by the
person documenting it, in the same session, while fixing a different instance of it.

---

## FIX 2 — `case_impossible` — CORRECT, NO MEASURED EFFECT

`check_case_impossible` detects an assertion no implementation can satisfy. It is unit-proven,
cannot false-positive (a theorem, not a heuristic), and is wired into the real pipeline.

**It did not move MCB-02.** Three runs after landing it: 0/3 delivered, 3/3 over-park,
`overstrict_findings: []` on every one. The impossible DOCTYPE assertion appeared **once in eight
runs** and did not recur — the Proctor writes different tests each time, so the shape is a long tail
rather than a driver.

Recorded as a null. The check is worth keeping (it is free, exact, and the failure it prevents is
unrecoverable when it happens) but it is not a fix for over-park, and its actuator — the ADR-0058
repair pass — is itself unproven at p=0.51.

### What MCB-02 actually keeps doing

Across eight runs the recurring defect is one shape, and it is not over-strictness:

```
assert os.path.exists(ref)      -> Local reference '#about' does not exist
assert Path(href).exists()      -> Referenced asset mailto:info@... does not exist
assert current_files == {...}   -> a README.md the task never forbade
```

**The Proctor writes a link checker that does not understand URLs**, taking every `href`/`src` and
asserting it exists on disk — anchors and `mailto:` included. Three of eight runs.

The general shape: on a deliverable with no natural test harness (HTML, CSS, SQL), the Proctor must
author *verification infrastructure* — a parser, a link checker, a validator — and that
infrastructure is unreviewed, untested code that is wrong. This is the same root as §"The structural
finding": the Proctor's output is the only artifact nothing verifies, and here it is not an
assertion but a whole program.

**No detector fixes this**, and ADR-0085 forbids the case-specific ones anyway. The fix is to stop
requiring the Proctor to write infrastructure — supply a real HTML/link checker as a TOOL rather
than making a weak model reinvent one per run. That is a capability, not a guard, and it is not
attempted here.

## MCB-26 — a capability limit, not an oracle defect

A PostgreSQL schema task. All four legs read False on all five runs: no Proctor vouch, no standing
suite, no `test_cmd`, no structural vouch. The engine has no way to verify a `.sql` file with no
database in the sandbox, so **parking is correct** — the over-park label is right about the outcome
and wrong about the blame.

What is wasteful is *when* it learns this. `oracle_plan()` already computes "no leg can vouch" and is
used at onboarding; a run that cannot possibly be verified still executes plan → design →
author_tests → implement → test → review → critic before refusing at the gate. Five full budgets to
reach a conclusion available before the first model call.

The honest fix is an early, deterministic ask — "I cannot verify a SQL schema; give me a `test_cmd`
or accept an unverified delivery" — not a weaker oracle. Not attempted here: it is a routing change
in `graph/build.py` (a hot file) and deserves its own issue.

---

## FIX 3 — the two-bars ask, and the trust-boundary defect found underneath it

### The ask

`oracle_dispute.py` computes an operator-facing question when the authored bar refused a tree AND
the repository's own standing suite vouches for it. It is computed AFTER the gate decision, changes
nothing about it, and its entire surface is a sentence carried into the approval payload and the
durable receipt. A control may refuse to act, never to speak (ADR-0107). Not a widening (ADR-0062):
nothing advances on it, and the failure mode of a wrong question is a wasted review.

Red-teamed across 7 attack classes — non-string returns, tamper re-read as a wrong bar, firing on a
delivering run, hostile/raising/`None`/`1/0` standing-suite callables, truthy-not-True verdicts,
residual-extraction equivalence, and injection via a failing-test NAME. Clean.

### Why the headline number was wrong

Chasing why the ask fired 0/3 live exposed something worse. **5 of 7 greenfield runs in the sweep
reported `standing_suite=True` — on repositories that start EMPTY.** A pre-existing suite cannot
exist there.

The cause: `plan_node` guarded its ADR-0036 baseline capture with

```python
if not state.get("integrity_baseline"):
```

and a repo with no tests baselines to `{}`, which is **falsy**. "Captured, and there was nothing"
and "not captured yet" were the same value. So on every gate-deny re-plan the guard fired again and
re-baselined a tree the Proctor and coder had already written to — recording the authored suite as
PRISTINE. The code's own comment forbids exactly this: *"we must never re-baseline a tree the coder
has already touched, or a real tamper would be silently absorbed."*

**Blast radius: repos that begin without tests.** A brownfield baseline is non-empty and truthy, so
the guard held there. Greenfield is also where the coder can write anything, so the hole sat on the
trees least able to survive it.

Fixed by guarding on `integrity_enumerator or integrity_baseline` — the enumerator is a non-empty
constant stamped in the same state update, so its presence is unambiguous. Kept as an OR so a caller
carrying only the older marker still skips: the fix ADDS a way to be sure rather than replacing one.

### What this does to the measurement

The 24/26 standing-suite signal is **contaminated on greenfield**: those vouches were the Proctor's
own re-baselined suite agreeing with itself. Excluding greenfield, the signal is **19/19 on
brownfield** — still strong, and now honest about where it applies. The 91% trigger precision should
be re-derived on a post-fix sweep before being quoted again.

The ask is therefore **shipped and unvalidated live**: it is unit-proven, red-teamed and wired into
the payload, receipt and bench card, but the corpus that motivated its threshold was measuring a
partly circular signal. It only asks, so the risk of shipping it unvalidated is a wasted review.

---

## FIX 4 — the static-site testkit — ADOPTED, AND A REGRESSION

The diagnosis said: on a deliverable with no natural harness the Proctor authors verification
INFRASTRUCTURE, and that infrastructure is wrong. All ten MCB-02 failures across two sweeps were
bugs in its own helpers, never in the page. So: hand it correct, tested helpers instead.

`statickit.py` is stdlib-only, 44 tests, copied VERBATIM into the workspace as `tests/_statickit.py`
(the frozen-copy pattern, so the code our suite exercises is byte-for-byte the code the authored
tests import). It replaces every measured defect: `is_local_ref` for the `#about` / `mailto:` class,
`unclosed_tags` for the void-element class, `has_doctype` for the case-folding class, `text_of` for
the missing-`re` class, and an explicit required root for the non-hermetic-path class.

### Measured on MCB-02, n=4

| | delivered |
|---|---|
| v063 (pre-arc) | 0/5 |
| v064 (no kit) | **4/5** |
| **kit ON** | **0/4** |

**Adoption was NOT the problem — 4/4 runs used the helpers.** The problem is how:

```
>   assert has_doctype(html_content), "HTML must have a doctype declaration"
E   NameError: name 'has_doctype' is not defined
```

The Proctor read the guidance, called the function, and **did not import it** — reproducing the
exact defect class that motivated the whole exercise (`NameError: name 're' is not defined`).

### The lesson, which is the same lesson

Handing a weak model a library it must remember to import reproduces the forgot-the-import defect.
This was a PROMPT-LEVEL lever, the fourth in this arc, and like the other three it did not work —
except this one actively made things worse, which the other three did not.

Every intervention that HAS worked here removed the model's discretion rather than asking for
behaviour: the engine authoring the oracle (ADR-0124), the scaffold declining to plant a bar it
cannot justify, the baseline guard. The version of this idea that would work is the same shape —
the ENGINE writes the static-site test file with the imports already correct, or the helpers arrive
as `conftest.py` fixtures needing no import at all. Neither is attempted here.

**Knob `static_testkit` ships default OFF and stays off.** The helpers themselves are correct and
tested and cost nothing sitting unused; what is disproven is the delivery mechanism, not the code.
