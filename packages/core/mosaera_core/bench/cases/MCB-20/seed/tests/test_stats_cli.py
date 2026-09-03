import subprocess
import sys


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "stats_cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_text_output() -> None:
    result = run("1", "2", "3", "4")
    assert result.returncode == 0
    assert "mean: 2.5" in result.stdout
    assert "max: 4" in result.stdout
    assert "min: 1" in result.stdout
