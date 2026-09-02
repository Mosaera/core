# ADR-0036: Test integrity — the coder can't make validation go green by weakening it

- Status: accepted
- Date: 2026-07-14
- Owners: Alejandro Rengifo
- Completes: [ADR-0026](ADR-0026-tamper-to-escalation.md) (declares the signal ADR-0026 emitted into a dropped channel)
- Closes the residual of: [ADR-0034](ADR-0034-only-executed-evidence-may-ship.md) (a `"suite"` is only trustworthy if the coder didn't weaken it)
- Related: [ADR-0012](ADR-0012-cohesive-team-supervision.md) ("a failing existing test is a STOP"), [ADR-0013](ADR-0013-adding-an-agent.md) (the tester's protected-test guard)
- Related threat model: docs/threat-models/TM-0001
- Completed by: [ADR-0044](ADR-0044-oracle-make-real.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.
- Extended by: [ADR-0087](ADR-0087-test-contracts-and-renegotiation.md) — back-link added 2026-08-18 by the doc-accuracy pass
  (`docs/audits/adr-corpus-review-2026-08-18.md`); the forward link was already declared there.

## Context

ADR-0034 narrowed autonomous delivery over a silent reviewer to require
`validation_strength == "suite"` — a real test suite ran and passed. That is only sound if
the coder cannot *manufacture* that evidence. It can, and the exploration for this change
found the manufacturing surface is wide open:

- **The coder has no write-scope restriction.** Only the *tester* is confined to `tests/`
  (`build.py:121`); the coder's `protected_paths` holds tester-*authored* files only, and the
  tester is **off by default**. So the coder may freely edit or delete any pre-existing test,
  or write `pyproject.toml` / `pytest.ini` / `setup.cfg` / `tox.ini` / `tests/conftest.py`.
- **The pytest invocation pins nothing** (`languages/python.py:166-177`): the argv is
  `[interp, "-m", "pytest", "-q"]`. No `-c`, `--confcutdir`, or `-o`. The workspace's own
  `addopts`, `testpaths`, and every `conftest.py` are honored.
- **There is no collected-count check anywhere.** `SandboxResult.ok` is `exit_code == 0`
  (`sandbox/_base.py:76-78`). Total erasure fails red (pytest exit 5), but **partial**
  suppression is invisible: `addopts = "--ignore=tests/test_acceptance.py"` while one trivial
  test still collects → exit 0 → `tests_passed=True`, `strength="suite"`. Going from
  "12 passed" to "1 passed" is silent.

So three vectors reach a green `"suite"` the coder never earned: edit a test, delete a test,
or shrink collection via config/`conftest`. Only the first touches a test file.

Separately, ADR-0026's tamper→escalate rule **never fired in production**. It wrote
`result["tests_modified"] = True` and asserted *"It merges into the terminal `final` state
automatically (LangGraph state reducer) — no plumbing."* That is false: `tests_modified` was
never declared in `RunState`, and LangGraph silently filters undeclared keys
(`langgraph/graph/state.py:1449`). The rule read a key the graph always dropped. Its unit
tests hand-built the state dict, so the break was invisible.

## Decision

**1. Baseline the integrity surface from the pristine clone, once, at run start.** A new
`integrity_baseline(workspace)` (`mosaera_core/testintegrity.py`) snapshots, by content hash:
every pre-existing **test file**, every **`conftest.py`**, and the **pytest section** of each
root config file. `plan_node` is the graph entry (`START → plan`) and runs before the coder's
first write; it takes the snapshot into a new `RunState.integrity_baseline`, guarded on
absence so a gate-deny re-plan never re-baselines a tree the coder has already touched.

**Why the pytest *section*, not the whole config file:** a legitimate run adds a dependency to
`pyproject.toml`. Hashing the whole file would false-park it — exactly the class of bug commit
`217d735`'s regression corpus exists to prevent. Config files contribute only their
`[tool.pytest.ini_options]` / `[pytest]` / `[tool:pytest]` section; a `conftest.py` (executable
collection logic) contributes its whole content. A newly-created `conftest`/pytest-config is
itself flagged (a fresh `collect_ignore` is a suppression vector that edits no baselined path).

**2. Detect at `test_node`, extending the existing tamper branch.** It already checked the
tester's `tests_baseline`; it now also checks `integrity_baseline` (excluding tester-authored
paths, which are created after the baseline and governed by their own guard). Any change sets
`tests_passed=False`, `stalled=True`, and — now on **declared** keys — `tests_modified=True`
and `tampered_paths`.

**3. A dedicated gate reason.** `evaluate_gate` gains `tests_tampered`, appended as the
`"tests_tampered"` `GateReason`. Because the reviewer-silence backstop requires
`core == ["reviewer_unknown"]`, a tamper reason riding alongside means it can **never** be
overridden autonomously — the run parks for a human. This is distinct from `validation_failed`:
a tamper is never the coder's to "fix" by finishing it, and the report names exactly which
paths were weakened so a human can judge it.

**4. Declaring `tests_modified` completes ADR-0026.** With the key in `RunState`,
`diagnose_bottleneck`'s rule 1b (`bench/escalation.py:58`) fires from a live run for the first
time — a tamper is attributed to the coder, not misread as a weak tester.

**On authorization (ADR-0012's "P3"):** the doctrine says a test may be edited "only when the
plan explicitly authorizes it," but no deterministic mechanism for that authorization was ever
built (it shipped as prompt text). This ADR does not build it. Instead, **a human at the gate
IS the authorization**: in guided mode the human sees which tests changed and approves or
denies; in autonomous mode the run parks rather than deciding for itself. That is sufficient
and avoids forcing every legitimate test-update task through an escalation round-trip.

## Consequences

- The three manufacture-a-green-suite vectors are closed for autonomous delivery: a tamper
  parks. A legitimate change (add a dependency, add a new source file + its test) does not
  trip it — guarded by unit tests that pin both the true-positives and the false-park cases.
- One canonical `is_test_file` predicate now exists; three divergent regexes can converge on
  it over time (not forced here).
- The first integration test that drives the **compiled graph** through a tamper — asserting
  `tests_modified` survives, the gate raises `tests_tampered`, `autonomous_resolution` parks,
  and `diagnose_bottleneck` returns `"coder"`. This is the test whose absence let the
  dropped-channel bug live.

## What this does NOT fix

The residual ADR-0034 named remains, one level down: a `"suite"` can still be the coder's
**own** tests, thin or self-serving. This ADR guarantees the coder didn't *weaken* the tests
the run was judged against; it does not guarantee those tests were *strong*. An independent
oracle (the tester, off by default; ADR-0027's arc) is still the real answer. And a coder that
creates a brand-new config file at the repo root mid-run to redirect `testpaths` to an empty
dir is only partially covered — total redirection collects zero and fails red (pytest exit 5),
but the general "new root config" case is flagged for `conftest`/known pytest files only.

## Amendment 2026-08-22 — the surface is FOUR named sets, and "test file" is the TARGET's definition

This ADR defined the surface as "every pre-existing **test file**, every `conftest.py`, and the
pytest section of each root config" and **never defined *test file***. The implementation used
pytest's DEFAULT naming (`test_*.py` / `*_test.py`). A target that sets `python_files` therefore had
**no test baselined at all**, and the producer could rewrite its own acceptance test undetected:

```
python_files = ["check_*.py"]
integrity_paths          -> ['pyproject.toml']     # the real test is absent
tamper after the rewrite -> []
```

That is `1f710222`'s headline claim still reproducing. That commit fixed which paths were
**enumerated**; it never fixed which of them **count**. `:90` of this ADR invited the convergence
("three divergent regexes can converge on it over time"); this is that work.

**"Test file" now means what the TARGET says it means.** `pytestconfig.resolve_naming` reads
`python_files` / `testpaths` from the four files already tabled here, in pytest's own precedence
order, taking the **first** file carrying a section — pytest does not merge them and neither may we,
since every extra baselined path is a terminal tamper park waiting for a regeneration. Untrusted
input, so the TOML read is hardened the way `recon/deps.py` is (ADR-0035: loud, never a crash).

**FOUR SETS, NOT ONE — the collapse this was scoped as is impossible.** Two live consumers of the
same call need opposite answers about the same file: `close_oracle_gap` requires a non-`test_`-named
helper IN (or its SHIP arm dies), while that same list becomes a pytest argv where a `.json` makes
pytest exit 4 — read, until recently, as "the mutation was caught". And putting fixtures under the
content-hash guard bricks a run on any fixture regeneration. So:

| set | meaning | width |
| --- | --- | --- |
| **S** `is_collection_control` | conftest + root pytest config | exact (unchanged) |
| **C** `TestSurface.collected` | what pytest actually collects | **exact** |
| **A** authorship | what the engine created this run | **exact — no safe side** |

*Precision on A, since the table overstated it:* there is no `authored_*` set-producer.
`authored_tests` is derived from the WIDE protection set and then narrowed per consumer
(`persist` and `eligibility` each apply their own rule, deliberately differently). So this is three
named functions plus a convention, not four functions — the distinction is real and enforced, but it
is not factored the way the row implies. Factoring it is successor work; claiming it was done is the
G-class defect this ADR keeps having to correct.
| **P** `protected_test_paths` | what a producer may not edit | **wide; over-inclusion is free** |

ADR-0081 recorded the smell before either defect landed: *"a single predicate serving both
[scrutiny and protection] is a smell."* Derived rule that keeps consumers simple: the baseline is
**C ∪ S**, and S is config-independent, so any consumer holding only the baseline recovers C as
`baseline − is_collection_control` — no workspace, and no second place that must know `python_files`.

**Verified once against pytest, never synthesised.** At `run_start_baseline`, on a cache miss only,
`pytest --collect-only -q` runs **with no path arguments** — ADR-0054 is explicit that synthesising
paths overrides the repo's own `testpaths`/`python_files` and was reverted by red team. Disagreement
between our reading and pytest's answer is **recorded**, not silently resolved. It is a drift
detector, not a gate: pytest failing to start is not evidence a repo has no tests.

**Fallback is explicit.** No config, an unparseable one, or a failed collect-only ⇒ pytest's
defaults, with `test_surface_resolution` recording *inferred* rather than *resolved*. Deliberately
unlike `security_listing`, which raises: that guards a source where no empty value is safe. Here a
defensible default exists, and an unprotected repo must not look identical to a protected one.

**Two gap defects closed at their dangerous consumers** — supersession may now only delete a
COLLECTED test (it calls `unlink()`, and the gap made a pre-existing human helper look
engine-authored), and the test-contract registry no longer claims first authorship of a non-test.

**HONEST LIMIT: non-Python targets have NO tamper protection.** The predicate is Python-only. The
seam is structured for a LanguagePack to supply its own, and JS/TS is not written. Stated here
rather than left implicit.

`INTEGRITY_ENUMERATOR` is `"3"`; in-flight runs are handled by the mechanism added in `8f102902`.

### Red-team round on the amendment (2026-08-22) — the parser is a FALLBACK, not the source

Two lenses, independently, found the same thing: **a hand-written model of pytest's config
resolution disagrees with pytest, and every disagreement failed the same way — protect NOTHING.**

| config an ordinary repo ships | pytest collects | we protected |
| --- | --- | --- |
| `testpaths = .` / `./tests` / `tests/*` | the tests | nothing |
| `python_files = tests/*.py` | the tests | nothing |
| `.pytest.ini` (pytest's hidden variant) | the tests | nothing, and it was not collection control |
| an EMPTY `pytest.ini` beside a populated `pyproject.toml` | the shrunken set | still claimed to guard the dropped test |

Plus a crash introduced in the same pass: `configparser` interpolates on ITEM ACCESS, so `log_cli_format =
%(asctime)s` — from pytest's own docs — raised out of `resolve_test_surface` and killed `plan_node`
on a repo pytest runs fine. And this repo lost two files, because its own `testpaths` is set.

**Fixed here (failure DIRECTION first, spellings second):**
- `interpolation=None` and the `dict()` inside the `try` — pytest's `iniconfig` does the same.
- **`testpaths` no longer narrows protection at all.** It decides where pytest looks *when given no
  arguments*, and ADR-0054 forbids us synthesising path arguments — so it never shapes a command we
  issue. Modelling it bought nothing and cost protection. A test outside `testpaths` is still a test
  someone can run explicitly.
- Anything else unmodellable widens to the whole tree. Over-protection is an honest park;
  under-protection is a producer rewriting its own exam undetected.
- `.pytest.ini` added to BOTH config tables; a section-less `pytest.ini` is authoritative (pytest:
  "always the source of configuration, even if empty").
- Separator-bearing `python_files` patterns match the whole path (pytest's `fnmatch_ex`).
- `security_listing`'s ignored-conftest bound used DEFAULT naming, so it was a no-op on exactly the
  repos it protects — now the target's naming.
- `test_surface_resolution` had **no reader anywhere**: an invisible control created in the commit
  that names that class. The delivery report now says plainly when the surface was inferred.

**ESCALATED, NOT PATCHED — the STOP rule.** Four rounds have now closed this class for one spelling
and left it open for the next. The successor makes `pytest --collect-only` (already run at
`run_start_baseline`) the SOURCE of the collected set and demotes this parser to the fallback for
when pytest cannot be asked. Note the prerequisite the round also found: that call must use the
repo's own interpreter the way `coveragemap` does, or it goes dark on any repo with a dependency.

**Deliberate asymmetry worth not "tidying":** `eligibility` keeps the default-naming predicate on the
authored half while `persist` drops it. Removing it from `eligibility` re-opens the path that
DELETES a human's test — the suite caught that within a minute of my trying it. There it fails
closed (a park stands), which is the right side for a control that calls `unlink()`.

**Also still open:** `python_functions` / `python_classes` are hard-coded defaults in five AST-level
sites, so the weakening measure behind the tamper excuse goes blind on a repo that sets them; and a
broad `python_files = *.py` baselines the source tree, turning an ordinary edit into a terminal park.
