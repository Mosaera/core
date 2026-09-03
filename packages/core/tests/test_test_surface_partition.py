"""The test surface is FOUR named sets, not one — and one of them must read the target's config.

Two defects made this necessary, both from treating `protected_test_paths` (wide) and
`integrity_paths` (exact) as the same thing: an oracle that vouched while pytest never collected
anything, and supersession deleting a pre-existing human test believing it engine-authored.

A collapse into one set is not achievable. Two live consumers of the same call need OPPOSITE answers
about the same file, and `test_the_partition_is_NECESSARY_not_stylistic` below is the pair that
proves it. ADR-0081 recorded the smell before either defect landed: "a single predicate serving both
[scrutiny and protection] is a smell".

Against `8f102902` every test here fails — but be precise about WHY, because the distinction is the
kind this file exists to enforce: most fail on LOGIC, while `test_regenerating_a_FIXTURE_...` and
half of `test_an_unconfigured_repo_...` passed under the old logic and fail there only because
`pytestconfig` did not exist (ImportError). They are valid regression pins; "all of them catch the
old defect" would have been an overstatement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mosaera_core.eligibility import trapping_engine_tests
from mosaera_core.pytestconfig import DEFAULT_PYTHON_FILES, resolve_naming
from mosaera_core.testintegrity import (
    integrity_baseline,
    integrity_paths,
    is_collection_control,
    is_test_file,
    protected_test_paths,
    resolve_test_surface,
    tampered_integrity,
)
from mosaera_core.tools.repo import Workspace

_REAL = "def test_requirement():\n    assert compute() == 7\n"
_NEUTERED = "def test_requirement():\n    assert True  # neutered\n"


def _repo(root: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=root, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    return Workspace(root=root, run_id="t", branch="b")


# --- the headline: a repo that renames its tests --------------------------------------------


def test_a_python_files_repo_is_PROTECTED(tmp_path: Path) -> None:
    """THE claim `1f710222` made and did not deliver.

    Its commit message said the producer could no longer rewrite its acceptance test undetected.
    On a repo setting `python_files`, that was still exactly reproducible: `is_test_file` hard-codes
    pytest's DEFAULT naming, so NO test was baselined and the rewrite raised nothing. `1f710222`
    fixed which paths were ENUMERATED; it never fixed which of them COUNT.

        integrity_paths -> ['pyproject.toml']
        tamper after rewriting the test -> []
    """
    ws = _repo(
        tmp_path,
        {
            "pyproject.toml": '[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n',
            "src/app.py": "def compute():\n    return 7\n",
            "tests/check_behaviour.py": _REAL,
        },
    )
    surface = resolve_test_surface(ws)
    assert surface.resolved, "the repo told us its naming; that must be recorded as resolved"
    assert surface.naming.source == "pyproject.toml"
    assert "tests/check_behaviour.py" in surface.collected

    baseline = integrity_baseline(ws)
    assert "tests/check_behaviour.py" in baseline, "the real test was never baselined"
    (tmp_path / "tests" / "check_behaviour.py").write_text(_NEUTERED, encoding="utf-8")
    assert tampered_integrity(ws, baseline) == ["tests/check_behaviour.py"]


def test_a_repo_that_renames_tests_does_not_protect_the_DEFAULT_names(tmp_path: Path) -> None:
    """The contrast that stops "fix" = "match both conventions".

    Under `python_files = ["check_*.py"]` a file called `test_legacy.py` is NOT collected by
    pytest, so it is not an oracle and must not be baselined — every extra baselined path is a
    tamper park waiting for someone to regenerate it.
    """
    ws = _repo(
        tmp_path,
        {
            "pytest.ini": "[pytest]\npython_files = check_*.py\n",
            "tests/check_real.py": _REAL,
            "tests/test_legacy.py": "def test_legacy():\n    assert True\n",
        },
    )
    collected = resolve_test_surface(ws).collected
    assert "tests/check_real.py" in collected
    assert "tests/test_legacy.py" not in collected, "pytest does not collect it; we must not pin it"


def test_testpaths_does_NOT_narrow_the_protected_set(tmp_path: Path) -> None:
    """`testpaths` is parsed and recorded, but never narrows protection. Deliberately.

    It was applied at first, by literal prefix match, and every disagreement with pytest failed the
    same way — protect NOTHING. `.`, `./tests`, `tests/*` and absolute entries all matched nothing
    while pytest collected the tests normally, and on THIS repo (`testpaths = ["packages","apps"]`)
    it silently dropped two real test files out of the protected set.

    The deeper reason it should never have been applied: `testpaths` only decides where pytest looks
    WHEN GIVEN NO ARGUMENTS, and ADR-0054 forbids synthesising pytest path arguments at all — so it
    never shapes a command we issue. Modelling it bought nothing and cost protection. A test outside
    `testpaths` is still a test someone can run explicitly; protecting it costs an honest park.
    """
    ws = _repo(
        tmp_path,
        {
            "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["suite"]\n',
            "suite/test_real.py": _REAL,
            "elsewhere/test_also_real.py": "def test_b():\n    assert True\n",
        },
    )
    collected = resolve_test_surface(ws).collected
    assert "suite/test_real.py" in collected
    assert "elsewhere/test_also_real.py" in collected, (
        "a test outside testpaths lost protection — the direction that costs a silent hole"
    )


def test_an_UNMODELLABLE_config_protects_MORE_not_less(tmp_path: Path) -> None:
    """The failure direction, pinned. Four probes disagreed with pytest and all failed the same way.

    A pattern containing a separator (`python_files = tests/*.py`) matched nothing under basename
    fnmatch, so the repo was wholly unprotected while pytest collected its tests. pytest matches the
    WHOLE path when the pattern has a separator.
    """
    ws = _repo(
        tmp_path,
        {"pytest.ini": "[pytest]\npython_files = tests/*.py\n", "tests/acceptance.py": _REAL},
    )
    assert "tests/acceptance.py" in resolve_test_surface(ws).collected


def test_a_pytest_ini_WITH_NO_SECTION_still_wins(tmp_path: Path) -> None:
    """pytest: "pytest.ini files are always the source of configuration, even if empty".

    Falling through to `pyproject.toml` let a producer void a repo's `ini_options` with a one-line
    comment file — the suite shrank, and `integrity_paths` went on claiming to guard the test.
    """
    naming = resolve_naming(
        lambda n: {
            "pytest.ini": "# nothing\n",
            "pyproject.toml": '[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n',
        }.get(n, "")
    )
    assert naming.source == "pytest.ini" and naming.python_files == DEFAULT_PYTHON_FILES


def test_the_HIDDEN_pytest_ini_is_read_and_is_collection_control(tmp_path: Path) -> None:
    """pytest's `locate_config` reads `.pytest.ini`; it was in neither config table.

    So a repo shipping one was unprotected, AND a producer could create one mid-run to shrink the
    suite without tripping the new-collection-control guard.
    """
    assert is_collection_control(".pytest.ini")
    naming = resolve_naming(
        lambda n: "[pytest]\npython_files = check_*.py\n" if n == ".pytest.ini" else ""
    )
    assert naming.source == ".pytest.ini" and naming.python_files == ("check_*.py",)


def test_an_ini_value_containing_a_PERCENT_does_not_crash() -> None:
    """A regression I shipped: `configparser` interpolates on ITEM ACCESS, not on parse.

    `log_cli_format = %(asctime)s ...` is straight out of pytest's documentation, and it raised past
    the guard, out of `resolve_test_surface`, and killed `plan_node` on a repo pytest itself runs
    fine. `interpolation=None` is what pytest's own `iniconfig` uses.
    """
    naming = resolve_naming(
        lambda n: (
            "[pytest]\nlog_cli_format = %(asctime)s %(levelname)s\n" if n == "pytest.ini" else ""
        )
    )
    assert naming.resolved is True and naming.python_files == DEFAULT_PYTHON_FILES


def test_a_ZERO_BYTE_pytest_ini_is_still_authoritative(tmp_path: Path) -> None:
    """EXISTENCE, not content — and my first fix for this checked content.

    pytest: "pytest.ini files are always the source of configuration, even if empty", and it prints
    `WARNING: ignoring pytest config in pyproject.toml`. Testing the truthiness of the file's TEXT
    cannot tell an empty file from an absent one, so one `touch pytest.ini` handed authority to a
    config pytest does not read, and the protected set came from rules that were not in force.

    Verified against real pytest on this fixture: it collects `tests/test_a.py` and NOT
    `tests/check_c.py`, which is what the defaults say and what pyproject would have overridden.
    """
    ws = _repo(
        tmp_path,
        {
            "pytest.ini": "",  # zero bytes, and decisive
            "pyproject.toml": '[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n',
            "tests/test_a.py": _REAL,
            "tests/check_c.py": "def test_c():\n    assert True\n",
        },
    )
    surface = resolve_test_surface(ws)
    assert surface.naming.source == "pytest.ini", "an empty pytest.ini must still win"
    assert surface.collected == {"tests/test_a.py"}


def test_a_pytest_ini_with_only_an_UNRELATED_section_still_wins(tmp_path: Path) -> None:
    """Non-empty, but no `[pytest]` section — pytest still treats it as THE configfile."""
    naming = resolve_naming(
        lambda n: {
            "pytest.ini": "[flake8]\nmax-line-length = 100\n",
            "pyproject.toml": '[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n',
        }.get(n, ""),
        lambda n: n in ("pytest.ini", "pyproject.toml"),
    )
    assert naming.source == "pytest.ini" and naming.python_files == DEFAULT_PYTHON_FILES


def test_the_baseline_filters_use_the_DERIVED_rule_not_default_naming(tmp_path: Path) -> None:
    """Four sites filtered a config-aware baseline with pytest's DEFAULT names.

    Each would have emptied on exactly the repos the config-awareness exists for — re-introducing
    the blindness one line after the baseline fixed it. Two were fixed when the baseline moved; a
    red team found the other two, including the one backing the weakening measure behind the
    Proctor/operator tamper excuse, which went blind in the PERMISSIVE direction.

    The rule: the baseline is collected-plus-controls, and controls are config-independent, so
    `baseline - is_collection_control` recovers the tests without needing a workspace.
    """
    baseline = {"tests/check_acceptance.py": "h", "conftest.py": "h", "pyproject.toml": "h"}
    recovered = {p for p in baseline if not is_collection_control(p)}
    assert recovered == {"tests/check_acceptance.py"}, (
        "the derived rule must recover a non-default-named test that is_test_file would drop"
    )
    assert not is_test_file("tests/check_acceptance.py"), "premise: default naming misses it"


def test_a_GREENFIELD_repo_does_not_warn_about_nothing(tmp_path: Path) -> None:
    """FOUND BY LIVE-VALIDATING THE DEPLOY, not by a test or a red team.

    The first cut surfaced "the surface was inferred" whenever a repo shipped no pytest config —
    which is every greenfield target, i.e. 100% of runs on the live instance. The live project is a
    README and nothing else, so every single run would have carried a line saying tests "are NOT
    protected", about a repo with no tests, whose tests the engine then writes itself as
    `test_*.py` and duly protects.

    A warning that always fires is one nobody reads. This is the other half of the standard
    (ISA-18.2) this arc already cited for the opposite failure — an operator who cannot see a
    suppressed alarm and an operator drowned in a constant one are equally blind. Deny-by-default
    governs whether the CONTROL fails closed, not how loud the prose is.
    """
    ws = _repo(tmp_path, {"README.md": "greenfield\n"})
    surface = resolve_test_surface(ws)
    assert surface.resolved is False, "premise: nothing told us the naming"
    assert surface.worth_telling_the_operator is False, (
        "a repo with nothing test-shaped has nothing unguarded to warn about"
    )


def test_default_named_tests_without_a_config_do_not_warn(tmp_path: Path) -> None:
    """The assumption is right here, so saying it costs attention and buys nothing."""
    ws = _repo(tmp_path, {"tests/test_real.py": _REAL})
    surface = resolve_test_surface(ws)
    assert "tests/test_real.py" in surface.collected
    assert surface.worth_telling_the_operator is False


def test_a_repo_whose_tests_the_assumption_MISSES_does_warn(tmp_path: Path) -> None:
    """And the case that matters still speaks — naming the file, not just the fact.

    No pytest config, but tests named `check_*.py`: the assumed default naming does not cover them,
    so they are genuinely unprotected and the operator must be told which ones.
    """
    ws = _repo(tmp_path, {"tests/check_behaviour.py": _REAL})
    surface = resolve_test_surface(ws)
    assert surface.collected == frozenset(), "premise: the assumption collects nothing here"
    assert surface.worth_telling_the_operator is True
    assert surface.unprotected_candidates == frozenset({"tests/check_behaviour.py"})


# --- the pair that proves the partition -----------------------------------------------------


def test_the_partition_is_NECESSARY_not_stylistic(tmp_path: Path) -> None:
    """ONE fixture, TWO consumers, OPPOSITE requirements. No single set satisfies both.

    * `disposition.close_oracle_gap` diffs the PROTECTION set to see what the tester authored, and
      needs `tests/check.py` — a non-`test_`-named helper — IN, or the SHIP arm dies with
      "the tester authored no new test file" (pinned by test_disposition.py).
    * That same authored list becomes a pytest ARGV. A `tests/fixtures/golden.json` in it makes
      pytest exit 4 (usage error, nothing collected), and non-zero was read as "the mutation was
      caught" — a rubber-stamp suite promoted to a vouch.

    So protection must be WIDE and collection must be EXACT, over the same directory. Anyone
    tempted to collapse these again should read this test first.
    """
    ws = _repo(
        tmp_path,
        {
            "src/app.py": "def compute():\n    return 7\n",
            "tests/test_real.py": _REAL,
            "tests/check.py": "def helper():\n    return 1\n",
            "tests/fixtures/golden.json": '{"rows": []}\n',
        },
    )
    protection = protected_test_paths(ws)
    collection = resolve_test_surface(ws).collected

    # WIDE: everything under a tests dir, whatever it is called.
    for rel in ("tests/test_real.py", "tests/check.py", "tests/fixtures/golden.json"):
        assert rel in protection, f"{rel} must be refused to a producer"

    # EXACT: only what pytest actually collects — a .json here is the exit-4 vouch bug.
    assert collection == {"tests/test_real.py"}, (
        "the collected set must contain neither the helper nor the fixture — both make pytest "
        "refuse to start when passed as arguments"
    )

    # And the fixture must NOT be baselined: the tamper verdict is TERMINAL, so a run that
    # regenerates a golden file would be unshippable.
    assert "tests/fixtures/golden.json" not in integrity_paths(ws)


def test_regenerating_a_FIXTURE_does_not_park_the_run(tmp_path: Path) -> None:
    """The failure direction that makes a naive collapse-to-wide unshippable."""
    ws = _repo(
        tmp_path, {"tests/test_real.py": _REAL, "tests/fixtures/golden.json": '{"rows": []}\n'}
    )
    baseline = integrity_baseline(ws)
    (tmp_path / "tests" / "fixtures" / "golden.json").write_text(
        '{"rows": [1]}\n', encoding="utf-8"
    )
    assert tampered_integrity(ws, baseline) == [], (
        "regenerating a fixture raised a TERMINAL tamper verdict"
    )


# --- the gap defect: a human's test must not be deletable ------------------------------------


def test_a_PRE_EXISTING_helper_is_never_supersedable(tmp_path: Path) -> None:
    """Supersession calls `target.unlink()`. It must never reach a file the human wrote.

    `authored_tests` rides the wide PROTECTION set; `_pre_existing_tests` reads the exact baseline.
    Anything in that gap — a pre-existing `tests/helpers.py` — is absent from the baseline, so the
    "only PROVEN-NEW tester files" subtraction left it looking engine-owned, and the docstring's
    promise ("proven NOT to have existed in the pristine clone") was false for exactly that class.
    """
    final = {
        "integrity_baseline": {"tests/test_real.py": "h"},
        "authored_tests": ["tests/helpers.py", "tests/test_new.py"],
        "test_output": "FAILED tests/helpers.py::test_x - AssertionError",
        "give_up_reason": "blocked",
    }
    assert "tests/helpers.py" not in trapping_engine_tests(final), (
        "a pre-existing helper was classified engine-owned and became deletable"
    )


# --- fallback is honest -----------------------------------------------------------------------


def test_an_unconfigured_repo_falls_back_AND_SAYS_SO(tmp_path: Path) -> None:
    """An unprotected repo must never look identical to a protected one.

    Contrast with `security_listing`, which RAISES: that guards a source where no empty value is
    safe. Here a defensible default exists, so the honest move is to use it and record that it was
    inferred rather than resolved.
    """
    ws = _repo(tmp_path, {"tests/test_real.py": _REAL})
    surface = resolve_test_surface(ws)
    assert surface.naming.python_files == DEFAULT_PYTHON_FILES
    assert surface.resolved is False, "an assumed answer must not be recorded as resolved"
    assert surface.naming.note, "the fallback must carry a reason a human can read"
    assert "tests/test_real.py" in surface.collected, "the default convention still protects"


def test_an_UNPARSEABLE_config_is_reported_not_swallowed() -> None:
    """A target repo is untrusted input: it may ship a pyproject that does not parse."""
    naming = resolve_naming(lambda n: "[[[[[not toml" if n == "pyproject.toml" else "")
    assert naming.resolved is False
    assert "did not parse" in naming.note


def test_a_section_that_sets_NOTHING_still_counts_as_resolved() -> None:
    """ "The repo has spoken and chose the defaults" differs from "we could not read the repo"."""
    naming = resolve_naming(lambda n: "[pytest]\naddopts = -q\n" if n == "pytest.ini" else "")
    assert naming.resolved is True
    assert naming.python_files == DEFAULT_PYTHON_FILES


def test_the_FIRST_config_wins_as_pytest_does_not_merge() -> None:
    """pytest takes the first file carrying a section, in a fixed order — it does not merge.

    Merging would protect paths the target's real config excludes, and every extra baselined path
    is a terminal tamper park waiting for a regeneration.
    """

    def _read(name: str) -> str:
        return {
            "pytest.ini": "[pytest]\npython_files = check_*.py\n",
            "pyproject.toml": '[tool.pytest.ini_options]\npython_files = ["spec_*.py"]\n',
        }.get(name, "")

    naming = resolve_naming(_read)
    assert naming.source == "pytest.ini"
    assert naming.python_files == ("check_*.py",)
