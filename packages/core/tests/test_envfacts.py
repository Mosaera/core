"""The environment is measured, not narrated (ADR-0110 slice 1).

Two live misdiagnoses motivate every assertion here. F87 concluded *"network issues installing
dependencies"* while validation ran the same suite to 79 passed (291,846 coder tokens). On
2026-08-23 the coder concluded *"likely due to Python caching or installation issues"* about an
`UnboundLocalError` in code it had just written, escalated twice, and never delivered.

Two pins below are load-bearing and are mutation-checked:

1. **the changed-file hash** — the fact that falsifies *"what I'm editing isn't what's executing"*;
2. **the editable path is quoted, never compared** — because `pip install -e .` runs inside the
   container and records `/work/...`. A comparison against the host workspace root would report a
   confident, false *"your install points elsewhere"*: a NEW invented cause, produced by the module
   built to end invented causes. That pin must fail if anyone later "improves" it into a check.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from mosaera_core.tools.repo._envfacts import environment_facts


class _FakeWorkspace:
    """The three things the fact block reads: a root, and a read-only diff."""

    def __init__(self, root: Path, diff: str = "") -> None:
        self.root = root
        self._diff = diff

    def diff_readonly(self) -> str:
        return self._diff


def _diff_for(*rels: str) -> str:
    return "\n".join(f"diff --git a/{r} b/{r}\n--- a/{r}\n+++ b/{r}" for r in rels)


def _ws(tmp_path: Path, *, diff: str = "") -> _FakeWorkspace:
    return _FakeWorkspace(tmp_path, diff)


# ------------------------------------------------------------------ the falsifier


def test_a_changed_file_reports_the_bytes_actually_on_disk(tmp_path: Path) -> None:
    """LOAD-BEARING. The producer believing its edit is not what runs can check this line against
    the edit it just made. If the hash is wrong or absent, the block cannot settle the question."""
    src = tmp_path / "pkg"
    src.mkdir()
    f = src / "cli.py"
    f.write_text("def main():\n    return 0\n")
    expected = hashlib.sha256(f.read_bytes()).hexdigest()[:12]

    out = environment_facts(_ws(tmp_path, diff=_diff_for("pkg/cli.py")))

    assert "pkg/cli.py" in out
    assert expected in out, "the recorded hash must be the hash of the bytes on disk"
    assert f"{f.stat().st_size}B" in out


def test_a_changed_file_that_vanished_says_so_rather_than_guessing(tmp_path: Path) -> None:
    out = environment_facts(_ws(tmp_path, diff=_diff_for("pkg/gone.py")))
    assert "not on disk" in out


# ------------------------------------------------ never claim a mismatch you cannot prove


def _editable(tmp_path: Path, records: str) -> None:
    sp = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    sp.mkdir(parents=True)
    (sp / "__editable__.demo-0.1.0.pth").write_text(records + "\n")


def test_the_editable_path_is_quoted_verbatim_and_never_called_a_mismatch(tmp_path: Path) -> None:
    """LOAD-BEARING. `pip install -e .` runs in the container, so the marker records a CONTAINER
    path. The block reports it and stops. Asserting disagreement with the host-side root would
    manufacture the very kind of false external cause this module exists to remove."""
    _editable(tmp_path, "/work/src")

    out = environment_facts(_ws(tmp_path))

    assert "/work/src" in out, "the recorded path must be shown verbatim"
    for verdict in ("mismatch", "does not match", "points elsewhere", "wrong", "unexpected"):
        assert verdict not in out.lower(), f"the block must not adjudicate the path ({verdict!r})"


def test_no_editable_marker_is_reported_as_absence_not_as_a_fault(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    assert "no editable install marker" in environment_facts(_ws(tmp_path))


def test_no_venv_at_all_is_stated_plainly(tmp_path: Path) -> None:
    """The case `_uninstalled_note` used to special-case, now answered by the general block —
    an import failure here is not evidence the producer's code is wrong."""
    out = environment_facts(_ws(tmp_path))
    assert "not installed into a project venv" in out
    assert "the install step has not run" in out


# ------------------------------------------------------------------ the caching story


def test_a_stale_pycache_entry_is_counted(tmp_path: Path) -> None:
    """ "Python caching" is a cause the producer has actually invented. Settle it either way."""
    pkg = tmp_path / "pkg"
    (pkg / "__pycache__").mkdir(parents=True)
    (pkg / "mod.py").write_text("x = 1\n")
    pyc = pkg / "__pycache__" / "mod.cpython-312.pyc"
    pyc.write_bytes(b"\x00")
    old = time.time() - 3600
    os.utime(pyc, (old, old))

    assert "OLDER than the source" in environment_facts(_ws(tmp_path))


def test_a_fresh_pycache_entry_is_not_reported_as_stale(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    (pkg / "__pycache__").mkdir(parents=True)
    (pkg / "mod.py").write_text("x = 1\n")
    pyc = pkg / "__pycache__" / "mod.cpython-312.pyc"
    pyc.write_bytes(b"\x00")
    old = time.time() - 3600
    os.utime(pkg / "mod.py", (old, old))

    out = environment_facts(_ws(tmp_path))
    assert "none older than its source" in out
    assert "OLDER" not in out


def test_no_pycache_is_stated_rather_than_omitted(tmp_path: Path) -> None:
    assert "no __pycache__" in environment_facts(_ws(tmp_path))


# ------------------------------------------------------------------ it can never break its caller


def test_a_broken_workspace_yields_an_empty_block_not_an_exception() -> None:
    """A block that explains a failure must never become one. Advisory, like `emit_activity`."""

    class _Exploding:
        @property
        def root(self) -> Any:
            raise RuntimeError("no workspace")

        def diff_readonly(self) -> str:
            raise RuntimeError("no git")

    assert environment_facts(_Exploding()) == ""


def test_a_diff_that_raises_still_yields_nothing_rather_than_half_a_block(tmp_path: Path) -> None:
    class _BadDiff(_FakeWorkspace):
        def diff_readonly(self) -> str:
            raise RuntimeError("git exploded")

    assert environment_facts(_BadDiff(tmp_path)) == ""


def test_the_block_names_itself_as_measured_so_it_is_not_read_as_advice(tmp_path: Path) -> None:
    out = environment_facts(_ws(tmp_path))
    assert "measured on disk, not inferred" in out


# ------------------------------------------------- the trigger: on failure, and only on failure


def _probe(tmp_path: Path, exit_code: int) -> str:
    """`sandbox_exec` over a canned sandbox result, exercising the real wiring."""
    from mosaera_core.sandbox import SandboxResult, SandboxWorker
    from mosaera_core.tools.repo._exec import build_sandbox_exec

    class _Fixed(SandboxWorker):
        def run(
            self,
            cmd: Any,
            cwd: Any = None,
            timeout: Any = None,
            image: Any = None,
            readonly_work: bool = False,
        ) -> SandboxResult:
            return SandboxResult(exit_code, "probe output", "", 0.1, False, True)

        def run_setup(
            self, cmd: Any, cwd: Any = None, timeout: Any = None, image: Any = None, env: Any = None
        ) -> SandboxResult:
            return self.run(cmd)

    from mosaera_core.progress import fingerprint

    tool = build_sandbox_exec(_ws(tmp_path), _Fixed(), fingerprint)
    return str(tool.invoke({"code": "print(1)"}))


def test_a_failing_probe_leads_with_the_facts(tmp_path: Path) -> None:
    out = _probe(tmp_path, exit_code=1)
    assert "measured on disk, not inferred" in out
    assert out.index("measured on disk") < out.index("probe output"), "facts must come FIRST"


def test_a_passing_probe_gets_no_block(tmp_path: Path) -> None:
    """Zero cost on the happy path — the trigger is the exit code, never a symptom."""
    out = _probe(tmp_path, exit_code=0)
    assert "measured on disk" not in out
    assert "probe output" in out


# ------------------------------------------------- the firing signal (the A/B's own instrument)


def test_the_block_announces_itself_so_a_run_can_be_audited(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The gap that voided the first live A/B: a tool's RETURN VALUE reaches no durable record, so
    "did the facts actually fire?" had no obtainable answer. Without this event the measurement
    ADR-0110 demands is inference, not observation."""
    seen: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "mosaera_core.tools.repo._envfacts.emit_activity",
        lambda kind, detail="", result="": seen.append((kind, detail, result)),
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")

    environment_facts(_ws(tmp_path, diff=_diff_for("pkg/a.py")))

    assert seen, "the block must record that it fired"
    kind, detail, result = seen[0]
    assert kind == "environment_facts"
    assert "1 changed file" in detail
    assert result == "tree consistent"


def test_the_signal_reports_stale_bytecode_so_the_caching_story_is_auditable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    seen: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "mosaera_core.tools.repo._envfacts.emit_activity",
        lambda kind, detail="", result="": seen.append((kind, detail, result)),
    )
    pkg = tmp_path / "pkg"
    (pkg / "__pycache__").mkdir(parents=True)
    (pkg / "mod.py").write_text("x = 1\n")
    pyc = pkg / "__pycache__" / "mod.cpython-312.pyc"
    pyc.write_bytes(b"\x00")
    old = time.time() - 3600
    os.utime(pyc, (old, old))

    environment_facts(_ws(tmp_path))
    assert seen[0][2] == "stale bytecode"


def test_no_signal_when_the_block_could_not_be_built(monkeypatch: Any) -> None:
    """A failed gather must stay silent both ways — an event claiming a block the producer never
    saw would be a record of something that did not happen."""
    seen: list[Any] = []
    monkeypatch.setattr(
        "mosaera_core.tools.repo._envfacts.emit_activity",
        lambda *a, **k: seen.append(a),
    )

    class _Exploding:
        @property
        def root(self) -> Any:
            raise RuntimeError("no workspace")

    assert environment_facts(_Exploding()) == ""
    assert seen == []


# --------------------------------- repeating unchanged facts is noise, not evidence


def test_unchanged_facts_are_not_repeated(tmp_path: Path) -> None:
    """Measured live 2026-08-24 (`20260824-015015-43a966`): a coder probing in circles failed 16
    times and received 16 near-identical blocks. The block exists to end confusion; sixteen copies
    of one paragraph plausibly add to it."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
    ws = _ws(tmp_path, diff=_diff_for("pkg/a.py"))
    seen: dict[str, str] = {}

    first = environment_facts(ws, seen)
    second = environment_facts(ws, seen)

    assert "measured on disk" in first
    assert second == "", "an unchanged block must not be shown twice"


def test_changed_facts_speak_again(tmp_path: Path) -> None:
    """The suppression is keyed on the FACTS, not on having spoken once — the moment the tree moves
    the producer must hear about it, or the silence becomes its own misinformation."""
    (tmp_path / "pkg").mkdir()
    f = tmp_path / "pkg" / "a.py"
    f.write_text("x = 1\n")
    ws = _ws(tmp_path, diff=_diff_for("pkg/a.py"))
    seen: dict[str, str] = {}

    environment_facts(ws, seen)
    f.write_text("x = 2  # the producer edited it\n")
    again = environment_facts(ws, seen)

    assert "measured on disk" in again, "a changed tree must re-announce itself"


def test_suppression_is_still_recorded_as_a_firing(tmp_path: Path, monkeypatch: Any) -> None:
    """ "fired but suppressed" and "never fired" are DIFFERENT facts, and the A/B has to tell them
    apart — otherwise de-duplication would look like the instrument going dark."""
    seen_events: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "mosaera_core.tools.repo._envfacts.emit_activity",
        lambda kind, detail="", result="": seen_events.append((kind, detail, result)),
    )
    ws = _ws(tmp_path)
    seen: dict[str, str] = {}

    environment_facts(ws, seen)
    environment_facts(ws, seen)

    assert len(seen_events) == 2, "both the shown and the suppressed block must be recorded"
    assert "unchanged, not repeated" in seen_events[1][2]
    assert "unchanged" not in seen_events[0][2]


def test_no_map_means_no_suppression(tmp_path: Path) -> None:
    """`seen=None` keeps the old behaviour, so a caller that has no per-run state cannot silently
    lose the block."""
    ws = _ws(tmp_path)
    assert "measured on disk" in environment_facts(ws)
    assert "measured on disk" in environment_facts(ws)


def test_each_toolset_dedupes_its_own_view(tmp_path: Path) -> None:
    """The coder and the Proctor get separate maps (`build_repo_tools` owns one per call), so the
    Proctor is never silenced by something the coder was already told."""
    ws = _ws(tmp_path)
    coder: dict[str, str] = {}
    proctor: dict[str, str] = {}

    environment_facts(ws, coder)
    assert "measured on disk" in environment_facts(ws, proctor)
