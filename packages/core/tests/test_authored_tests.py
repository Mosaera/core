"""Which test files count as Proctor-authored (F35).

The defect this pins: `author_tests_node` snapshots `before` at the top, and every write gate
interrupts INSIDE the tool, so LangGraph re-executes the node from the top on resume and re-takes
`before` with the already-approved file at its FINAL hash. Diffing against that moving snapshot
dropped every authored file but the last, so they never reached `ctx.protected_tests` and the coder
rewrote a Proctor acceptance file unrefused.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from mosaera_core.graph.nodes_plan import authored_test_files
from mosaera_core.tools.repo import Workspace


def _git_ws(root: Path) -> Workspace:
    """A real git-init'd `Workspace` — `protected_test_paths` reads the git-sourced listing."""
    subprocess.run(("git", "init", "-q"), cwd=root, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; fixture
    return Workspace(root=root, run_id="t", branch="b")


def test_a_new_file_stays_authored_after_a_resume_re_observes_it() -> None:
    # THE regression. This is the exact post-resume state: `before` already contains A at the very
    # hash `after` has, because the gate approved it and the node restarted. Under the old
    # hash-diff A vanished from `authored` and became writable by the coder.
    after = ["tests/test_a.py", "tests/test_b.py"]
    after_hashes = {"tests/test_a.py": "h1", "tests/test_b.py": "h2"}
    before_hashes = {"tests/test_a.py": "h1"}  # re-snapshotted after A was approved
    assert authored_test_files(after, after_hashes, before_hashes, baseline_paths=set()) == after


def test_a_pre_existing_test_is_authored_only_when_it_changed() -> None:
    # Behaviour for a repo that already had tests is unchanged: a baselined file must actually
    # differ to count as authored.
    after = ["tests/test_old.py"]
    baseline = {"tests/test_old.py"}
    assert (
        authored_test_files(
            after, {"tests/test_old.py": "same"}, {"tests/test_old.py": "same"}, baseline
        )
        == []
    )
    assert authored_test_files(
        after, {"tests/test_old.py": "new"}, {"tests/test_old.py": "old"}, baseline
    ) == ["tests/test_old.py"]


def test_a_missing_baseline_protects_everything() -> None:
    # Deny-by-default: for an oracle guard, over-protecting is the safe failure direction.
    after = ["tests/test_a.py"]
    hashes = {"tests/test_a.py": "h"}
    assert authored_test_files(after, hashes, hashes, baseline_paths=set()) == after


def test_an_unhashable_file_is_not_authored() -> None:
    # Unchanged guard: an empty hash means the file could not be read, which is not authorship.
    assert authored_test_files(["tests/x.py"], {"tests/x.py": ""}, {}, set()) == []


def test_the_result_is_sorted_and_deduped_by_construction() -> None:
    after = ["tests/test_b.py", "tests/test_a.py"]
    hashes = {"tests/test_a.py": "h1", "tests/test_b.py": "h2"}
    assert authored_test_files(after, hashes, {}, set()) == ["tests/test_a.py", "tests/test_b.py"]


# --- The regression proper: a REAL interrupt/resume between two authored files. ---
# Every pre-existing test called author_tests_node ONCE, which is why F35 survived: the defect only
# appears when a write gate interrupts INSIDE the tool and LangGraph re-executes the node from the
# top. Verified against the pre-fix code, where this yields ['tests/test_b.py'] and test_a.py is
# silently writable by the coder.


def test_both_authored_files_survive_a_write_gate_interrupt(
    tmp_path: Any, monkeypatch: Any
) -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command
    from mosaera_core.graph import nodes_plan
    from mosaera_core.graph.state import RunState
    from mosaera_policies.approval import request_approval

    (tmp_path / "tests").mkdir()
    protected: set[str] = set()

    def author_tests(instruction: str, config: Any = None, corrections: Any = ()) -> Any:
        # File A, a write gate, then file B — the guided-mode shape. On resume this whole
        # function re-runs, so A is already on disk at its final hash the second time through.
        (tmp_path / "tests" / "test_a.py").write_text(
            "def test_a():\n    assert 1\n", encoding="utf-8"
        )
        request_approval("write_file", "write tests/test_a.py", {"path": "tests/test_a.py"})
        (tmp_path / "tests" / "test_b.py").write_text(
            "def test_b():\n    assert 2\n", encoding="utf-8"
        )
        return {}

    ctx = SimpleNamespace(
        # A REAL Workspace. This was a SimpleNamespace whose `file_listing` was an UNCAPPED
        # rglob, while the real one caps at 300 — so this test exercised a workspace that does not
        # exist, and the protected-set blindness it is nominally about stayed invisible.
        workspace=_git_ws(tmp_path),
        sandbox=object(),
        protected_tests=protected,
        agents=SimpleNamespace(
            tester_enabled=True,
            author_tests=author_tests,
            validate_and_repair_tests=lambda *a, **k: None,
        ),
        settings=SimpleNamespace(
            tester_repairs_tests=False,
            proctor_faithfulness_guard=False,
            behavior_preservation_guard=False,
            refactor_oracle_scaffold=False,
        ),
    )
    # monkeypatch, NOT bare assignment: these are module-level names and a bare assignment leaks
    # into every later test in the session (it broke the already-satisfied test exactly that way).
    monkeypatch.setattr(nodes_plan, "authored_seed_results", lambda *a, **k: (True, []))
    monkeypatch.setattr(nodes_plan, "authored_suite_asserts_behaviour", lambda *a, **k: True)

    g = StateGraph(RunState)
    g.add_node(
        "author_tests",
        lambda s, config: nodes_plan.author_tests_node(ctx, s, config),  # type: ignore[arg-type]
    )
    g.add_edge(START, "author_tests")
    g.add_edge("author_tests", END)
    app = g.compile(checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "t1"}}
    seed = cast(RunState, {"task": "t", "iteration": 0, "integrity_baseline": {}})
    first = app.invoke(seed, cast(Any, cfg))
    assert "__interrupt__" in first  # the write gate really paused the node
    final = app.invoke(
        Command(resume={"approve": True, "feedback": "", "actor": "human"}), cast(Any, cfg)
    )

    both = ["tests/test_a.py", "tests/test_b.py"]
    assert final.get("authored_tests") == both
    # protected_tests is what makes the coder's tools REFUSE a write — the actual guarantee.
    assert sorted(protected) == both
