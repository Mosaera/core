"""Hidden acceptance suite for MCB-01 (the todo CLI).

This is the ground truth — it is NEVER shown to Mosaera and is injected into the
delivered workspace only at grade time. It drives the delivered `python -m todo`
CLI as a black box (a fresh JSON file per test via TODO_FILE) and asserts each
acceptance criterion as one test, so the pass rate is the Implementation score.

It runs with the delivered workspace as the working directory, so `python -m
todo` resolves the delivered package from cwd.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def run(*args: str, todo_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "todo", *args],
        capture_output=True,
        text=True,
        env={"TODO_FILE": str(todo_file), "PATH": _path(), "PYTHONPATH": ""},
        timeout=30,
    )


def _path() -> str:
    import os

    return os.environ.get("PATH", "")


@pytest.fixture
def todo_file(tmp_path: Path) -> Path:
    return tmp_path / "tasks.json"


def test_add_prints_id_and_list_shows_it(todo_file: Path) -> None:
    added = run("add", "buy milk", todo_file=todo_file)
    assert added.returncode == 0
    assert added.stdout.strip(), "add should print the new task id"
    listed = run("list", todo_file=todo_file)
    assert listed.returncode == 0
    assert "buy milk" in listed.stdout
    assert "[ ]" in listed.stdout  # a new task is not done


def test_list_empty_is_blank_and_exit_zero(todo_file: Path) -> None:
    listed = run("list", todo_file=todo_file)
    assert listed.returncode == 0
    assert listed.stdout.strip() == ""


def test_done_marks_the_task(todo_file: Path) -> None:
    tid = run("add", "walk dog", todo_file=todo_file).stdout.strip().split()[-1]
    assert run("done", tid, todo_file=todo_file).returncode == 0
    listed = run("list", todo_file=todo_file)
    assert "walk dog" in listed.stdout and "[x]" in listed.stdout


def test_delete_removes_the_task(todo_file: Path) -> None:
    tid = run("add", "temporary", todo_file=todo_file).stdout.strip().split()[-1]
    assert run("delete", tid, todo_file=todo_file).returncode == 0
    listed = run("list", todo_file=todo_file)
    assert "temporary" not in listed.stdout


def test_ids_are_stable_across_add_and_list(todo_file: Path) -> None:
    run("add", "first", todo_file=todo_file)
    second = run("add", "second", todo_file=todo_file).stdout.strip().split()[-1]
    run("done", second, todo_file=todo_file)
    listed = run("list", todo_file=todo_file)
    # Both tasks survive; the second is marked done, the first is not.
    lines = [ln for ln in listed.stdout.splitlines() if ln.strip()]
    assert any("first" in ln and "[ ]" in ln for ln in lines)
    assert any("second" in ln and "[x]" in ln for ln in lines)


def test_persistence_across_processes(todo_file: Path) -> None:
    run("add", "persist me", todo_file=todo_file)
    assert todo_file.exists(), "the todo file should be created on first write"
    # A completely separate process must see the stored task.
    listed = run("list", todo_file=todo_file)
    assert "persist me" in listed.stdout


def test_unknown_command_exits_nonzero_without_traceback(todo_file: Path) -> None:
    result = run("frobnicate", todo_file=todo_file)
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr


def test_operation_on_missing_id_exits_nonzero(todo_file: Path) -> None:
    result = run("done", "9999", todo_file=todo_file)
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr
