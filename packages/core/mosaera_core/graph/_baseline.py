"""Was the target repo's suite green BEFORE this run touched anything?

Nothing used to ask. `plan_node` snapshots `integrity_baseline` — content HASHES, for tamper
detection — and never runs the suite, so a failing count is uninterpretable: no human and no agent
can tell a regression this run caused from a repo that was already red.

Measured cost of that gap (run `20260820-185125-994a3d`, 2026-08-20): every validation reported
`35 failed, 35 passed`, three times identically, with the failures in PRE-EXISTING tests
(`tests/test_cli_add.py`, `AssertionError: 2 != 0` on a command the item never touched). The coder
wrote `cli.py` seven times, concluded "the failing tests are all due to environment issues (package
not properly installed)", and parked. The environment was fine; its own change had broken the CLI.
It spent ~$1.65 of $1.80 shadow arguing with the wrong file. Given nothing to distinguish the two
explanations, the producer invented one and nothing contradicted it.

This repo already enforces the precondition ON ITSELF — `tests/test_guard_liveness.py:101-104`:
"a suite that is already failing 'detects' anything". Target repos got no such rule.

Two deliberately small pieces:

**The baseline is a STOP, not a signal.** A red baseline routes `plan → gate` (ADR-0056/#51's
honest early park), so it costs one pytest run to discover instead of a whole run to fail at. It
must not go through `supervise`: an autonomous escalation auto-resolves to `rescope`
(`runner/_budget.py`), which against a red suite is an infinite wall.

**Regressions are named, not guessed.** A set difference over test ids — no model call, no
heuristic. `integrity_baseline`'s keys ARE the pre-existing test files, so a failing test's file
says whether it existed before the run; nothing extra needs storing.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from mosaera_core.seedcheck import seed_failures_from_output
from mosaera_core.testintegrity import (
    INTEGRITY_ENUMERATOR,
    integrity_baseline,
    resolve_test_surface,
)
from mosaera_core.validation import resolve_plan, run_plan

#: How much of the baseline failure list to put in front of a human. The full set is in the run's
#: transcript; the park message is a summons, not a report.
_NAMED = 5


def take_suite_baseline(ctx: Any) -> dict[str, Any]:
    """Run the EXISTING suite once and record whether it was green.

    Measured with the same planner, sandbox and interpreter the `test` node uses — deliberately.
    `seedcheck` measures its red phase under a THIRD interpreter (`sys.executable`,
    `install=False`) and is therefore structurally unable to see an interpreter mismatch; a
    baseline that disagreed with real validation would be worse than none.

    Returns `{"green": bool, "failing": [...], "read": bool}`. `read=False` means the output was
    unparseable — recorded as such rather than guessed at, because `None` and `[]` are different
    evidence (`seed_failures_from_output`) and collapsing them is the absence-read-as-fact class
    this repo keeps finding.
    """
    try:
        plan = resolve_plan(
            ctx.workspace,
            ctx.test_cmd,
            install=ctx.settings.sandbox_install,
            install_timeout=ctx.settings.sandbox_install_timeout,
        )
        outcome = run_plan(plan, ctx.sandbox, cwd=ctx.workspace.root)
    except Exception:
        # A baseline that cannot be TAKEN must never cost the operator the run. An unreachable
        # sandbox, an unbuildable plan, a daemon restart — none of those are evidence that the
        # repository is broken, and turning every one of them into a crashed run would trade a
        # blind spot for an outage. Unread, so nothing downstream claims to know what it does not:
        # `red_baseline_reason` will not park and `caused_regressions` will name nothing.
        return {"green": False, "failing": [], "read": False}
    if outcome.passed:
        return {"green": True, "failing": [], "read": True}
    failing = seed_failures_from_output(outcome.output)
    return {"green": False, "failing": failing or [], "read": failing is not None}


def red_baseline_note(baseline: Mapping[str, Any]) -> str:
    """What was ALREADY failing when the run began, as context — never as a stop.

    An earlier cut parked the run here. That was wrong, and an end-to-end fixture said so: "the
    suite is red and your job is to make it green" is Mosaera's canonical task, so a red baseline
    is ordinary input, not a fault. What it must never do again is go UNRECORDED — an unexplained
    failing count is what the producer filled with "environment issues" on 2026-08-20.

    An UNREADABLE baseline says nothing. A suite whose output could not be parsed has not been
    shown to be broken, and reporting it as broken would make the note fire on this code's own
    blindness rather than on evidence.
    """
    if baseline.get("green", True) or not baseline.get("read"):
        return ""
    failing = list(baseline.get("failing") or [])
    named = ", ".join(failing[:_NAMED])
    more = f" (+{len(failing) - _NAMED} more)" if len(failing) > _NAMED else ""
    return (
        f"{len(failing)} test(s) were ALREADY failing before this run started: {named}{more}. "
        f"Those are pre-existing, not caused by this change."
    )[:400]


def caused_regressions(
    baseline: Mapping[str, Any],
    integrity: Mapping[str, str],
    failing_now: Sequence[str],
) -> list[str]:
    """Failing tests this run BROKE: pre-existing files that were passing when the run began.

    A test is pre-existing when its file is in `integrity_baseline`, which is snapshotted from the
    pristine clone before the coder's first write — so the Proctor's newly authored tests are
    excluded by construction. That matters: an authored test failing is the *intended* red phase,
    and calling it a regression would make the message lie in the one place it must not.

    A set difference against what was ALREADY failing, not a green-baseline requirement. "The
    suite is red and your job is to make it green" is Mosaera's canonical task (`make run
    TASK="make the failing test pass"`), so demanding green would have refused the most common
    shape of work there is — caught by an end-to-end fixture whose contract test fails on purpose.

    Empty unless the baseline was READ. Without that, "was it passing before?" has no answer, and a
    confident list would be exactly the invention this module exists to prevent.
    """
    if not baseline.get("read"):
        return []
    files = set(integrity or {})
    if not files:
        return []
    was_failing = {str(t) for t in (baseline.get("failing") or [])}
    return sorted(
        {
            tid
            for tid in failing_now
            if str(tid).split("::", 1)[0] in files and str(tid) not in was_failing
        }
    )


def regression_note(regressions: Sequence[str]) -> str:
    """One line naming what this run broke, for the fix instruction and the escalation payload."""
    if not regressions:
        return ""
    named = ", ".join(list(regressions)[:_NAMED])
    more = f" (+{len(regressions) - _NAMED} more)" if len(regressions) > _NAMED else ""
    return (
        f"REGRESSION — your change broke {len(regressions)} test(s) that PASSED before this run "
        f"started: {named}{more}. These are pre-existing tests, not the acceptance tests for this "
        f"item; the fault is in the change, not in the environment or the suite."
    )


def _verdict_of(baseline: Mapping[str, Any]) -> str:
    """The durable vocabulary for a measurement. Unreadable is `unknown`, never `failed`."""
    if not baseline.get("read"):
        return "unknown"
    return "pass" if baseline.get("green") else "failed"


def record_verdict(ctx: Any, tree_hash: str, baseline: Mapping[str, Any]) -> None:
    """Persist a measurement as the project's verdict FOR THIS TREE. Best-effort.

    Written where the suite is measured rather than at run end: `persist_run` is only reached from
    `deliver_node`, so a cancelled run, a crash, a resilient-sweep give-up or an unanswered park
    would record nothing — and those are the runs whose knowledge is most worth keeping.

    Never fatal. A verdict that cannot be stored costs the NEXT run a suite run; a raise here would
    cost this one everything.
    """
    if ctx.memory is None or ctx.project_id is None or not tree_hash:
        return
    with contextlib.suppress(Exception):
        ctx.memory.record_suite_health(
            ctx.project_id,
            tree_hash=tree_hash,
            verdict=_verdict_of(baseline),
            failing=list(baseline.get("failing") or []),
            run_id=ctx.run_id,
        )


def known_verdict(ctx: Any, tree_hash: str) -> dict[str, Any] | None:
    """The recorded verdict for exactly this tree, in `take_suite_baseline`'s shape, or None.

    The store returns nothing on a tree mismatch, so a stale verdict cannot be read as a current
    one. `unknown` is deliberately NOT a cache hit — "we could not tell last time" is no reason to
    skip trying again on a tree that may since have become readable.
    """
    if ctx.memory is None or ctx.project_id is None or not tree_hash:
        return None
    try:
        row = ctx.memory.suite_health(ctx.project_id, tree_hash)
    except Exception:
        return None
    if not row or row.get("verdict") not in ("pass", "failed"):
        return None
    return {
        "green": row["verdict"] == "pass",
        "failing": list(row.get("failing") or []),
        "read": True,
    }


def _collect_only_drift(ctx: Any, predicted: Collection[str]) -> str:
    """Ask pytest what it ACTUALLY collects, and report any disagreement with our prediction.

    The predicate is parsed from the target's own `python_files`/`testpaths` — cheap enough for the
    hot path, but it is a REIMPLEMENTATION of pytest's resolution, and a reimplementation that
    drifts from the tool it models is the defect class this arc has paid for repeatedly. So it is
    checked once, here, where a sandbox already exists and the suite is already being run.

    NO PATH ARGUMENTS. ADR-0054 is explicit that synthesising explicit pytest paths OVERRIDES the
    repo's own `testpaths`/`python_files` — it was built, then reverted by red team, for exactly the
    reason this function exists. Only the additive `--ignore` is permitted.

    Returns "" when the two agree or when pytest could not be asked. This is a DRIFT DETECTOR, not a
    gate: it never changes the baseline, because pytest failing to start is not evidence that the
    repo has no tests. Its whole job is to stop a disagreement being silent.
    """
    try:
        plan = resolve_plan(
            ctx.workspace,
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "--ignore=.mosaera"],
            install=False,
        )
        outcome = run_plan(plan, ctx.sandbox, cwd=ctx.workspace.root)
    except Exception:
        return ""
    if outcome.passed is not True:
        # Exit 5 (nothing collected) or a collection error. Either way pytest did not answer the
        # question, so there is nothing to compare — see `mutation._never_collected` for why the
        # exit code, not the prose, is the thing to read.
        return ""
    seen = {
        line.split("::", 1)[0].strip()
        for line in (outcome.output or "").splitlines()
        if "::" in line and not line.startswith(("=", "-", " "))
    }
    if not seen:
        return ""
    missed = sorted(seen - set(predicted))
    extra = sorted(set(predicted) - seen)
    if not missed and not extra:
        return ""
    parts = []
    if missed:
        parts.append(f"pytest collects {len(missed)} file(s) we do not pin (e.g. {missed[:3]})")
    if extra:
        parts.append(f"we pin {len(extra)} file(s) pytest does not collect (e.g. {extra[:3]})")
    return "; ".join(parts)


def run_start_baseline(ctx: Any) -> dict[str, Any]:
    """The tamper hashes and the suite verdict for the tree this run starts on.

    The suite is only RUN when the verdict for this exact tree is unknown. An unchanged tree is
    free — the last run already answered the question, and re-asking it is the cost the owner
    rightly objected to. A tree that moved (a delivery, an external merge, `check_base_drift`'s
    fast-forward) has no recorded answer, so it is measured and recorded.

    Bazel's rule, and the same rule this codebase already applies to its own evidence cache
    (ADR-0003, `evidence_memo` keyed by `tree_hash`) — given a durable home so it outlives the run
    that computed it.
    """
    tree = _content_key(ctx)
    baseline = known_verdict(ctx, tree)
    reused = baseline is not None
    # SAY WHICH HAPPENED. The code-evidence control shipped earlier today was unverifiable from
    # outside until it printed one line, and a whole deploy was spent guessing whether it was live.
    # A cache that silently never hits and a cache that works look identical from every surface.
    if baseline is not None:
        seen = "green" if baseline["green"] else "red"
        print(f"  suite-verdict: reusing {seen} for {tree[:12]} — no suite run")
    else:
        baseline = take_suite_baseline(ctx)
        record_verdict(ctx, tree, baseline)
        state = "green" if baseline["green"] else ("red" if baseline["read"] else "unknown")
        n = len(baseline["failing"])
        print(f"  suite-verdict: measured {state} for {tree[:12]} ({n} failing)")
    surface = resolve_test_surface(ctx.workspace)
    # HOW the surface was decided, always recorded — an unprotected repo must never look identical
    # to a protected one. `resolved=False` means the target said nothing and pytest's defaults were
    # assumed; the drift note means our reading and pytest's answer disagree.
    note = surface.naming.note
    if not surface.resolved:
        print(f"  test-surface: INFERRED (no pytest config) — {note}")
    else:
        print(
            f"  test-surface: resolved from {surface.naming.source} {surface.naming.python_files}"
        )
    # ONLY on a cache miss — the same condition, and the same reason, as the suite measurement
    # above. The drift question is a property of the TREE ("does our reading of this repo's config
    # match pytest's?"), so a tree whose verdict was already recorded had its surface checked then,
    # and re-asking costs a sandbox round-trip per run to re-learn a fixed answer. It also keeps
    # "an unchanged tree runs nothing at all" true, which is a property the suite pins.
    drift = "" if reused else _collect_only_drift(ctx, surface.collected)
    if drift:
        print(f"  test-surface: DRIFT vs pytest --collect-only — {drift}")
    return {
        "test_surface_resolution": (
            f"{'resolved from ' + surface.naming.source if surface.resolved else 'inferred'}"
            + (f" · {note}" if note else "")
            + (f" · DRIFT: {drift}" if drift else "")
        ),
        "integrity_baseline": integrity_baseline(ctx.workspace),
        # Stamped in the SAME update as the baseline it describes, so a checkpoint can never hold
        # one without the other (ADR-0036 / the 1f710222 enumerator widening).
        "integrity_enumerator": INTEGRITY_ENUMERATOR,
        "suite_baseline": baseline,
    }


def _content_key(ctx: Any) -> str:
    """A CROSS-RUN key for the committed tree: git's own content hash. "" when there is none.

    NOT `Workspace.tree_hash`, whose docstring says exactly why: it hashes `(path, size,
    mtime_ns)` and is "the memo key for WITHIN-RUN evidence reuse … run/process-scoped, so no
    cross-run staleness". `git reset --hard` at run start rewrites every file the previous run
    touched, so identical content gets a different fingerprint on the next run.

    Measured on the live instance 2026-08-20: the verdict was recorded and then never reused —
    two consecutive runs on the same tip both logged `measured`, because the first had written
    files and the second's reset gave them new mtimes.

    **A dirty tree has no key.** The durable verdict describes the COMMITTED tree, and at run start
    — right after the reset — that is exactly what the workspace holds. If anything is uncommitted
    the verdict would not describe the commit, so it is neither read nor written rather than
    recorded against a key that means something else. Test-run detritus (`__pycache__`,
    `.pytest_cache`) is excluded by the clone's own `.git/info/exclude`, so a suite run does not by
    itself make the tree dirty.
    """
    try:
        repo = ctx.workspace.repo
        if repo.is_dirty(untracked_files=True):
            return ""
        return str(repo.git.rev_parse("HEAD^{tree}"))
    except Exception:
        return ""


def _stat_key(ctx: Any) -> str:
    """The WITHIN-RUN fingerprint: did anything change since the last node looked?

    `Workspace.tree_hash` is exactly right here and wrong for the durable verdict — it is
    mtime-sensitive, which inside one process means "somebody wrote", which is the question the
    delivery backstop asks.
    """
    try:
        return str(ctx.workspace.evidence_hash())
    except Exception:
        return ""


def delivery_check(ctx: Any, state: Mapping[str, Any]) -> dict[str, Any]:
    """Does the tree about to be COMMITTED still pass? `{}` when there is nothing to answer.

    The gate's `tests_passed` is a fact about the tree the `test` node measured, held in a channel
    nothing invalidates. Two paths then change the tree before `commit_all`: `hygiene`'s autofix
    writes and routes on without re-testing, and the give-up diversion reaches the gate carrying a
    verdict from before the coder's last writes (the human gate's `interrupt` adds the same window
    across processes). Nothing ran after `commit_all` at all.

    Returns `{"verdict": ..., "failing": [...], "tree": hash}` describing the tree ABOUT TO SHIP, or
    `{}` when the question does not arise:

    - the verified tree IS the current tree — the existing green binds, and no suite runs. This is
      the ordinary case and the reason the backstop is affordable;
    - `tests_passed` is not True (unavailable, or `deliver_unverified`'s coercion) — there is no
      green to invalidate, and manufacturing one here would be worse than the gap.

    An unreadable re-check yields `unknown` and must not be treated as a red tree.
    """
    if state.get("tests_passed") is not True:
        return {}
    verified = str(state.get("verified_tree") or "")
    current = _stat_key(ctx)
    if not current or (verified and current == verified):
        return {}
    baseline = take_suite_baseline(ctx)
    record_verdict(ctx, _content_key(ctx), baseline)
    was = verified[:12] or "?"
    print(
        f"  delivery-check: tree moved after validation ({was} -> {current[:12]}) — "
        f"re-verified {_verdict_of(baseline)}"
    )
    return {
        "verdict": _verdict_of(baseline),
        "failing": list(baseline.get("failing") or []),
        "tree": current,
    }


def stale_tree_reason(check: Mapping[str, Any], quarantine: str) -> str:
    """The operator-facing reason a delivery was quarantined instead of committed."""
    failing = list(check.get("failing") or [])
    named = ", ".join(failing[:_NAMED])
    more = f" (+{len(failing) - _NAMED} more)" if len(failing) > _NAMED else ""
    detail = f": {named}{more}" if failing else ""
    return (
        f"the tree changed after it was validated and now FAILS its own suite "
        f"({len(failing)} failing{detail}). It was not committed to "
        f"the item branch — every later item is cut from that tip, so a red commit there is "
        f"inherited by all of them. The work is preserved on '{quarantine}' and this run's failing "
        f"tests are recorded, so it can be retargeted rather than redone."
    )[:400]


def regression_fields(state: Mapping[str, Any], failing_now: Any) -> dict[str, Any]:
    """`{"regressions": [...]}` for the escalation payload, or `{}` when there are none.

    Absent rather than empty on purpose: an empty dict is truthy in JS and blanked the gate panel
    live (2026-08-07), so the escalation reached the operator and the screen that would let them
    answer it did not.
    """
    broke = caused_regressions(
        state.get("suite_baseline") or {},
        state.get("integrity_baseline") or {},
        list(failing_now or []),
    )
    note = red_baseline_note(state.get("suite_baseline") or {})
    return {
        **({"regressions": broke} if broke else {}),
        **({"already_failing": note} if note else {}),
    }


def regressions_in(state: Mapping[str, Any]) -> list[str]:
    """Regressions derivable from the CURRENT validation output on `state`.

    The failing ids are parsed from `test_output` rather than read from a state key: there is no
    RunState channel carrying them at the fix node, and inventing one would be the undeclared-key
    bug `check_state_keys` exists to catch (LangGraph drops it silently, so the caller reads a
    permanent empty and behaves as if the answer were legitimately "nothing").
    """
    return caused_regressions(
        state.get("suite_baseline") or {},
        state.get("integrity_baseline") or {},
        seed_failures_from_output(str(state.get("test_output") or "")) or [],
    )
