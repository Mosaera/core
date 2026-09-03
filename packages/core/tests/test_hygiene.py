"""Unit tests for the deterministic hygiene gate (packages/core/mosaera_core/hygiene.py).

These exercise the REAL ruff/mypy in the dev venv (same as test_quality.py), so they
assert on genuine tool behaviour: auto-format + safe autofix, and residual detection of
type errors and F-class real-bug lint.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mosaera_core import hygiene as hygiene_mod
from mosaera_core._hosttools import ToolResult
from mosaera_core.hygiene import autofix, hygiene_findings, hygiene_targets
from mosaera_core.tools.repo import Workspace


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="t", branch="b")


def test_autofix_formats_unformatted_code(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"mod.py": "x=1\ny   =2\n"})
    changed = autofix(ws, ["mod.py"])
    assert changed is True
    # ruff format normalises the spacing.
    assert (tmp_path / "mod.py").read_text(encoding="utf-8") == "x = 1\ny = 2\n"


def test_autofix_strips_unused_import(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"mod.py": "import os\nx = 1\n"})
    changed = autofix(ws, ["mod.py"])
    assert changed is True
    assert "import os" not in (tmp_path / "mod.py").read_text(encoding="utf-8")  # F401 fixed


def test_autofix_noop_on_clean_code(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"mod.py": "x = 1\n"})
    assert autofix(ws, ["mod.py"]) is False  # nothing to change


def test_autofix_rewrites_single_to_double_quotes(tmp_path: Path) -> None:
    # ADR-0068: ruff format rewrites single→double quotes. This is exactly why `hygiene_node` MUST
    # EXCLUDE the engine's authored/protected tests — the scaffold emits `_CASES` in single quotes,
    # so reformatting a BASELINED test rewrites it → the tamper guard false-trips on the engine's
    # own file → a self-inflicted thrash on correct code (the dominant thrash cause).
    ws = _ws(tmp_path, {"tests/golden.py": "CASES = [('grade', 1), ('grade', 2)]\n"})
    assert autofix(ws, ["tests/golden.py"]) is True
    assert '("grade"' in (tmp_path / "tests" / "golden.py").read_text(encoding="utf-8")


def test_hygiene_findings_reports_type_error(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"mod.py": 'def f() -> int:\n    return "not an int"\n'})
    report = hygiene_findings(ws, ["mod.py"])
    assert any("error" in f.lower() for f in report.findings)  # mypy flags the bad return
    assert report.unavailable == []


def test_hygiene_findings_reports_undefined_name(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"mod.py": "y = undefined_name\n"})
    report = hygiene_findings(ws, ["mod.py"])
    assert any("F821" in f for f in report.findings)  # ruff F-class real-bug lint


def test_hygiene_findings_clean_code_is_empty(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"mod.py": "x: int = 1\n"})
    report = hygiene_findings(ws, ["mod.py"])
    # Genuinely clean: nothing found AND everything actually ran.
    assert report.findings == []
    assert report.unavailable == []


# --- Security: the repo under analysis is UNTRUSTED, and these tools run on the HOST ---


def test_hygiene_ignores_a_hostile_mypy_plugin_config(tmp_path: Path) -> None:
    """A cloned repo must not be able to execute code on the host via mypy config.

    mypy has no ``--isolated``: with no ``--config-file`` it reads ``mypy.ini`` from its
    cwd — the untrusted clone — and ``plugins =`` makes it IMPORT the named file. Without
    the pinned config this test's ``pwn.py`` runs inside the Mosaera process (which holds
    the GitLab PAT and provider keys), entirely outside the sandbox.
    """
    sentinel = tmp_path / "pwned.txt"
    ws = _ws(
        tmp_path,
        {
            "mypy.ini": "[mypy]\nplugins = ./pwn.py\n",
            "pwn.py": (
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            ),
            "mod.py": "x: int = 1\n",
        },
    )
    hygiene_findings(ws, ["mod.py"])
    assert not sentinel.exists(), "hostile mypy plugin executed on the host — RCE is open"


def test_hygiene_reports_f_lint_a_repo_config_tries_to_suppress(tmp_path: Path) -> None:
    """A repo must not be able to switch off the real-bug lint that gates its own delivery.

    Formatting honors the project's ruff config (style is theirs to choose); the FINDINGS
    calls run ``--isolated`` so a per-file-ignore can't hide an undefined name.
    """
    ws = _ws(
        tmp_path,
        {
            "pyproject.toml": ('[tool.ruff.lint.per-file-ignores]\n"mod.py" = ["F821"]\n'),
            "mod.py": "y = undefined_name\n",
        },
    )
    report = hygiene_findings(ws, ["mod.py"])
    assert any("F821" in f for f in report.findings), "repo config suppressed the F-class lint"


def test_hygiene_reports_tool_unavailable_instead_of_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool that cannot run must never read as 'the code is clean'."""
    ws = _ws(tmp_path, {"mod.py": "x: int = 1\n"})

    real = hygiene_mod.run_tool

    def fake(argv: list[str], cwd: Path) -> ToolResult:
        if "mypy" in argv:
            return ToolResult()  # unavailable: could not run at all
        return real(argv, cwd)

    monkeypatch.setattr(hygiene_mod, "run_tool", fake)
    report = hygiene_findings(ws, ["mod.py"])
    assert report.findings == []
    assert report.unavailable == ["mypy"]  # NOT silently clean


def test_hygiene_targets_filters_to_delivered_py(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"pkg/mod.py": "x = 1\n"})
    diff = "+++ b/pkg/mod.py\n+++ b/index.html\n+++ b/gone.py\n"
    # index.html is non-python; gone.py isn't on disk → only the real .py file remains.
    assert hygiene_targets(ws, diff) == ["pkg/mod.py"]
