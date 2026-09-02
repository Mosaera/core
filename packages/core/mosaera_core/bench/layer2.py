"""The bench's Layer-2 conversion attempt — and, since 2026-08-08, WHY it decided what it did.

Split out of `bench/cli.py` (which sat at the 500-line ceiling) when the decline reason was wired
through. The split is not incidental: the reason this module exists at all is that `cli.py` kept
only the *verdict* and dropped the evidence beside it.

`close_oracle_gap` returns a `DispositionResult` carrying `verdict`, `reason`, `green` and
`mutation_caught`. The caller kept the first and discarded the rest — so a card recorded
`unverified` with no way to tell apart:

- *"the delivered code fails the independent acceptance test"* — the authored test contradicts the
  delivery, and the park is right;
- *"the authored test does not catch a mutation of the change (not a real oracle)"* — the test is a
  rubber stamp;
- *"the mutation check was inconclusive"* — the oracle could not form a question at all.

Those mean opposite things about whether the mechanism, the test, or the change is at fault. On
2026-08-08 that cost two hours and a wrong conclusion: seven consecutive `unverified` verdicts on
runs the hidden grader PASSED were read as "the authored tests are too weak", when re-running the
real check on a parked workspace showed **inconclusive** — the delivered fix was a one-line
arithmetic change (`page * per_page` -> `(page - 1) * per_page`) and the mutation operators cover
returns, comparisons and bare calls, none of which appear on that line.

`mutation_caught` is the field that settles it: ``True`` caught, ``False`` survived (a proven rubber
stamp), ``None`` inconclusive. It was computed and thrown away the whole time.
"""

from __future__ import annotations

import shutil
from typing import Any, NamedTuple

from mosaera_core.agents_bridge import build_default_team
from mosaera_core.bench.cases import BenchCase
from mosaera_core.bench.faithfulness import POISON_SENTINEL
from mosaera_core.bench.grade import GRADER_DIR
from mosaera_core.bench.harness import RunOutcome
from mosaera_core.config import Settings
from mosaera_core.disposition import (
    close_oracle_gap,
    supersede_engine_tests,
    trapping_engine_tests,
)
from mosaera_core.models import get_chat_model
from mosaera_core.sandbox import create_sandbox
from mosaera_core.testintegrity import protected_test_paths
from mosaera_core.tools.repo import build_repo_tools
from mosaera_core.validation import resolve_plan, run_plan


class Layer2Outcome(NamedTuple):
    """What the conversion attempt decided, and the evidence for it.

    `verdict` alone is not a finding — `reason` and `mutation_caught` are what make an `unverified`
    actionable. Kept as a NamedTuple so adding a field cannot silently reorder a tuple unpack at the
    call site, which is how the evidence went missing in the first place.
    """

    verdict: str | None
    authored: tuple[str, ...] = ()
    superseded: list[str] = []  # noqa: RUF012 - positional default, never mutated
    reason: str = ""
    green: bool | None = None
    mutation_caught: bool | None = None
    source: tuple[str, ...] = ()  # the files the mutation check judged — the workspace is reaped
    # The changed-line set the real verdict used. The grader probe reuses it rather than
    # recomputing, so the two checks provably ask about the same lines (one origin).
    changed: dict[str, set[int]] | None = None


_NOT_ATTEMPTED = Layer2Outcome(None, (), [], "")


def assert_judgeable(ws: Any) -> str:
    """``""`` if this tree is the agent's own work product, else WHY it must not be judged.

    Two contaminants, both bench-only, both of which make the bench read SAFER than production —
    the dangerous direction for evidence used to decide whether to switch a mechanism on.

    **The answer key** (`_mcb_grader/`). Removed here; see `_purge_grader`.

    **The reference implementation** (`faithfulness.overstrict_vs_reference` overlays the correct
    solution over the delivered code and leaves it). That one is NOT removable — the delivered work
    is gone, overwritten — so the only honest response is to refuse. It was safe until now purely
    because it happened to run after the Layer-2 attempt in a dict literal; this makes
    ordering-independence a mechanism rather than a comment.
    """
    if (ws.root / POISON_SENTINEL).exists():
        return "the reference solution was overlaid on this tree — it is not the agent's work"
    if not _purge_grader(ws):
        return "could not purge the hidden grader from the workspace"
    return ""


def _purge_grader(ws: Any) -> bool:
    """Remove the hidden acceptance suite from the delivered tree before ANY Layer-2 step runs.

    `grade()` copies the answer key to ``<workspace>/_mcb_grader/`` and never removes it, and
    grading happens BEFORE the Layer-2 attempt. Two consequences, both measured 2026-08-09:

    1. The green step runs ``pytest`` at the workspace root with only ``--ignore=.mosaera``, so it
       COLLECTED the hidden suite. Layer 2's "the delivered code passes green" was, in the bench,
       partly "the delivered code passes the answer key".
    2. The tester authors with repo tools that can READ the tree — so the "independent" test could
       be copied from the answer key sitting next to it.

    The signature in the data was unmistakable: 6 of 7 grader-WRONG deliveries failed the green
    step and 0 of 6 grader-RIGHT ones did — a perfect separation produced by an authored test the
    same cards show is a rubber stamp 4 times in 7.

    This makes the bench flatter the mechanism: it grants Layer 2 an oracle production does not
    have, so the bench reads SAFER than production. That is the dangerous direction for a
    measurement whose purpose is deciding whether to switch the mechanism on.
    """
    target = ws.root / GRADER_DIR
    if not target.exists():
        return True
    try:
        shutil.rmtree(target)
    except OSError:
        return False
    return not target.exists()


def try_layer2_conversion(
    run: RunOutcome, case: BenchCase, settings: Settings, backend: str, cls: str
) -> Layer2Outcome:
    """Layer-2 (#76, ADR-0074/0075): on a convertible honest-park, run the REAL
    ``close_oracle_gap`` on the parked workspace — the tester authors an independent test from the
    case brief (the visible spec) and the deterministic green + comprehensive-mutation gate decides.
    For the ``engine_blocked_give_up`` class the trapping engine tests are SUPERSEDED first,
    mirroring the production rung, and the whole remaining suite must be green. Never raises: a
    fault becomes ``verdict="ERROR"`` so it cannot crash the sweep.

    The bench holds the HIDDEN grader, so the caller cross-tabs this verdict against
    ``grader.all_passed`` to detect a FALSE conversion (verified but the code is actually wrong)."""
    ws = run.workspace
    if ws is None:
        return _NOT_ATTEMPTED
    unjudgeable = assert_judgeable(ws)
    if unjudgeable:
        # Fail CLOSED. A measurement taken on a contaminated tree is worthless AND reads as a SAFE
        # result — the direction that gets a bad mechanism switched on. Decline, and say why.
        return Layer2Outcome(None, (), [], unjudgeable)
    try:
        sandbox = create_sandbox(
            backend,
            ws.root,
            image=settings.sandbox_image,
            docker_bin=settings.docker_bin,
            default_timeout=settings.sandbox_timeout,
            install_network=settings.sandbox_install_network,
            index_url=settings.sandbox_index_url,
            allow_install=settings.sandbox_install,
        )
        # Snapshot protected tests BEFORE supersession — mirrors production (`_open_author_context`
        # snapshots before the rung supersedes), so the deleted trapping files stay protected and a
        # held-out tester cannot re-create them (red-team R2 bench-fidelity fix).
        protected = protected_test_paths(ws)
        superseded: list[str] = []
        held_out = cls == "engine_blocked_give_up"
        if held_out:
            # Class 2 needs an INDEPENDENT tester (red-team R1) — mirror the production gate.
            if not settings.held_out_ok():
                return Layer2Outcome(None, (), [], "no held-out model — no independence")
            trapping = trapping_engine_tests(run.final)
            superseded = supersede_engine_tests(ws, trapping) if trapping else []
            if not superseded:
                return Layer2Outcome(None, (), [], "tree does not match the park's final state")
        tk: dict[str, Any] = {
            "approval_gate": False,
            "install": settings.sandbox_install,
            "install_timeout": settings.sandbox_install_timeout,
        }
        all_tools = build_repo_tools(ws, sandbox, **tk)
        tester_tools = build_repo_tools(
            ws, sandbox, write_prefix="tests/", protected_paths=protected, actor="Proctor", **tk
        )
        # Class 2 authors with the held-out critic model (independence); class 1 keeps the default.
        factory = (
            (lambda role, s: get_chat_model("critic" if role == "tester" else role, s))
            if held_out
            else get_chat_model
        )
        team = build_default_team(settings, all_tools, tester_tools, factory)

        def _author(instr: str) -> None:
            team.author_tests(instr, None)

        res = close_oracle_gap(ws, sandbox, _author, acceptance=case.brief, task=case.brief)
        if res.verdict == "verified" and superseded:
            # Mirror the rung's post-supersession whole-suite check: a deleted engine test another
            # test imported would break the delivered tree — that must count as NOT converted.
            suite = run_plan(resolve_plan(ws, None, install=False), sandbox, cwd=ws.root)
            if suite.passed is not True:
                return Layer2Outcome(
                    "unverified",
                    res.authored,
                    superseded,
                    "the remaining suite is not green after supersession",
                    res.green,
                    res.mutation_caught,
                )
        return Layer2Outcome(
            res.verdict,
            res.authored,
            superseded,
            res.reason,
            res.green,
            res.mutation_caught,
            tuple(res.detail.get("source") or ()),
            res.detail.get("changed"),
        )
    except Exception as exc:
        print(f"  layer2 error: {type(exc).__name__}: {exc}")
        return Layer2Outcome("ERROR", (), [], f"{type(exc).__name__}: {exc}")
