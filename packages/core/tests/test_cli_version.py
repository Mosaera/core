"""The `mosaera --version` flag (ADR-0055) + the maturity channel (ADR-0088)."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import mosaera_core
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_version_flag_prints_engine_version(capsys: Any) -> None:
    from mosaera_core.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert mosaera_core.__version__ in out
    # ADR-0088: the channel travels with the number wherever the number is shown.
    assert mosaera_core.__maturity__ in out


def test_version_is_present_and_dotted() -> None:
    # A minimal shape guard so an accidental blank/malformed bump is caught.
    assert mosaera_core.__version__.count(".") >= 2
    assert all(part.isdigit() for part in mosaera_core.__version__.split(".")[:3])


def test_version_is_a_plain_release_not_a_prerelease() -> None:
    """ADR-0088: maturity is a SEPARATE axis, never a suffix on the number.

    A SemVer-style ``0.6.1-beta.1`` is invalid PEP 440 — ``packaging`` normalizes it to
    ``0.6.1b1`` in metadata, filenames and lockfiles while ``__version__`` keeps the hyphen.
    That is drift by normalization, so the plain X.Y.Z shape is enforced, not merely preferred.
    """
    assert mosaera_core.__version__.replace(".", "").isdigit(), (
        f"{mosaera_core.__version__!r} must be a plain X.Y.Z release; "
        "maturity belongs in __maturity__ (ADR-0088)"
    )


def test_maturity_is_on_the_ladder() -> None:
    """ADR-0088: a closed set, so a typo can't invent an unmeaning channel."""
    assert mosaera_core.MATURITY_CHANNELS == ("alpha", "beta", "rc", "stable")
    assert mosaera_core.__maturity__ in mosaera_core.MATURITY_CHANNELS


def test_bump_script_ladder_matches_the_package() -> None:
    """The bump script carries its own copy of the ladder; it must not diverge."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bump_version", _REPO_ROOT / "scripts" / "bump_version.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.MATURITY_CHANNELS == mosaera_core.MATURITY_CHANNELS


def test_every_workspace_package_moves_together() -> None:
    """ADR-0055: "all 7 packages move together — one product".

    Enforced here because the invariant was PROSE-ONLY and duly drifted: the 0.5.0→0.6.0 bump
    edited six pyprojects and `__init__.py` but missed the WORKSPACE ROOT, which sat a release
    behind undetected. A mechanically-checkable invariant deserves a mechanical guard.

    Widened 2026-08-07 to cover `apps/web/package.json`, which had sat at 0.1.0 through two
    releases for exactly the same reason: it was outside the only guard that existed.
    """
    pyprojects = [
        _REPO_ROOT / "pyproject.toml",
        _REPO_ROOT / "apps" / "api" / "pyproject.toml",
        *sorted((_REPO_ROOT / "packages").glob("*/pyproject.toml")),
    ]
    found = {
        p.relative_to(_REPO_ROOT).as_posix(): tomllib.loads(p.read_text(encoding="utf-8"))[
            "project"
        ]["version"]
        for p in pyprojects
        if p.is_file()
    }
    assert len(found) == 7, f"expected 7 workspace pyprojects, found {sorted(found)}"

    web = _REPO_ROOT / "apps" / "web" / "package.json"
    if web.is_file():
        found["apps/web/package.json"] = json.loads(web.read_text(encoding="utf-8"))["version"]

    drifted = {k: v for k, v in found.items() if v != mosaera_core.__version__}
    assert not drifted, (
        f"version drift vs mosaera_core.__version__={mosaera_core.__version__}: {drifted}"
    )


def test_no_second_version_constant_in_the_workspace() -> None:
    """ADR-0055 names ONE runtime source of truth; a second constant is drift surface.

    `mosaera_agents.__version__` existed, was imported by nothing, and sat two releases behind.
    It was removed rather than synced — this keeps it removed.
    """
    # Match an ASSIGNMENT at column 0, not the bare token — prose explaining why a package has
    # no version constant is exactly the documentation this rule wants to keep.
    assignment = re.compile(r"^__version__\s*[:=]", re.MULTILINE)
    offenders = [
        p.relative_to(_REPO_ROOT).as_posix()
        for p in (_REPO_ROOT / "packages").glob("*/*/__init__.py")
        if p.parent.name != "mosaera_core" and assignment.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"second __version__ constant(s) found: {offenders}. ADR-0055: mosaera_core.__version__ "
        "is the single runtime source of truth."
    )


# --- the release-record check, which had ZERO coverage (2026-08-07 audit) ----------------------
#
# `verify_record` is the whole point of the CI `version-record` job, and nothing tested it. Its one
# real CI run was VACUOUS: the MR that introduced it did not move `__version__`, so it took the
# `old == new` early exit and reported success without ever exercising the rule. Four separate
# paths returned 0 on "could not look", and the job runs ONLY when `__init__.py` changed — i.e.
# exactly when it must actually verify. Every branch is pinned here, including the negatives.


def _bump_mod() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bump_version_rec", _REPO_ROOT / "scripts" / "bump_version.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_unverifiable_base_PASSES_locally_and_FAILS_in_ci() -> None:
    """The green-by-vacancy fix. A shallow-clone hiccup in CI must not be indistinguishable from
    a verified release; a developer on a detached tree should still get a note, not a red herring.
    """
    mod = _bump_mod()
    assert mod.verify_record("deadbeefdeadbeef") == 0
    assert mod.verify_record("deadbeefdeadbeef", strict=True) == 1


def test_an_unchanged_version_is_a_pass_in_both_modes() -> None:
    """The only honest early exit: nothing moved, so there is nothing to record."""
    mod = _bump_mod()
    assert mod.verify_record("HEAD") == 0
    assert mod.verify_record("HEAD", strict=True) == 0


def test_a_bump_with_no_CHANGELOG_heading_FAILS(monkeypatch: Any, tmp_path: Any) -> None:
    """THE rule the job exists to enforce, and the case its single CI run never reached.
    ADR-0055: a bump with no entry is a version number with no evidence behind it."""
    mod = _bump_mod()
    empty = tmp_path / "CHANGELOG.md"
    empty.write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
    monkeypatch.setattr(mod, "CHANGELOG", empty)
    monkeypatch.setattr(mod, "_current_version", lambda: "9.9.9")
    assert mod.verify_record("HEAD") == 1


def test_a_bump_WITH_its_CHANGELOG_heading_passes(monkeypatch: Any, tmp_path: Any) -> None:
    mod = _bump_mod()
    ch = tmp_path / "CHANGELOG.md"
    ch.write_text("# Changelog\n\n## 9.9.9 — 2026-08-07 — headline\n", encoding="utf-8")
    monkeypatch.setattr(mod, "CHANGELOG", ch)
    monkeypatch.setattr(mod, "_current_version", lambda: "9.9.9")
    assert mod.verify_record("HEAD") == 0
