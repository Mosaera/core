"""Shipped-tree hygiene: what the coder may NOT create, and the sanctioned scratch space.

A coder that gets stuck litters the tree with debug/scratch scripts and stray root-level test
files. That clutter ships with the project and pollutes the test run, so these writes are refused
at the source rather than discouraged in a prompt — the refusal message redirects it to the
sanctioned space (#59, ADR-0064) or to `run_tests`.
"""

from __future__ import annotations

import re

# A coder that gets stuck tends to litter the tree with debug/scratch scripts and
# stray root-level test files. That clutter ships with the project and pollutes
# the test run — a senior keeps the working tree clean — so writes of these names
# are refused at the source (the error redirects the coder to run_tests / tests/).
SCRATCH_NAME = re.compile(r"^(debug|scratch|tmp|temp|trace|manual|scratchpad)[_a-z0-9]*\.py$", re.I)
ROOT_TEST_NAME = re.compile(r"^(test_.+|.+_test)\.py$", re.I)

# The sanctioned scratch space (#59, ADR-0064): a write-anything dir the coder uses for throwaway
# probes/fixtures/notes. Excluded from delivery + grading via .git/info/exclude (clone.py), and
# hidden from listings/tamper by workspace._SKIP_DIRS, so nothing here ever ships or is judged.
SCRATCH_DIR = ".mosaera/scratch"


def under_scratch(rel: str) -> bool:
    """Whether ``rel`` (a normalized, workspace-relative posix path) is inside the scratch space."""
    return rel == SCRATCH_DIR or rel.startswith(SCRATCH_DIR + "/")


def disallowed_scratch(rel: str, *, scratch_enabled: bool = False) -> str | None:
    """Why ``rel`` is a throwaway/misplaced file the coder should not create, or None if it's fine.

    When ``scratch_enabled``, a path under ``.mosaera/scratch/`` is always allowed (any name) — that
    is the sanctioned throwaway space; the refusal below applies only to the SHIPPED tree."""
    if scratch_enabled and under_scratch(rel):
        return None
    name = rel.rsplit("/", 1)[-1]
    if SCRATCH_NAME.match(name):
        redirect = (
            f"write it under {SCRATCH_DIR}/ (a scratch space that never ships)"
            if scratch_enabled
            else "use sandbox_exec to run a snippet, or run_tests, to check behaviour"
        )
        return f"debug/scratch scripts don't belong in the shipped tree — {redirect}"
    if "/" not in rel and ROOT_TEST_NAME.match(name):
        return "put automated tests under tests/, not at the repo root"
    return None
