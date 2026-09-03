"""Hidden acceptance suite for MCB-04 (add `search` to the notes CLI).

Ground truth — never shown to the agent, injected at grade time. Drives the
delivered `python -m notes` as a black box with a fresh NOTES_FILE per test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run(*args: str, notes_file: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["NOTES_FILE"] = str(notes_file)
    return subprocess.run(
        [sys.executable, "-m", "notes", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    nf = tmp_path / "notes.json"
    run("add", "buy milk", notes_file=nf)
    run("add", "walk the dog", notes_file=nf)
    run("add", "call the milkman", notes_file=nf)
    return nf


def test_search_matches_substring(seeded: Path) -> None:
    result = run("search", "milk", notes_file=seeded)
    assert result.returncode == 0
    assert "buy milk" in result.stdout
    assert "call the milkman" in result.stdout
    assert "walk the dog" not in result.stdout


def test_search_is_case_insensitive(seeded: Path) -> None:
    result = run("search", "DOG", notes_file=seeded)
    assert result.returncode == 0
    assert "walk the dog" in result.stdout


def test_search_no_match_is_blank_exit_zero(seeded: Path) -> None:
    result = run("search", "zzz", notes_file=seeded)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_search_output_format_has_ids(seeded: Path) -> None:
    result = run("search", "milk", notes_file=seeded)
    # same "<id>: <text>" format as list, in id order
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines[0].startswith("1: buy milk")
    assert any(ln.startswith("3: call the milkman") for ln in lines)


def test_missing_term_exits_nonzero_without_traceback(seeded: Path) -> None:
    result = run("search", notes_file=seeded)
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr


def test_existing_add_and_list_still_work(tmp_path: Path) -> None:
    nf = tmp_path / "notes.json"
    assert run("add", "first", notes_file=nf).returncode == 0
    listed = run("list", notes_file=nf)
    assert "1: first" in listed.stdout
