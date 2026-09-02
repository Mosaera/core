"""Cherry-pick selected commits onto a fresh branch (the commit-picker's engine, A2).

The operator picks a subset of commits in the compose Sheet; this cuts a fresh branch at the
base and cherry-picks exactly those commits onto it, so the MR opened from that branch contains
ONLY the chosen commits.

DANGER — this mutates the LONG-LIVED shared project clone (a ``checkout -B`` + commits), which
races the run lifecycle. The CALLER must hold the project mutex and refuse when a run is active
(the same precondition ``open_project_workspace(reset=True)`` relies on). This function itself
guarantees one thing on failure: it ``cherry-pick --abort``s so no conflict markers or
``CHERRY_PICK_HEAD`` are left to poison the next run. It never raises — a conflict is a structured
result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from git import GitCommandError

from mosaera_core.tools.repo.workspace import Workspace


@dataclass(frozen=True)
class CherryResult:
    branch: str = ""
    picked: list[str] = field(default_factory=list)
    conflict_sha: str | None = None  # the sha that failed to apply (a conflict), if any
    error: str | None = None


def cherry_pick_into_branch(
    workspace: Workspace, base: str, shas: list[str], new_branch: str
) -> CherryResult:
    """Cut ``new_branch`` at ``base`` and cherry-pick ``shas`` (in order) onto it. On the FIRST
    conflict: abort (leave the tree clean) and return the failing sha — nothing is left
    half-applied. Returns the branch + picked shas on success. Never raises."""
    if not shas:
        return CherryResult(error="no commits selected")
    repo = workspace.repo
    try:
        repo.git.checkout("-B", new_branch, base)
    except GitCommandError as exc:
        # Local git only (no remote URL / token in the message) — truncate, no scrub needed.
        return CherryResult(error=str(exc)[:200] or "could not cut branch")
    picked: list[str] = []
    for sha in shas:
        try:
            repo.git.cherry_pick(sha)
            picked.append(sha)
        except GitCommandError as exc:
            # Leave the shared clone clean — a stray CHERRY_PICK_HEAD poisons the next run.
            try:
                repo.git.cherry_pick("--abort")
            except GitCommandError:
                pass
            return CherryResult(
                branch=new_branch,
                picked=picked,
                conflict_sha=sha,
                error=str(exc)[:200] or "cherry-pick conflict",
            )
    return CherryResult(branch=new_branch, picked=picked)
