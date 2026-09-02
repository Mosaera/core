# ADR-0059: The coder reliability toolkit — tools, feedback, and discipline to converge (#55, arc #43)

- Status: accepted
- Date: 2026-07-18
- Owners: Mosaera core
- Related issue: #55 (coder reliability toolkit) — arc #43/#49; successor to #51 (ADR-0056) / #54 (ADR-0058)
- Related threat model: TM-0001 (updated — a new coder capability: sandboxed, read-only, network-off exec)
- Red-team: **DONE** (2026-07-18, P1, 3 refute-agents incl. a LIVE-Docker attack battery; NO security break,
  NO HIGH; 1 MED fixed (a hard total-probe cap), 1 LOW accepted; see §Red-team)

## Context

The full-posture re-baseline (#54 merged) measured **thrash_park ≈ 45%** — flat vs pre-#54. #54 fixed the
*bad-test* half of thrash (over-strict tests → relaxed → deliver); the dominant remaining half is the **coder
flailing blind**. Live evidence: **MCB-01**, a *trivial* greenfield "todo CLI", 3/3 `thrash_park` at ~11
min/run — the coder BUILT the app but couldn't match a one-space output-format detail and, with no way to
"just run a snippet and see", wrote **seven debug scripts into `tests/`** (dodging the anti-scratch guard by
naming them `test_*.py`) and never converged. Three root causes, all confirmed in the code:

1. **No sanctioned way to probe behaviour** — the coder's only run-code tool is the whole-suite `run_tests`,
   so it is forced to write debug files.
2. **It can't see the failure** — validation ran `pytest -q` with no `-vv`, so pytest *truncated* the exact
   expected-vs-actual diff.
3. **No convergence discipline** — the fix prompt was reactive ("fix the failing tests"), and the stall
   detector strips digits, so a failing-count *trend* (12→3 vs 12→12) was invisible.

## Decision

Give the coder what a strong engineer has, as **four deterministic levers** (owner-scoped: the coder toolkit
now, the honest-stop as the paired next arc). The goal is to convert coder-flailing thrash → `clean_deliver`.

### 1. A sanctioned read-only probe tool (`sandbox_exec`) — TRUST-BOUNDARY

`sandbox_exec(code)` runs a Python snippet in the sandbox so the coder OBSERVES behaviour
(`from pkg import f; print(repr(f(x)))`) instead of writing debug scripts. A thin wrapper over the existing
`sandbox.run([python, "-B", "-c", code])` primitive.
- **Containment = read-only probe.** A new `readonly_work` flag threads to the Docker mount (`:ro` instead of
  `:rw`); the writable `/tmp` tmpfs stays for scratch. The coder can import + run repo code but **cannot
  persist**, so the tool can never bypass the write-approval gate, `protected_paths`, or the ADR-0036 tamper
  guard. Network stays off. The subprocess backend can't enforce read-only, so it **fails closed** (raises
  `SandboxViolation`) and the tool reports itself unavailable there — never a writable exec.
- Anti-abuse mirrors the existing tools: output cap, a per-session identical-snippet repeat cap, activity
  telemetry. CODEOWNERS: `packages/policies/allowlist.py` (the `coder` allowlist) + `AGENTS.md` + the
  `CODER_TOOL_CAPABILITIES` drift map. Opt-in knob `coder_repl_enabled` (default ON), a ceiling like
  `delete_file`. The `_STUCK_HINT` / `coder_system` now direct probing here.

### 2. The coder can SEE the failure (`verbosity_assertions=2`)

The Python validation plan now runs `pytest -q -o verbosity_assertions=2 --import-mode=importlib`. This keeps
`-q`'s quiet whole-suite summary but shows the **full expected-vs-actual on a failing assertion** — plain
`-q` prints "Full output truncated, use -vv", hiding exactly the kind of single-space format mismatch that
sank MCB-01. **This is strictly better than the planned targeted `-vv` re-run**: no extra sandbox run, no
node-id parsing, no venv-interpreter complications — the diff is simply in the validation output the coder
already receives. Passing tests still print as `.`.

### 3. Diagnose-before-edit + a convergence signal (`coder_diagnose_loop`, default ON)

On a failing iteration, `fix_instruction` now (a) requires the coder to state a one-line
`HYPOTHESIS: <root cause>` and make ONE surgical change — moving the ADR-0017 "state the root cause"
discipline EARLIER (into every failure, not only a stall trip); and (b) shows the failing-count trend
(`Failing tests: 3 (was 8 — getting CLOSER)` / `NO change — find a different root cause`). The count is parsed
by a new `progress.parse_failing_count` (the one place counts are read back, since the fingerprint strips
digits) and carried in `test_failing_now`/`test_failing_prev` — also the seed the **honest-stop successor**'s
progress-based breaker needs.

### 4. The contract up front

`author_tests_node` now hands the coder the acceptance tests' **bodies** (capped, budget-shared), not just
their file names — so it codes to the exact asserted values/format instead of an imagined spec (the top
source of first-pass misses). The coder could already read the files; this surfaces them proactively.

Housekeeping: `Settings.from_env` split earlier; here the PM-capability surface moved to
`tools/repo/_capabilities.py` and the reason nodes to `graph/nodes_reason.py` to keep `factory.py` /
`nodes_impl.py` under the god-file ceiling.

## Options considered

- **Read-only probe (chosen) vs. match run_tests (rw /work).** Read-only is airtight: the probe structurally
  cannot persist, so it adds no write channel. rw would re-open the write-gate/protected-paths bypass for a
  marginal capability gain. (Owner chose read-only.)
- **`verbosity_assertions=2` (chosen) vs. a targeted `pytest -vv` re-run.** The re-run needs node-id parsing +
  the same venv interpreter the main run used (hard to reconstruct) + an extra sandbox run. The ini option
  gets the full diff for free.
- **Diagnose gate as a prompt (chosen) vs. a graph node / agent middleware.** `fix_instruction` re-enters the
  coder every failing iteration and is unit-testable; a node duplicates the existing `reason_node`, and the
  react-loop middleware has no "fix iteration" hook.
- **Coder toolkit first vs. all-thrash-in-one.** Owner scoped the toolkit (help the coder succeed) now; the
  honest-stop (bail early + honestly when it genuinely can't) is the paired successor.

## Security implications

The only new trust surface is `sandbox_exec`, and it is the SAME containment as the existing `run_tests`
(arbitrary code, throwaway cap-dropped container, network-off) MINUS the ability to write — read-only `/work`
means it can never persist, so it cannot weaken a test, mutate source outside the gate, or bypass approval.
The subprocess fallback fails closed. Levers 2–4 are prompt/output changes with no trust surface. → TM-0001.

## Red-team (DONE — 2026-07-18, P1 definition-of-done gate)

Target = `sandbox_exec` + its allowlist entry + the `readonly_work` mount. 3 refute-agents on distinct lenses:
persist/escape (a LIVE-Docker attack battery), fail-closed + flag-threading, and gating/cost/output. **No
security break, no HIGH, no FIX-NOW on the trust property.**

**Verified NO-BREAK:**
- **Persist / escape / network (live).** 32 attack snippets ran against REAL `mosaera-sandbox:dev` containers
  with `readonly_work=True`, plus a control (a `readonly_work=False` write DOES persist, proving the flag is
  what blocks). Every write class — `open('w')`, `pathlib.write_text`, append, `os.rename/replace`,
  `shutil.copy`, `os.remove`, `chmod/utime/setxattr`, `mkdir/mkfifo`, write THROUGH a `/tmp`→`/work` symlink,
  hardlink, `/work/../work`, `/proc/self/cwd`, `/proc/1/root/work` — returned `EROFS`. `mount -o remount,rw` /
  `unshare -m` blocked by non-root + cap-drop + no-new-privileges; the docker socket is not mounted; the
  network is `--network none` (`ENETUNREACH`); `/tmp` writes stay in the ephemeral tmpfs. The `:ro` bind mount
  enforces at the KERNEL mount boundary, so any process (the probe, its subprocesses, imported repo code)
  fails `EROFS` regardless of path tricks — the layers (`:ro`, `--read-only`, cap-drop, non-root,
  no-new-privileges, network-none) are independent.
- **Fail-closed + threading.** Every `SandboxWorker.run` honors `readonly_work` (Docker → `:ro`; Subprocess
  RAISES `SandboxViolation` as its first statement — no partial write); the tool catches only
  `SandboxViolation` (a real bug isn't swallowed); the flag defaults `False` everywhere so `run_tests` /
  `run_plan` / scan / recon keep the read-write mount; `run_setup` (install) never gets it; `-B` +
  interpreter translation intact. No path runs the probe writable.
- **Gating / output / disclosure.** The tool is coder-only + built only when `coder_repl_enabled` (the tester
  toolset omits `enable_exec` AND the tester allowlist lacks it — double-safe); its output is a `ToolMessage`
  to the coder's own loop and never reaches a deterministic trust decision (the failing-count parser + stall
  fingerprint read the SEPARATE validation output; `parse_yield` reads only `type=="ai"` messages;
  `parse_reviewer_verdict` reads the reviewer's state) — and the `:ro` mount even blocks planting a fake
  conftest for the validator to read; the container gets NO `-e` flags and no host env, mounts only `/work:ro`
  + `/tmp`, so the PAT / `MOSAERA_SECRET_KEY` / provider keys never enter it.

**1 MED — FIXED:** the identical-snippet repeat cap fingerprints with digits stripped (the known `run_tests`
repeat-guard class), so cosmetic variation (a renamed var) evades it → unbounded *distinct* probes (bounded
only by `coder_step_limit × max_iterations` — cost, not a security escape). **Fixed** with a hard TOTAL
per-run probe cap (`_EXEC_SESSION_LIMIT = 25`) so container cost is bounded regardless of how the snippet
varies; re-verified by test.

**1 LOW — ACCEPT:** `coder_system` names `sandbox_exec` even when `coder_repl_enabled` is off, so a coder on
a probe-disabled instance could waste one "tool not found" step. Self-correcting — the prompt already says
"if sandbox_exec is unavailable, fall back to run_tests" — and default-on, so gating the (woven) prompt text
isn't worth the churn. Documented residual.

**Verdict:** the trust property (a probe can run/import repo code but cannot persist, reach the network, or
escape) holds against every live vector; 1 MED cost-bound tightened, 1 LOW accepted. No further rounds.

## Consequences

- **Good:** the coder gets the probe, the exact diff, forced diagnosis, and the real contract — the toolkit
  aimed squarely at the coder-capability thrash the re-baseline exposed.
- **Follow-up:** the red-team disposition; the re-baseline (`mosaera-bench --all --repeat 3`,
  `MOSAERA_MODEL_ESCALATION=0`) measuring `thrash_park` ↓ / `clean_deliver` ↑, watching MCB-01/05; and the
  **honest-stop successor arc** (a progress-based no-convergence breaker — reading the failing-count trend
  this arc parses — that routes to `supervise` for a re-scope/escalate/honest-park decision instead of
  grinding to the cap, and labels a diagnosed give-up `honest_park`, not `thrash_park`).
- **Ops:** two knobs (`coder_repl_enabled`, `coder_diagnose_loop`, default ON); no migration; `sandbox_exec`
  is Docker-only.

## Amendment — 2026-08-09 (verb-arc slice 2.1): the probe now reports when it fell short

Slice 2's goal is *"close the largest **measured** harness gap."* It was not measured, and the
attempt to raise `sandbox_exec`'s ceilings surfaced why. Of the four ways the probe can fall short:

| degradation | visible to the coder? | recorded? |
|---|---|---|
| output truncated | yes — `combined_output` appends a marker | **no** |
| **timed out** | **NO** — partial output, no marker at all | **no** |
| unavailable (backend) | yes — an explanatory string | **no** (returned before any telemetry) |
| repeat / session budget | yes — a STOP directive | **no** |

**The timeout row was a correctness bug, not missing telemetry.** `outcome.ok` was False and the
return path ignored it, handing back whatever partial output existed. A coder could read a
half-finished probe as the complete answer and conclude the opposite of the truth — the tool
misleading its own user. It now says `TIMED OUT after Ns — output below is PARTIAL`, stated FIRST so
it cannot be missed under a wall of output. The partial output is still shown: it is evidence, just
labelled.

**Nothing reached a durable record.** `emit_activity` writes to the ephemeral LangGraph stream — no
checkpoint, no scorecard. So *"does the 30 s / 4 KB ceiling actually bind?"* had no answer. All four
degradations now count into a caller-owned map (the `coder_validation` ownership shape — not a
module global, so concurrent runs cannot pollute each other), reaching a declared RunState key and
the bench card.

**No ceiling was raised, and no knob was added — deliberately.** The original plan was to make the
four ceilings configurable so a raise could be A/B'd. That is speculative machinery: if the corpus
shows no ceiling binds, the right answer is no raise, and if one does bind, changing a constant on
evidence is a one-line diff. Raising a ceiling nobody had measured would have been F83's mistake
(naming a cause without measuring it) for the third time this week.

**Containment is untouched and that is the point.** `readonly_work=True`, `-B`, network-off, and the
fail-closed `SandboxViolation` on backends that cannot enforce read-only all stand unchanged —
verified structurally, since "raise the ceiling" never meant relaxing the mount. `sandbox_exec` was
extracted to `tools/repo/_exec.py` for the god-file guard (the same split `_read`/`_scratch`/
`_activity` already had); the extraction is behaviour-preserving.

**Red team (1 pass — an extraction plus advisory counting, no new capability):** R1 containment
properties and all four ceiling values unchanged. R2 each count is emitted *before* its STOP return
with nothing between, so counting cannot weaken a budget. R3 the timeout marker names only the
timeout value — no path, host or argv. R4 no `packages/policies` reader: the sink is advisory and
cannot route or gate. No findings.

**Owed:** the corpus measurement. Coverage limit stated honestly — the counts are pinned in
`test_node`, so a run that hand-raises from `capture` straight to `supervise` records nothing. That
UNDER-counts, biasing the ceiling question toward "no raise needed": the conservative wrong answer
rather than the dangerous one.

### Follow-up — 2026-08-10: the count needed a denominator

The owed measurement ran (52 runs, `--all --repeat 2`) and returned **zero degradations** — a result
that could not be read. *"The 30 s / 4 KB ceiling does not bind on this corpus"* and *"the coder
barely called the probe"* produce the same zero, and probe **invocations** were recorded nowhere:
`emit_activity` is ephemeral and `cost.calls` counts model calls, not tool calls. A count with no
denominator is not a measurement, and deciding whether a ceiling is worth raising is the whole
stated purpose of this amendment.

`exec_usage` (`{"calls": n}`) is now recorded on the same seam, as a **separate** map from
`exec_degradations` — not a reserved key inside it. Any-key-means-degraded would force every reader
to filter, and that implicit coupling is exactly what left verb-arc slice 3 reading state that was
never populated. Both maps are written together in `test_node`, so the under-count caveat above
applies to numerator and denominator equally and the *rate* stays honest even where the absolute
counts are low.
