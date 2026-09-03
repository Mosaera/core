"""Deterministic code-quality analysis (product capability).

Static analysis of delivered code — style (ruff), types (mypy), complexity, and
cleanliness — plus a 0..100 per-dimension score and composite. No LLM, no model
opinion, so the same code always yields the same result. Used by the per-run
quality ring (on the changed files) and the MCB benchmark's craftsmanship gates
(on the whole greenfield tree).

This runs host-side against a clone of an UNTRUSTED repo, so every tool call goes
through ``_hosttools``: mypy's config is pinned (repo config discovery honors
``plugins =``, which would execute repo code on the host) and ruff runs
``--isolated``. A tool that cannot run yields ``None`` (scored N/A) and is named in
``QualityReport.unavailable`` — a dimension we failed to measure is reported as
unmeasured, never as a good score.
"""

from __future__ import annotations

import ast
import contextlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mosaera_core._hosttools import isolated_mypy_args, mypy_argv, run_tool
from mosaera_core.tools.repo import Workspace

_EXCLUDE = (".venv", "_mcb_grader", ".git", "__pycache__", "node_modules", ".mosaera")
_SCRATCH = re.compile(r"^(debug|scratch|manual|tmp|temp|trace|final|simple)[_a-z0-9]*\.py$", re.I)
_TEST = re.compile(r"^(test_[^/]+|[^/]+_test)\.py$", re.I)
_MYPY_FOUND = re.compile(r"Found (\d+) error")
_CHANGED = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_CHANGED_OLD = re.compile(r"^--- a/(.+)$", re.MULTILINE)  # old-side paths (modified + DELETED)

# Scoring bands (fewer findings = better). Shared with bench/scorecard.py.
_LINT_BANDS = ((0, 100), (2, 80), (5, 60), (10, 40))
_CX_BANDS = ((0, 100), (1, 80), (2, 60), (4, 40))
_CLEAN_BANDS = ((0, 100), (1, 75), (2, 50), (3, 25))


def _band(count: int, pairs: tuple[tuple[int, int], ...], default: int) -> int:
    for edge, sc in pairs:
        if count <= edge:
            return sc
    return default


@dataclass(frozen=True)
class QualityReport:
    style_violations: int | None = None
    type_errors: int | None = None
    complex_functions: int | None = None
    cleanliness_issues: list[str] = field(default_factory=list)
    # Tools that produced no verdict at all. A None dimension above is "not measured";
    # this names WHY, so a missing toolchain can't quietly read as a good score.
    unavailable: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualityDimension:
    name: str
    score: int | None  # 0..100, or None when not measurable
    detail: str


@dataclass(frozen=True)
class QualityScore:
    composite: int  # 0..100 mean of the measurable dimensions
    dimensions: list[QualityDimension]
    # Tools that could not run. The composite is a mean over the MEASURABLE dimensions,
    # so a missing toolchain would otherwise inflate it (Cleanliness alone is always
    # measurable and usually 100). Carry the reason so the ring can say so out loud.
    unavailable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite": self.composite,
            "dimensions": [
                {"name": d.name, "score": d.score, "detail": d.detail} for d in self.dimensions
            ],
            "unavailable": list(self.unavailable),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityScore:
        dims = [
            QualityDimension(str(d["name"]), d.get("score"), str(d.get("detail", "")))
            for d in data.get("dimensions", [])
        ]
        return cls(
            composite=int(data.get("composite", 0)),
            dimensions=dims,
            unavailable=[str(t) for t in data.get("unavailable", [])],
        )


def analyze(workspace: Workspace, paths: list[str] | None = None) -> QualityReport:
    """Analyse ``paths`` (relative to the workspace) when given — the files a run
    changed — otherwise the whole tree (benchmark greenfield)."""
    root = workspace.root
    targets = list(paths) if paths else [str(root)]
    unavailable: list[str] = []
    style, style_ran = _ruff_count(root, targets, extra=[])
    complexity, cx_ran = _ruff_count(
        root, targets, extra=["--select", "C901", "--config", "lint.mccabe.max-complexity=10"]
    )
    types, mypy_ran = _mypy_count(root, targets)
    if not (style_ran and cx_ran):
        unavailable.append("ruff")
    if not mypy_ran:
        unavailable.append("mypy")
    return QualityReport(
        style_violations=style,
        complex_functions=complexity,
        type_errors=types,
        cleanliness_issues=cleanliness_issues(workspace, paths),
        unavailable=unavailable,
    )


def quality_score(report: QualityReport) -> QualityScore:
    """Per-dimension 0..100 + composite. A dimension whose tool could not run is
    N/A (None) and dropped from the composite — and the tool is named in
    ``unavailable`` so the composite is never mistaken for a complete measurement."""
    dims = [
        _dim("Style", report.style_violations, _LINT_BANDS, "finding"),
        _dim("Types", report.type_errors, _LINT_BANDS, "error"),
        _dim("Complexity", report.complex_functions, _CX_BANDS, "over-complex function"),
        QualityDimension(
            "Cleanliness",
            _band(len(report.cleanliness_issues), _CLEAN_BANDS, 0),
            f"{len(report.cleanliness_issues)} stray/misplaced file(s)",
        ),
    ]
    scored = [d.score for d in dims if d.score is not None]
    composite = round(sum(scored) / len(scored)) if scored else 0
    return QualityScore(composite=composite, dimensions=dims, unavailable=list(report.unavailable))


def run_quality(workspace: Workspace, diff: str) -> QualityScore | None:
    """The per-run quality of a change: score the CHANGED python files only (never
    the whole repo, so a run isn't judged on pre-existing debt). None when the
    change touches no python files."""
    files = [f for f in changed_python_files(diff) if (workspace.root / f).is_file()]
    if not files:
        return None
    score = quality_score(analyze(workspace, files))
    if score.unavailable:
        # Say it out loud: the ring is partial, and the composite is a mean over
        # whatever DID run — never let a missing toolchain pass for good code.
        print(
            f"  WARNING: code-quality tools unavailable ({', '.join(score.unavailable)}) — "
            f"those dimensions were NOT measured; composite {score.composite} covers the rest."
        )
    return score


# --- Phase 2: gating decision helpers (pure; consumed by the run graph) -----------


def below_bar(score: QualityScore, min_composite: int, dim_floor: int) -> bool:
    """Is the change below our quality bar — composite under ``min_composite`` OR any
    measurable dimension under ``dim_floor``."""
    if score.composite < min_composite:
        return True
    return any(d.score is not None and d.score < dim_floor for d in score.dimensions)


def worst_dimension(score: QualityScore) -> QualityDimension | None:
    """The weakest measurable dimension worth improving (lowest score below 100), or
    None when everything measurable is already perfect."""
    scored = [d for d in score.dimensions if d.score is not None and d.score < 100]
    if not scored:
        return None
    return min(scored, key=lambda d: d.score or 0)


def regressed(prev: QualityScore, curr: QualityScore) -> list[str]:
    """Dimensions whose score dropped from ``prev`` to ``curr`` — the no-regression
    signal that stops a whack-a-mole revise (fixing one dimension broke another)."""
    prev_by = {d.name: d.score for d in prev.dimensions if d.score is not None}
    dropped: list[str] = []
    for d in curr.dimensions:
        before = prev_by.get(d.name)
        if before is not None and d.score is not None and d.score < before:
            dropped.append(d.name)
    return dropped


def should_revise(
    quality_json: str,
    quality_prev_json: str,
    *,
    iteration: int,
    max_iter: int,
    revises: int,
    min_composite: int,
    dim_floor: int,
    max_revises: int,
) -> bool:
    """The pure decision behind the run graph's route_after_review: is another
    targeted quality revise warranted? False once at bar, out of budget, capped, or
    when the last revise regressed / didn't improve (the no-whack-a-mole guard)."""
    if not quality_json or iteration >= max_iter or revises >= max_revises:
        return False
    curr = QualityScore.from_dict(json.loads(quality_json))
    if not below_bar(curr, min_composite, dim_floor):
        return False
    if quality_prev_json:
        prev = QualityScore.from_dict(json.loads(quality_prev_json))
        if regressed(prev, curr) or curr.composite <= prev.composite:
            return False
    return worst_dimension(curr) is not None


def quality_findings(workspace: Workspace, paths: list[str] | None = None) -> dict[str, list[str]]:
    """Actionable messages per dimension (not just counts) so a revise instruction can
    name concrete fixes. Best-effort: a tool that can't run yields an empty list."""
    root = workspace.root
    targets = list(paths) if paths else [str(root)]
    return {
        "Style": _ruff_messages(root, targets, extra=[]),
        "Complexity": _ruff_messages(
            root, targets, extra=["--select", "C901", "--config", "lint.mccabe.max-complexity=10"]
        ),
        "Types": _mypy_messages(root, targets),
        "Cleanliness": cleanliness_issues(workspace, paths),
    }


def changed_python_files(diff: str) -> list[str]:
    return [
        m
        for m in _CHANGED.findall(diff)
        if m.endswith(".py") and not any(p in _EXCLUDE for p in Path(m).parts)
    ]


def changed_files(diff: str) -> list[str]:
    """Every changed path in ``diff`` on EITHER side (any extension), minus the vendored/cache dirs.
    The unfiltered companion to ``changed_python_files`` — used to reason about non-``.py`` changes
    (config/data) that a Python suite can't be shown to cover. Captures the old side (``--- a/``)
    too so a DELETED module is visible: a delete-only change would otherwise look like "no source
    changed" and be credited via the docs branch (adversarial Finding-2). Pure 100%-similarity
    renames (which emit neither side) remain invisible — the narrow F-C residual."""
    paths = set(_CHANGED.findall(diff)) | set(_CHANGED_OLD.findall(diff))
    return sorted(m for m in paths if not any(p in _EXCLUDE for p in Path(m).parts))


def function_stats(
    workspace: Workspace,
    paths: list[str] | None = None,
    *,
    min_statements: int = 5,
    limit: int = 20,
) -> list[str]:
    """Objective per-function body-statement counts for the changed python ``paths``.

    The raw structural facts a refactor/decomposition review CHECK can be verified
    AGAINST rather than eyeballed — e.g. "checkout.py: `checkout_total` = 9 body
    statements" lets a reviewer judge a "keep the orchestrator short" check on data,
    not vibes. Counts top-level statements in each function body (the same measure the
    benchmark's structural graders use). Reports only functions with at least
    ``min_statements`` statements (short functions aren't worth noting). Best-effort:
    files that don't parse are skipped.
    """
    root = workspace.root
    out: list[str] = []
    for rel in paths or []:
        if not rel.endswith(".py") or any(p in _EXCLUDE for p in Path(rel).parts):
            continue
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                count = len(node.body)
                if count >= min_statements:
                    out.append(f"{rel}: `{node.name}` = {count} body statements")
            if len(out) >= limit:
                break
    return out[:limit]


def cleanliness_issues(workspace: Workspace, paths: list[str] | None = None) -> list[str]:
    """Stray/misplaced files a senior would not ship — over ``paths`` when given
    (the change), otherwise the whole tree."""
    listing = paths if paths is not None else workspace.file_listing(limit=500)
    issues: list[str] = []
    for rel in listing:
        if any(part in _EXCLUDE for part in Path(rel).parts):
            continue
        name = rel.rsplit("/", 1)[-1]
        if _SCRATCH.match(name):
            issues.append(f"scratch script: {rel}")
        elif _TEST.match(name) and not rel.startswith("tests/"):
            issues.append(f"test file outside tests/: {rel}")
    return issues


def _dim(
    name: str, count: int | None, pairs: tuple[tuple[int, int], ...], unit: str
) -> QualityDimension:
    if count is None:
        return QualityDimension(name, None, "not measured — tool unavailable")
    plural = "" if count == 1 else "s"
    return QualityDimension(name, _band(count, pairs, 20), f"{count} {unit}{plural}")


def _ruff_count(root: Path, targets: list[str], *, extra: list[str]) -> tuple[int | None, bool]:
    """(count, ran). ``ran=False`` means we learned nothing — not that there is nothing."""
    cmd = [
        sys.executable, "-m", "ruff", "check", "--isolated",
        "--exclude", ",".join(_EXCLUDE), "--output-format", "json", *extra, *targets,
    ]  # fmt: skip
    res = run_tool(cmd, root)
    if res.unavailable:
        return None, False
    try:
        return len(json.loads(res.stdout or "[]")), True
    except (json.JSONDecodeError, ValueError):
        return None, False


def _mypy_count(root: Path, targets: list[str]) -> tuple[int | None, bool]:
    """(count, ran). Config is pinned — see ``_hosttools.isolated_mypy_args``."""
    with isolated_mypy_args() as cfg:
        res = run_tool(
            mypy_argv(
                ["--ignore-missing-imports", "--no-color-output",
                 "--exclude", r"(\.venv|_mcb_grader|__pycache__|node_modules)/"],
                targets,
                cfg,
            ),
            root,
        )  # fmt: skip
    if res.unavailable:
        return None, False
    if "no issues found" in res.stdout.lower() or res.returncode == 0:
        return 0, True
    m = _MYPY_FOUND.search(res.stdout)
    return (int(m.group(1)), True) if m else (None, False)


def _ruff_messages(
    root: Path, targets: list[str], *, extra: list[str], limit: int = 20
) -> list[str]:
    cmd = [
        sys.executable, "-m", "ruff", "check", "--isolated",
        "--exclude", ",".join(_EXCLUDE), "--output-format", "json", *extra, *targets,
    ]  # fmt: skip
    res = run_tool(cmd, root)
    if res.unavailable:
        return []
    try:
        items = json.loads(res.stdout or "[]")
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[str] = []
    for it in items[:limit]:
        loc = it.get("location") or {}
        path = it.get("filename", "")
        with contextlib.suppress(ValueError):
            # POSIX-normalise: repo-relative paths in findings must read the same on Windows
            # and Linux (str(WindowsPath) would emit backslashes and diverge from the coder's
            # forward-slash paths the message is meant to match).
            path = Path(path).relative_to(root).as_posix()
        code = it.get("code") or ""
        where = f"{path}:{loc.get('row', '?')}:{loc.get('column', '?')}"
        out.append(f"{where} {code} {it.get('message', '')}".strip())
    return out


def _mypy_messages(root: Path, targets: list[str], limit: int = 20) -> list[str]:
    with isolated_mypy_args() as cfg:
        res = run_tool(
            mypy_argv(
                ["--ignore-missing-imports", "--no-color-output", "--no-error-summary",
                 "--exclude", r"(\.venv|_mcb_grader|__pycache__|node_modules)/"],
                targets,
                cfg,
            ),
            root,
        )  # fmt: skip
    if res.unavailable:
        return []
    return [ln.strip() for ln in res.stdout.splitlines() if ": error:" in ln][:limit]
