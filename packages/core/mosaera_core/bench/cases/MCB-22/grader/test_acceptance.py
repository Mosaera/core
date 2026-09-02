"""Hidden acceptance suite for MCB-22 (the calc variables feature).

Ground truth — NEVER shown to Mosaera, injected only at grade time. Drives the
delivered ``python -m calc "<program>"`` as a black box and asserts EXACT results
(a pure-logic interpreter needs no format looseness). It runs with the delivered
workspace as cwd, so ``python -m calc`` resolves the delivered package.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def run(program: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "calc", program],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": ""},
        timeout=30,
    )


def value(program: str) -> str:
    result = run(program)
    assert result.returncode == 0, f"{program!r} -> exit {result.returncode}: {result.stderr}"
    return result.stdout.strip()


# --- existing arithmetic must survive the change -------------------------------


def test_precedence_preserved() -> None:
    assert value("2 + 3 * 4") == "14"


def test_parentheses_preserved() -> None:
    assert value("(2 + 3) * 4") == "20"


# --- the new variable behaviour ------------------------------------------------


def test_assignment_then_reference() -> None:
    assert value("x = 5; x + 1") == "6"


def test_later_statement_sees_earlier_bindings() -> None:
    assert value("a = 2; b = a * 3; b") == "6"


def test_reassignment() -> None:
    assert value("x = 1; x = 9; x") == "9"


def test_last_statement_value_is_printed() -> None:
    assert value("x = 1; 2 + 2") == "4"


def test_variable_used_inside_arithmetic() -> None:
    assert value("w = 10; (w - 4) / 2") == "3"


# --- error handling: non-zero, no traceback ------------------------------------


def test_undefined_variable_errors_cleanly() -> None:
    result = run("y + 1")
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr


def test_syntax_error_is_clean() -> None:
    result = run("2 +")
    assert result.returncode != 0
    assert "Traceback (most recent call last)" not in result.stderr
