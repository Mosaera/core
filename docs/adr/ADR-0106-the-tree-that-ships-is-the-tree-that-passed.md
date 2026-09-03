# ADR-0106 — The tree that ships is the tree that passed

- **Status:** accepted (owner-approved 2026-08-20, in-session)
- **Scope:** core + memory (Alembic 0032) · delivery spine · no trust-boundary change
- **Builds on:** [ADR-0003](ADR-0003-evidence-cache-work-packets.md) (tree-hash-keyed
  evidence — this gives the suite verdict the same key and a durable home) ·
  [ADR-0102](ADR-0102-delivery-spine-truth-up.md) (the delivery spine this adds a branch to) ·
  [ADR-0025](ADR-0025-behaviour-smoke-gate.md) ("green" must mean "works") ·
  [ADR-0056](ADR-0056-thrash-reducer-sensitivity.md) (the honest early park this deliberately
  does NOT reuse) · [ADR-0026](ADR-0026-tamper-to-escalation.md) (declared keys)

## Context — `tests_passed` was a fact about no particular tree

The delivery path did not guarantee that the tree it committed was the tree that passed. Two routes
reach `deliver` after a write with no re-validation:

- **`hygiene`'s autofix, on every Python delivery.** `hygiene_node` calls `autofix`, which runs
  `ruff check --isolated --select F --fix` and `ruff format` and **writes to the working tree**,
  then routes `→ scan → review → gate → deliver`. `--select F --fix` removes "unused" imports,
  which can change import side effects. This is the normal path, not an edge case.
- **The give-up diversion.** `review → quality_revise → implement` (the coder writes) `→ capture →
  supervise` (give up) `→ gate → deliver` carries a `tests_passed` from before those writes;
  `evaluate_gate` takes no `give_up_reason`. The human gate's `interrupt` opens the same window
  across processes, and `commit_all` does `git add -A` on whatever is on disk at resume.

Nothing ran after `commit_all` — every `run_plan` call site was enumerated and the deliver path had
none. So the guarantee was *"some tree, at some earlier point in this run, passed"*.

It compounds. Item branches are cut at the clone's current tip, so a red commit is **inherited by
every later item** — and the run-start baseline added the same day would then report those failures
as "already failing, not caused by this change", blaming nobody and making the red permanent.

Separately, that baseline re-ran the suite at the start of **every** run, including when nothing had
changed since the last measurement. The owner asked the obvious question: why measure at the start
at all, rather than keeping a verdict and inheriting it?

## Confirmed in the wild, 2026-08-20 — the day it shipped

Item 107 on LedgerCLI ("add a `--version` flag") reported **67 passed** and delivered `completed`.
The very next run's baseline found one of ITS OWN tests failing:
`tests/test_version_flag.py::test_version_flag_not_hardcoded_in_cli`.

Cause, evidenced end to end:

1. the coder wrote `action='store_true'` (single quotes — seen in the diff at the write gate);
2. `test` ran and passed on that tree — 67 passed;
3. `hygiene`'s autofix ran `ruff format`, which normalises quotes;
4. nothing re-tested;
5. `commit_all` committed the reformatted tree and the run reported success.

The delivered `cli.py` now holds `action="store_true"` — 232 double quotes to 5 single — while the
authored test asserts `"action='store_true'" in cli_content`. A delivery that reported success
shipped a tree failing its own suite, and the next run discovered it.

The repo had already met this exact ruff behaviour: `hygiene_node` carries "NEVER reformat the
engine's OWN protected tests (ADR-0068) … ruff's single→double quotes on the scaffold's `_CASES`
rewrites a BASELINED test". That lesson was applied to protected tests and nowhere else, so the same
mechanism went on to break a source file that a test asserts on.

Two faults, both real: the engine rewrote after validating (this ADR), and the Proctor authored a
bar that asserts a QUOTING STYLE rather than behaviour, which no formatter can leave alone
(**F86**; recorded as F53 here when first written, which was wrong — F53 is the Proctor WEAKENING a
bar it already committed, this is MIS-AUTHORING one. Fixed 2026-08-20 by the doctrine + detection
slice recorded in the [ADR-0085](ADR-0085-oracle-defect-detection-strategy.md) amendment). This ADR fixes the first. The second is what makes the first cheap to trigger.

## The first cut of this ADR shipped INERT — and one log line found it

The durable verdict was keyed on `Workspace.tree_hash`, whose own docstring says it is "the memo
key for WITHIN-RUN evidence reuse … run/process-scoped, so no cross-run staleness". It hashes
`(path, size, mtime_ns)`, and `git reset --hard` at run start rewrites every file the previous run
touched — so identical content got a different key on the next run and the verdict was recorded and
never reused. Every run kept re-measuring, which is the exact cost this ADR exists to remove.

Two consecutive live runs on the same tip both logged `suite-verdict: measured`, and no `reusing`
line ever appeared. Confirmed offline: a `reset --hard` on an untouched tree preserves the
fingerprint; dirty-then-reset changes it — which is every real run.

The liveness test did not catch it because it called twice in ONE process with no writes between,
so the mtimes were stable. It demonstrated within-process reuse and was reported as cross-run: the
"passes for the wrong reason" shape, inside the verification itself. The test now writes files, does
a real `reset --hard` + `clean -fd`, and only then asks again — and fails if the old key returns.

**Two keys, each used for what it guarantees.** Cross-run: git's own content hash (`HEAD^{tree}`),
with a dirty tree getting NO key, because the verdict describes the committed tree and at run start
— after the reset — that is exactly what the workspace holds. Within-run: the mtime fingerprint,
which is correct for the delivery backstop, where a changed mtime inside one process means
"somebody wrote", which is precisely the question being asked.

## Decision

**1. One verdict, keyed by the tree it measured.** `project_suite_health` (Alembic 0032) holds
`{tree_hash, verdict, failing[], run_id, measured_at}` per project. A verdict is a fact about a
specific repository state, so the store refuses to return one for a different tree.

This is Bazel's rule — an action is indexed by a digest of its inputs, and unchanged targets are
never re-run — and the same rule this codebase already applies to `evidence_memo` (ADR-0003), given
a durable home so it outlives the run that computed it. Run start consults it: same hash → **no
suite run at all**; different hash (a delivery, an external merge, `check_base_drift`'s
fast-forward) → measure and record.

**2. Written where it is measured, not at run end.** `persist_run` is reached only from
`deliver_node`, so a resilient-sweep give-up, a cancelled run, a crash, or a park nobody answers
records nothing — and those are the runs whose knowledge is most worth keeping. Writing at the
measurement point makes the fact durable before the run's fate is decided.

**3. The verdict is bound to its tree, and checked before the commit.** `test_node` records
`verified_tree`. `deliver_node` compares it to the tree it is about to commit: equal → the green
binds and nothing runs; different → re-measure; red → do not deliver.

**4. Red work is QUARANTINED, not discarded.** A failing tree is committed to
`mosaera/quarantine-<run-id>` and the item branch is left where it was — still green, still the tip
every later item is cut from. The run records `approved=False` with the failing tests and the branch.

This is the merge-queue answer: [Zuul](https://zuul-ci.org/docs/zuul/latest/gating.html)
speculatively tests against the future state and, on failure, re-tests the rest *without the
offender*. Dropping the batch was never the practice, and it is a worse trade here than it looks —
uncommitted work is swept by `reset --hard` + `clean -fd` at the next run's start, so "refuse to
commit" would have destroyed a paid-for run rather than isolating it.

**5. `hygiene` re-tests when it rewrote the tree.** `autofix` already returned whether it changed
anything; the value was discarded. It now routes `hygiene → test` through the existing spine, so an
autofix-induced regression reaches the fix loop where the coder can repair it, rather than being
refused at the door. Checked *after* the residual-findings branch: a tree that still needs a coder
edit will be re-tested when that edit lands, and testing it twice buys nothing. `autofix` is
idempotent, which is the loop's termination bound.

## Consequences

- An unchanged tree costs **nothing** at run start; the common case gets cheaper, not dearer. The
  binding constraint for agent-driven systems is CI cost and speed, so a verdict already held must
  not be re-earned.
- The delivery backstop costs one suite run **only when the tree moved after validation**, which
  after (5) should be rare. When it fires, something genuinely unexpected happened.
- A red delivery no longer poisons the stack, and no longer destroys the work either.
- **Honest tri-state throughout.** An unreadable validator is `unknown`, never `failed`; a missing
  green (`validation_unavailable`, `deliver_unverified`) means the backstop stays silent rather than
  manufacturing a verdict. A control that fired on its own blindness would be worse than the gap.

## What this deliberately does NOT do

- **It does not park on a red baseline.** An earlier cut did, and an end-to-end fixture refused it:
  "the suite is red and your job is to make it green" is the canonical task (`make run TASK="make
  the failing test pass"`). A red baseline is ordinary input; what it must never be again is
  unrecorded.
- **It does not retarget quarantined work automatically.** The recorded facts and the surviving
  branch are the prerequisite; who proposes the follow-up is a separate decision.
- **It does not speculate over stacked items** (Zuul's parallel model). The clone is linear and
  shared, so there is nothing to speculate over until items can run concurrently.
- **It does not narrow `test_cmd`.** An operator command like `pytest tests/test_foo.py` is stamped
  `strength="suite"` and counts as an oracle independence leg, so it both narrows what is measured
  and maximally strengthens how the gate reads it. Intentional per ADR-0034; recorded here, not
  changed.
