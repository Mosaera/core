"""Hidden acceptance suite for MCB-20 (add a `--json` flag to the stats CLI).

Ground truth — never shown to the agent, injected at grade time. Drives the
delivered ``python -m stats_cli`` as a black box, broader than the seed's own
visible tests.
"""

from __future__ import annotations

import json
import subprocess
import sys


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "stats_cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_text_output_still_works() -> None:
    result = run("1", "2", "3", "4")
    assert result.returncode == 0
    assert "mean: 2.5" in result.stdout


def test_json_flag_first() -> None:
    result = run("--json", "1", "2", "3", "4")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"mean": 2.5, "max": 4.0, "min": 1.0}


def test_json_flag_last() -> None:
    result = run("1", "2", "3", "4", "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"mean": 2.5, "max": 4.0, "min": 1.0}


def test_json_output_is_not_text_lines() -> None:
    result = run("--json", "1", "2", "3", "4")
    assert result.returncode == 0
    # a single JSON object, not the three "mean:/max:/min:" text lines
    assert "mean:" not in result.stdout
    assert len([ln for ln in result.stdout.splitlines() if ln.strip()]) == 1


def test_no_args_usage_nonzero() -> None:
    result = run()
    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert result.stderr.strip() != ""
