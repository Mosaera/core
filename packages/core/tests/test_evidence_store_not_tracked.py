"""The evidence store must never be a tracked path — it is how the corpus was destroyed, twice.

**What happened.** A `.mosaera` symlink was committed on 2026-08-10 (`a9f7fe3`, accidentally, as a
side effect of an unrelated audit commit). This repository carried the WSL-era setting
`core.symlinks=false`, under which git materialises a symlink as a **regular file containing its
target path**. So checking out or merging any branch carrying that blob replaced the live evidence
store directory with a 47-byte text file. ~2,500 scorecards were destroyed on 2026-08-10, and the
identical write reproduced on 2026-08-11 during a routine merge — recovered only because a backup
had been taken hours earlier. See
`docs/engineering-history/evidence-store-loss-2026-08-10.md`.

**Why `.gitignore` did not stop it.** The rule read `.mosaera/`. A trailing slash matches a
*directory* only, so a symlink or file of that same name was never ignored at all. The rule now has
no trailing slash.

**Why a test and not a `make lint` guard.** `make test` is in the same CI gate, and a seventh guard
would change the CODEOWNERS-protected Makefile command contract for no additional coverage.

This is a POSITIVE CONTROL, per the discipline in `test_guard_liveness.py`: the check is a pure
function of a path list, and a synthetic tracked entry below proves it can still fail. A check that
only ever sees a clean repository is indistinguishable from one that cannot fail.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_GIT = shutil.which("git") or "git"

# Runtime state that lives on disk beside the code and must never be version-controlled. A tracked
# entry here does not merely add noise — git will WRITE it over live data on checkout.
_STORE_ROOTS = (".mosaera",)


def _offending(tracked: list[str]) -> list[str]:
    """Tracked paths colliding with the store. Pure, so it can be positive-controlled."""
    return sorted(
        p for p in tracked if any(p == root or p.startswith(f"{root}/") for root in _STORE_ROOTS)
    )


def _tracked_paths() -> list[str]:
    proc = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
        [_GIT, "ls-files"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_ROOT,
    )
    return [line for line in proc.stdout.splitlines() if line]


def test_the_evidence_store_is_not_tracked() -> None:
    """THE CHECK. No path under the evidence store may be in the index, in any form."""
    tracked = _tracked_paths()
    assert tracked, "git ls-files returned nothing — this test would then be vacuous"

    offending = _offending(tracked)
    assert not offending, (
        f"the evidence store is tracked: {offending}. Git will materialise these over live run "
        "data on the next checkout — under core.symlinks=false a symlink becomes a regular file, "
        "which is what destroyed the corpus on 2026-08-10. Run `git rm --cached` and confirm the "
        ".gitignore rule has NO trailing slash."
    )


def test_the_check_detects_a_tracked_store() -> None:
    """The positive control. Without this, a clean repo and a broken check score identically."""
    assert _offending([".mosaera"]) == [".mosaera"], "a bare tracked store must be caught"
    assert _offending([".mosaera/settings.json"]) == [".mosaera/settings.json"], (
        "a file INSIDE the store must be caught too — the 2026-08-10 blob was the store root, "
        "but a settings.json commit would be just as destructive on checkout"
    )
    assert _offending(["packages/core/mosaera_core/cli.py", ".mosaera.example"]) == [], (
        "must not fire on ordinary source, nor on a prefix that merely starts with the same text"
    )


def test_the_store_is_ignored_in_every_form() -> None:
    """`.mosaera/` ignored a directory and let the symlink through. Assert all three forms."""
    for candidate in (".mosaera", ".mosaera/reports", ".mosaera/settings.json"):
        proc = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
            [_GIT, "check-ignore", "-q", candidate],
            capture_output=True,
            check=False,
            cwd=_ROOT,
        )
        assert proc.returncode == 0, (
            f"{candidate} is NOT gitignored, so it can be committed by accident — exactly the "
            "2026-08-10 failure. The rule must have no trailing slash."
        )


def test_symlinks_are_not_silently_materialised_as_files() -> None:
    """`core.symlinks=false` is the amplifier that turned a stray symlink into data destruction.

    It is WSL-era residue; the dev box has been native Linux since 2026-07-28. Pinned so the
    setting cannot drift back unnoticed on a machine where it is not needed.
    """
    if sys.platform.startswith("win"):
        return  # the one platform where core.symlinks=false is legitimate
    proc = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
        [_GIT, "config", "--get", "core.symlinks"],
        capture_output=True,
        text=True,
        check=False,
        cwd=_ROOT,
    )
    value = proc.stdout.strip().lower()
    assert value != "false", (
        "core.symlinks=false on a non-Windows checkout. Git will write tracked symlinks as "
        "regular files containing their target path, silently replacing whatever is there. "
        "This turned one stray committed symlink into the loss of ~2,500 scorecards."
    )
