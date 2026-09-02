"""Hidden acceptance suite for MCB-17 (harden the CSV table parser).

Ground truth — never shown to the agent, injected at grade time. Imports the
delivered module from the workspace cwd and asserts a ragged row becomes a clean
``TableError`` (naming the line) rather than silent data loss, and that the empty
and header-only edge cases are handled.
"""

from __future__ import annotations

import pytest
from csvtable import TableError, parse_table


def test_well_formed_table_parses() -> None:
    rows = parse_table("name,age\nalice,30\nbob,40")
    assert rows == [
        {"name": "alice", "age": "30"},
        {"name": "bob", "age": "40"},
    ]


def test_empty_input_returns_empty_list() -> None:
    assert parse_table("") == []


def test_blank_only_input_returns_empty_list() -> None:
    assert parse_table("\n   \n\n") == []


def test_header_only_returns_empty_list() -> None:
    assert parse_table("name,age\n") == []


def test_ragged_short_row_raises_tableerror() -> None:
    with pytest.raises(TableError):
        parse_table("name,age\nalice")


def test_ragged_long_row_raises_tableerror() -> None:
    with pytest.raises(TableError):
        parse_table("name,age\nalice,30,extra")


def test_tableerror_message_names_the_line_number() -> None:
    # The offending row is the 3rd input line (header is line 1, a valid row
    # is line 2), so the message must mention line 3.
    with pytest.raises(TableError) as exc:
        parse_table("name,age\nalice,30\nbob")
    message = str(exc.value)
    assert message.strip() != ""
    assert "3" in message
