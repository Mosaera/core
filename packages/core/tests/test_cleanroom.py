"""The delivered artifact is checked as a CONSUMER meets it, not as the sandbox prepared it (#104).

Every fixture here is drawn from the real LedgerCLI failure of 2026-08-23, where 15 gate-approved
items and a proof panel reading 14/14 on every axis produced a repository that did not run when
cloned. The load-bearing pins:

- **an unparseable manifest is `not_checked`, never `passed`** — a check that reported success on a
  project it could not examine would be this same defect one level up;
- **the README is read, never executed** — CLAUDE.md treats repo content as untrusted data, and the
  install phase is the sandbox's one egress exception.
"""

from __future__ import annotations

from pathlib import Path

from mosaera_core.cleanroom import (
    documented_commands,
    read_manifest,
    undeclared_imports,
    undocumented_entry_points,
)


def _tree(tmp_path: Path, pyproject: str | None = None, readme: str | None = None) -> Path:
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject)
    if readme is not None:
        (tmp_path / "README.md").write_text(readme)
    return tmp_path


# ---------------------------------------------------------------- the manifest is the authority


def test_a_declared_package_reports_its_scripts_and_dependencies(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        pyproject="""
[project]
name = "budget_tracker"
version = "0.1.0"
dependencies = []

[project.scripts]
budget = "budget_tracker.cli:main"
""",
    )
    m = read_manifest(root)
    assert m.installable is True
    assert m.name == "budget_tracker"
    assert m.scripts == ("budget",)
    assert m.dependencies == ()


def test_LEDGERCLI_AS_DELIVERED_declared_no_scripts(tmp_path: Path) -> None:
    """Verbatim from the merged `main` of 2026-08-23. `pip install -e .` succeeded and the `budget`
    command the README used in every example did not exist, because nothing declared it."""
    root = _tree(
        tmp_path,
        pyproject="""
[build-system]
requires = ["setuptools>=45"]
build-backend = "setuptools.build_meta"

[project]
name = "budget_tracker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
""",
    )
    m = read_manifest(root)
    assert m.installable is True
    assert m.scripts == (), "no console script was declared — that WAS the defect"


def test_a_missing_manifest_is_UNREADABLE_not_installable(tmp_path: Path) -> None:
    m = read_manifest(tmp_path)
    assert m.installable is False
    assert "no pyproject.toml" in m.unreadable


def test_a_tool_config_only_pyproject_declares_no_package(tmp_path: Path) -> None:
    """`_install_step` draws the same line for the same reason: `pip install .` on it fails."""
    root = _tree(tmp_path, pyproject="[tool.ruff]\nline-length = 100\n")
    m = read_manifest(root)
    assert m.installable is False
    assert "no [project]" in m.unreadable


def test_a_corrupt_manifest_says_so_rather_than_raising(tmp_path: Path) -> None:
    root = _tree(tmp_path, pyproject="[project\nname = broken")
    m = read_manifest(root)
    assert m.installable is False
    assert "could not be parsed" in m.unreadable


# ------------------------------------------------------ the README is read, and only read


def test_commands_are_taken_from_FENCED_BLOCKS_not_prose() -> None:
    """Prose mentioning a word is not a usage example. Precision is what makes this worth
    reporting at all — a finding the operator cannot trust is noise."""
    readme = """
# Budget

Run the budget command to track spending.

```
$ budget add 12.34 food
$ budget list
```
"""
    assert documented_commands(readme) == ("budget",)


def test_well_known_tooling_is_not_mistaken_for_the_project(tmp_path: Path) -> None:
    """A README showing `pip install .` documents pip, not a promised `pip` entry point."""
    readme = "```\n$ pip install -e .\n$ python -m budget_tracker.cli --help\n$ pytest\n```"
    assert documented_commands(readme) == ()


def test_THE_LEDGERCLI_DEFECT_documented_command_that_nothing_provides(tmp_path: Path) -> None:
    """The finding worth having, obtained by READING: every usage example ran `budget`, and
    `[project.scripts]` was absent, so `budget` did not exist after installing."""
    root = _tree(
        tmp_path,
        pyproject='[project]\nname = "budget_tracker"\nversion = "0.1.0"\n',
        readme="```\n$ budget add 12.34 food\n$ budget summary --month 2026-08\n```",
    )
    missing = undocumented_entry_points(read_manifest(root), (root / "README.md").read_text())
    assert missing == ("budget",)


def test_a_declared_script_is_not_reported(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        pyproject=(
            '[project]\nname = "budget_tracker"\nversion = "0.1.0"\n'
            '\n[project.scripts]\nbudget = "budget_tracker.cli:main"\n'
        ),
        readme="```\n$ budget add 12.34 food\n```",
    )
    assert undocumented_entry_points(read_manifest(root), (root / "README.md").read_text()) == ()


def test_an_unreadable_manifest_reports_NO_missing_commands(tmp_path: Path) -> None:
    """With nothing to compare against, every documented command would look missing. A wall of
    false findings is worse than none, and would teach the operator to ignore this panel."""
    root = _tree(tmp_path, readme="```\n$ budget add 1\n$ ledger report\n```")
    assert undocumented_entry_points(read_manifest(root), (root / "README.md").read_text()) == ()


def test_control_characters_in_a_README_cannot_shape_the_verdict() -> None:
    """Repo content is untrusted. A crafted README must not be able to fake structure in a
    verdict the operator reads — the treatment `mapview` already gives repo-sourced text."""
    readme = "```\n$ budget\x00\x07 add\n```"
    assert documented_commands(readme) == ("budget",)


def test_no_readme_is_not_a_finding() -> None:
    assert documented_commands("") == ()


def test_OUTPUT_INSIDE_A_BLOCK_IS_NOT_A_COMMAND() -> None:
    """Found by running this against LedgerCLI's real README before trusting it.

    A fenced block holds commands AND their output, and output is far more common. Without the `$`
    prompt requirement this reported `amount`, `category`, `food` and `transport` — CSV headers and
    `status` output — as missing entry points. Four false findings on the first real repository,
    which is exactly how a panel teaches an operator to ignore it.

    The unit fixtures all used `$` and so could not have caught this. Real data did."""
    readme = """
```sh
$ budget list
amount,category,note,date
12.34,food,Lunch,2026-08-01
```

```sh
$ budget status
food: spent 12.34 / cap 200.00 (OK)
transport: spent 5.67 / cap 50.00 (OK)
```
"""
    assert documented_commands(readme) == ("budget",)


def test_a_readme_without_prompts_yields_nothing_rather_than_guesses() -> None:
    """Precision over recall — the bar `reachability.py` sets for the sibling intake axis. A missed
    finding costs nothing; a false one costs the panel's credibility."""
    assert documented_commands("```\nbudget add 1 food\n```") == ()


# ------------------------------------------------ undeclared imports: the pytest defect itself


def _pkg(tmp_path: Path, deps: str = "[]", name: str = "budget_tracker") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.1.0"\ndependencies = {deps}\n'
    )
    (tmp_path / "src" / name).mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_THE_LEDGERCLI_DEFECT_a_zero_dep_project_that_imports_pytest(tmp_path: Path) -> None:
    """Three test files did exactly this, against a brief mandating zero dependencies, and every
    gate passed — `_install_step` builds the sandbox venv with `--system-site-packages`, so the base
    image's pytest was importable regardless of what the project declared."""
    root = _pkg(tmp_path)
    (root / "tests" / "test_version.py").write_text("import pytest\nimport unittest\n")
    found = undeclared_imports(root, read_manifest(root))
    assert len(found) == 1
    assert found[0].startswith("pytest (imported by tests/test_version.py)")


def test_stdlib_is_never_reported(tmp_path: Path) -> None:
    root = _pkg(tmp_path)
    (root / "tests" / "test_a.py").write_text(
        "import unittest, csv, decimal, pathlib\nfrom datetime import date\n"
    )
    assert undeclared_imports(root, read_manifest(root)) == ()


def test_the_projects_own_package_is_not_third_party(tmp_path: Path) -> None:
    root = _pkg(tmp_path)
    (root / "tests" / "test_a.py").write_text(
        "import budget_tracker\nfrom budget_tracker.cli import main\nfrom . import helpers\n"
    )
    assert undeclared_imports(root, read_manifest(root)) == ()


def test_a_DECLARED_dependency_is_not_a_finding(tmp_path: Path) -> None:
    """A project that legitimately uses pytest and says so is not doing anything wrong."""
    root = _pkg(tmp_path, deps='["pytest>=7.0"]')
    (root / "tests" / "test_a.py").write_text("import pytest\n")
    assert undeclared_imports(root, read_manifest(root)) == ()


def test_a_distribution_whose_import_name_differs_is_given_the_benefit_of_the_doubt(
    tmp_path: Path,
) -> None:
    """`PyYAML` provides `yaml`, `Pillow` provides `PIL`. The mapping is many-to-many in the wild,
    so a false finding here is easy and expensive — this check reports only where it is certain."""
    root = _pkg(tmp_path, deps='["PyYAML>=6", "python-dateutil"]')
    (root / "tests" / "test_a.py").write_text("import yaml\nimport dateutil\n")
    assert undeclared_imports(root, read_manifest(root)) == ()


def test_the_venv_and_caches_are_not_scanned(tmp_path: Path) -> None:
    """A consumer's clone has none of these; a prepared workspace does. Scanning them would report
    every dependency of every installed package."""
    root = _pkg(tmp_path)
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "thing.py").write_text("import requests\n")
    assert undeclared_imports(root, read_manifest(root)) == ()


def test_an_unparsable_python_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    root = _pkg(tmp_path)
    (root / "tests" / "broken.py").write_text("def (((\n")
    (root / "tests" / "test_a.py").write_text("import pytest\n")
    assert len(undeclared_imports(root, read_manifest(root))) == 1


def test_an_unreadable_manifest_reports_NOTHING(tmp_path: Path) -> None:
    """LOAD-BEARING. With no declaration to compare against, every import looks undeclared. A check
    that reported findings on a project it could not examine would be this same defect one level
    up — and unlike a missed finding, a wall of false ones destroys the panel's credibility."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("import pytest\nimport requests\n")
    assert undeclared_imports(tmp_path, read_manifest(tmp_path)) == ()
