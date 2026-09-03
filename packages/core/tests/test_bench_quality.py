"""Craftsmanship analysis — cleanliness detection (pure) + an analyze() smoke that
runs the real ruff/mypy over a tiny fixture (host-side, no sandbox)."""

from __future__ import annotations

from pathlib import Path

from mosaera_core.bench.quality import QualityReport, analyze, cleanliness_issues
from mosaera_core.tools.repo import Workspace


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="t", branch="b")


def test_cleanliness_flags_scratch_and_misplaced_tests(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            "todo/__init__.py": "x = 1\n",  # real package file — clean
            "tests/test_ok.py": "def test_x():\n    pass\n",  # correctly under tests/ — clean
            "debug_thing.py": "print(1)\n",  # scratch script — flagged
            "test_root.py": "def test_y():\n    pass\n",  # test outside tests/ — flagged
        },
    )
    joined = " ".join(cleanliness_issues(ws))
    assert "debug_thing.py" in joined and "test_root.py" in joined
    assert "tests/test_ok.py" not in joined and "todo/__init__.py" not in joined


def test_cleanliness_ignores_venv_and_grader(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            ".venv/lib/debug_lib.py": "print(1)\n",  # dependency — not the delivered code
            "_mcb_grader/test_acceptance.py": "def test_z(): pass\n",  # the injected grader
        },
    )
    assert cleanliness_issues(ws) == []


def test_analyze_runs_and_detects_lint_and_mess(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {
            "pkg/__init__.py": "import os\n",  # unused import → a ruff finding
            "debug_x.py": "print(1)\n",  # scratch → a cleanliness issue
        },
    )
    q = analyze(ws)
    assert isinstance(q, QualityReport)
    assert any("debug_x.py" in s for s in q.cleanliness_issues)
    # ruff, when available, flags the unused import; None if the tool couldn't run.
    assert q.style_violations is None or q.style_violations >= 1
    assert q.type_errors is None or isinstance(q.type_errors, int)
