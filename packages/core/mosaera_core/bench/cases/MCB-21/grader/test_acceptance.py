"""Hidden acceptance suite for MCB-21 (the journal CLI tag/find feature).

This is the ground truth — NEVER shown to Mosaera, injected into the delivered
workspace only at grade time. It drives the delivered ``python -m journal`` CLI
as a black box (a fresh JSON file per test via ``JOURNAL_FILE``) and asserts each
acceptance criterion as one test, so the pass rate is the Implementation score.

It runs with the delivered workspace as the working directory, so ``python -m
journal`` resolves the delivered package from cwd. The assertions are format-loose
(they check that the right id/text appear on a line, not an exact layout) — the
contract fixes behaviour, not whitespace — but strict on the observable contract:
tagging, finding in id order, persistence, and clean non-zero exits.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run(*args: str, journal_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "journal", *args],
        capture_output=True,
        text=True,
        env={
            "JOURNAL_FILE": str(journal_file),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": "",
        },
        timeout=30,
    )


@pytest.fixture
def journal_file(tmp_path: Path) -> Path:
    return tmp_path / "journal.json"


def _add(text: str, journal_file: Path) -> str:
    added = run("add", text, journal_file=journal_file)
    assert added.returncode == 0, added.stderr
    return added.stdout.strip().split()[-1]  # the printed id


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


# --- existing behaviour must survive the change --------------------------------


def test_add_and_list_still_work(journal_file: Path) -> None:
    _add("buy milk", journal_file=journal_file)
    _add("walk dog", journal_file=journal_file)
    listed = run("list", journal_file=journal_file)
    assert listed.returncode == 0
    lines = _lines(listed.stdout)
    assert len(lines) == 2
    assert "buy milk" in lines[0] and "walk dog" in lines[1]  # id order


# --- the new tag / find behaviour ----------------------------------------------


def test_tag_then_find_returns_the_entry(journal_file: Path) -> None:
    tid = _add("read book", journal_file=journal_file)
    assert run("tag", tid, "hobby", journal_file=journal_file).returncode == 0
    found = run("find", "hobby", journal_file=journal_file)
    assert found.returncode == 0
    assert "read book" in found.stdout


def test_find_no_match_is_blank_and_exit_zero(journal_file: Path) -> None:
    _add("something", journal_file=journal_file)
    found = run("find", "nonesuch", journal_file=journal_file)
    assert found.returncode == 0
    assert found.stdout.strip() == ""


def test_tag_persists_across_processes(journal_file: Path) -> None:
    tid = _add("persist me", journal_file=journal_file)
    run("tag", tid, "keep", journal_file=journal_file)
    # A completely separate invocation must still find it.
    found = run("find", "keep", journal_file=journal_file)
    assert "persist me" in found.stdout


def test_find_returns_matches_in_id_order(journal_file: Path) -> None:
    a = _add("alpha", journal_file=journal_file)
    b = _add("beta", journal_file=journal_file)
    c = _add("gamma", journal_file=journal_file)
    for tid in (c, a, b):  # tag out of order
        run("tag", tid, "x", journal_file=journal_file)
    found = run("find", "x", journal_file=journal_file)
    lines = _lines(found.stdout)
    assert len(lines) == 3
    assert "alpha" in lines[0] and "beta" in lines[1] and "gamma" in lines[2]


def test_find_only_returns_tagged_entries(journal_file: Path) -> None:
    tagged = _add("tagged", journal_file=journal_file)
    _add("untagged", journal_file=journal_file)
    run("tag", tagged, "here", journal_file=journal_file)
    found = run("find", "here", journal_file=journal_file)
    assert "tagged" in found.stdout
    assert "untagged" not in found.stdout


# --- error handling: non-zero, no traceback ------------------------------------


def test_tag_missing_id_exits_nonzero_without_traceback(journal_file: Path) -> None:
    _add("only one", journal_file=journal_file)
    result = run("tag", "9999", "ghost", journal_file=journal_file)
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr


def test_unknown_command_exits_nonzero_without_traceback(journal_file: Path) -> None:
    result = run("frobnicate", journal_file=journal_file)
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr
