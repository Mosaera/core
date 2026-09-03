"""Driver failures, written for a person.

The string in `_REAL` is the one an operator actually saw: ten lines of SQLAlchemy and psycopg
internals, centred, with the sentence that mattered buried in the middle.
"""

from __future__ import annotations

import pytest
from mosaera_api.setup.explain import explain

_REAL = (
    "OperationalError: (psycopg.OperationalError) connection failed: connection to server at "
    '"127.0.0.1", port 5432 failed: FATAL:  database "mosaera_try" does not exist\n'
    "Multiple connection attempts failed. All failures were:\n"
    "- host: 'localhost', port: 5432, hostaddr: '::1': connection failed: connection to server at "
    '"::1", port 5432 failed: Connection refused\n'
    "\tIs the server running on that host and accepting TCP/IP connections?\n"
    "(Background on this error at: https://sqlalche.me/e/20/e3q8)"
)


def test_the_real_failure_becomes_one_sentence() -> None:
    out = explain(_REAL)
    assert out.summary == 'The database "mosaera_try" does not exist on that server.'
    assert "Create it" in out.action
    # The specific cause wins over the generic one: this text ALSO contains "Connection refused",
    # and reporting that would send the operator to start a server that is already running.
    assert "listening" not in out.summary


def test_the_raw_cause_is_kept_but_demoted() -> None:
    # Summarising a failure and hiding what happened is how a diagnosis becomes unfalsifiable.
    out = explain(_REAL)
    assert "psycopg" in out.detail
    assert "\n" not in out.detail  # one line, not a wall
    assert "sqlalche.me" not in out.detail  # the part that helps nobody


@pytest.mark.parametrize(
    ("raw", "expect"),
    [
        ('FATAL: password authentication failed for user "mosaera"', "rejected the password"),
        ('FATAL:  role "nobody" does not exist', 'user "nobody" does not exist'),
        ("connection refused", "Nothing is listening"),
        ("could not translate host name", "does not resolve"),
        ("permission denied while trying to connect to the Docker daemon socket", "may not talk"),
        ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", "not running"),
        ("docker: 'compose' is not a docker command", "no Compose v2 plugin"),
    ],
)
def test_each_cause_gets_its_own_sentence(raw: str, expect: str) -> None:
    assert expect in explain(raw).summary


def test_an_unknown_failure_keeps_its_first_line_only() -> None:
    # The rest is almost always the driver explaining itself to other drivers.
    out = explain("RuntimeError: the flux capacitor is misaligned\nand then some more\nand more")
    assert out.summary == "the flux capacitor is misaligned"
    assert "and then some more" in out.detail


def test_a_prefix_that_is_not_an_error_class_is_left_alone() -> None:
    # Only a `…Error:` wrapper is stripped. Removing any `Word:` prefix would eat real content —
    # "FATAL: …" and "postgres: …" both carry meaning.
    assert explain("Disk quota: exceeded on /var").summary == "Disk quota: exceeded on /var"


def test_it_never_returns_nothing() -> None:
    # An empty explanation is worse than a bad one: the screen would show a blank where the reason
    # should be.
    for raw in ("", "   ", "\n\n"):
        assert explain(raw).summary
