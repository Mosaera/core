"""The protected-test set was EMPTY on every real target repo, two independent ways.

Round 3 of the ADR-0108 red team found the class is far wider than the arc that started it. Seven
security controls built their protected-file set from `Workspace.file_listing()` — a PRESENTATION
listing capped at 300 globally-sorted paths — and six of them additionally filtered on a ROOT
`tests/` directory. Either blind spot alone empties the set:

    401-file repo:   integrity_paths() -> []      (the cap; `tests/` sorts late)
    this repo:       git ls-files | grep -c '^tests/' -> 0   (the predicate; tests are nested)

An empty set means: the coder's write tools refuse nothing, the tamper baseline hashes nothing, and
`close_oracle_gap`'s guard — `any(...)` over an empty dict — is vacuously true while an EDITED
pre-existing test is promoted to the oracle the run ships on. Verified: the producer rewrote its own
acceptance test to `assert True` and `tampered_integrity` returned `[]`.

Every test here fails against `4d261e0d`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mosaera_core.testintegrity import (
    integrity_baseline,
    integrity_text,
    protected_test_paths,
    tampered_integrity,
)
from mosaera_core.tools.repo import Workspace

_REAL_TEST = "def test_the_customer_requirement():\n    assert compute(2) == 4\n"
_NEUTERED = "def test_the_customer_requirement():\n    assert True  # neutered\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)  # noqa: S603,S607 — git from PATH, no shell; test fixture


def _repo(root: Path, files: dict[str, str], *, commit: bool = True) -> Workspace:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    if commit:
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "base", "--allow-empty")
    return Workspace(root=root, run_id="t", branch="b")


def _big(root: Path, extra: dict[str, str]) -> Workspace:
    """A repo past the 300-path cap, with the interesting files sorting AFTER the cut."""
    files = {f"apps/f{i:04d}.ts": "export const x = 1\n" for i in range(400)}
    files.update(extra)
    return _repo(root, files)


# --- blind spot 1: the 300-path cap -------------------------------------------------------


def test_the_tamper_guard_SEES_a_rewritten_test_past_the_cap(tmp_path: Path) -> None:
    """THE headline defect. The guard the coder 'cannot edit around' was silent on any real repo."""
    ws = _big(tmp_path, {"tests/test_acceptance.py": _REAL_TEST})
    assert len(ws.file_listing()) == 300, "the presentation cap must still be 300 — the contrast"

    baseline = integrity_baseline(ws)
    assert "tests/test_acceptance.py" in baseline, (
        "the acceptance test was never baselined, so nothing about it is protected"
    )

    (tmp_path / "tests" / "test_acceptance.py").write_text(_NEUTERED, encoding="utf-8")
    assert tampered_integrity(ws, baseline) == ["tests/test_acceptance.py"], (
        "the producer rewrote its own exam and the tamper guard returned nothing"
    )


# --- blind spot 2: the root-`tests/` predicate ---------------------------------------------


def test_the_protected_set_is_NON_EMPTY_on_a_src_layout_repo(tmp_path: Path) -> None:
    """No root `tests/` — the shape of Mosaera itself, where `^tests/` matches 0 tracked files.

    Six sites filtered on `startswith("tests/")`, so on this layout they were empty regardless of
    the cap. Fixing only the famous blind spot would have shipped a control still dead here.
    """
    ws = _repo(
        tmp_path,
        {
            "packages/core/src/app.py": "def compute(n):\n    return n * 2\n",
            "packages/core/tests/test_app.py": _REAL_TEST,
            "packages/core/tests/conftest.py": "import sys\n",
        },
    )
    protected = protected_test_paths(ws)
    assert "packages/core/tests/test_app.py" in protected
    assert "packages/core/tests/conftest.py" in protected, (
        "a conftest decides WHICH tests run; the old `startswith('tests/')` covered it and the "
        "replacement must not narrow the set while claiming to widen it"
    )
    assert "packages/core/src/app.py" not in protected, "source files are not protected"


# --- the source must not over-protect ------------------------------------------------------


def test_the_protected_set_EXCLUDES_what_only_the_FILESYSTEM_WALK_can_see(tmp_path: Path) -> None:
    """THE CANARY — rebuilt, because the first version did not red the design it claimed to red.

    It said "This test reds that design" and it did not: a red-team agent implemented the union and
    all six tests passed. Its noise lived under `.tox/` and `vendor/node_modules/` — both
    `_SKIP_DIRS` names, never walked, so the union could never contain them. The test was
    decorative and its comment was false — the G-class defect, inside the guard against it.

    The noise here is visible to the WALK and invisible to GIT — the actual difference between
    the two sources:
      * a gitignored build tree — walked by `os.walk`, omitted by `--exclude-standard`;
      * a NESTED CHECKOUT — `os.walk` descends it, `ls-files` is boundary-aware and stops.
    Neither name is in `_SKIP_DIRS`, so `file_listing(limit=None)` genuinely returns both.

    The union of walk-plus-git therefore DOES contain them, so this test reds. Under it, any
    regenerated build artifact or sibling-checkout write raises `tests_tampered` — which is
    TERMINAL. That is the trade the union makes: a silent hole for a park that bricks every run.
    """
    ws = _repo(
        tmp_path,
        {
            "src/app.py": "x = 1\n",
            "tests/test_real.py": _REAL_TEST,
            ".gitignore": "build_out/\n",
            "build_out/tests/test_generated.py": "def test_g():\n    assert True\n",
        },
    )
    nested = tmp_path / "sibling"
    (nested / "tests").mkdir(parents=True)
    (nested / "tests" / "test_sibling.py").write_text(_REAL_TEST, encoding="utf-8")
    _git(nested, "init", "-q")

    walked = set(ws.file_listing(limit=None))
    assert "build_out/tests/test_generated.py" in walked, "premise: the walk sees the ignored tree"
    assert "sibling/tests/test_sibling.py" in walked, "premise: the walk descends a nested checkout"

    protected = protected_test_paths(ws)
    assert "tests/test_real.py" in protected
    for noise in ("build_out/tests/test_generated.py", "sibling/tests/test_sibling.py"):
        assert noise not in protected, (
            f"{noise} is visible only to the filesystem walk; protecting it makes every "
            f"regeneration a TERMINAL tamper park"
        )


def test_a_TRACKED_cache_named_directory_is_still_protected(tmp_path: Path) -> None:
    """The contrast: `_SKIP_DIRS` is a PRESENTATION concern and must not narrow the evidence set.

    `file_listing` prunes `htmlcov/` by name at any depth. If a repo TRACKS a test there, it ships —
    so the security listing must see it even though the walk would not. This is the direction the
    whole arc exists to fix, and it stops anyone "simplifying" the source back to the walk.
    """
    ws = _repo(tmp_path, {"src/app.py": "x = 1\n", "htmlcov/tests/test_tracked.py": _REAL_TEST})
    assert "htmlcov/tests/test_tracked.py" not in set(ws.file_listing(limit=None)), (
        "premise: the walk prunes it by directory name"
    )
    assert "htmlcov/tests/test_tracked.py" in protected_test_paths(ws), (
        "a TRACKED test the delivery path commits must be protected, wherever it lives"
    )


# --- the hole a pure-git source would CREATE ------------------------------------------------


def test_an_IGNORED_conftest_cannot_launder_a_suppression(tmp_path: Path) -> None:
    """Why `security_listing` is not simply `committable_paths`.

    pytest runs the WORKTREE, not the index. So a coder that writes `.gitignore` naming
    `conftest.py` and then an untracked `tests/conftest.py` carrying `collect_ignore` shrinks the
    suite while it still exits 0 — and a purely git-sourced listing cannot see the file at all.
    `security_listing` adds back ignored COLLECTION CONTROLS only, never ignored test files (which
    can neither ship nor suppress), so the vector closes without reopening the explosion above.
    """
    ws = _repo(tmp_path, {"src/app.py": "x = 1\n", "tests/test_real.py": _REAL_TEST})
    baseline = integrity_baseline(ws)

    (tmp_path / ".gitignore").write_text("conftest.py\n", encoding="utf-8")
    (tmp_path / "tests" / "conftest.py").write_text(
        'collect_ignore = ["test_real.py"]\n', encoding="utf-8"
    )
    assert "tests/conftest.py" not in ws.committable_paths(), "premise: git cannot see it"
    assert "tests/conftest.py" in ws.security_listing(), "but the security listing must"
    assert "tests/conftest.py" in tampered_integrity(ws, baseline), (
        "an ignored conftest silently dropped a requirement and nothing flagged it"
    )


# --- containment ----------------------------------------------------------------------------


def test_a_TRACKED_SYMLINK_never_leaks_host_bytes(tmp_path: Path) -> None:
    """`committable_paths` does not filter symlinks the way `file_listing` deliberately did.

    Without a guard, a source repo tracking `tests/test_x.py -> /etc/passwd` gets it read HOST-SIDE
    and carried into a model prompt and the operator's report. Skipping instead would be worse than
    useless: `""` reads as deleted, so every symlinked test would park the run forever. Git's own
    semantics are the answer — a link's content is its TARGET STRING.
    """
    secret = tmp_path / "outside_secret.txt"
    secret.write_text("SUPER-SECRET-HOST-BYTES\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_real.py").write_text(_REAL_TEST, encoding="utf-8")
    os.symlink(secret, root / "tests" / "test_leak.py")
    ws = _repo(root, {})

    assert "tests/test_leak.py" in protected_test_paths(ws), "a tracked symlink IS committable"
    text = integrity_text(ws, "tests/test_leak.py")
    assert "SUPER-SECRET" not in text, "host bytes were read through a tracked symlink"
    assert text == str(secret), "the content must be the link target, as git stores it"

    # Repointing the link is a real change and must trip the guard.
    baseline = integrity_baseline(ws)
    other = tmp_path / "other.txt"
    other.write_text("x\n", encoding="utf-8")
    (root / "tests" / "test_leak.py").unlink()
    os.symlink(other, root / "tests" / "test_leak.py")
    assert "tests/test_leak.py" in tampered_integrity(ws, baseline)


def test_security_listing_RAISES_rather_than_returning_an_empty_set(tmp_path: Path) -> None:
    """The polarity that is opposite to `evidence_hash`, and the reason it is spelled out.

    `evidence_hash` returns `""` on failure and that FAILS CLOSED — an empty fingerprint can never
    equal a stamp. There is no such value here: an empty listing reads downstream as
    refuses-nothing / baselines-nothing / guard-vacuously-true. So it must raise and let each
    caller decide, rather than fall back to the listing just proven blind.
    """
    import pytest
    from git.exc import InvalidGitRepositoryError, NoSuchPathError

    ws = Workspace(root=tmp_path / "not-a-repo", run_id="t", branch="b")
    with pytest.raises((InvalidGitRepositoryError, NoSuchPathError)):
        ws.security_listing()
