"""Workspace clone management and repo tools.

Agents only ever receive a ``Workspace`` pointing at a clone under
``.mosaera/workspaces/<run-id>/`` — never the source repository. Every path an agent
supplies is resolved and checked against the clone root (symlinks included) before any
read or write.

This package is the Phase-5 split of the former ``repo.py`` god-file into one concern
per module — ``workspace`` (the clone + path guard), ``clone`` (cloning/reopening),
``diff`` (read-only inspection), ``factory`` (the agent toolset). This ``__init__`` is a
thin facade: it re-exports the public surface so ``from mosaera_core.tools.repo import X``
keeps working unchanged.
"""

from __future__ import annotations

from mosaera_core.tools.repo._capabilities import (
    CODER_TOOL_CAPABILITIES,
    describe_coder_capabilities,
)
from mosaera_core.tools.repo._read import (
    _MAX_READ_CHARS as _MAX_READ_CHARS,  # re-exported for tests
)
from mosaera_core.tools.repo.cherry import CherryResult, cherry_pick_into_branch
from mosaera_core.tools.repo.clone import (
    DriftStatus,
    check_base_drift,
    clone_project,
    clone_repo,
    init_project,
    open_project_workspace,
)
from mosaera_core.tools.repo.clone import (
    _auth_url as _auth_url,  # re-exported for tests
)
from mosaera_core.tools.repo.diff import (
    OVERVIEW_RULES_VERSION,
    branch_standing,
    build_overview,
    commit_list,
    hash_files,
    local_branches,
    parse_numstat,
    project_base,
    project_diff,
    project_diff_stats,
    project_item_diff,
    remote_synced,
    tampered_files,
)
from mosaera_core.tools.repo.factory import build_repo_tools
from mosaera_core.tools.repo.workspace import PathEscapeError, Workspace

__all__ = [
    "CODER_TOOL_CAPABILITIES",
    "OVERVIEW_RULES_VERSION",
    "CherryResult",
    "DriftStatus",
    "PathEscapeError",
    "Workspace",
    "branch_standing",
    "build_overview",
    "build_repo_tools",
    "check_base_drift",
    "cherry_pick_into_branch",
    "clone_project",
    "clone_repo",
    "commit_list",
    "describe_coder_capabilities",
    "hash_files",
    "init_project",
    "local_branches",
    "open_project_workspace",
    "parse_numstat",
    "project_base",
    "project_diff",
    "project_diff_stats",
    "project_item_diff",
    "remote_synced",
    "tampered_files",
]
