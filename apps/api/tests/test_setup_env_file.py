"""The `.env` rewriter — the piece that must never lose an operator's configuration.

Until the wizard, no Python wrote `.env` at all: `scripts/install.sh` copies `.env.example` once and
never touches it again. These tests hold the line that made that safe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mosaera_api.setup.env_file import read_env_file, write_env_file

# S104 (binding all interfaces) is about a SERVER choosing to listen everywhere. Here _PUBLIC is
# just the string this rewriter must round-trip, so the rule has nothing to say about it.
_PUBLIC = "0.0.0.0"  # noqa: S104


def test_a_commented_example_is_not_an_active_value(tmp_path: Path) -> None:
    # `.env.example` ships nearly every key commented out. Reading `#MOSAERA_API_PORT=8000` as a
    # live setting would make the wizard believe the operator had already chosen one.
    env = tmp_path / ".env"
    env.write_text("#MOSAERA_API_PORT=8000\nMOSAERA_API_HOST=127.0.0.1\n")
    assert read_env_file(env) == {"MOSAERA_API_HOST": "127.0.0.1"}


def test_export_prefixed_and_spaced_assignments_are_read(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("export MOSAERA_API_PORT=8000\n  MOSAERA_API_HOST = 0.0.0.0 \n")
    assert read_env_file(env) == {"MOSAERA_API_PORT": "8000", "MOSAERA_API_HOST": _PUBLIC}


def test_a_missing_file_reads_as_empty_rather_than_raising(tmp_path: Path) -> None:
    assert read_env_file(tmp_path / "nope") == {}


def test_an_existing_value_is_replaced_where_it_stands(tmp_path: Path) -> None:
    # In place, so the comment above a key still explains the line beneath it.
    env = tmp_path / ".env"
    env.write_text("# the port the API serves on\nMOSAERA_API_PORT=8000\n# trailing note\n")
    write_env_file(env, {"MOSAERA_API_PORT": "9000"})
    assert (
        env.read_text() == "# the port the API serves on\nMOSAERA_API_PORT=9000\n# trailing note\n"
    )


def test_comments_and_unrelated_keys_survive_untouched(tmp_path: Path) -> None:
    original = (
        "# --- Inference (Ollama) ---\n"
        "#MOSAERA_OLLAMA_BASE_URL=http://localhost:11434\n"
        "\n"
        "MOSAERA_DB_PORT=5432\n"
    )
    env = tmp_path / ".env"
    env.write_text(original)
    write_env_file(env, {"MOSAERA_API_TOKEN": "secret"})
    after = env.read_text()
    # Every original line is still there, in order.
    assert after.startswith(original.rstrip("\n"))
    assert "# --- Inference (Ollama) ---" in after
    assert "#MOSAERA_OLLAMA_BASE_URL=http://localhost:11434" in after
    assert "MOSAERA_DB_PORT=5432" in after
    assert "MOSAERA_API_TOKEN=secret" in after


def test_a_commented_example_is_left_commented_and_the_value_appended(tmp_path: Path) -> None:
    # Rewriting the commented example in place would destroy the documentation for the next person
    # who opens this file.
    env = tmp_path / ".env"
    env.write_text("# the bind address\n#MOSAERA_API_HOST=127.0.0.1\n")
    write_env_file(env, {"MOSAERA_API_HOST": _PUBLIC})
    after = env.read_text()
    assert "#MOSAERA_API_HOST=127.0.0.1" in after  # the example is intact
    assert "\nMOSAERA_API_HOST=0.0.0.0" in after  # and the real value is set


def test_writing_is_idempotent(tmp_path: Path) -> None:
    # The wizard is re-runnable, so writing the same answers twice must not accumulate blocks.
    env = tmp_path / ".env"
    env.write_text("MOSAERA_DB_PORT=5432\n")
    write_env_file(env, {"MOSAERA_API_HOST": _PUBLIC})
    once = env.read_text()
    write_env_file(env, {"MOSAERA_API_HOST": _PUBLIC})
    assert env.read_text() == once


def test_nothing_is_written_when_there_is_nothing_to_change(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MOSAERA_DB_PORT=5432\n")
    write_env_file(env, {})
    assert env.read_text() == "MOSAERA_DB_PORT=5432\n"


def test_the_file_is_owner_only_because_it_holds_a_token(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    write_env_file(env, {"MOSAERA_API_TOKEN": "secret"})
    assert env.stat().st_mode & 0o777 == 0o600


def test_it_survives_the_real_env_example(tmp_path: Path) -> None:
    """The actual 238-line file, not a fixture — this is what the wizard edits on a real install."""
    example = Path(__file__).resolve().parents[3] / ".env.example"
    if not example.exists():  # pragma: no cover - repo layout guard
        pytest.skip(".env.example not found from this checkout")
    env = tmp_path / ".env"
    env.write_text(example.read_text())
    before_lines = env.read_text().splitlines()

    write_env_file(env, {"MOSAERA_API_HOST": _PUBLIC, "MOSAERA_API_TOKEN": "tok"})
    after_lines = env.read_text().splitlines()

    # Every original line survives, in its original order, with the new keys appended after.
    assert after_lines[: len(before_lines)] == before_lines
    assert read_env_file(env)["MOSAERA_API_HOST"] == _PUBLIC
    assert read_env_file(env)["MOSAERA_API_TOKEN"] == "tok"


def test_the_write_is_atomic_and_never_leaves_a_half_file(tmp_path: Path) -> None:
    """`write_text` truncates then writes, so a crash mid-write left a TRUNCATED `.env` — of the
    file this module calls "the operator's, not ours". A temp file plus `os.replace` means a reader
    sees the old file or the new one, never a partial one."""
    import os
    from unittest.mock import patch

    env = tmp_path / ".env"
    env.write_text("MOSAERA_DB_PORT=5432\n")
    with patch("mosaera_api.setup.env_file.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            write_env_file(env, {"MOSAERA_API_TOKEN": "tok"})
    # The original survived the failure intact, and no debris was left beside it.
    assert env.read_text() == "MOSAERA_DB_PORT=5432\n"
    assert [p.name for p in tmp_path.iterdir() if p.name != ".env"] == []
    assert os.path.exists(env)


def test_the_token_is_never_briefly_world_readable(tmp_path: Path) -> None:
    # chmod used to run AFTER the write, so a new file held a service token at 0644 in the window
    # between. It is created 0600 now, before any content exists.
    env = tmp_path / ".env"
    write_env_file(env, {"MOSAERA_API_TOKEN": "secret"})
    assert env.stat().st_mode & 0o777 == 0o600
