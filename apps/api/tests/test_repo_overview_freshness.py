"""The PM's view of the repository must not be a one-time snapshot (migration 0030).

`repo_overview` was written once, at intake, and never again — while the project clone advances
on every approved delivery. A project cloned when its repository was empty kept an empty view of
itself permanently. On the live LedgerCLI project that produced backlog items asking to create a
file that already existed and to delete imports that are actually used; the second cost a whole
run when the Proctor encoded the false premise as an acceptance test.

Every test here drives `refresh_repo_overview` against a REAL git clone rather than a stub, and
asserts on the rebuild *decision* (was `build_overview` called?) rather than only on the returned
text — a text-only assertion passes whether or not the cache did its job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from git import Repo
from mosaera_api import projects as projects_mod
from mosaera_api.projects import refresh_repo_overview
from mosaera_core.config import Settings
from mosaera_core.grounding_text import ground_project_files
from mosaera_core.tools.repo import clone_project


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    src = tmp_path / "source-repo"
    src.mkdir()
    repo = Repo.init(src, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (src / "README.md").write_text("# Demo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    return src


class _Mem:
    """The two columns 0030 added, and nothing else."""

    def __init__(self) -> None:
        self.overview = ""
        self.key = ""
        self.writes = 0

    def get_repo_overview(self, project_id: str) -> str:
        return self.overview

    def get_repo_overview_key(self, project_id: str) -> str:
        return self.key

    def set_repo_overview(self, project_id: str, overview: str, key: str) -> None:
        self.overview, self.key = overview, key
        self.writes += 1


def _settings(home: Path) -> Settings:
    """An explicit `home` under tmp_path. `Settings.home` is cwd-relative, so a test that let it
    default would operate on whatever `.mosaera` sits in the working directory — the rule the
    2026-08-10 evidence-store loss exists to enforce."""
    s = Settings.from_env()
    return type(s)(**{**s.__dict__, "home": home})


def _clone(source: Path, tmp_path: Path) -> tuple[Any, Settings, _Mem]:
    settings = _settings(tmp_path / "home")
    ws = clone_project(str(source), settings.projects_dir, "proj-x")
    return ws, settings, _Mem()


def test_a_cold_project_builds_and_keys_the_overview(source_repo: Path, tmp_path: Path) -> None:
    _ws, settings, mem = _clone(source_repo, tmp_path)
    overview, current = refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]

    assert current is True
    assert "README.md" in overview
    assert mem.key, "the overview was stored without the HEAD it was built from"
    assert mem.writes == 1


def test_an_unmoved_clone_is_not_rewalked(
    source_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The freshness check must be a HEAD compare, not a tree walk — it runs on the interactive
    chat path. Asserting the CALL COUNT, not the text: identical text proves nothing, since a
    rebuild returns the same string."""
    _ws, settings, mem = _clone(source_repo, tmp_path)
    refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]

    calls = {"n": 0}
    real = projects_mod.build_overview

    def _counted(ws: Any) -> str:
        calls["n"] += 1
        return real(ws)

    monkeypatch.setattr(projects_mod, "build_overview", _counted)
    overview, current = refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]

    assert calls["n"] == 0, "rebuilt the overview although the clone had not moved"
    assert current is True and "README.md" in overview
    assert mem.writes == 1


def test_a_delivery_moves_the_clone_and_the_overview_follows(
    source_repo: Path, tmp_path: Path
) -> None:
    """The case that broke live: the clone gains a file, and the PM must see it.

    A commit into the project clone is what `nodes_deliver` does on an approved delivery.
    """
    ws, settings, mem = _clone(source_repo, tmp_path)
    first, _ = refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]
    assert "storage.py" not in first
    key_before = mem.key

    (Path(ws.root) / "storage.py").write_text("x = 1\n", encoding="utf-8")
    ws.repo.index.add(["storage.py"])
    ws.repo.index.commit("mosaera: deliver")

    second, current = refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]

    assert current is True
    assert "storage.py" in second, "the PM would still be planning against the old tree"
    assert mem.key != key_before, "the key must move with the text, or staleness is undetectable"
    assert mem.writes == 2


def test_an_unreadable_clone_is_reported_as_possibly_stale(tmp_path: Path) -> None:
    """No clone on disk. The stored text is still returned — a stale listing beats none — but
    `is_current` is False so the renderer says so. A failed enrichment must never cost the
    operator their conversation, and must never be presented as a current fact."""
    mem = _Mem()
    mem.overview, mem.key = "## Files\nold.py", "deadbeef"

    settings = _settings(tmp_path / "no-such-home")
    overview, current = refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]

    assert current is False
    assert overview == "## Files\nold.py"
    assert mem.writes == 0, "wrote a key for a clone it never read"


def test_the_context_says_so_when_the_overview_could_not_be_refreshed() -> None:
    """Driven through the real section renderer, not by reading the constant."""
    from mosaera_api.pm_sections import _overview_caveat

    assert _overview_caveat(True) == ""
    stale = _overview_caveat(False)
    assert "POSSIBLY STALE" in stale
    assert "current state" in stale


def test_changing_the_listing_rules_invalidates_every_cached_overview(
    source_repo: Path, tmp_path: Path
) -> None:
    """Live regression, 2026-08-19. Excluding tool caches from the listing changed nothing on any
    live project: the key was the clone HEAD, no clone had moved, so every project kept serving
    text built under the old rules. A cache keyed on its inputs but not on its BUILDER is the
    original stale-overview defect one level up.

    Simulated the way it actually happens — the stored key was written by an older build of the
    code — because that is the only state a deploy can leave behind.
    """
    _ws, settings, mem = _clone(source_repo, tmp_path)
    refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]
    assert mem.writes == 1
    head_only = mem.key.split(":")[-1]
    assert mem.key != head_only, "the key carries no rules version"

    # A row written before the version existed: the bare sha, and stale text.
    mem.overview, mem.key = "## Files\n.ruff_cache/0.15.20/123", head_only

    overview, current = refresh_repo_overview(mem, settings, "proj-x")  # type: ignore[arg-type]

    assert current is True
    assert ".ruff_cache" not in overview, "served text built under the old listing rules"
    assert "README.md" in overview
    assert mem.writes == 2, "did not rebuild despite the rules having changed"


# --- code evidence for the bar-authoring stages (F60 / #70) --------------------------------------
# Same real-clone discipline: `_code_evidence` is driven against an actual clone, never a stub,
# because its whole job is reading one.


def test_ground_project_files_reads_a_file_the_text_names(
    source_repo: Path, tmp_path: Path
) -> None:
    (source_repo / "cli.py").write_text("def status():\n    return 'ok'\n", encoding="utf-8")
    repo = Repo(source_repo)
    repo.index.add(["cli.py"])
    repo.index.commit("add cli")
    _ws, settings, _mem = _clone(source_repo, tmp_path)

    block = ground_project_files(settings.projects_dir, "proj-x", "Fix the output of cli.py status")
    assert "| def status():" in block
    assert "|     return 'ok'" in block  # indentation preserved — de-indented code is not evidence


def test_ground_project_files_is_empty_when_no_file_is_named(
    source_repo: Path, tmp_path: Path
) -> None:
    _ws, settings, _mem = _clone(source_repo, tmp_path)
    assert ground_project_files(settings.projects_dir, "proj-x", "Make the reports nicer") == ""


def test_ground_project_files_returns_empty_rather_than_raising_without_a_clone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Curate also runs unattended from spec-lint and escalation; losing grounding must not lose
    the curation — but it MUST say so.

    Failing open SILENTLY made the control undetectable: a wrong `projects_dir` or a missing clone
    produced the same empty string as "the item named no file", so the whole change could be inert
    in production with every surface looking normal. Live validation hit exactly that ambiguity and
    could not resolve it from outside the instance.
    """
    settings = _settings(tmp_path / "home")
    assert ground_project_files(settings.projects_dir, "never-cloned", "edit cli.py") == ""
    assert "UNAVAILABLE" in capsys.readouterr().out


def test_ground_project_files_reports_how_much_it_grounded(
    source_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A success line too, so "grounded 0 chars" and "never ran" are distinguishable in a log."""
    (source_repo / "cli.py").write_text("def status():\n    return 'ok'\n", encoding="utf-8")
    repo = Repo(source_repo)
    repo.index.add(["cli.py"])
    repo.index.commit("add cli")
    _ws, settings, _mem = _clone(source_repo, tmp_path)

    ground_project_files(settings.projects_dir, "proj-x", "Fix cli.py status")
    grounded = capsys.readouterr().out
    ground_project_files(settings.projects_dir, "proj-x", "no filename here")
    silent = capsys.readouterr().out

    assert "code-evidence:" in grounded and "UNAVAILABLE" not in grounded
    assert "named no file" in silent


def test_ground_project_files_does_not_reset_or_checkout_the_clone(
    source_repo: Path, tmp_path: Path
) -> None:
    """A read path that reset would destroy a live run's uncommitted coder writes."""
    ws, settings, _mem = _clone(source_repo, tmp_path)
    (ws.root / "cli.py").write_text("def status():\n    return 'live edit'\n", encoding="utf-8")
    before = Repo(ws.root).active_branch.name

    ground_project_files(settings.projects_dir, "proj-x", "edit cli.py")

    assert (ws.root / "cli.py").read_text(
        encoding="utf-8"
    ) == "def status():\n    return 'live edit'\n"
    assert Repo(ws.root).active_branch.name == before
