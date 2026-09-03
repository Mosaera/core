"""A security verdict from an earlier tree still vouches at the gate — and it SHIPS.

The audit's CRITICAL. `scan_node` is the sole writer of `security_status`, `RunState` is
last-write-wins, and NOTHING clears it on a re-plan. So on the give-up edge —
`review -> review_fix -> implement -> capture -> supervise -> gate`, where the coder writes AFTER
scan and review ran — the gate reads iteration N's `"clean"` about a tree that no longer exists.

`scan_attempted` (ADR-0107, 2026-08-21) closed the ABSENT case: a gate reached without ever entering
`scan_node` now says `security_not_attempted` and parks. The STALE case is untouched, and it is the
worse of the two: absent merely suppresses a question, stale produces `reasons == []` and delivers.

`tests_passed` is the ONE channel protected — ADR-0106 pins it to `verified_tree` and
`delivery_check` re-measures when the tree moved. Security and the reviewer have no backstop at any
layer.

## What this file proves, and what it models

PROVEN here with real LangGraph channels and the real `scan_node` / `evaluate_gate`:
  1. a verdict written by `scan_node` on tree T1 is STILL IN STATE after the tree becomes T2, and
  2. the gate, fed that persisted state, emits no security reason and resolves to `approve`.

MODELLED, not driven: the write between scan and the gate is a test node standing in for
`implement`. Driving the real spine needs a coder that writes and then hand-raises on command, and a
live run refused to do that (~1.5M tokens on 2026-08-22). The routing half — that a give-up reaches
the gate without `scan_node` — is already pinned by
`test_scan_node.py::test_a_gate_reached_WITHOUT_scanning_reports_unavailable_never_clean`.

The contestable step is the PERSISTENCE, and that is the half driven through real channels here: a
hand-built state dict would ASSUME it, which is the mistake `test_control_polarity.py`'s own
docstring warns about, one level up.
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from mosaera_core.config import Settings
from mosaera_core.graph._freshness import is_fresh, live_tree
from mosaera_core.graph.nodes_review import gate_node, review_node, scan_node
from mosaera_core.graph.state import RunState
from mosaera_core.tools.repo import Workspace
from mosaera_core.tools.scan import GitleaksScanner
from mosaera_policies import autonomous_resolution, evaluate_gate
from test_scan_node import _FakeSandbox

_SRC = "def render(rows):\n    return ','.join(rows)\n"


def _ws_at(root: Path) -> Workspace:
    """git-init whatever is already on disk at `root`."""
    run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731,S603
    for cmd in (
        ("git", "init", "-q"),
        ("git", "config", "user.email", "t@t"),
        ("git", "config", "user.name", "t"),
        ("git", "add", "-A"),
        ("git", "commit", "-qm", "base", "--allow-empty"),
    ):
        run(*cmd)
    return Workspace(root=root, run_id="t", branch="b")


def _ws(root: Path) -> Workspace:
    """A real git workspace whose `tree_hash()` moves when a file changes."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text(_SRC, encoding="utf-8")
    run = lambda *a: subprocess.run(a, cwd=root, check=True, capture_output=True)  # noqa: E731,S603
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")
    return Workspace(root=root, run_id="t", branch="b")


def _ctx(ws: Workspace) -> Any:
    """The ctx `scan_node` actually touches, with a scanner that always reports clean."""
    return SimpleNamespace(
        settings=SimpleNamespace(scan_enabled=True),
        scanners=[GitleaksScanner()],
        scan_sandbox=_FakeSandbox(0, "[]"),
        workspace=ws,
    )


def _gate_args_as_gate_node_builds_them(ws: Workspace, state: dict[str, Any]) -> dict[str, Any]:
    """The three security derivations `gate_node` performs, quoted so drift is visible here.

    `nodes_review.py`:
        security_status=str(state.get("security_status") or "unavailable"),
        scan_attempted="security_status" in state,
        scan_fresh=is_fresh(ctx, state, "security_tree"),
    """
    return {
        "security_status": str(state.get("security_status") or "unavailable"),
        "scan_attempted": "security_status" in state,
        "scan_fresh": is_fresh(SimpleNamespace(workspace=ws), state, "security_tree"),
    }


def _drive_scan_then_mutate(ws: Workspace) -> dict[str, Any]:
    """Real `scan_node` -> a write -> read the persisted channels back.

    The graph is what makes this evidence rather than an assertion: `security_status` survives to
    the second node through LangGraph's own channel semantics, not because a fixture put it there.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    ctx = _ctx(ws)

    def mutate(_state: RunState) -> dict[str, Any]:
        # Stands in for `implement` writing after review — the coder's post-scan edit.
        (ws.root / "src" / "app.py").write_text(_SRC.replace(",", "|"), encoding="utf-8")
        return {}

    g: Any = StateGraph(RunState)
    g.add_node("scan", lambda s: scan_node(ctx, s))
    g.add_node("mutate", mutate)
    g.add_edge(START, "scan")
    g.add_edge("scan", "mutate")
    g.add_edge("mutate", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "stale-1"}}
    return dict(app.invoke(cast(RunState, {"task": "t"}), cfg))


def test_the_scan_verdict_survives_a_tree_change(tmp_path: Path) -> None:
    """The premise, driven rather than assumed: the channel is not cleared when the tree moves."""
    ws = _ws(tmp_path)
    before = ws.tree_hash()
    final = _drive_scan_then_mutate(ws)
    after = ws.tree_hash()

    assert final["security_status"] == "clean", "scan_node must have produced a real clean verdict"
    assert before != after, "the mutate node must actually move the tree, or this proves nothing"
    # ...and the verdict for the OLD tree is still sitting in state, describing the NEW one.
    assert "security_status" in final


def test_a_STALE_clean_must_not_ship(tmp_path: Path) -> None:
    """THE regression, written as the CONTRACT rather than the current behaviour.

    RED until the fix lands: today the gate emits no security reason and resolves to `approve`.
    Asserting what the gate SHOULD do — rather than characterising what it does — is what makes
    this a regression test; a test that asserts the hole goes green today and red the moment the
    hole closes, which is exactly backwards.

    Note what makes stale worse than the absent case ADR-0107 fixed: absent produces
    `security_not_attempted` and parks. Stale produces `reasons == []` and DELIVERS.
    """
    ws = _ws(tmp_path)
    final = _drive_scan_then_mutate(ws)

    decision = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=len(final.get("findings", [])),
        oracle_verified=True,
        validation_strength="suite",
        iteration=1,
        max_iterations=6,
        **_gate_args_as_gate_node_builds_them(ws, final),
    )

    assert [r for r in decision.reasons if r.startswith("security_")], (
        "the scanner never saw THIS tree and the gate raised nothing about it — ADR-0076's "
        f"deny-by-default is defeated by staleness. reasons={list(decision.reasons)}"
    )
    assert decision.action != "deliver"
    assert autonomous_resolution(decision) != "approve", (
        "an unscanned tree must not reach delivery unattended"
    )


def test_the_absent_case_still_parks_so_the_two_are_not_confused(tmp_path: Path) -> None:
    """The contrast that makes the finding precise: ADR-0107's fix works, and does not cover this.

    If this ever fails, the stale fix broke the absent one and the audit's CRITICAL was traded for
    a regression rather than closed.
    """
    never_scanned = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        oracle_verified=True,
        validation_strength="suite",
        iteration=1,
        max_iterations=6,
        security_status="unavailable",
        scan_attempted=False,
    )
    assert "security_not_attempted" in never_scanned.reasons
    assert never_scanned.action != "deliver"


def _drive_scan_only(ws: Workspace) -> dict[str, Any]:
    """Real `scan_node`, nothing after — the tree it saw IS the tree that would ship."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    ctx = _ctx(ws)
    g: Any = StateGraph(RunState)
    g.add_node("scan", lambda s: scan_node(ctx, s))
    g.add_edge(START, "scan")
    g.add_edge("scan", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "fresh-1"}}
    return dict(app.invoke(cast(RunState, {"task": "t"}), cfg))


def test_a_FRESH_clean_still_ships(tmp_path: Path) -> None:
    """The other polarity, and the one that keeps the fix from being 'park everything'.

    Added because mutation testing caught this file's own gap: blanking the writer's stamp left
    every assertion above still passing. `is_fresh` reads an empty stamp as NOT fresh, so a broken
    stamp parks — which is the safe direction but would park EVERY run, and nothing here noticed.
    A control that can only reach one outcome is a constant, whichever outcome that is.
    """
    ws = _ws(tmp_path)
    final = _drive_scan_only(ws)

    assert final["security_status"] == "clean"
    assert final["security_tree"], "the stamp must be a real hash, not empty"

    decision = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=0,
        oracle_verified=True,
        validation_strength="suite",
        iteration=1,
        max_iterations=6,
        **_gate_args_as_gate_node_builds_them(ws, final),
    )
    assert not [r for r in decision.reasons if r.startswith("security_")], list(decision.reasons)
    assert decision.action == "deliver"


def test_the_pin_SEES_past_the_300_path_listing_cap(tmp_path: Path) -> None:
    """Round 1's regime: an edit past the 300th sorted path.

    `file_listing` caps at 300; on this repo that is 300 of 1,315 tracked files, so a red-team
    agent built a 401-file tree, wrote a backdoor to a path sorting after the cut, and reproduced
    the ORIGINAL bug straight through the first fix. Lifting the cap fixed this case. It was not
    enough — see the skip-dir test below — but it must not regress, and `committable_paths` is
    unbounded by construction rather than by a flag someone can re-bound.
    """
    (tmp_path / "apps").mkdir()
    for i in range(400):  # 400 paths sorting BEFORE the one that matters
        (tmp_path / "apps" / f"f{i:04d}.ts").write_text("export const x = 1\n", encoding="utf-8")
    (tmp_path / "packages").mkdir()
    auth = tmp_path / "packages" / "auth.py"
    auth.write_text("def check(token):\n    return verify(token)\n", encoding="utf-8")
    ws = _ws_at(tmp_path)

    ctx = SimpleNamespace(workspace=ws)
    stamped = live_tree(ctx)
    assert len(ws.file_listing()) == 300, "the presentation cap must still be 300 — the contrast"
    assert len(ws.committable_paths()) == 401, "the EVIDENCE listing must not be capped at all"
    auth.write_text("def check(token):\n    return True  # backdoor\n", encoding="utf-8")

    assert not is_fresh(ctx, {"security_tree": stamped}, "security_tree"), (
        "an edit past the 300th sorted path left the evidence pin unmoved"
    )


def test_the_pin_SEES_a_write_into_a_SKIPPED_DIRECTORY(tmp_path: Path) -> None:
    """ROUND 2's CRITICAL — the one that reproduced the original bug straight through the fix.

    `file_listing` prunes `_SKIP_DIRS` by directory NAME AT ANY DEPTH. The delivery path excludes
    only the ROOT `.mosaera/` — anchored deliberately (#59 red team) so a legitimate nested
    `src/.mosaera/` deliverable is not silently dropped. So the pin and the committer disagreed
    about what is in the tree, and the gap was a ship path: with nothing but the coder's ordinary
    `write_file`,

        stamp before : 3dfe3e62f4bdddbd     # write src/.mosaera/backdoor.py
        live  after  : 3dfe3e62f4bdddbd     # the pin is blind
        git would commit: A  src/.mosaera/backdoor.py

    and the gate emitted `reasons == []`, `action == "deliver"`. `htmlcov/`, `node_modules/`,
    `__pycache__/` at any depth were the same hole. This is the test the whole successor exists
    for: it fails the moment the evidence listing goes back to sharing a skip-set with the
    presentation listing.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(_SRC, encoding="utf-8")
    ws = _ws_at(tmp_path)
    ctx = SimpleNamespace(workspace=ws)
    stamped = live_tree(ctx)

    for buried in ("src/.mosaera/backdoor.py", "htmlcov/backdoor.py", "src/__pycache__/b.py"):
        target = tmp_path / buried
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TOKEN = 'sk-live-stolen'\n", encoding="utf-8")
        assert buried in ws.committable_paths(), f"{buried} is committable and must be pinned"
        assert not is_fresh(ctx, {"security_tree": stamped}, "security_tree"), (
            f"a write to {buried} left the pin unmoved — it is invisible to the evidence pin and "
            f"fully deliverable, which is ADR-0108's own CRITICAL reproduced through ADR-0108"
        )
        target.unlink()


def test_the_pin_IGNORES_the_scratch_namespace_the_committer_ignores(tmp_path: Path) -> None:
    """The other half of "one origin": root `.mosaera/` must NOT move the pin.

    `_stage_all` resets it out of the index, so nothing there can ever ship. If the pin flagged it,
    every run that used the agent scratch workbench between scan and gate would park with "the code
    changed" — a false park, on the repo's own scratch directory. Blindness and over-sensitivity
    are the same bug from opposite sides; matching `_stage_all` exactly is what avoids both.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(_SRC, encoding="utf-8")
    ws = _ws_at(tmp_path)
    ctx = SimpleNamespace(workspace=ws)
    stamped = live_tree(ctx)

    scratch = tmp_path / ".mosaera" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "notes.md").write_text("thinking out loud\n", encoding="utf-8")

    assert not any(p.startswith(".mosaera") for p in ws.committable_paths())
    assert is_fresh(ctx, {"security_tree": stamped}, "security_tree"), (
        "a write to the agent scratch namespace moved the evidence pin, but it can never ship"
    )


def test_an_unreadable_workspace_does_not_vouch(tmp_path: Path) -> None:
    """FAILS CLOSED — and two successive cuts did not, despite both saying so in their docstrings.

    Cut 1: `tree_hash` builds from `os.walk`, which swallows traversal errors, so a missing root
    returned `sha256("")` rather than `""`; with that same sentinel on both sides `is_fresh`
    returned True and vouched for a tree it could not read. Cut 2 added an `is_dir()`/non-empty
    probe — which guarded the ROOT's existence, not whether the walk produced anything, so a tree
    whose entire content sat under pruned directories still hashed to `sha256("")`. Same bug, one
    predicate over, found by the next round.

    `evidence_hash` ends the class rather than patching it a third time: git either answers or
    raises, and an empty committable set is `""` instead of a hash of nothing. Unreadable and empty
    are both "no fingerprint", and `""` can never equal a stamp.
    """
    gone = SimpleNamespace(workspace=Workspace(root=tmp_path / "nope", run_id="t", branch="b"))
    assert live_tree(gone) == ""
    assert not is_fresh(gone, {"security_tree": "anything"}, "security_tree")
    assert not is_fresh(gone, {"security_tree": live_tree(gone) or ""}, "security_tree")

    # ...and the case cut 2 missed: a root that EXISTS and yields nothing committable.
    empty = tmp_path / "empty"
    empty.mkdir()
    ws = _ws_at(empty)
    hollow = SimpleNamespace(workspace=ws)
    assert live_tree(hollow) == "", "an empty committable set must not hash to sha256('')"
    assert not is_fresh(hollow, {"security_tree": live_tree(hollow) or ""}, "security_tree")


def test_the_operator_opt_out_is_never_a_stale_park(tmp_path: Path) -> None:
    """`disabled` means the operator turned scanning off — there is no verdict to be stale.

    Parking it would be a false park explained by a false sentence ("the code changed after the
    security scan ran"), and `bench/harness.py` disables scanning on EVERY benchmark run, so it
    would have shifted every measured rate. The instrument-contaminating class this repo has
    already paid for once.
    """

    def _stale(status: str) -> Any:
        return evaluate_gate(
            tests_passed=True,
            reviewer_verdict="APPROVE",
            findings_count=0,
            oracle_verified=True,
            validation_strength="suite",
            iteration=1,
            max_iterations=6,
            security_status=status,
            scan_attempted=True,
            scan_fresh=False,
        )

    assert _stale("disabled").action == "deliver"
    assert "security_stale" in _stale("clean").reasons


def test_gate_node_ITSELF_asks_the_freshness_question(tmp_path: Path, monkeypatch: Any) -> None:
    """The production wiring, pinned by execution instead of by a quoted comment.

    `_gate_args_as_gate_node_builds_them` above RE-DERIVES what `gate_node` derives and says a
    comment keeps the two in step. A red-team agent tested that claim by mutating `gate_node` to
    stop asking (`nodes_review.is_fresh -> lambda *a: True`) and running every test in
    `packages/core` and `packages/policies`: 2136 passed, **0 killed it**. A quote is not a binding.

    So call `gate_node` and capture the kwargs it really passes. `evaluate_gate` is stubbed to grab
    them and bail before `request_approval` interrupts — the node's own derivation is the subject,
    and nothing downstream of it is.
    """
    ws = _ws(tmp_path)
    ctx = _ctx(ws)
    state = cast(RunState, {"task": "t"})
    state.update(cast(Any, scan_node(ctx, state)))  # a real "clean" + a real stamp for tree T1
    # Stamp the reviewer leg on the SAME tree, exactly as `review_node` does — otherwise the key is
    # merely absent and `review_fresh is False` would pass without testing freshness at all.
    state["review_tree"] = live_tree(ctx)
    state["review"] = "APPROVE"
    (tmp_path / "src" / "app.py").write_text(_SRC + "BACKDOOR = True\n", encoding="utf-8")  # -> T2

    seen: dict[str, Any] = {}

    class _Bail(Exception):
        pass

    def _capture(**kwargs: Any) -> Any:
        seen.update(kwargs)
        raise _Bail

    monkeypatch.setattr("mosaera_core.graph.nodes_review.evaluate_gate", _capture)
    full = SimpleNamespace(
        **{**vars(ctx), "run_id": "t", "max_iter": 3, "test_cmd": "", "operator_sanctioned": {}}
    )
    # The REAL Settings: `gate_node` reads a long tail of knobs, and stubbing them one at a time
    # would let a future read of an unstubbed knob look like a test bug rather than a wiring change.
    full.settings = Settings()
    with contextlib.suppress(_Bail):
        gate_node(cast(Any, full), state)

    assert seen, "gate_node never reached evaluate_gate — the capture proves nothing"
    assert seen["security_status"] == "clean", "premise: the stale verdict is still in state"
    assert seen["scan_fresh"] is False, (
        "gate_node handed the gate scan_fresh=True for a tree that moved after the scan — the "
        "freshness question is not actually being asked in production, whatever the test above "
        "re-derives on its own"
    )
    # Asserting `"review_fresh" in seen` — key PRESENCE — was the whole assertion here, next to a
    # security leg that checks the VALUE. Round 2 mutated the reviewer leg two ways: deleting
    # `review_tree` from `review_node`, and hardcoding `review_fresh=True`. BOTH survived all of
    # `packages/core` + `packages/policies`. The second is ADR-0108's own bug reinstated for the
    # reviewer channel; the first parks EVERY approved run, an availability regression CI would
    # not have noticed either. A membership check is not a pin.
    assert seen["review_fresh"] is False, (
        "gate_node reported the reviewer's APPROVE as describing the current tree, but the tree "
        "moved after review_node stamped it"
    )


def test_review_node_ACTUALLY_STAMPS_the_tree_it_reviewed(tmp_path: Path) -> None:
    """The reviewer's writer, pinned positively — the mutation above only covers the reader.

    Round 2 ran two mutations on the reviewer leg. Hardcoding `review_fresh=True` is caught by
    `test_gate_node_ITSELF_asks_the_freshness_question`. DELETING the stamp from `review_node` is
    not caught by it, or by anything else: with no stamp, `review_fresh` is False on every APPROVE
    and **every approved run parks with `reviewer_stale`**. That is a total availability regression
    with the whole suite green — the same "a control that can only reach one outcome is a constant"
    shape the roadmap already records for the security leg's first cut.

    Reader and writer need separate pins because they fail in opposite directions: the reader fails
    OPEN (ships stale work), the writer fails CLOSED (parks everything). One test cannot see both.
    """
    ws = _ws(tmp_path)
    reviewed: dict[str, Any] = {}

    def _review(*_a: Any, **_k: Any) -> str:
        reviewed["tree_at_review_time"] = live_tree(SimpleNamespace(workspace=ws))
        return "VERDICT: APPROVE"

    ctx = SimpleNamespace(
        workspace=ws,
        agents=SimpleNamespace(review=_review, clarify=lambda *a, **k: ""),
        settings=Settings(),
    )
    out = review_node(cast(Any, ctx), cast(RunState, {"task": "t"}), cast(Any, {}))

    assert out.get("review_tree"), (
        "review_node returned no `review_tree`. `review_fresh` is then False for every APPROVE and "
        "every approved run parks with `reviewer_stale` — with the suite green"
    )
    assert out["review_tree"] == reviewed["tree_at_review_time"], (
        "the stamp names a different tree than the one the reviewer actually looked at"
    )
