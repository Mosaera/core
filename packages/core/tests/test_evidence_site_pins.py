"""The four evidence stamp/compare sites, pinned by BEHAVIOUR — because a full revert was green.

`f0666bfa` moved four evidence sites from the walk-based `tree_hash` onto the git-sourced
`evidence_hash`. Red-team round 3 then reverted ALL FOUR back to `tree_hash()` and ran the full
suite: `2914 passed, 0 failed`. Only the freshness pin (`live_tree`) was defended; the other three
were held up by nothing — class (e), in the commit that claimed to close class (e).

Every test here pins the PROPERTY, never a hash value:

    a write the delivery path WOULD commit moves the stamp;
    a write to the root scratch namespace does NOT.

The lever is a file under `htmlcov/` — committable (untracked, not ignored in these fixtures) yet
invisible to `file_listing`'s `_SKIP_DIRS` walk — so a site quietly reverted to `tree_hash` goes
blind to it and its test reds, while the planned index-sourced fingerprint (which still sees every
committable path) keeps them green. No test asserts what the hash IS.

One deliberate asymmetry, so nobody "fixes" it: `test_node` stamps BEFORE `run_plan` (the suite is
pointed at that tree; the run itself executes target-repo code writably), while `factory.run_tests`
stamps AFTER its run — the coder's evidence describes the tree its run actually saw, and any later
write invalidates it at the comparator. Both directions are correct for what each stamp means.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from mosaera_core.config import Settings
from mosaera_core.graph._amendment import pinned_coder_validation
from mosaera_core.tools.repo import Workspace, build_repo_tools
from mosaera_core.validation import ValidationOutcome, ValidationPlan

_PLAN = ValidationPlan(project_type="python-pytest", steps=[], reason="stub", strength="suite")


def _ws(tmp_path: Path) -> Workspace:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def compute():\n    return 7\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(("git", "config", *cfg), cwd=tmp_path, check=True, capture_output=True)  # noqa: S603,S607 — git from PATH, no shell; test fixture
    subprocess.run(("git", "add", "-A"), cwd=tmp_path, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    subprocess.run(("git", "commit", "-qm", "base"), cwd=tmp_path, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    return Workspace(root=tmp_path, run_id="t", branch="b")


def _buried_write(root: Path, name: str = "backdoor.py") -> None:
    """Committable, but invisible to the `_SKIP_DIRS` walk — the discriminating write."""
    (root / "htmlcov").mkdir(exist_ok=True)
    (root / "htmlcov" / name).write_text("TOKEN = 'x'\n", encoding="utf-8")


def _scratch_write(root: Path) -> None:
    """Root `.mosaera/` — `_stage_all` resets it out of every commit; must never move a stamp."""
    (root / ".mosaera" / "scratch").mkdir(parents=True, exist_ok=True)
    (root / ".mosaera" / "scratch" / "notes.md").write_text("scratch\n", encoding="utf-8")


def _test_node(ws: Workspace, monkeypatch: Any, run_plan: Any = None) -> dict[str, Any]:
    """The real `test_node`, validation stubbed — the stamp is what is under test."""
    import mosaera_core.graph.nodes_impl as impl

    monkeypatch.setattr(impl, "resolve_plan", lambda *a, **k: _PLAN)
    monkeypatch.setattr(
        impl,
        "run_plan",
        run_plan or (lambda *a, **k: ValidationOutcome(passed=True, output="1 passed")),
    )
    ctx = SimpleNamespace(
        settings=Settings(scan_enabled=False),
        workspace=ws,
        sandbox=None,
        test_cmd=None,
        evidence_memo={},
        max_iter=8,
        max_reason=1,
        memory=None,
        item_id=None,
        project_id=None,
        operator_sanctioned={},
    )
    return impl.test_node(ctx, {})  # type: ignore[arg-type]


# --- site 1: nodes_impl `verified_tree` (writer) --------------------------------------------


def test_verified_tree_MOVES_on_a_committable_write_and_not_on_scratch(
    tmp_path: Path, monkeypatch: Any
) -> None:
    ws = _ws(tmp_path)
    stamp1 = _test_node(ws, monkeypatch)["verified_tree"]
    _buried_write(tmp_path)
    stamp2 = _test_node(ws, monkeypatch)["verified_tree"]
    assert stamp1 != stamp2, (
        "a write the delivery path would commit left `verified_tree` unmoved — the stamp is blind "
        "to part of the tree that ships"
    )
    _scratch_write(tmp_path)
    stamp3 = _test_node(ws, monkeypatch)["verified_tree"]
    assert stamp2 == stamp3, "a root-scratch write moved the stamp; scratch can never ship"


def test_verified_tree_is_stamped_BEFORE_the_suite_runs(tmp_path: Path, monkeypatch: Any) -> None:
    """The 1b timing regression, pinned. `run_plan` is the writable, network-on phase running
    TARGET-REPO code; a post-run stamp certifies a tree including whatever validation itself wrote.
    This slid to post-run in `f0666bfa` and nothing noticed until a red team read the ordering."""
    ws = _ws(tmp_path)
    before = ws.evidence_hash()

    def _writing_run(*_a: Any, **_k: Any) -> ValidationOutcome:
        _buried_write(tmp_path, "written_during_validation.py")
        return ValidationOutcome(passed=True, output="1 passed")

    result = _test_node(ws, monkeypatch, run_plan=_writing_run)
    assert result["verified_tree"] == before, (
        "`verified_tree` includes a file written DURING validation — the stamp certifies a tree "
        "the suite never saw"
    )
    assert ws.evidence_hash() != before, "premise: the run really did move the tree"


# --- sites 1+2 as a pair: the stamp `delivery_check` actually compares ----------------------


def test_delivery_check_reverifies_a_moved_tree_and_only_a_moved_tree(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Writer and comparator together, so a revert of EITHER side reds.

    Same-source revert of both (the exact red-team M14 mutation) fails the moved-tree half — the
    buried write is invisible to the walk, so `current == verified` and the backstop stays silent.
    A one-sided revert fails the fresh half, because the two sides then speak different formats.
    """
    import mosaera_core.graph._baseline as bl

    ws = _ws(tmp_path)
    stamp = _test_node(ws, monkeypatch)["verified_tree"]  # the PRODUCTION writer's stamp

    monkeypatch.setattr(bl, "resolve_plan", lambda *a, **k: _PLAN)
    monkeypatch.setattr(
        bl, "run_plan", lambda *a, **k: ValidationOutcome(passed=True, output="1 passed")
    )
    ctx = SimpleNamespace(
        workspace=ws,
        sandbox=object(),
        test_cmd=None,
        memory=None,
        project_id="p1",
        run_id="r1",
        settings=SimpleNamespace(sandbox_install=False, sandbox_install_timeout=None),
    )
    state = {"tests_passed": True, "verified_tree": stamp}

    assert bl.delivery_check(ctx, state) == {}, (
        "an UNMOVED tree was re-verified — the writer's stamp and the comparator's reading of the "
        "same tree disagree"
    )
    _buried_write(tmp_path)
    assert bl.delivery_check(ctx, state) != {}, (
        "a committable write landed after validation and the delivery backstop stayed silent"
    )
    # And scratch alone must not trigger it: fresh stamp, scratch write, still no question.
    stamp2 = _test_node(ws, monkeypatch)["verified_tree"]
    _scratch_write(tmp_path)
    assert bl.delivery_check(ctx, {"tests_passed": True, "verified_tree": stamp2}) == {}


# --- sites 4+3 as a pair: the coder's own validation, stamped by the REAL tool --------------


def test_the_coders_run_tests_evidence_is_pinned_to_the_tree_it_saw(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """`run_tests` (the production stamp writer) + `pinned_coder_validation` (the comparator).

    This is the F70/#75 pin: the coder runs the suite, then writes code and raises its hand — the
    recorded output must stop vouching the moment the tree moves, because it is about to help
    authorize amending an acceptance test.
    """
    ws = _ws(tmp_path)
    # A walk-invisible committable file must exist BEFORE the stamp, or the test cannot see a
    # stamp-source revert at all: on a tree where the walk and git listings coincide, `tree_hash`
    # and `evidence_hash` emit IDENTICAL hashes (same stat-line format over the same set), so the
    # reverted writer produces the right value by accident and every assertion stays green. The
    # first version of this test had exactly that hole — its M-factory mutation survived.
    _buried_write(tmp_path, "pre_existing.py")
    # `build_repo_tools` imports these function-locally at build time, so patch the SOURCE module
    # before building — patching the factory namespace is a silent no-op.
    monkeypatch.setattr("mosaera_core.validation.resolve_plan", lambda *a, **k: _PLAN)
    monkeypatch.setattr(
        "mosaera_core.validation.run_plan",
        lambda *a, **k: ValidationOutcome(passed=True, output="32 passed"),
    )
    coder_validation: dict[str, str] = {}
    tools = build_repo_tools(
        ws,
        sandbox=cast(Any, None),  # run_plan is stubbed; the sandbox is never touched
        approval_gate=False,
        install=False,
        coder_validation=coder_validation,
    )
    run_tests = next(t for t in tools if t.name == "run_tests")
    run_tests.invoke({})
    assert coder_validation.get("output") == "32 passed", "premise: the real tool stamped"

    ctx = SimpleNamespace(workspace=ws, coder_validation=coder_validation)
    assert pinned_coder_validation(ctx) == "32 passed", (
        "an unmoved tree was refused — stamp and comparator disagree about the same tree"
    )
    _scratch_write(tmp_path)
    assert pinned_coder_validation(ctx) == "32 passed", "scratch alone must not void the evidence"
    _buried_write(tmp_path, "written_after_the_run.py")
    assert pinned_coder_validation(ctx) == "", (
        "the tree moved after the coder's run and its output still vouches — the exact evidence "
        "laundering the pin exists to stop"
    )
