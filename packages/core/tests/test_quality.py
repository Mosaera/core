"""Per-run quality: changed-file extraction, scoping, and the 0..100 scoring.

The bench craftsmanship path is covered by test_bench_quality.py (which imports
the same engine via the re-export shim); here we cover the product additions —
diff-scoped analysis and quality_score.
"""

from __future__ import annotations

from pathlib import Path

from mosaera_core.quality import (
    QualityDimension,
    QualityReport,
    QualityScore,
    analyze,
    below_bar,
    changed_files,
    changed_python_files,
    function_stats,
    quality_findings,
    quality_score,
    regressed,
    run_quality,
    should_revise,
    worst_dimension,
)
from mosaera_core.tools.repo import Workspace


def _score(**dims: int | None) -> QualityScore:
    """A QualityScore from name=score kwargs; composite = mean of measurable dims."""
    ds = [QualityDimension(n, s, "") for n, s in dims.items()]
    measurable = [s for s in dims.values() if s is not None]
    comp = round(sum(measurable) / len(measurable)) if measurable else 0
    return QualityScore(composite=comp, dimensions=ds)


def _json(score: QualityScore) -> str:
    import json

    return json.dumps(score.to_dict())


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="t", branch="b")


def test_changed_python_files_filters_to_delivered_py() -> None:
    diff = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -0,0 +1 @@\n+x = 1\n"
        "+++ b/index.html\n"  # not python
        "+++ b/.venv/dep.py\n"  # dependency, excluded
        "+++ /dev/null\n"  # a deletion — no b/ path
    )
    assert changed_python_files(diff) == ["pkg/mod.py"]


def test_changed_files_captures_both_sides_including_deletions() -> None:
    # changed_files must see a DELETED module (old side only) so a delete-only change isn't
    # mistaken for "no source changed" downstream (oracle Finding-2).
    diff = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"  # modified
        "diff --git a/pkg/gone.py b/pkg/gone.py\n"
        "--- a/pkg/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-y = 1\n"  # DELETED (old side only)
        "diff --git a/README.md b/README.md\n"
        "--- /dev/null\n+++ b/README.md\n@@ -0,0 +1 @@\n+hi\n"  # added
    )
    assert changed_files(diff) == ["README.md", "pkg/gone.py", "pkg/mod.py"]


def test_function_stats_reports_body_statement_counts(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            "mod.py": (
                "def big():\n    a = 1\n    b = 2\n    c = 3\n"
                "    d = 4\n    e = 5\n    return a\n\n"
                "def small():\n    return 1\n"
            )
        },
    )
    joined = "\n".join(function_stats(ws, ["mod.py"]))
    assert "`big` = 6 body statements" in joined  # 6 >= min 5 → reported
    assert "small" not in joined  # 1 statement < min → not noteworthy


def test_function_stats_skips_non_python_and_unparseable(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"a.txt": "hello", "broken.py": "def (:\n"})
    assert function_stats(ws, ["a.txt", "missing.py", "broken.py"]) == []


def test_quality_score_bands_and_composite() -> None:
    report = QualityReport(
        style_violations=0,  # → 100
        type_errors=2,  # → 80
        complex_functions=1,  # → 80
        cleanliness_issues=[],  # 0 → 100
    )
    q = quality_score(report)
    scores = {d.name: d.score for d in q.dimensions}
    assert scores == {"Style": 100, "Types": 80, "Complexity": 80, "Cleanliness": 100}
    assert q.composite == 90  # mean(100, 80, 80, 100)


def test_quality_score_drops_na_dimensions_from_composite() -> None:
    report = QualityReport(
        style_violations=None,  # tool unavailable → N/A, excluded
        type_errors=0,  # → 100
        complex_functions=None,  # N/A, excluded
        cleanliness_issues=["scratch script: debug.py"],  # 1 → 75
    )
    q = quality_score(report)
    scores = {d.name: d.score for d in q.dimensions}
    assert scores["Style"] is None and scores["Complexity"] is None
    assert q.composite == 88  # mean(100, 75) over the two measurable dims only


def test_run_quality_none_without_python_change(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"index.html": "<h1>hi</h1>\n"})
    assert run_quality(ws, "+++ b/index.html\n") is None  # non-python
    assert run_quality(ws, "") is None  # empty diff
    # A python path in the diff that isn't on disk (e.g. a deletion) is not scored.
    assert run_quality(ws, "+++ b/gone.py\n") is None


def test_run_quality_scores_changed_python(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"pkg/mod.py": "x = 1\n"})
    q = run_quality(ws, "+++ b/pkg/mod.py\n")
    assert q is not None
    assert 0 <= q.composite <= 100
    assert {d.name for d in q.dimensions} == {"Style", "Types", "Complexity", "Cleanliness"}


def test_analyze_scopes_to_given_paths(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            "pkg/clean.py": "x = 1\n",
            "pkg/dirty.py": "import os\n",  # unused import → a ruff finding
        },
    )
    clean = analyze(ws, ["pkg/clean.py"])
    dirty = analyze(ws, ["pkg/dirty.py"])
    # When ruff is available, scoping to clean.py sees no finding while dirty.py does;
    # tolerate None so the offline suite (no ruff) still passes.
    if clean.style_violations is not None and dirty.style_violations is not None:
        assert clean.style_violations == 0
        assert dirty.style_violations >= 1


# --- Phase 2: gating-decision helpers -------------------------------------------------


def test_below_bar_composite_and_dimension_floors() -> None:
    at_bar = _score(Style=100, Types=100, Complexity=80, Cleanliness=100)  # composite 95
    assert not below_bar(at_bar, 80, 70)
    assert below_bar(at_bar, 96, 70)  # composite floor raised above 95
    # composite fine, but one dimension under the per-dimension floor
    dim_low = _score(Style=100, Types=100, Complexity=60, Cleanliness=100)  # composite 90
    assert below_bar(dim_low, 80, 70)


def test_worst_dimension_picks_lowest_measurable() -> None:
    s = _score(Style=100, Types=60, Complexity=80, Cleanliness=None)
    worst = worst_dimension(s)
    assert worst is not None and worst.name == "Types"
    # all measurable dims perfect → nothing to improve
    assert worst_dimension(_score(Style=100, Types=100)) is None


def test_regressed_reports_dropped_dimensions() -> None:
    prev = _score(Style=100, Types=100, Complexity=60)
    curr = _score(Style=80, Types=100, Complexity=80)  # Style dropped, Complexity rose
    assert regressed(prev, curr) == ["Style"]
    assert regressed(prev, prev) == []


def test_should_revise_gating() -> None:
    low = _json(_score(Style=100, Types=100, Complexity=60, Cleanliness=100))  # composite 90
    kw = dict(iteration=1, max_iter=3, revises=0, min_composite=80, dim_floor=70, max_revises=1)
    # Complexity 60 < dim_floor 70 → revise
    assert should_revise(low, "", **kw)  # type: ignore[arg-type]
    # at bar → no
    at = _json(_score(Style=100, Types=100, Complexity=80, Cleanliness=100))
    assert not should_revise(at, "", **kw)  # type: ignore[arg-type]
    # budget exhausted / cap reached → no
    assert not should_revise(low, "", **{**kw, "iteration": 3})  # type: ignore[arg-type]
    assert not should_revise(low, "", **{**kw, "revises": 1})  # type: ignore[arg-type]
    # non-python (no quality) → no
    assert not should_revise("", "", **kw)  # type: ignore[arg-type]


def test_should_revise_stops_on_no_improvement_or_regression() -> None:
    kw = dict(iteration=2, max_iter=5, revises=1, min_composite=80, dim_floor=70, max_revises=3)
    prev = _json(_score(Style=100, Types=100, Complexity=60, Cleanliness=100))  # composite 90
    # a revise that didn't improve composite → stop
    same = _json(_score(Style=100, Types=100, Complexity=60, Cleanliness=100))
    assert not should_revise(same, prev, **kw)  # type: ignore[arg-type]
    # a revise that raised the target but regressed another dimension → stop
    regress = _json(_score(Style=80, Types=100, Complexity=80, Cleanliness=100))
    assert not should_revise(regress, prev, **kw)  # type: ignore[arg-type]


def test_quality_findings_returns_actionable_messages(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"pkg/mod.py": "import os\n"})  # unused import
    found = quality_findings(ws, ["pkg/mod.py"])
    assert set(found) == {"Style", "Types", "Complexity", "Cleanliness"}
    # when ruff is available the unused import surfaces as a concrete Style message
    if found["Style"]:
        assert any("pkg/mod.py" in m for m in found["Style"])
