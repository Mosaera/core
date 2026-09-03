"""A guard-test must FAIL if its guard is deleted.

**Why.** `make lint` runs six guards. Whether each one is genuinely tested has been established by
inspection, and inspection has now missed it twice:

- `check_file_sizes.py` shipped with **no guard-test at all** — found 2026-08-08, the same gap
  `test_doc_links_guard.py` exists to close for the link guard;
- `test_doc_claims.py` used a specific ADR number as its **synthetic invalid fixture**, so when an
  ADR with that number was written (2026-08-10), reality satisfied the fixture and the guard-test
  silently stopped testing the guard. The guard did not break; its test became vacuous.

Both are the session's recurring shape one level up: a control that *looks* validated and is not.
The mechanical question is sharper than "does a test exist?":

    Neuter the guard. Does its test go red?

If not, the test is not evidence about the guard, whatever it asserts. This subsumes "does the
fixture belong to the test" — a fixture that reality can satisfy cannot detect a deleted guard.

**Method.** Each guard is a script the guard-test invokes by subprocess, so "deleted" is modelled as
the honest worst case: a guard that always exits 0. The original bytes are restored in a `finally`
and re-asserted, so a crash mid-test cannot leave a neutered guard behind.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "scripts"
_TESTS = Path(__file__).resolve().parent

# A guard that always passes — what "the guard was deleted" looks like from the test's side.
_NEUTERED = "import sys\n\nsys.exit(0)\n"

# Guards with NO guard-test, pinned so the debt is visible and SHRINK-ONLY — the same ratchet
# `check_control_liveness.py` uses for its own grandfathered rows. Removing a name means the test
# now exists. Adding one is a deliberate act that shows up in review.
_UNTESTED: frozenset[str] = frozenset({"check_layer_imports.py", "check_state_keys.py"})


def _guards() -> list[str]:
    """The guards `make lint` runs — parsed from the Makefile, never transcribed, so a guard added
    later cannot escape this test by not being on a hand-list."""
    text = (_ROOT / "Makefile").read_text(encoding="utf-8")
    targets = re.search(r"^lint:(.*)$", text, re.M)
    assert targets, "could not parse the Makefile `lint:` line — the test drifted, not the code"
    scripts: list[str] = []
    for target in targets.group(1).split():
        body = re.search(rf"^{re.escape(target)}:\n(.*?)(?=\n\S|\Z)", text, re.M | re.S)
        if body:
            scripts += re.findall(r"scripts/(\w+\.py)", body.group(1))
    return sorted(set(scripts))


def _test_file_for(guard: str) -> Path | None:
    """The test that invokes this guard — found by searching, not mapped by hand."""
    for candidate in sorted(_TESTS.glob("test_*.py")):
        if candidate.name == Path(__file__).name:
            continue
        if guard in candidate.read_text(encoding="utf-8"):
            return candidate
    return None


def _suite_passes(test_file: Path) -> bool:
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        check=False,
        cwd=_ROOT,
    )
    return proc.returncode == 0


def test_every_lint_guard_is_accounted_for() -> None:
    """Either a guard has a test, or it is on the shrink-only debt list. No third option."""
    guards = _guards()
    assert guards, "parsed zero guards from the Makefile — this test would then be vacuous"
    missing = {g for g in guards if _test_file_for(g) is None}
    assert missing == _UNTESTED, (
        f"guards with no guard-test changed: {sorted(missing)} vs pinned {sorted(_UNTESTED)}. "
        "The list may only SHRINK — a new guard ships with a test that detects its deletion."
    )


@pytest.mark.parametrize("guard", [g for g in _guards() if g not in _UNTESTED])
def test_the_guard_test_detects_a_deleted_guard(guard: str) -> None:
    """THE MECHANICAL CHECK. Replace the guard with one that always passes; its test must go red."""
    test_file = _test_file_for(guard)
    assert test_file is not None, f"{guard} has no test but is not on the debt list"
    script = _SCRIPTS / guard
    original = script.read_bytes()

    assert _suite_passes(test_file), (
        f"{test_file.name} is red BEFORE neutering {guard} — the result below would be "
        "meaningless, since a suite that is already failing 'detects' anything."
    )
    try:
        script.write_text(_NEUTERED, encoding="utf-8")
        assert not _suite_passes(test_file), (
            f"{test_file.name} PASSES with {guard} replaced by `sys.exit(0)`. It is not evidence "
            "about that guard — whatever it asserts, deleting the guard changes nothing it sees."
        )
    finally:
        script.write_bytes(original)
    assert script.read_bytes() == original, f"failed to restore {guard} — repo left modified"
