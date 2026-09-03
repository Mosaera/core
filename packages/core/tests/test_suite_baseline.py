"""Was the target repo's suite green before the run started?

Nothing asked, and on 2026-08-20 a live run paid for it: `35 failed, 35 passed` three times over,
the failures in PRE-EXISTING tests, and a producer that concluded "the failing tests are all due to
environment issues (package not properly installed)". The environment was fine — its own change had
broken the CLI's other subcommands. With no baseline, a regression and an already-red repo are the
same observation, so the gap was filled by invention.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mosaera_core.graph import nodes_plan
from mosaera_core.graph._baseline import (
    caused_regressions,
    red_baseline_note,
    regression_fields,
    regression_note,
    regressions_in,
    run_start_baseline,
)
from mosaera_core.graph.nodes_plan import plan_node, route_after_plan


class _Agents:
    def plan(self, *a: Any, **k: Any) -> str:
        return "a real plan"

    def plan_is_fallback(self, plan: str) -> bool:
        return False

    def plan_fallback_reason(self) -> str:
        return ""

    def plan_fallback_evidence(self) -> dict[str, Any]:
        return {}


def _ctx() -> Any:
    return SimpleNamespace(
        agents=_Agents(),
        # `root` must be a real Path, not a str: `run_start_baseline` now resolves the test surface
        # from the target's own pytest config, and that reads root files through `workspace.root /
        # name`. A fake whose root is a bare string is less capable than the real object — the same
        # shape that let the protected-set blindness live through a green suite.
        workspace=SimpleNamespace(root=Path("/work"), security_listing=lambda: []),
        memory=None,
        item_id=None,
        test_cmd=None,
        sandbox=object(),
        settings=SimpleNamespace(
            stall_detection_enabled=False,
            plan_stall_limit=2,
            pm_step_limit=20,
            sandbox_install=True,
            sandbox_install_timeout=None,
        ),
    )


@pytest.fixture(autouse=True)
def _no_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes_plan, "planning_overview", lambda ctx: "(files)")


def _stub_baseline(monkeypatch: pytest.MonkeyPatch, *, passed: bool, output: str) -> None:
    """Stub the validation seam, not the baseline helper — so the test exercises the real
    plan/run/parse path and would notice if it stopped being called."""
    import mosaera_core.graph._baseline as bl

    monkeypatch.setattr(bl, "resolve_plan", lambda *a, **k: SimpleNamespace(as_dict=dict))
    monkeypatch.setattr(
        bl, "run_plan", lambda *a, **k: SimpleNamespace(passed=passed, output=output)
    )
    monkeypatch.setattr(bl, "integrity_baseline", lambda ws: {"tests/test_existing.py": "h"})


# --- a red baseline stops the run BEFORE the coder cycle ----------------------------------------


def test_a_red_baseline_is_RECORDED_and_the_run_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """An earlier cut parked here. An end-to-end fixture said that was wrong: "the suite is red and
    your job is to make it green" is Mosaera's canonical task (`make run TASK="make the failing
    test pass"`), so parking would refuse the most common shape of work there is.

    Asserted on the ROUTE as well as the record — a text-only assertion would pass while the run
    was being stopped anyway."""
    _stub_baseline(
        monkeypatch, passed=False, output="FAILED tests/test_existing.py::test_a\n1 failed"
    )
    out = plan_node(_ctx(), {"task": "t"}, None)  # type: ignore[arg-type]

    assert route_after_plan(_ctx(), out) == "design"  # type: ignore[arg-type]
    assert "plan_unworkable_reason" not in out
    assert out["suite_baseline"] == {
        "green": False,
        "failing": ["tests/test_existing.py::test_a"],
        "read": True,
    }
    note = red_baseline_note(out["suite_baseline"])
    assert "ALREADY failing before this run started" in note
    assert "not caused by this change" in note


def test_a_green_baseline_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    """This must not become a new way for healthy runs to stop."""
    _stub_baseline(monkeypatch, passed=True, output="70 passed in 2.5s")
    out = plan_node(_ctx(), {"task": "t"}, None)  # type: ignore[arg-type]

    assert route_after_plan(_ctx(), out) == "design"  # type: ignore[arg-type]
    assert "plan_unworkable_reason" not in out
    assert out["suite_baseline"] == {"green": True, "failing": [], "read": True}


def test_an_unreadable_baseline_is_not_treated_as_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """A validator this code cannot parse has not been shown to be broken. Parking on it would
    make the control fire on its own blindness rather than on evidence."""
    _stub_baseline(monkeypatch, passed=False, output="Segmentation fault")
    out = plan_node(_ctx(), {"task": "t"}, None)  # type: ignore[arg-type]

    assert route_after_plan(_ctx(), out) == "design"  # type: ignore[arg-type]
    assert out["suite_baseline"]["read"] is False
    # …and it claims NOTHING about the repo on the strength of output it could not parse.
    assert red_baseline_note(out["suite_baseline"]) == ""
    assert regression_fields(out, ["tests/test_existing.py::x"]) == {}


def test_the_baseline_is_taken_once_not_on_every_replan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gate-deny re-plan must not re-baseline a tree the coder has already written to — that
    would launder a regression into the baseline and silence the whole control."""
    calls: list[int] = []
    import mosaera_core.graph._baseline as bl

    monkeypatch.setattr(bl, "resolve_plan", lambda *a, **k: SimpleNamespace(as_dict=dict))

    def _counted(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(passed=True, output="1 passed")

    monkeypatch.setattr(bl, "run_plan", _counted)
    monkeypatch.setattr(bl, "integrity_baseline", lambda ws: {"tests/t.py": "h"})

    plan_node(_ctx(), {"task": "t"}, None)  # type: ignore[arg-type]
    first = len(calls)
    plan_node(_ctx(), {"task": "t", "integrity_baseline": {"tests/t.py": "h"}}, None)  # type: ignore[arg-type]
    # Count the SECOND visit's contribution, not a raw total: taking a baseline now also asks
    # `pytest --collect-only` once, to check our reading of the repo's config against pytest's own
    # answer. That is a second sandbox call on a cache MISS and it is not a second baselining.
    assert first > 0, "the first plan_node must take the baseline"
    assert len(calls) == first, "a re-plan re-baselined a tree the coder has already written to"


# --- naming what the run broke ------------------------------------------------------------------

_GREEN = {"green": True, "failing": [], "read": True}
_PRE_EXISTING = {"tests/test_cli_add.py": "h", "tests/test_storage.py": "h"}


def test_a_pre_existing_test_that_now_fails_is_named_a_regression() -> None:
    broke = caused_regressions(
        _GREEN, _PRE_EXISTING, ["tests/test_cli_add.py::TestCLIAdd::test_add_writes_row"]
    )
    assert broke == ["tests/test_cli_add.py::TestCLIAdd::test_add_writes_row"]
    note = regression_note(broke)
    assert "PASSED before this run started" in note
    assert "not in the environment" in note or "not in the suite" in note


def test_an_authored_test_failing_is_NOT_a_regression() -> None:
    """The Proctor's tests are SUPPOSED to fail first — that is the red phase. Calling that a
    regression would make the message lie in the one place it has to be right."""
    assert caused_regressions(_GREEN, _PRE_EXISTING, ["tests/test_cli_version.py::test_flag"]) == []


def test_a_test_that_was_ALREADY_failing_is_not_a_regression() -> None:
    """The canonical task is to make a failing test pass. Calling that failure a regression would
    accuse the run of breaking the very thing it was asked to fix."""
    red = {"green": False, "failing": ["tests/test_cli_add.py::x"], "read": True}
    assert caused_regressions(red, _PRE_EXISTING, ["tests/test_cli_add.py::x"]) == []
    # …but a DIFFERENT pre-existing test breaking in the same run still is one.
    assert caused_regressions(red, _PRE_EXISTING, ["tests/test_storage.py::y"]) == [
        "tests/test_storage.py::y"
    ]


def test_nothing_is_named_when_the_baseline_could_not_be_READ() -> None:
    """Without a readable baseline, "was it passing before?" has no answer, and a confident list is
    exactly the invention this module exists to prevent."""
    unread = {"green": False, "failing": [], "read": False}
    assert caused_regressions(unread, _PRE_EXISTING, ["tests/test_cli_add.py::x"]) == []


def test_regressions_are_parsed_from_the_run_s_own_output() -> None:
    state = {
        "suite_baseline": _GREEN,
        "integrity_baseline": _PRE_EXISTING,
        "test_output": (
            "FAILED tests/test_cli_add.py::TestCLIAdd::test_add - AssertionError: 2 != 0\n"
            "FAILED tests/test_cli_version.py::test_flag - AssertionError\n"
            "35 failed, 35 passed in 2.54s"
        ),
    }
    assert regressions_in(state) == ["tests/test_cli_add.py::TestCLIAdd::test_add"]


def test_the_escalation_payload_omits_the_key_when_there_is_nothing_to_say() -> None:
    """An empty dict is truthy in JS and blanked the gate panel live (2026-08-07): the escalation
    reached the operator and the screen that would let them answer it did not."""
    assert regression_fields({"suite_baseline": _GREEN}, []) == {}
    got = regression_fields(
        {"suite_baseline": _GREEN, "integrity_baseline": _PRE_EXISTING},
        ["tests/test_storage.py::test_x"],
    )
    assert got == {"regressions": ["tests/test_storage.py::test_x"]}


def test_the_red_note_survives_a_suite_with_hundreds_of_failures() -> None:
    many = [f"tests/test_existing.py::test_{i}" for i in range(40)]
    note = red_baseline_note({"green": False, "failing": many, "read": True})
    assert "40 test(s) were ALREADY failing" in note and "+35 more" in note
    assert len(note) <= 400  # the durable columns downstream are bounded


def test_run_start_baseline_takes_both_snapshots_of_the_same_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_baseline(monkeypatch, passed=True, output="3 passed")
    delta = run_start_baseline(_ctx())
    assert delta["integrity_baseline"] == {"tests/test_existing.py": "h"}
    assert delta["suite_baseline"]["green"] is True
    # It REPORTS; it never stops a run.
    assert "plan_unworkable_reason" not in delta


# --- the replay: today's failure, through the prompt the coder actually reads -------------------


def test_the_2026_08_20_failure_now_names_what_the_change_broke() -> None:
    """Verbatim shape from run `20260820-185125-994a3d`, which cost $1.80 to produce once.

    The coder saw only "35 failed, 35 passed" and its own reasoning, and concluded the package was
    not installed. The install had in fact succeeded and pytest exited 1 (assertion failures, not
    collection errors). It must now be told, before anything else in the prompt, that it broke a
    test which was passing when it started.
    """
    from mosaera_core.graph.instructions import fix_instruction

    output = (
        "[step install: skipped — .venv/.stamp-801234fc43b0 already present]\n\n"
        "[step pytest: exit code 1]\n"
        "FAILED tests/test_cli_add.py::TestCLIAdd::test_add_command_writes_correct_row_to_csv - "
        "AssertionError: 2 != 0\n"
        "FAILED tests/test_cli_version.py::test_version_flag_prints_version - AssertionError\n"
        "35 failed, 35 passed in 2.54s"
    )
    state = {
        "suite_baseline": _GREEN,
        "integrity_baseline": {"tests/test_cli_add.py": "h"},
        "test_output": output,
    }

    prompt = fix_instruction(output, regressions=regressions_in(state))

    assert prompt.startswith("REGRESSION")  # the first thing it reads, not a footnote
    assert "tests/test_cli_add.py::TestCLIAdd::test_add_command_writes_correct_row_to_csv" in prompt
    # The acceptance test for THIS item is failing too, and must not be blamed on the change.
    assert "tests/test_cli_version.py" not in prompt.split("Validation output:")[0]


def test_a_run_that_broke_nothing_gets_the_prompt_it_always_got() -> None:
    """The note must not appear on an ordinary red-phase iteration, or it becomes noise and the
    one time it matters nobody reads it."""
    from mosaera_core.graph.instructions import fix_instruction

    plain = fix_instruction("FAILED tests/test_cli_version.py::test_flag\n1 failed", regressions=[])
    assert "REGRESSION" not in plain
    assert plain.startswith("The validation suite failed.")


def test_a_baseline_that_cannot_be_taken_never_costs_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable sandbox is not evidence that the repository is broken.

    Trading a blind spot for an outage would be the worse bargain: `plan_node` now does I/O on its
    first visit, so every infrastructure hiccup would otherwise crash a run that could have
    proceeded. It records `read=False` and continues — nothing downstream then claims to know
    something it does not.
    """
    import mosaera_core.graph._baseline as bl

    monkeypatch.setattr(bl, "integrity_baseline", lambda ws: {"tests/t.py": "h"})
    monkeypatch.setattr(
        bl, "resolve_plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("docker is down"))
    )

    out = plan_node(_ctx(), {"task": "t"}, None)  # type: ignore[arg-type]

    assert route_after_plan(_ctx(), out) == "design"  # type: ignore[arg-type]
    assert out["suite_baseline"] == {"green": False, "failing": [], "read": False}
    assert "plan_unworkable_reason" not in out
    # …and nothing is asserted about regressions on the strength of a baseline we never took.
    assert regressions_in({**out, "test_output": "FAILED tests/t.py::x\n1 failed"}) == []


# --- one verdict, keyed by the tree it measured -------------------------------------------------


class _Health:
    """The suite-health slice of MemoryStore, in-memory."""

    def __init__(self) -> None:
        self.row: dict[str, Any] | None = None
        self.writes = 0

    def suite_health(self, project_id: str, tree_hash: str | None = None) -> Any:
        if self.row is None:
            return None
        if tree_hash is not None and self.row["tree_hash"] != tree_hash:
            return None
        return dict(self.row)

    def record_suite_health(self, project_id: str, **kw: Any) -> bool:
        self.writes += 1
        self.row = {"project_id": project_id, **kw}
        return True


def _cached_ctx(health: _Health, tree: str) -> Any:
    ctx = _ctx()
    ctx.memory = health
    ctx.project_id = "p1"
    ctx.run_id = "r1"
    # The durable key is git CONTENT (`HEAD^{tree}`), not the mtime fingerprint — so the fake
    # workspace has to offer the same surface the real one does.
    ctx.workspace = SimpleNamespace(
        root=Path("/work"),
        # `run_start_baseline` resolves the test surface, which reads the security listing.
        security_listing=lambda: [],
        tree_hash=lambda: tree,
        repo=SimpleNamespace(
            is_dirty=lambda untracked_files=False: False,
            git=SimpleNamespace(rev_parse=lambda _spec: tree),
        ),
    )
    return ctx


def test_an_unchanged_tree_runs_no_suite_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of keying the verdict by tree hash. Asserted on the CALL COUNT, not the
    verdict: a verdict-only assertion passes whether or not the suite ran, which is the cost the
    owner objected to."""
    import mosaera_core.graph._baseline as bl

    calls: list[int] = []
    monkeypatch.setattr(bl, "integrity_baseline", lambda ws: {"tests/t.py": "h"})
    monkeypatch.setattr(bl, "resolve_plan", lambda *a, **k: SimpleNamespace(as_dict=dict))

    def _counted(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(passed=True, output="9 passed")

    monkeypatch.setattr(bl, "run_plan", _counted)

    health = _Health()
    ctx = _cached_ctx(health, "tree-aaa")

    first = bl.run_start_baseline(ctx)  # cache miss → measures once, records
    # Asserted as a DELTA, not an absolute: a cache MISS now makes two sandbox calls — the suite,
    # and one `pytest --collect-only` to check our reading of the repo's pytest config against
    # pytest's own answer. Both are keyed to the tree, which is the property under test.
    measured = len(calls)
    assert measured > 0 and health.writes == 1
    assert first["suite_baseline"]["green"] is True

    second = bl.run_start_baseline(ctx)  # same tree → free
    assert len(calls) == measured, "an unchanged tree cost a sandbox call"
    assert second["suite_baseline"]["green"] is True


def test_a_moved_tree_invalidates_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivery, an external merge, or check_base_drift's fast-forward changes the hash — and a
    verdict about the old tree must never be read as an answer about the new one."""
    import mosaera_core.graph._baseline as bl

    calls: list[int] = []
    monkeypatch.setattr(bl, "integrity_baseline", lambda ws: {"tests/t.py": "h"})
    monkeypatch.setattr(bl, "resolve_plan", lambda *a, **k: SimpleNamespace(as_dict=dict))

    def _counted(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(passed=True, output="9 passed")

    monkeypatch.setattr(bl, "run_plan", _counted)

    health = _Health()
    bl.run_start_baseline(_cached_ctx(health, "tree-aaa"))
    per_tree = len(calls)
    bl.run_start_baseline(_cached_ctx(health, "tree-bbb"))  # the repo moved

    assert per_tree > 0, "the first tree must be measured"
    assert len(calls) == 2 * per_tree, "a moved tree reused a verdict about the old one"
    assert health.row is not None and health.row["tree_hash"] == "tree-bbb"


def test_an_unreadable_verdict_is_never_a_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "We could not tell last time" is no reason to skip trying again — and it must never be
    recorded or reused as "failed"."""
    import mosaera_core.graph._baseline as bl

    health = _Health()
    ctx = _cached_ctx(health, "tree-aaa")
    health.row = {"tree_hash": "tree-aaa", "verdict": "unknown", "failing": []}

    assert bl.known_verdict(ctx, "tree-aaa") is None


def test_the_recorded_verdict_never_says_failed_about_output_it_could_not_read() -> None:
    import mosaera_core.graph._baseline as bl

    health = _Health()
    ctx = _cached_ctx(health, "tree-aaa")
    bl.record_verdict(ctx, "tree-aaa", {"green": False, "failing": [], "read": False})

    assert health.row is not None and health.row["verdict"] == "unknown"
