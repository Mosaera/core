"""The integration gates must fail CLOSED (#58).

`sandbox-e2e` — the job whose whole purpose is running the Docker/Postgres-gated
tests — skipped ~105 of them and reported success for months. Skips are not
failures, so the pipeline was green by vacancy and a vacant run was
indistinguishable from a real one.

These tests pin the rule that replaced it, using a sub-pytest so the real gates
(which depend on this machine's daemon and database) can't influence the result:

  * default            → a missing precondition SKIPS, with the reason stated;
  * MOSAERA_INTEGRATION=required → a missing precondition is an ERROR.

The second is the load-bearing one: absence of evidence is not evidence, the same
rule ADR-0081 already applies to experiments.
"""

from __future__ import annotations

import pathlib

import pytest

pytest_plugins = ["pytester"]

_ROOT_CONFTEST = pathlib.Path(__file__).resolve().parents[3] / "conftest.py"

# A conftest that reuses the repo-root gate machinery but forces the probes to
# report "unavailable" — so the assertion is about the GATE, not about whether
# this machine happens to have Docker or Postgres running.
_CONFTEST = """
import importlib.util
import sys

# Load the REAL repo-root conftest by path (importing it by name would import this
# file, which is also called conftest.py). The gates under test are the shipped ones.
_spec = importlib.util.spec_from_file_location("mosaera_root_conftest", {root!r})
root = importlib.util.module_from_spec(_spec)
sys.modules["mosaera_root_conftest"] = root
_spec.loader.exec_module(root)

# Force both probes to report unavailable, so the assertion is about the GATE and
# not about whether this machine happens to run Docker or Postgres.
root._docker_unavailable = lambda image=None: "forced unavailable for the test"
root._db_unavailable = lambda: "forced unavailable for the test"

pytest_collection_modifyitems = root.pytest_collection_modifyitems
pytest_runtest_setup = root.pytest_runtest_setup
pytest_configure = root.pytest_configure
"""

_TEST = """
import pytest

@pytest.mark.requires_db
def test_needs_a_database():
    raise AssertionError("must never execute without its precondition")
"""


def _run(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, mode: str | None
) -> pytest.RunResult:
    pytester.makeconftest(_CONFTEST.format(root=str(_ROOT_CONFTEST)))
    pytester.makepyfile(_TEST)
    if mode is None:
        monkeypatch.delenv("MOSAERA_INTEGRATION", raising=False)
    else:
        monkeypatch.setenv("MOSAERA_INTEGRATION", mode)
    # A subprocess run: the sub-pytest re-imports the root conftest with the env
    # above, so the mode under test is the one that takes effect.
    return pytester.runpytest_subprocess("-q", "-rs")


def test_missing_precondition_skips_by_default(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run(pytester, monkeypatch, None)
    result.assert_outcomes(skipped=1)
    # The reason is stated — a skip whose cause is invisible is how #58 survived.
    result.stdout.fnmatch_lines(["*requires_db: forced unavailable for the test*"])


def test_missing_precondition_is_an_error_when_required(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _run(pytester, monkeypatch, "required")
    # An ERROR, not a skip, and therefore a red run.
    result.assert_outcomes(errors=1, skipped=0, passed=0)
    assert result.ret != 0, "a run that could not execute its gated tests must not exit 0"
    result.stdout.fnmatch_lines(["*requires_db is REQUIRED here but unavailable*"])


def test_the_required_mode_is_opt_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A developer laptop must stay unaffected — the strictness is CI's, not theirs."""
    result = _run(pytester, monkeypatch, "skip")
    result.assert_outcomes(skipped=1)
