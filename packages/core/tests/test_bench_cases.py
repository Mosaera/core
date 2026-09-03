"""Offline soundness check for the benchmark cases' hidden graders.

For every case that ships a ``reference/`` solution + a ``grader/``, the grader — the
Implementation ground truth — must satisfy two invariants, or the case can't be
trusted:

- it **FAILS on the bare state** (the committed ``seed/``, or an empty tree for a
  greenfield case): the target behaviour is genuinely absent, so a do-nothing run
  cannot score 100; and
- it **PASSES once the reference solution is present**: the case is winnable — a
  correct change actually satisfies the grader.

Language-aware: the grader runs on the host with the deliverable's own toolchain —
pytest for Python, ``node grader/run.mjs`` for Node/TS — and a case self-skips when
that toolchain isn't installed (mirroring the Docker-gated tests). SQL graders need a
live Postgres, so they're validated by the Docker sandbox / live run, not here. No
model or Docker required for the Python/Node checks, so ``make test`` proves the
benchmark's ground truth is real wherever the toolchain exists.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mosaera_core.bench.cases import available_cases, load_case

_CASES_DIR = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"

# Kinds whose grader can run on the host with just an interpreter (no sandbox/DB), and
# the binary that must be present for it. SQL is absent on purpose — its grader needs a
# live Postgres, so it's validated in the Docker sandbox / live run, not host-side.
_HOST_GRADEABLE = {
    "python-cli": "python",
    "python": "python",
    "node-cli": "node",
    "node": "node",
}


def _gradable_cases() -> list[str]:
    """Cases that ship a reference solution + grader (seed optional). A reference proves
    the grader is winnable; the bare state (seed, or empty for greenfield) proves it is
    not trivially satisfied."""
    out = []
    for cid in available_cases():
        d = _CASES_DIR / cid
        if (d / "reference").is_dir() and (d / "grader").is_dir():
            out.append(cid)
    return out


def _overlay(src: Path, dst: Path) -> None:
    """Copy every file under ``src`` onto ``dst`` (the reference overlays the bare
    state to produce the solved tree)."""
    for p in src.rglob("*"):
        if p.is_file():
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def _grader_argv(kind: str) -> list[str]:
    if kind in ("node-cli", "node"):
        return ["node", "grader/run.mjs"]
    return [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "grader"]


def _run_grader(workdir: Path, kind: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(workdir)  # a Python package resolves from the workspace
    return subprocess.run(  # noqa: S603 — argv is a fixed per-kind literal, not user input
        _grader_argv(kind),
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=240,
        env=env,
    )


def _prepare(case_id: str, tmp_path: Path, *, solved: bool) -> tuple[Path, str]:
    """Materialise the bare (seed/empty) or solved (reference overlaid) tree + grader,
    skipping the case when its host toolchain isn't installed. Returns (workdir, kind)."""
    case = _CASES_DIR / case_id
    kind = load_case(case_id).kind
    binary = _HOST_GRADEABLE.get(kind)
    if binary is None:
        pytest.skip(f"{case_id}: kind {kind!r} is not host-gradeable (validated in the sandbox)")
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


_GRADABLE = _gradable_cases()


@pytest.mark.skipif(not _GRADABLE, reason="no cases ship a reference solution yet")
@pytest.mark.parametrize("case_id", _GRADABLE)
def test_grader_fails_on_bare_state(case_id: str, tmp_path: Path) -> None:
    work, kind = _prepare(case_id, tmp_path, solved=False)
    result = _run_grader(work, kind)
    assert result.returncode != 0, (
        f"{case_id}: grader PASSED on the bare state — a do-nothing run would score "
        f"Implementation=100. The grader must assert something the bare tree lacks.\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(not _GRADABLE, reason="no cases ship a reference solution yet")
@pytest.mark.parametrize("case_id", _GRADABLE)
def test_grader_passes_on_reference(case_id: str, tmp_path: Path) -> None:
    work, kind = _prepare(case_id, tmp_path, solved=True)
    result = _run_grader(work, kind)
    assert result.returncode == 0, (
        f"{case_id}: grader FAILED on the reference solution — the case is unwinnable "
        f"(a correct change cannot satisfy it).\n{result.stdout}\n{result.stderr}"
    )


# --- `#64` guided-posture corpus -------------------------------------------------------------


def test_the_guided_corpus_is_separate_from_mcb() -> None:
    """The standing baseline (91.7% clean-conclusion, false_ship 1.4%, n=72) is over the MCB set.
    `bench --all` enumerates `available_cases()`, so a GMB case visible there would enlarge the
    suite and silently move that denominator — making every historical figure non-comparable."""
    from mosaera_core.bench.cases import available_cases, available_guided_cases

    guided = available_guided_cases()
    assert guided == ["GMB-01", "GMB-02", "GMB-03"]
    assert not [c for c in available_cases() if c.startswith("GMB")]


def test_every_guided_case_ships_a_seeded_broken_oracle() -> None:
    """A guided case is only an instrument if the trap is actually in the repo the producer gets.

    The broken test must live under `seed/`, because that is what puts it in the run's
    `integrity_baseline` and therefore beyond the producer's reach — a defect the producer could
    simply repair would measure nothing.
    """
    from mosaera_core.bench.cases import available_guided_cases, load_guided_case

    for case_id in available_guided_cases():
        case = load_guided_case(case_id)
        assert case.has_seed, f"{case_id} must ship a seed repo"
        seeded_test = case.seed_dir / "tests" / "test_add.py"
        assert seeded_test.is_file(), f"{case_id} must seed a pre-existing test"
        assert "SEEDED DEFECT" in seeded_test.read_text(encoding="utf-8")
        assert (case.grader_dir / "test_acceptance.py").is_file()
        assert (case.seed_dir / "src" / "tracker" / "cli.py").is_file()
        assert case.brief.strip()


def test_the_guided_grader_checks_for_corruption_not_just_the_feature() -> None:
    """GMB-01's graded question is whether the product SURVIVED a wrong oracle.

    Verified by hand against a real install: on the clean seed the grader's date check passes and
    only the unbuilt feature fails; after applying the observed F43 corruption
    (`date.today()` -> `date(2023, 1, 1)`) the seeded suite turns fully GREEN while this check
    fails. That gap is the measurement.
    """
    from mosaera_core.bench.cases import load_guided_case

    grader = (load_guided_case("GMB-01").grader_dir / "test_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert "test_the_default_date_is_still_today" in grader
    assert "date.today()" in grader
