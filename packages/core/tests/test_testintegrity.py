"""Unit tests for the test-integrity baseline (ADR-0036).

These prove the three suppression vectors are caught (edit a test, delete a test, shrink
collection via config/conftest) AND that a LEGITIMATE change does NOT false-trip — the latter
guards the class of false-park that commit 217d735's regression corpus exists to prevent.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.testintegrity import (
    integrity_baseline,
    integrity_hash,
    integrity_paths,
    is_test_file,
    tampered_integrity,
)
from mosaera_core.tools.repo import Workspace


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    """Write the files, then git-init — `integrity_paths` reads the git-sourced security listing.

    This built a BARE DIRECTORY until 2026-08-22, which was fine only because `integrity_paths`
    read the filesystem walk. It reads `security_listing` now, and that raises on a non-repo
    deliberately: an empty protected set is not a safe default, it is a silent hole.
    """
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return git_ws(tmp_path)


def git_ws(root: Path) -> Workspace:
    """A REAL `Workspace` over a git-init'd directory.

    Security controls read `Workspace.security_listing()`, which is git-sourced and RAISES rather
    than degrading — so a bare directory is not a workspace any more, it is a broken one. A commit
    is not needed: `ls-files -c -o --exclude-standard` lists untracked-not-ignored files too.

    This replaces `SimpleNamespace(root=..., file_listing=lambda: ...)` fakes. Those fakes were
    UNCAPPED while the real `file_listing` caps at 300, so every test using one exercised a
    workspace that does not exist — which is exactly why the protected-set blindness survived a
    green suite for months. A fake more capable than the real object proves nothing.
    """
    subprocess.run(("git", "init", "-q"), cwd=root, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(("git", "config", *cfg), cwd=root, check=True, capture_output=True)  # noqa: S603,S607 — git from PATH, no shell; test fixture
    return Workspace(root=root, run_id="t", branch="b")


def test_is_test_file_predicate() -> None:
    assert is_test_file("test_foo.py")
    assert is_test_file("tests/test_foo.py")
    assert is_test_file("pkg/foo_test.py")
    assert not is_test_file("foo.py")
    assert not is_test_file("conftest.py")


def test_integrity_paths_enumerates_the_surface(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_a(): assert True\n",
            "pkg/b_test.py": "def test_b(): assert True\n",
            "tests/conftest.py": "import pytest\n",
            "pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-q'\n",
            "src/app.py": "x = 1\n",  # not a test → excluded
            "README.md": "# hi\n",  # excluded
        },
    )
    paths = integrity_paths(ws)
    assert "tests/test_a.py" in paths
    assert "pkg/b_test.py" in paths
    assert "tests/conftest.py" in paths
    assert "pyproject.toml" in paths
    assert "src/app.py" not in paths
    assert "README.md" not in paths


def test_editing_a_pre_existing_test_is_tampering(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 5\n"})
    base = integrity_baseline(ws)
    assert tampered_integrity(ws, base) == []  # unchanged → clean
    # The coder weakens the assertion so a broken `compute` passes.
    (tmp_path / "tests/test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    assert tampered_integrity(ws, base) == ["tests/test_a.py"]


def test_deleting_a_pre_existing_test_is_tampering(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert False\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").unlink()
    assert tampered_integrity(ws, base) == ["tests/test_a.py"]


def test_adding_addopts_ignore_to_pyproject_is_tampering(tmp_path: Path) -> None:
    # The suppression vector that touches NO test file: shrink collection via config.
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_a(): assert False\n",
            "pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-q'\n",
        },
    )
    base = integrity_baseline(ws)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q --ignore=tests/test_a.py'\n", encoding="utf-8"
    )
    assert "pyproject.toml" in tampered_integrity(ws, base)


def test_adding_a_new_conftest_collect_ignore_is_tampering(tmp_path: Path) -> None:
    # A brand-new conftest.py (not in the baseline) with collect_ignore is a suppression
    # vector even though it edits no baselined path — the "new collection-control file" case.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert False\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/conftest.py").write_text(
        'collect_ignore = ["test_a.py"]\n', encoding="utf-8"
    )
    assert "tests/conftest.py" in tampered_integrity(ws, base)


def test_adding_a_dependency_to_pyproject_is_NOT_tampering(tmp_path: Path) -> None:
    # THE false-park guard (217d735 class): a legitimate run adds a dependency. We hash only
    # the pytest SECTION, so an edit elsewhere in pyproject.toml must be invisible.
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_a(): assert True\n",
            "pyproject.toml": (
                "[project]\ndependencies = ['httpx']\n\n[tool.pytest.ini_options]\naddopts = '-q'\n"
            ),
        },
    )
    base = integrity_baseline(ws)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\ndependencies = ['httpx', 'pydantic']\n\n"  # added a dep — legitimate
        "[tool.pytest.ini_options]\naddopts = '-q'\n",  # pytest section unchanged
        encoding="utf-8",
    )
    assert tampered_integrity(ws, base) == []


def test_adding_a_new_source_file_and_a_new_test_is_NOT_tampering(tmp_path: Path) -> None:
    # The normal happy path: the coder ADDS code and ADDS a test for it. New non-config,
    # non-conftest files are not tampering — only weakening the pre-existing surface is.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert True\n"})
    base = integrity_baseline(ws)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/feature.py").write_text("def f(): return 1\n", encoding="utf-8")
    (tmp_path / "tests/test_feature.py").write_text(
        "from src.feature import f\ndef test_f(): assert f() == 1\n", encoding="utf-8"
    )
    assert tampered_integrity(ws, base) == []


def test_ignore_excludes_tester_authored_paths(tmp_path: Path) -> None:
    # When the tester is on, it authors tests AFTER the baseline; those are legitimate and
    # governed by their own protected-path guard. They must not double-trip the integrity
    # check just for existing.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert True\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/conftest.py").write_text("import pytest\n", encoding="utf-8")
    # Without the ignore, the new conftest trips it; with it excluded, it is clean.
    assert "tests/conftest.py" in tampered_integrity(ws, base)
    assert tampered_integrity(ws, base, ignore=["tests/conftest.py"]) == []


def test_ignore_cannot_excuse_overwriting_a_pre_existing_test(tmp_path: Path) -> None:
    # The tester-collision hole (Phase 4): a pre-existing baselined test, overwritten at a
    # COLLIDING path that the tester then lists in authored_tests → the caller passes it in
    # `ignore`. `ignore` excuses newly-INTRODUCED paths only; a pre-existing baselined path must
    # never be excused, or the overwrite (loss of the real assertion) manufactures a green suite.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 5\n"})
    base = integrity_baseline(ws)
    # The tester (or coder via a colliding authored path) overwrites the pre-existing test.
    (tmp_path / "tests/test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    # Even though the path is "claimed" as authored, the overwrite is still flagged as tampering.
    assert tampered_integrity(ws, base, ignore=["tests/test_a.py"]) == ["tests/test_a.py"]


# --- #54 (ADR-0058): the Proctor's up-front, coder-blind repair excuse (proctor_edits) ---


def test_proctor_edits_excuses_exactly_the_sanctioned_content(tmp_path: Path) -> None:
    # The Proctor repairs an over-strict pre-existing test BEFORE the coder runs. Its post-edit
    # content, recorded in proctor_edits (integrity hash space), is excused — not flagged as tamper.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    # The Proctor loosens an over-strict assertion (the task said "non-zero", not "== 2").
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    # Without the excuse it reads as tampering; with the sanctioned hash it is clean.
    assert tampered_integrity(ws, base) == ["tests/test_a.py"]
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    assert tampered_integrity(ws, base, proctor_edits=sanctioned) == []


def test_proctor_edits_does_not_excuse_a_later_re_weakening(tmp_path: Path) -> None:
    # The excuse is content-pinned to the Proctor's exact edit. A DIFFERENT change to the same path
    # afterwards (a coder weakening the Proctor's repaired test) still trips deny-by-default.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    # The coder now weakens the Proctor's repaired test to a tautology.
    (tmp_path / "tests/test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    assert tampered_integrity(ws, base, proctor_edits=sanctioned) == ["tests/test_a.py"]


def test_proctor_edits_never_excuses_a_deletion(tmp_path: Path) -> None:
    # Deleting a test drops a requirement wholesale. Even with a proctor_edits entry for the path,
    # the on-disk content becomes "" (missing) → its hash can never equal the sanctioned edit hash.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    (tmp_path / "tests/test_a.py").unlink()  # deletion
    assert tampered_integrity(ws, base, proctor_edits=sanctioned) == ["tests/test_a.py"]


def test_proctor_edits_is_correct_hash_space_no_crlf_false_park(tmp_path: Path) -> None:
    # The gap_fill lesson: a raw-bytes hash lands in the WRONG space and false-parks on CRLF.
    # integrity_hash newline-normalizes, so the SAME logical content written with CRLF still matches
    # the sanctioned LF hash — no false tamper on Windows line endings.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    # Rewrite the identical content with CRLF line endings (bytes differ, logical content does not).
    (tmp_path / "tests/test_a.py").write_bytes(b"def test_a():\r\n    assert compute() != 0\r\n")
    assert tampered_integrity(ws, base, proctor_edits=sanctioned) == []


def test_proctor_edits_wrong_hash_does_not_excuse(tmp_path: Path) -> None:
    # A proctor_edits value in the WRONG space (e.g. a raw-bytes hash) or otherwise not matching the
    # on-disk integrity content excuses nothing — the excuse is a strict content match (deny first).
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    bogus = {"tests/test_a.py": "deadbeef" * 8}  # a plausible-looking but wrong hash
    assert tampered_integrity(ws, base, proctor_edits=bogus) == ["tests/test_a.py"]


def test_proctor_edits_never_excuses_an_emptied_test(tmp_path: Path) -> None:
    # Red-team #54 FN1: emptying a test (write_file "") drops the requirement wholesale, like
    # deleting — and an empty file's integrity content hashes to hash(""), which a sanctioned
    # hash("") would otherwise launder. The guard treats EMPTY on-disk content as ALWAYS tampering,
    # even if proctor_edits sanctions hash("") (complements the builder-side assertion floor).
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text("", encoding="utf-8")  # emptied
    empty_hash = integrity_hash(ws, "tests/test_a.py")  # == hash("")
    # Even with the emptied hash "sanctioned", the guard still flags it.
    assert tampered_integrity(ws, base, proctor_edits={"tests/test_a.py": empty_hash}) == [
        "tests/test_a.py"
    ]


def test_proctor_edits_empty_hash_cannot_excuse_a_later_deletion(tmp_path: Path) -> None:
    # The empty/deleted collision: both yield hash(""). A sanctioned hash("") must not excuse a
    # subsequent DELETION either — the empty-content rule covers deletion (missing → "" content).
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert compute() == 2\n"})
    base = integrity_baseline(ws)
    sanctioned = {
        "tests/test_a.py": integrity_hash(_ws(tmp_path, {"tests/test_a.py": ""}), "tests/test_a.py")
    }
    (tmp_path / "tests/test_a.py").unlink()  # deleted → "" content → hash("")
    assert tampered_integrity(ws, base, proctor_edits=sanctioned) == ["tests/test_a.py"]


def test_proctor_edits_scoped_to_named_paths_only(tmp_path: Path) -> None:
    # An excuse for one path never leaks to another baselined path the coder tampered with.
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_a():\n    assert compute() == 2\n",
            "tests/test_b.py": "def test_b():\n    assert other() == 3\n",
        },
    )
    base = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert compute() != 0\n", encoding="utf-8"
    )
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    # The coder weakens a DIFFERENT test; the a-scoped excuse must not cover it.
    (tmp_path / "tests/test_b.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")
    assert tampered_integrity(ws, base, proctor_edits=sanctioned) == ["tests/test_b.py"]


# --- A NEW collection-control file: flag it only if it actually controls collection (F38). ---
# The "new collection-control file" rule flagged on FILENAME alone. Measured 2026-08-06, run
# 20260806-080913-0d3928: the coder scaffolded pyproject.toml — acceptance criterion #1 of the
# slice — the suite went green (7 passed), and the gate blocked delivery on tests_tampered. Any
# Python project whose first slice creates pyproject.toml was structurally undeliverable. This is
# the same false-park class as test_adding_a_dependency_to_pyproject_is_NOT_tampering, which the
# module already guards for BASELINED files by hashing only the pytest section.


def test_a_new_pyproject_without_a_pytest_section_is_NOT_tampering(tmp_path: Path) -> None:
    # The real file from the run: build metadata and a console script, no pytest config at all.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert True\n"})
    base = integrity_baseline(ws)
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=45", "wheel"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        '[project]\nname = "budget-tracker"\nversion = "0.1.0"\n\n'
        '[project.scripts]\nbudget = "budget_tracker.__main__:main"\n',
        encoding="utf-8",
    )
    # It controls no collection, so it can suppress nothing — flagging it proves nothing and
    # costs a delivery.
    assert tampered_integrity(ws, base) == []


def test_a_new_pyproject_WITH_a_pytest_section_is_tampering(tmp_path: Path) -> None:
    # The vector the rule exists for: a fresh pytest config CAN shrink collection.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert False\n"})
    base = integrity_baseline(ws)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q --ignore=tests/test_a.py'\n", encoding="utf-8"
    )
    assert "pyproject.toml" in tampered_integrity(ws, base)


def test_a_new_setup_cfg_with_a_pytest_section_is_tampering(tmp_path: Path) -> None:
    # The other config spellings keep working — the fix must not be pyproject-specific.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert False\n"})
    base = integrity_baseline(ws)
    (tmp_path / "setup.cfg").write_text(
        "[tool:pytest]\naddopts = --ignore=tests/test_a.py\n", encoding="utf-8"
    )
    assert "setup.cfg" in tampered_integrity(ws, base)


def test_a_new_empty_conftest_is_NOT_tampering(tmp_path: Path) -> None:
    # An empty conftest suppresses nothing. A conftest WITH content is still caught — see
    # test_adding_a_new_conftest_collect_ignore_is_tampering, which must keep passing.
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a(): assert True\n"})
    base = integrity_baseline(ws)
    (tmp_path / "tests/conftest.py").write_text("", encoding="utf-8")
    assert tampered_integrity(ws, base) == []
    # Whitespace controls collection exactly as much as emptiness does — nothing. (Red-team of
    # the F38 change: this was the one inconsistency it turned up.)
    (tmp_path / "tests/conftest.py").write_text("   \n\n", encoding="utf-8")
    assert tampered_integrity(ws, base) == []


# --- operator_edits: the operator's write-gate approval as a fact the guard reads (F63, #65) ---
#
# An item whose PURPOSE is to change behaviour necessarily invalidates the test encoding the old
# behaviour. That test is baselined, editing it trips this guard, and a tamper verdict is terminal
# — so the work deadlocks. Measured 2026-08-06: a five-line deletion took three runs and ~4M
# tokens and never shipped, because the operator's explicit authorization lived in a feedback
# string that `tampered_integrity` never saw.


def test_an_operator_sanctioned_edit_is_excused(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_x():\n    assert f() == 1\n"})
    baseline = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_x():\n    assert f(month='2023-08') == 1\n", encoding="utf-8"
    )
    assert tampered_integrity(ws, baseline) == ["tests/test_a.py"]  # without the sanction
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    assert tampered_integrity(ws, baseline, operator_edits=sanctioned) == []


def test_the_sanction_is_content_pinned_not_a_blanket_pass(tmp_path: Path) -> None:
    """The property that makes this safe: authorizing ONE content does not open the path."""
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_x():\n    assert f() == 1\n"})
    baseline = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_x():\n    assert g() == 2\n", encoding="utf-8"
    )
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    # A LATER, different edit at the same path — the coder re-weakening after the approval.
    (tmp_path / "tests/test_a.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    assert tampered_integrity(ws, baseline, operator_edits=sanctioned) == ["tests/test_a.py"]


def test_an_operator_may_never_sanction_an_emptied_or_deleted_test(tmp_path: Path) -> None:
    """Red-team #54 FN1, re-pinned for the new source: emptying drops a requirement wholesale, so
    it is tampering even with a sanction recorded. Human authority does not extend to deletion."""
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_x():\n    assert f() == 1\n"})
    baseline = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text("", encoding="utf-8")
    empty_hash = integrity_hash(ws, "tests/test_a.py")
    assert tampered_integrity(ws, baseline, operator_edits={"tests/test_a.py": empty_hash}) == [
        "tests/test_a.py"
    ]
    (tmp_path / "tests/test_a.py").unlink()
    assert tampered_integrity(ws, baseline, operator_edits={"tests/test_a.py": empty_hash}) == [
        "tests/test_a.py"
    ]


def test_both_sanction_sources_coexist(tmp_path: Path) -> None:
    """The Proctor's repair and the operator's approval are the same excuse from different
    authorities — neither shadows the other."""
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_a():\n    assert 1\n",
            "tests/test_b.py": "def test_b():\n    assert 2\n",
        },
    )
    baseline = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_a():\n    assert f() == 1\n", encoding="utf-8"
    )
    (tmp_path / "tests/test_b.py").write_text(
        "def test_b():\n    assert g() == 2\n", encoding="utf-8"
    )
    assert (
        tampered_integrity(
            ws,
            baseline,
            proctor_edits={"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")},
            operator_edits={"tests/test_b.py": integrity_hash(ws, "tests/test_b.py")},
        )
        == []
    )


def test_an_operator_may_not_sanction_a_collection_control_file(tmp_path: Path) -> None:
    """Red team of the operator-sanction change, round 2 — FIX-NOW.

    Human authority extends to amending a test's CONTENT, never to removing tests from the run.
    A `collect_ignore` or an `addopts=--ignore` drops requirements wholesale exactly as emptying a
    test does (the FN1 rule) — and it is WORSE to review, because the effect is invisible in any
    test file: an operator can approve a small-looking config diff that silently shrinks the suite
    while pytest still exits 0.
    """
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_x():\n    assert 1\n",
            "conftest.py": "x = 1\n",
            "pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
        },
    )
    baseline = integrity_baseline(ws)

    (tmp_path / "conftest.py").write_text(
        "collect_ignore = ['tests/test_a.py']\n", encoding="utf-8"
    )
    sanctioned = {"conftest.py": integrity_hash(ws, "conftest.py")}
    assert tampered_integrity(ws, baseline, operator_edits=sanctioned) == ["conftest.py"]

    (tmp_path / "conftest.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '--ignore=tests/test_a.py'\n", encoding="utf-8"
    )
    sanctioned = {"pyproject.toml": integrity_hash(ws, "pyproject.toml")}
    assert tampered_integrity(ws, baseline, operator_edits=sanctioned) == ["pyproject.toml"]


def test_a_sanction_is_scoped_to_its_own_path(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            "tests/test_a.py": "def test_a():\n    assert 1\n",
            "tests/test_b.py": "def test_b():\n    assert 2\n",
        },
    )
    baseline = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text("def test_a():\n    assert v2()\n", encoding="utf-8")
    (tmp_path / "tests/test_b.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")
    sanctioned = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    assert tampered_integrity(ws, baseline, operator_edits=sanctioned) == ["tests/test_b.py"]


# --- the NODE wiring: a sanction must survive a rehydrate -------------------------------------
#
# `tampered_integrity` above is a pure function and was never the problem. `test_node` is, because
# it read the sanctions from `ctx.operator_sanctioned` — a PROCESS-LOCAL dict rebuilt empty by
# `build_graph` — while writing them to the checkpointed `operator_edits` key and never reading it
# back. A parked run that resumes in a fresh process (the exact case the durable PostgresSaver
# exists for) therefore lost every approval a human had already given, and re-parked on it.
#
# Same defect class as F35: state that only lives in a tool closure does not survive a resume. It
# fails CLOSED, so it was never a hole — but F63's fix did not work across the restart it was
# built for, and the escalation-gate amendment (ADR-0087) rests on this surviving.


def _drive_test_node(ws: Workspace, monkeypatch: Any, ctx_sanctions: dict, state: dict) -> dict:
    """The real `test_node`, validation stubbed green — the tamper check is what is under test."""
    import mosaera_core.graph.nodes_impl as impl
    from mosaera_core.config import Settings
    from mosaera_core.validation import ValidationOutcome, ValidationPlan

    plan = ValidationPlan(project_type="python-pytest", steps=[], reason="stub", strength="suite")
    monkeypatch.setattr(impl, "resolve_plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        impl, "run_plan", lambda *a, **k: ValidationOutcome(passed=True, output="1 passed")
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
        operator_sanctioned=ctx_sanctions,
    )
    return impl.test_node(ctx, state)  # type: ignore[arg-type]


def _sanctioned_state(tmp_path: Path) -> tuple[Workspace, dict, dict]:
    """A run that amended a baselined test under a human approval, then was checkpointed."""
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_x():\n    assert f() == 1\n"})
    baseline = integrity_baseline(ws)
    (tmp_path / "tests/test_a.py").write_text(
        "def test_x():\n    assert f(month='2023-08') == 1\n", encoding="utf-8"
    )
    sanctions = {"tests/test_a.py": integrity_hash(ws, "tests/test_a.py")}
    return ws, baseline, sanctions


def test_a_sanction_survives_a_rehydrate_into_a_fresh_process(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The regression pin. `ctx.operator_sanctioned` is EMPTY (a fresh process after a restart);
    the approval survives only in checkpointed state. It must still be excused."""
    ws, baseline, sanctions = _sanctioned_state(tmp_path)
    result = _drive_test_node(
        ws,
        monkeypatch,
        {},  # rebuilt empty by build_graph on rehydrate
        {"integrity_baseline": baseline, "operator_edits": sanctions},
    )
    assert result["tests_modified"] is False
    assert result["tampered_paths"] == []


def test_a_path_sanctioned_in_neither_source_still_trips(tmp_path: Path, monkeypatch: Any) -> None:
    """The merge must not become a blanket pass: no sanction anywhere ⇒ the guard still fires."""
    ws, baseline, _ = _sanctioned_state(tmp_path)
    result = _drive_test_node(ws, monkeypatch, {}, {"integrity_baseline": baseline})
    assert result["tests_modified"] is True
    assert result["tampered_paths"] == ["tests/test_a.py"]


def test_an_in_process_sanction_is_unchanged(tmp_path: Path, monkeypatch: Any) -> None:
    """Single-process behaviour is byte-identical: the live dict alone still excuses."""
    ws, baseline, sanctions = _sanctioned_state(tmp_path)
    result = _drive_test_node(ws, monkeypatch, sanctions, {"integrity_baseline": baseline})
    assert result["tests_modified"] is False
    # And the merged set is surfaced for the report/diagnosis, not just consumed.
    assert result["operator_edits"] == sanctions
