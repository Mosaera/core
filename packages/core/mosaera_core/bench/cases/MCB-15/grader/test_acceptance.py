"""Hidden acceptance suite for MCB-15 (refactor parse_log_line).

Ground truth — never shown to the agent, injected at grade time. Two kinds of
check:

- **behavioural** — the refactor must not change any output; these pass on the
  original code too (a refactor preserves behaviour), and
- **structural** — ``parse_log_line`` must actually be decomposed into a short
  orchestrator that delegates to >= 3 module-level helpers. This FAILS on the
  original one-block function, so a run that changes nothing cannot pass.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import logparse
import pytest
from logparse import parse_log_line

# --- behavioural: outputs are unchanged by the refactor ---


def test_representative_line() -> None:
    assert parse_log_line("ERROR 2024-01-01T10:00:00 Disk full path=/var code=5") == {
        "level": "ERROR",
        "timestamp": "2024-01-01T10:00:00",
        "message": "Disk full",
        "fields": {"path": "/var", "code": "5"},
    }


def test_line_with_no_fields() -> None:
    assert parse_log_line("INFO 2024-02-02T00:00:00 service started cleanly") == {
        "level": "INFO",
        "timestamp": "2024-02-02T00:00:00",
        "message": "service started cleanly",
        "fields": {},
    }


def test_line_with_no_message_words() -> None:
    assert parse_log_line("WARN 2024-03-03T12:00:00 retry=3 host=db1") == {
        "level": "WARN",
        "timestamp": "2024-03-03T12:00:00",
        "message": "",
        "fields": {"retry": "3", "host": "db1"},
    }


def test_field_value_containing_equals() -> None:
    result = parse_log_line("DEBUG 2024-04-04T09:00:00 eq=a=b")
    assert result["fields"] == {"eq": "a=b"}
    assert result["message"] == ""


def test_message_and_fields_interleaved_preserves_word_order() -> None:
    # A field token in the middle must not reorder the surrounding message words.
    result = parse_log_line("ERROR 2024-05-05T08:00:00 could not path=/tmp open file")
    assert result["message"] == "could not open file"
    assert result["fields"] == {"path": "/tmp"}


# --- structural: the function was genuinely decomposed ---


def _parse_log_line_ast() -> ast.FunctionDef:
    src = textwrap.dedent(inspect.getsource(parse_log_line))
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_parse_log_line_is_a_short_orchestrator() -> None:
    fn = _parse_log_line_ast()
    assert len(fn.body) <= 7, (
        f"parse_log_line should be a short orchestrator, but its body has "
        f"{len(fn.body)} statements — extract the work into helpers"
    )


def test_parse_log_line_delegates_to_helpers() -> None:
    fn = _parse_log_line_ast()
    module_fns = {name for name, _ in inspect.getmembers(logparse, inspect.isfunction)}
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in module_fns
        and node.func.id != "parse_log_line"
    }
    assert len(called) >= 3, (
        f"parse_log_line should delegate to >= 3 module-level helpers; "
        f"found delegation to {sorted(called)}"
    )
