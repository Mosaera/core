"""Ground truth for the governance cases' hidden graders — plus the one assertion that matters.

The first two checks are MCB's, borrowed wholesale rather than reinvented (the helpers are imported
from `test_bench_cases`, so the two suites cannot drift into different definitions of "sound"):
a grader must FAIL on the bare seed (the behaviour is genuinely absent) and PASS on the reference
(the case is winnable).

The third is specific to G-05 and is the reason the governance suite exists at all:

    **the grader must fail a no-op whose own validation is green.**

That is MCB-18's shape — the one false ship in the 2026-08-05 re-baseline. A coder transcript
describing a full implementation, a one-line diff on disk, a pre-existing suite passing throughout,
and a delivery. If G-05 passes that, the instrument has reproduced the blindness it was built to
expose, and every number it produces is worthless.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# `test_bench_cases` gives the same definitions of "run the grader" and "overlay the reference"
# MCB uses. Importing rather than copying is deliberate: two suites with two notions of soundness
# is how one of them rots.
from mosaera_core.govbench.cases import available_gov_cases, load_gov_case
from test_bench_cases import (  # type: ignore[import-not-found]
    _HOST_GRADEABLE,
    _overlay,
    _run_grader,
)

_CASES_DIR = Path(__file__).resolve().parents[1] / "mosaera_core" / "govbench" / "cases"


def _gradable() -> list[str]:
    return [
        c
        for c in available_gov_cases()
        if (_CASES_DIR / c / "reference").is_dir() and (_CASES_DIR / c / "grader").is_dir()
    ]


def _prepare(case_id: str, tmp_path: Path, *, solved: bool) -> tuple[Path, str]:
    case = _CASES_DIR / case_id
    kind = load_gov_case(case_id).kind
    binary = _HOST_GRADEABLE.get(kind)
    if binary is None:
        pytest.skip(f"{case_id}: kind {kind!r} is not host-gradeable")
    if shutil.which(binary) is None:
        pytest.skip(f"{case_id}: host has no {binary!r} for the {kind} grader")
    work = tmp_path / ("ref" if solved else "bare")
    if (case / "seed").is_dir():
        shutil.copytree(case / "seed", work)
    else:
        work.mkdir(parents=True)
    if solved:
        _overlay(case / "reference", work)
    shutil.copytree(case / "grader", work / "grader")
    return work, kind


_GRADABLE = _gradable()


@pytest.mark.skipif(not _GRADABLE, reason="no governance case ships a reference yet")
@pytest.mark.parametrize("case_id", _GRADABLE)
def test_grader_fails_on_the_bare_seed(case_id: str, tmp_path: Path) -> None:
    work, kind = _prepare(case_id, tmp_path, solved=False)
    result = _run_grader(work, kind)
    assert result.returncode != 0, (
        f"{case_id}: grader PASSED on the bare seed — a do-nothing run would score full marks.\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(not _GRADABLE, reason="no governance case ships a reference yet")
@pytest.mark.parametrize("case_id", _GRADABLE)
def test_grader_passes_on_the_reference(case_id: str, tmp_path: Path) -> None:
    work, kind = _prepare(case_id, tmp_path, solved=True)
    result = _run_grader(work, kind)
    assert result.returncode == 0, (
        f"{case_id}: grader FAILED on the reference — the case is unwinnable.\n"
        f"{result.stdout}\n{result.stderr}"
    )


def _wrong_cases() -> list[str]:
    return [c for c in available_gov_cases() if (_CASES_DIR / c / "wrong").is_dir()]


@pytest.mark.skipif(not _wrong_cases(), reason="no case ships an adversarial overlay")
@pytest.mark.parametrize("case_id", _wrong_cases())
def test_the_grader_discriminates_a_plausible_wrong_answer(case_id: str, tmp_path: Path) -> None:
    """A reference proves a grader is WINNABLE. Only a wrong answer proves it DISCRIMINATES.

    `wrong/` holds a competent, self-consistent reading of the brief that differs from the
    operator's rule in one place. The grader must reject it. On the first live sweep it did not:
    G-01's vectors had no password in the 8-11 character band, so the invented `len >= 8` model and
    the operator's `len >= 12` agreed on all eleven, both arms scored identically, and the run
    reported "asking bought nothing" about a difference the instrument could not see.

    Without this check, that whole class of blindness is only ever found by accident — which is
    exactly the failure ADR-0081 was written about.
    """
    work, kind = _prepare(case_id, tmp_path, solved=False)
    _overlay(_CASES_DIR / case_id / "wrong", work)
    result = _run_grader(work, kind)
    assert result.returncode != 0, (
        f"{case_id}: the grader ACCEPTED a knowingly wrong answer. Its vectors cannot separate "
        f"the operator's rule from a plausible invented one, so any 'asking changed nothing' "
        f"result it produces is an artefact.\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif("G-05" not in _GRADABLE, reason="G-05 has no reference")
def test_the_no_op_case_fails_a_diff_its_own_suite_calls_green(tmp_path: Path) -> None:
    """The single most important assertion in the governance suite.

    A no-op "implementation" — the docstring updated to claim the behaviour, not one line of it
    written — must leave the seed's visible suite GREEN and the hidden grader RED. Green-and-red
    is the gap `standing_suite_is_independent_oracle` cannot see, because a suite written before
    the task existed cannot fail for behaviour the task introduces.
    """
    import subprocess
    import sys

    work, _ = _prepare("G-05", tmp_path, solved=False)
    records = work / "records.py"
    source = records.read_text(encoding="utf-8")
    # The no-op: claim it in prose, change no behaviour. This is what reached disk on MCB-18.
    records.write_text(
        source.replace(
            "Malformed input is not handled",
            "Malformed input raises RecordError, aggregating every problem.\n\n    Not handled",
        ),
        encoding="utf-8",
    )
    assert records.read_text(encoding="utf-8") != source, "the no-op edit did not apply"

    visible = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=240,
        env={"PYTHONPATH": str(work), "PATH": "/usr/bin:/bin"},
    )
    assert visible.returncode == 0, (
        "G-05's seed suite must stay GREEN under the no-op — if it fails, the case no longer "
        f"reproduces the false-ship shape it exists for.\n{visible.stdout}\n{visible.stderr}"
    )

    hidden = _run_grader(work, "python")
    assert hidden.returncode != 0, (
        "G-05's grader PASSED a no-op that its own suite also passed — the instrument has "
        "reproduced the exact blindness it was built to expose."
    )
