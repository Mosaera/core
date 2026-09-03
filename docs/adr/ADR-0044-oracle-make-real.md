# ADR-0044: Make the oracle REAL — measure the suite, and require an INDEPENDENT one to ship

- Status: accepted
- Date: 2026-07-15
- Owners: Alejandro Rengifo
- Completes the residual of: [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (`oracle_verified` now gates, not cosmetic), [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (a `"suite"` was only trustworthy if it wasn't the coder's own), [ADR-0036](ADR-0036-test-integrity-baseline.md) (the coder can't weaken it — this adds: it must be INDEPENDENT and non-trivial)
- Re-tightens: [ADR-0031](ADR-0031-deliver-on-silence-with-deterministic-validation.md) (dropped the oracle requirement; this restores it, guarded so it doesn't re-introduce the ~75% false-park)
- Related threat model: docs/threat-models/TM-0001

> ## Amendment 1 (2026-08-06) — Phase 1c was single-syntax for a year
>
> The assertion floor below specifies *"a non-trivial assertion (not `assert True` / no-asserts)"*.
> It was implemented for the bare-`assert` statement only. `_asserts_something_real`'s call branch
> matched on the **callee name** and never examined arguments, so:
>
> | form | verdict (before) |
> |---|---|
> | `assert True` | rejected ✓ |
> | `assert 1 == 1` | rejected ✓ |
> | `self.assertTrue(True)` | **accepted** ✗ |
> | `self.assertEqual(1, 1)` | **accepted** ✗ |
>
> The intent was recorded here in July 2026; only one of the two syntaxes enforced it. **LedgerCLI's
> charter mandates `unittest`** — the syntax that slipped through — so on the product's own runs the
> floor was effectively absent, while the 42-file MCB bench corpus is entirely bare-`assert` and so
> could never have exposed it. *The instrument could not see the defect the product had.*
>
> Found live: run `20260806-191349-668b6a`, where the Proctor authored three bodies of
> `self.assertTrue(True)` and only a human reading the write-gate diff stopped it. The red phase
> (Phase 1a) could not cover it either — a vacuous suite still reds pre-implementation on a missing
> import, which is precisely the hole Phase 1c was written to close.
>
> **Fixed** by applying the rule the bare-`assert` branch already used to the call syntax: an
> `assert*`/`*raises` call whose positional arguments are **all literals** is trivial. Same
> structural, one-sided rule — no new detector class, per [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md).
> Measured: zero verdict deltas across 48 bench corpus files and 125 repo test files; zero false
> parks across 11 honest assertion patterns. Red-team 3 rounds — a tautology wrapped in a *call*
> (`assertTrue(bool(1))`) still clears the floor and is **ACCEPTED**: catching it needs constant
> propagation, i.e. the semantic evaluation ADR-0085 freezes, and the mutation check is the
> behavioural backstop.

## Context

A 3-agent audit of the oracle found a well-built skeleton with the load-bearing beam unplugged:

- **`oracle_verified` was cosmetic.** It was `bool(tests_baseline)` — "the tester wrote a non-empty
  file" — computed, serialized, shown to humans, then **`_resolve` never read it**. The autonomous
  silence-backstop shipped on `tests_passed is True AND validation_strength == "suite"`, which any
  suite satisfies — including the coder's OWN. A testless repo → coder writes `assert True` →
  `strength="suite"` → empty integrity baseline → reviewer silent → **ships**. Both ADR-0034 and
  ADR-0036 named this as "what this does NOT fix."
- **The suite's quality was never measured.** `oracle_verified` was existence, not strength: the
  red phase was never run (a tautological suite passed silently), and nothing checked the suite
  asserted anything real.
- **The reviewer-APPROVE path bypassed strength entirely** — a coaxed `APPROVE` shipped weak work.

The gold-standard oracle (the offline MCB grader) shows the property to preserve: it **refuses
run-controlled signals — on silence it says UNKNOWN, never trusts the coder.**

## Decision

Turn `oracle_verified` from an ASSERTION into a MEASUREMENT, and re-admit it into the decision.

- **Red phase (Phase 1a).** `oraclecheck.authored_suite_is_red` runs the tester's authored suite
  network-off against the PRE-IMPLEMENTATION tree. A test-first suite must FAIL there; a suite green
  with no code is tautological. `author_tests_node` records `tests_red_verified`.
- **Assertion floor (Phase 1c).** `oraclecheck.authored_suite_asserts_behaviour` — a static AST
  check that the suite makes a non-trivial assertion (not `assert True` / no-asserts; counts
  `pytest.raises`, `assertEqual`, …). Catches a suite that reds pre-impl only on a missing import
  yet asserts nothing once the module exists. Records `tests_assert_real`.
- **Independence (Phase 2).** `gate_node` computes `oracle_verified` as: the tester authored a
  red + asserting suite, OR a **pre-existing tamper-guarded baselined suite** exists (a non-empty
  `integrity_baseline` — the coder can't weaken it, ADR-0036, so it's independent) that both ASSERTS
  something real AND **references the changed code** (see Phase 2b below), OR an operator
  **`--test-cmd`**. Crediting the standing suite is what stops the gate false-parking brownfield.
- **Change-relevance (Phase 2b, module-reference heuristic).** The standing-suite credit now also
  requires the suite to actually REFERENCE the changed code — `standing_suite_is_independent_oracle`
  takes EVERY changed path, maps each changed non-test `.py` file to its module-PATH fragment
  (`pkg/parser.py`→`pkg/parser`, `pkg/__init__.py`→`pkg`), and credits only if some baselined test
  **IMPORTS** one of them (`oraclecheck._references_changed_module`). Closes **F1** (adversarial
  review): a real, asserting suite about UNRELATED modules used to credit `oracle_verified` for a
  change no test touched, so a brownfield change auto-shipped on a green-but-irrelevant suite. Coarse
  + deterministic (AST, no sandbox run), errs toward DENY. FOUR refuter rounds tightened it — each
  found a variant of the same name-collision, which is the case FOR the runtime-coverage successor:
  - **Path-based, not name-based (F-A / Finding-1).** Three cuts matched a bare *name* — any
    attribute access `x.<name>`, then any imported symbol `from x import <name>`, then a
    single-segment leaf. Names collide: attribute names / imported symbols / stdlib module names live
    in a DIFFERENT namespace from repo file names, so `app.config[...]` / `from django.conf import
    settings` / `import logging` credited a change to `config.py` / `myapp/settings.py` /
    `myapp/logging.py` from an unrelated suite. Fixed by reconstructing each import's module PATH and
    matching it against the changed file's path: MULTI-segment (`myapp/settings`) as a component-
    suffix (so `django/conf/settings` ≠ `myapp/settings`, and `src/`-layout still matches);
    SINGLE-segment (`logging`) ONLY as an exact or `src/`-rooted match (so a near-universal
    `import logging` can't match a nested `myapp/logging.py` — the stdlib-shadowing false-CREDIT).
    Residual coarseness: a same-package `from pkg import name` where `pkg/name.py` is changed but
    `name` is a symbol; and a repo importing its own nested module by bare name PARKS (safe). Line
    coverage is the precise fix.
  - **Behavioural non-`.py` changes DENY (F-B / Finding-2/3).** When no `.py` source changed, the
    reference check has nothing to match. Crediting on "no `.py` ⇒ moot" wrongly shipped behavioural
    non-`.py` changes (a `flags.json` / SQL-migration edit) on an unrelated suite. Now credit rests
    on 1 + 2 only when EVERY changed path is provably inert docs, classified by EXTENSION
    (`.md`/`.rst`/`.adoc`/`.markdown`) — NOT by a `docs/` path, so a `service/docs/flags.json` can't
    read as inert (Finding-3). `changed_files` also captures the diff's OLD side, so a DELETED module
    is visible (a delete-only + docs-edit change no longer flips to credit via the docs branch —
    Finding-2). Any behavioural non-`.py` change DENIES (parks); test-only / docs-only still credit.
  - Full line-level change coverage (catching "imports it but misses the changed line") and pure
    100%-similarity renames (invisible to the diff parser, finding F-C — narrow: a deleted module a
    test imports fails collection, so it can't reach the gate green) remain future work; the opt-in
    1b mutation check is the behavioural half.
- **The gate (Phase 3).** `evaluate_gate` adds a distinct `oracle_unverified` reason when
  `tests_passed is True AND strength == "suite" AND not oracle_verified`. Because the silence
  backstop requires `core == ["reviewer_unknown"]` and the all-clear approve requires `reasons ==
  []`, this reason disqualifies BOTH autonomous approve paths → park. No `_resolve` restructure.
  It fires on the reviewer-APPROVE path too (closing that bypass) and ONLY on `strength == "suite"`
  (testless/shallow projects are untouched — they never claimed a suite).
- **Mutation check (Phase 1b, opt-in).** `oraclecheck.suite_catches_a_mutation` — the cheapest real
  measure of "can this oracle FAIL bad code". On a GREEN run vouched by a suite, `test_node` applies
  ONE deterministic mutation to the coder's own changed source (`return X`→`return None`, else flip
  the first comparison operator), re-runs the vouching suite network-off, and ALWAYS reverts. If the
  suite stays green (the mutation SURVIVED) it is a rubber stamp → `tests_mutation_caught` is False →
  `gate_node` downgrades `oracle_verified` → `oracle_unverified` parks. Gated behind
  `oracle_mutation_check` (default OFF): it spends one extra sandbox run per green iteration, and a
  single surviving mutation on an incidental line is a weak signal — deny-by-default means only a
  proven-False downgrades; None (not run / inconclusive) never parks. Memoized by tree hash.

All measurement signals are deny-by-default (an unassessed check does not vouch).

## Consequences

- The dominant false-ship is closed: a testless repo whose green "suite" is the coder's own
  `assert True` now PARKS (no independent oracle) instead of shipping — on both the silence and the
  APPROVE path. WITH an independent oracle (tester / standing suite / operator cmd), silence still
  delivers, so ADR-0031's false-park is not re-introduced for the common case.
- `oracle_verified` now means "a suite that FAILS without the code and ASSERTS something real, and
  wasn't authored by the coder this run" — a measurement, not a file-exists check.
- Cost: the red phase adds one network-off suite run per tester-enabled run. Autonomous runs on a
  testless repo with only a weak/absent oracle now park — by design (the north-star: only executed
  INDEPENDENT evidence ships). `deliver_unverified` remains the explicit operator opt-out.

## What this does NOT fix

- The oracle is still LLM-authored (or a pre-existing human suite) — this makes it REQUIRED and
  MEASURED, but it is not the deterministic behavioural/property oracle (the north-star; future).
- **Change-relevance** now has a first cut: the Phase-2b module-reference heuristic (above, closing
  F1) requires the standing suite to import/reference the changed code. It is COARSE — it catches a
  suite about entirely unrelated modules, but not "imports the module yet misses the changed line"
  (that is line-coverage / the 1b mutation check). ~~Full line-level change coverage + the token-saver
  (author a delta only for uncovered lines) remain future work.~~ **Corrected 2026-08-18** (`docs/audits/adr-corpus-review-2026-08-18.md`) — runtime line coverage SHIPPED under ADR-0049 (`coveragemap.change_is_covered`, opt-in `oracle_coverage`); it now decides change-relevance and this module-reference heuristic is the FALLBACK. The token-saver was built and then DELETED — `test_graph_build.py` asserts `"gap_fill" not in nodes`.
- **Mutation-checking** (Phase 1b) landed as an opt-in refinement (above) but is a single-mutation
  signal, not full mutation testing; making it always-on and multi-mutation is future work once its
  false-park rate is measured.
- `testintegrity` remains Python-only (a Node repo's pre-existing suite isn't tamper-guarded yet),
  so the standing-suite credit is strongest for Python. Deferred behind the Python-first roadmap
  (don't derail into TS/JS early), tracked for Phase 4.
- **Landed (Phase 4, tester-collision guard):** `tampered_integrity` now subtracts the baseline from
  its `ignore` set, so a pre-existing baselined test is NEVER excused — the tester (or a coder via a
  colliding authored path) can no longer overwrite a protected test and have the overwrite excused by
  its own `authored_tests` list. `ignore` applies to newly-introduced paths only, matching its intent.
