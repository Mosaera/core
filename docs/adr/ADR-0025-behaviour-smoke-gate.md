# ADR-0025: Make "green" mean "works" — a behaviour-smoke floor + a tester integration-test doctrine

- Status: accepted
- Date: 2026-07-13
- Owners: Alejandro Rengifo
- Related: [ADR-0020](ADR-0020-autonomous-correctness-gate.md) (the correctness gate whose "LLM-authored tests are only as complete as the model made them" residual this narrows), [ADR-0013](ADR-0013-adding-an-agent.md)/[ADR-0015](ADR-0015-tester-contract-scope.md) (Proctor, the tester), [ADR-0007](ADR-0007-capability-benchmark-suite.md) (the benchmark that measures this)

## Context

The first live end-to-end autonomous build (the pyledger case study) delivered a CLI whose **25 unit tests all
passed while the tool crashed on real use** — `cli.py` handed a `str` to a storage layer that expected a `Path`.
The tests never crossed the module boundary: they validated the pieces the model controlled, not the behaviour a
user gets. This is the exact residual ADR-0020 flagged, now concrete — and it **generalizes to every project
type**: a web service that 500s on startup, a library with a broken public import, any deliverable whose "green"
comes from tests that never exercise the assembled thing.

The delivery gate's correctness signal is `tests_passed` (from the validation planner). Today the planner runs
`pytest` (+ syntax/HTML/config checks) but has **no step that actually starts the deliverable's entrypoint** — so
a deliverable that can't even run can still be green.

## Decision

Two complementary, general changes — neither touches the CODEOWNERS trust boundary (`packages/policies`).

### 1. A deterministic behaviour-smoke floor (`validation.py`)

> **Location note, 2026-08-18.** The floor still exists and still behaves as described, but it no longer lives in
> `validation.py`: [ADR-0032](ADR-0032-adding-a-languagepack.md) extracted the language-tied chain into
> `LanguagePack`s behaviour-preservingly, so `_behaviour_smoke_step` and `_implements_help` are now in
> `packages/core/mosaera_core/languages/python.py` (`PythonPack`), reached through `dispatch` rather than through
> `detect_validation_plan`'s own `if/elif`. Read every `validation.py` reference below as `languages/python.py`.
> Recorded in `docs/audits/adr-corpus-review-2026-08-18.md`.

`detect_validation_plan` gains a conservative entrypoint sniff (`_behaviour_smoke_step`): when the workspace has a
runnable entrypoint — a package `<pkg>/__main__.py`, or a top-level script that uses `argparse` AND guards
`if __name__ == "__main__"` — it appends a network-off `cli-smoke` step that runs `--help` (`python -m <pkg>
--help` or `python <script>.py --help`). `--help` exits 0 for a well-formed argparse CLI and has **no side
effects** (no writes, no network), so it's a clean "does it even start" probe that catches import errors, an
import-time crash, or broken argparse wiring. It runs in the **normal test phase** — the same hardened
`DockerSandbox` (`--network none`) that runs pytest; the planner is sandbox-agnostic. Because `run_plan` ANDs
every step's exit into `passed`, a failing smoke → `tests_passed=False` → the gate's existing `validation_failed`
→ the existing `fix` loop. **No gate/policy change** — it reuses the same tri-state as the existing `py-compile`,
HTML, and config-parse executed checks. Conservative by design: no confidently-detected entrypoint → no step
(never false-fail a fine library).

### 2. A tester integration-test doctrine (Proctor persona)
The `--help` floor catches "won't start" but not the deeper `str`/`Path`-class bug (which only crashed with real
args). So Proctor's persona is directed to author **≥1 integration test that drives the real surface end-to-end**
(run the command with real arguments + a temp data file and assert stdout/exit code; or import and call the public
entrypoint the way a user does) — on top of the unit tests — whenever the deliverable has a runtime surface. A
purely internal change (a library function, no entrypoint) still needs only unit tests. The fix-run's Proctor
already did exactly this once the item was about the CLI surface (25→28 tests); the doctrine makes it standard.

## Consequences

- **"Green" moves toward "works."** The floor makes a non-running deliverable fail deterministically; the doctrine
  pushes the (LLM-authored) acceptance suite across the assembly boundary where the real bugs hide.
- **General, not pyledger-specific.** Any Python package/CLI benefits; the `javascript` branch inherits the same
  pattern when the Node track lands; the shape (an executed behaviour step folded into `passed`) is language- and
  domain-agnostic.
- **Honest residual (narrows, doesn't close).** The floor is a floor — `--help` passing ≠ correct; the deeper
  coverage is still an LLM-authored test (per ADR-0020, only as complete as Proctor made it). The true
  independent oracle remains the benchmark's hidden grader (ADR-0007); a live equivalent is future work.
- **No trust-boundary or infra change.** `validation.py` + the tester persona only; `packages/policies/gate.py`,
  `graph.py`'s gate, and the sandbox image are untouched. *(As of 2026-08-18 the `validation.py` half of this
  sentence reads `packages/core/mosaera_core/languages/python.py` — see the location note above; the
  trust-boundary claim is unchanged.)*

## Alternatives considered
- **A new `behaviour_failed` gate reason.** Would let the gate *distinguish* a behaviour failure from a unit
  failure in its reason taxonomy — but that edits `packages/policies/gate.py` (CODEOWNERS `@Ashura`) + `AGENTS.md`.
  Rejected as unnecessary: folding into `tests_passed` gates identically and reuses the fix/stall machinery.
- **A deep auto-generated smoke (run real commands).** Rejected: there's no general way to know a correct
  invocation for an arbitrary CLI without false-failing; the *spec-aware* deep test is exactly the tester's job
  (change 2), while the deterministic floor stays a safe `--help`.

## Correction (2026-07-13): `--help` false-fails non-argparse CLIs

The original `_behaviour_smoke_step` smoked `python -m <pkg> --help` for **any** package with a
`<pkg>/__main__.py` — without checking the CLI framework (the top-level-script branch already
guarded on `argparse`, but the package branch did not). `--help` only exits 0 for a framework
that implements it (argparse/click/typer); a **hand-rolled `sys.argv` dispatcher** treats `--help`
as an unknown command and exits non-zero. So a *correct, fully unit-tested* package CLI was marked
broken purely because `--help` returned 1 — the exact "false-fail a fine deliverable" the function's
own docstring promised to avoid.

Impact (measured on MCB-01, local `qwen3-coder:30b`): the coder shipped a working, fully-tested
`todo` CLI, behaviour-smoke false-failed it, and the coder then looped against a phantom failure
until it **parked** — a ~4× token blow-up (196k baseline → 762k) and a **delivery regression**
introduced after this ADR merged.

Fix: gate **both** smoke branches on `_implements_help(src)` (source uses argparse/click/typer).
A non-framework CLI now gets **no `--help` floor** (its behaviour is the tester's integration-test
job) instead of a false failure. Deterministic regression tests pin it
(`test_handrolled_{package,script}_cli_gets_no_smoke`). `validation.py` only — no gate/policy/infra
change; the floor still catches import/syntax errors and broken argparse wiring for framework CLIs.
