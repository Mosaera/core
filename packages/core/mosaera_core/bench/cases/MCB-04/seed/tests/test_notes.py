import subprocess
import sys
from pathlib import Path


def run(*args: str, notes_file: Path) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    env["NOTES_FILE"] = str(notes_file)
    return subprocess.run(
        [sys.executable, "-m", "notes", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_add_then_list(tmp_path: Path) -> None:
    nf = tmp_path / "notes.json"
    assert run("add", "buy milk", notes_file=nf).returncode == 0
    listed = run("list", notes_file=nf)
    assert "buy milk" in listed.stdout
