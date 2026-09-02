"""Unit tests for the recon engine's tri-state honesty + per-dimension fingerprints.

The security tests live in test_recon_security.py. These cover the other half of the
issue's acceptance: a tool miss is UNAVAILABLE and never clean, and each dimension's
fingerprint covers only its own inputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mosaera_core._hosttools import ToolResult
from mosaera_core.recon import (
    DimensionResult,
    Observation,
    recon_ci,
    recon_cleanliness,
    recon_deps,
    recon_quality,
    recon_security,
    recon_structure,
)
from mosaera_core.recon import _tools as tools_mod
from mosaera_core.recon import ci as ci_mod


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _dead_tool(argv: list[str], cwd: Path) -> ToolResult:
    """A tool that produced no verdict at all (missing binary / crash / timeout)."""
    return ToolResult()


# --- The invariant: "did not check" is never "clean" (ADR-0047 §5) ---


def test_a_result_cannot_be_clean_while_a_tool_is_unavailable() -> None:
    with pytest.raises(ValueError, match="never 'clean'"):
        DimensionResult(dimension="quality", status="clean", fingerprint="f", unavailable=("mypy",))


def test_unavailable_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="needs a reason"):
        DimensionResult(dimension="quality", status="unavailable", fingerprint="f")


def test_clean_cannot_carry_observations() -> None:
    with pytest.raises(ValueError, match="cannot carry observations"):
        DimensionResult(
            dimension="quality",
            status="clean",
            fingerprint="f",
            observations=(Observation(text="x", provenance="p"),),
        )


def test_finding_needs_an_observation() -> None:
    with pytest.raises(ValueError, match="needs at least one observation"):
        DimensionResult(dimension="quality", status="finding", fingerprint="f")


def test_from_parts_prefers_unavailable_over_findings() -> None:
    """Deny-by-default: a partial read keeps what it learned but never reads as clean
    or as a complete finding set."""
    result = DimensionResult.from_parts(
        "cleanliness", "f", [Observation(text="a lint hit", provenance="tool:ruff")], ["mypy"]
    )
    assert result.status == "unavailable"
    assert result.unavailable == ("mypy",)
    assert len(result.observations) == 1


def test_quality_reports_unavailable_when_mypy_cannot_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _repo(tmp_path, {"mod.py": "x: int = 1\n"})
    monkeypatch.setattr(tools_mod, "run_tool", _dead_tool)
    result = recon_quality(root)
    assert result.status == "unavailable"
    assert result.unavailable == ("mypy",)


def test_cleanliness_reports_unavailable_when_ruff_cannot_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _repo(tmp_path, {"mod.py": "x = 1\n"})
    monkeypatch.setattr(tools_mod, "run_tool", _dead_tool)
    result = recon_cleanliness(root)
    assert result.status == "unavailable"
    assert set(result.unavailable) == {"ruff check", "ruff format"}


def test_cleanliness_is_unavailable_when_only_one_ruff_call_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Partial availability is still unavailable — never rounded down."""
    root = _repo(tmp_path, {"mod.py": "x = 1\n"})

    def half_dead(argv: list[str], cwd: Path) -> ToolResult:
        if "format" in argv:
            return ToolResult()
        return ToolResult(stdout="[]", returncode=0, unavailable=False)

    monkeypatch.setattr(tools_mod, "run_tool", half_dead)
    result = recon_cleanliness(root)
    assert result.status == "unavailable"
    assert result.unavailable == ("ruff format",)


def test_garbled_tool_output_is_unavailable_not_zero_findings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Corrupt output is not evidence of clean code."""
    root = _repo(tmp_path, {"mod.py": "x = 1\n"})
    monkeypatch.setattr(
        tools_mod,
        "run_tool",
        lambda argv, cwd: ToolResult(stdout="not json at all", returncode=0, unavailable=False),
    )
    findings, ran = tools_mod.ruff_findings(root, ["mod.py"])
    assert (findings, ran) == ([], False)


def test_security_is_unavailable_without_a_sandbox(tmp_path: Path) -> None:
    """No scanner ran, so we cannot say the repo is free of secrets."""
    root = _repo(tmp_path, {"mod.py": "x = 1\n"})
    result = recon_security(root, None)
    assert result.status == "unavailable"


def test_ci_is_unavailable_when_pyyaml_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A broken install must be honest, not silently CI-less."""
    root = _repo(tmp_path, {".gitlab-ci.yml": "stages: [test]\n"})
    monkeypatch.setattr(ci_mod, "yaml", None)
    result = recon_ci(root)
    assert result.status == "unavailable"
    assert "PyYAML" in result.unavailable[0]


def test_ci_refuses_a_yaml_bomb_instead_of_parsing_it(tmp_path: Path) -> None:
    """A billion-laughs config must be refused, not expanded on the host.

    The bomb is a few hundred bytes that expands to gigabytes, so a size cap cannot
    catch it — the anchor/alias count is the guard.
    """
    bomb = "a: &a [" + ",".join(["'x'"] * 10) + "]\n"
    bomb += "b: &b [" + ",".join(["*a"] * 300) + "]\n"
    root = _repo(tmp_path, {".gitlab-ci.yml": bomb})
    result = recon_ci(root)
    assert result.status == "unavailable"
    assert "YAML bomb" in result.unavailable[0]


def test_ci_reports_unavailable_for_unparseable_yaml(tmp_path: Path) -> None:
    root = _repo(tmp_path, {".gitlab-ci.yml": "stages: [test\n  broken: ][\n"})
    result = recon_ci(root)
    assert result.status == "unavailable"


def test_deps_does_not_crash_on_a_deeply_nested_manifest(tmp_path: Path) -> None:
    """Red-team #41: a ~6KB deeply-nested manifest (well under the read cap) blows the
    parser's recursion limit. RecursionError is not a ValueError, so before the fix it
    escaped `recon_deps` and crashed the whole dimension. It must be `unavailable`."""
    depth = 5000
    nested_json = _repo(tmp_path / "j", {"package.json": "[" * depth + "]" * depth})
    result = recon_deps(nested_json)
    assert result.status == "unavailable"
    assert any("unparseable" in u.lower() for u in result.unavailable)

    nested_toml = _repo(tmp_path / "t", {"pyproject.toml": "a = " + "[" * depth + "]" * depth})
    assert recon_deps(nested_toml).status == "unavailable"


def test_deps_distinguishes_no_manifest_from_an_unreadable_one(tmp_path: Path) -> None:
    """'This project declares nothing' is a FINDING; 'we could not read the manifest'
    is UNAVAILABLE. Collapsing them is the ADR-0033 false-green."""
    empty = recon_deps(_repo(tmp_path / "empty", {"mod.py": "x = 1\n"}))
    assert empty.status == "finding"
    assert "no dependency manifest" in empty.observations[0].text

    corrupt = recon_deps(_repo(tmp_path / "corrupt", {"pyproject.toml": "this ain't toml ["}))
    assert corrupt.status == "unavailable"
    assert "unparseable TOML" in corrupt.unavailable[0]


# --- Deterministic observations ---


def test_deps_counts_declared_dependencies_and_notes_a_missing_lockfile(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx", "rich"]\n'},
    )
    result = recon_deps(root)
    assert result.status == "finding"
    assert any("declares 2 Python dependencies" in o.text for o in result.observations)
    assert any("no lockfile" in o.text for o in result.observations)


def test_deps_notes_a_present_lockfile(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = []\n',
            "uv.lock": "version = 1\n",
        },
    )
    result = recon_deps(root)
    assert any("lockfile(s) present: uv.lock" in o.text for o in result.observations)


def test_ci_describes_gitlab_jobs(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {".gitlab-ci.yml": "stages:\n  - test\n  - build\nunit:\n  script: pytest\n"},
    )
    result = recon_ci(root)
    assert result.status == "finding"
    assert any("GitLab CI declaring 1 job(s)" in o.text for o in result.observations)
    assert any("stages: test, build" in o.text for o in result.observations)


def test_structure_reports_the_file_mix(tmp_path: Path) -> None:
    root = _repo(
        tmp_path, {"src/a.py": "x = 1\n", "src/b.py": "y = 2\n", "web/i.ts": "let z = 3\n"}
    )
    result = recon_structure(root)
    assert any("3 files" in o.text for o in result.observations)
    assert any("top-level directories: src, web" in o.text for o in result.observations)
    assert any(".py (2)" in o.text for o in result.observations)


def test_every_observation_carries_provenance(tmp_path: Path) -> None:
    """ADR-0047 §1: an observation you cannot attribute is one you cannot check."""
    root = _repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx"]\n',
            "README.md": "# A project\n",
            "src/a.py": "x = 1\n",
        },
    )
    for result in (recon_deps(root), recon_structure(root)):
        for observation in result.observations:
            assert observation.provenance, f"unattributed observation: {observation.text}"


# --- Advisory severity (triage hint; recon-assigned, never from repo content) ---


def test_severity_defaults_to_info_and_all_emitted_values_are_valid(tmp_path: Path) -> None:
    from mosaera_core.recon.types import SEVERITIES, Observation

    # Default keeps every existing call site neutral.
    assert Observation(text="x", provenance="tool:walk").severity == "info"
    # Every severity any dimension actually emits must be a known value (deny-by-default set).
    root = _repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx", "rich"]\n',
            "src/a.py": "x = 1\n",
            "web/i.ts": "let z = 3\n",
        },
    )
    for result in (recon_deps(root), recon_structure(root), recon_ci(root)):
        for o in result.observations:
            assert o.severity in SEVERITIES, o


def test_inventory_stays_info_but_a_missing_lockfile_is_low(tmp_path: Path) -> None:
    # deps: the counts/inventory are neutral; "no lockfile" is a mild (low) concern.
    root = _repo(
        tmp_path,
        {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx"]\n'},
    )
    obs = {o.text: o.severity for o in recon_deps(root).observations}
    assert obs["declares 1 Python dependencies"] == "info"
    assert next(s for t, s in obs.items() if "no lockfile" in t) == "low"


def test_no_manifest_is_medium(tmp_path: Path) -> None:
    result = recon_deps(_repo(tmp_path, {"mod.py": "x = 1\n"}))
    assert result.observations[0].severity == "medium"  # nothing declared — a real gap


def test_structure_inventory_is_all_info(tmp_path: Path) -> None:
    # The screenshot bug: pure inventory must NOT read as an elevated finding.
    result = recon_structure(_repo(tmp_path, {"src/a.py": "x = 1\n", "src/b.py": "y = 2\n"}))
    assert all(o.severity == "info" for o in result.observations)


def test_no_ci_config_is_low(tmp_path: Path) -> None:
    result = recon_ci(_repo(tmp_path, {"mod.py": "x = 1\n"}))
    assert result.observations[0].severity == "low"


# --- Per-dimension fingerprints (ADR-0047 §4) ---


def test_a_lockfile_edit_does_not_invalidate_the_ci_fingerprint(tmp_path: Path) -> None:
    """The whole economic argument for the map: per-dimension keys mean a dependency
    bump re-recons deps ONLY (ADR-0047 §4)."""
    root = _repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx"]\n',
            ".gitlab-ci.yml": "stages: [test]\n",
        },
    )
    deps_before = recon_deps(root).fingerprint
    ci_before = recon_ci(root).fingerprint

    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["httpx", "rich"]\n', encoding="utf-8"
    )

    assert recon_deps(root).fingerprint != deps_before, "deps fingerprint missed a manifest edit"
    assert recon_ci(root).fingerprint == ci_before, (
        "a manifest edit invalidated the CI dimension — per-dimension keying is broken"
    )


def test_the_security_fingerprint_covers_every_file_including_lockfiles(tmp_path: Path) -> None:
    """A deliberate divergence from ADR-0047 §4's illustrative example.

    §4 says "a lockfile edit must not invalidate the security scan". Taken literally
    that is unsafe: the scanners scan the whole tree, and a lockfile is a real place
    for a credential to live (a poetry.lock / .npmrc index URL carries a token). If
    security excluded lockfiles from its key, a secret committed to uv.lock would
    never re-trigger the scan and the map would keep reporting clean over a live
    credential. Over-invalidation costs a rescan; under-invalidation is a durable
    false-green over a leaked secret.
    """
    root = _repo(tmp_path, {"uv.lock": "version = 1\n", "mod.py": "x = 1\n"})
    before = recon_security(root, None).fingerprint
    (root / "uv.lock").write_text(
        'version = 1\nindex = "https://user:glpat-leaked@example.com/simple"\n', encoding="utf-8"
    )
    assert recon_security(root, None).fingerprint != before, (
        "a secret added to a lockfile did not re-key the security dimension"
    )


def test_tests_fingerprint_covers_coverage_config_not_just_python(tmp_path: Path) -> None:
    """Red-team #41: the coverage verdict is produced by RUNNING the suite, so a
    `.coveragerc`/`pytest.ini` edit changes the measured number while touching no `.py`.
    Fingerprinting only `*.py` served a stale coverage number as fresh (under-
    invalidation — the dangerous direction). The config must be in the key.
    """
    from mosaera_core.recon import recon_tests
    from mosaera_core.tools.repo import Workspace

    root = _repo(tmp_path, {"src.py": "x = 1\n", "test_src.py": "def test(): assert True\n"})
    ws = Workspace(root=root, run_id="t", branch="b")
    before = recon_tests(ws, None).fingerprint

    (root / ".coveragerc").write_text("[run]\nomit = src.py\n", encoding="utf-8")
    assert recon_tests(ws, None).fingerprint != before, (
        "a .coveragerc that changes what coverage measures did not move the tests fingerprint"
    )


def test_a_source_edit_does_not_invalidate_the_deps_fingerprint(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx"]\n',
            "mod.py": "x = 1\n",
        },
    )
    deps_before = recon_deps(root).fingerprint
    (root / "mod.py").write_text("x = 2\n", encoding="utf-8")
    assert recon_deps(root).fingerprint == deps_before


def test_fingerprints_are_content_based_not_mtime_based(tmp_path: Path) -> None:
    """The map is durable and cross-run. mtime does not survive a fresh clone, so a
    stat-based key (Workspace.tree_hash) would miss every cache on an unchanged repo.
    """
    first = _repo(tmp_path / "clone-a", {"pyproject.toml": '[project]\nname = "x"\n'})
    second = _repo(tmp_path / "clone-b", {"pyproject.toml": '[project]\nname = "x"\n'})
    import os
    import time

    # Give the second clone a distinctly later mtime, as a re-clone would.
    later = time.time() + 120
    os.utime(second / "pyproject.toml", (later, later))

    assert recon_deps(first).fingerprint == recon_deps(second).fingerprint


def test_an_unavailable_dimension_still_returns_a_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """So the caller can cache 'could not read at this input state' and retry only
    when the inputs actually change."""
    root = _repo(tmp_path, {"mod.py": "x = 1\n"})
    monkeypatch.setattr(tools_mod, "run_tool", _dead_tool)
    result = recon_quality(root)
    assert result.status == "unavailable"
    assert result.fingerprint and result.fingerprint != "0" * 64


def test_as_dict_round_trips_the_tri_state(tmp_path: Path) -> None:
    """The caller (#6a's store) persists this shape; recon itself never does."""
    result = DimensionResult.could_not_run("quality", "abc", ["mypy"])
    assert result.as_dict() == {
        "dimension": "quality",
        "status": "unavailable",
        "fingerprint": "abc",
        "observations": [],
        "unavailable": ["mypy"],
    }
