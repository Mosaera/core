"""Read-only inspection of a project clone: the merge base, accumulated/per-item
diffs, per-file stats, the PM overview, and content-hash snapshots for tamper
detection. None of these mutate the workspace.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from mosaera_core.tools.repo.workspace import Workspace


def project_base(workspace: Workspace) -> str:
    """The source default branch a project branch will merge back into.

    Prefers the clone's ``origin/HEAD``; falls back to a local ``main``/``master``.
    """
    repo = workspace.repo
    try:
        ref = repo.git.rev_parse("--abbrev-ref", "origin/HEAD")  # e.g. "origin/main"
        name = ref.split("/", 1)[1] if "/" in ref else ref
        if name:
            return name
    except Exception:  # noqa: S110 — fall through to a heuristic default
        pass
    heads = {h.name for h in repo.heads}
    for candidate in ("main", "master"):
        if candidate in heads:
            return candidate
    return "main"


def commit_list(
    workspace: Workspace, base: str, ref: str = "HEAD", limit: int = 200
) -> list[dict[str, Any]]:
    """Commits on ``ref`` ahead of ``base`` (``base..ref``), newest first — the material for the
    commit-picker (A2). One commit per delivered item today, so this is effectively a per-item
    picker. Read-only; empty on any git fault (a bad ref must not 500 the picker)."""
    try:
        commits = workspace.repo.iter_commits(f"{base}..{ref}", max_count=limit)
        return [
            {
                "sha": c.hexsha,
                "short": c.hexsha[:8],
                "subject": c.summary,
                "author": c.author.name or "",
                "date": c.committed_datetime.isoformat(),
            }
            for c in commits
        ]
    except Exception:
        return []


def local_branches(workspace: Workspace) -> list[dict[str, Any]]:
    """The clone's branches for the target-branch picker — read from the LOCAL clone, so it
    needs NO api token (ADR-0103 follow-up). Remote-tracking refs (``origin/*``, the real merge
    targets) are the primary list; Mosaera's own local branches (``mosaera/*``) are excluded as
    they're never a human MR target. No fetch — a fetch mutates ``.git`` and would race a run, so
    this serves whatever the last run-start fetch left; possibly stale but zero-risk."""
    repo = workspace.repo
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        default = project_base(workspace)
    except Exception:
        default = "main"
    try:
        for ref in repo.remotes.origin.refs:
            name = ref.name.split("/", 1)[1] if "/" in ref.name else ref.name
            if name in ("HEAD", "") or name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "merged": False, "protected": name == default})
    except Exception:  # noqa: S110 — no origin / bare clone → local heads only
        pass
    for head in repo.heads:
        if head.name.startswith("mosaera/") or head.name in seen:
            continue
        seen.add(head.name)
        out.append({"name": head.name, "merged": False, "protected": head.name == default})
    out.sort(key=lambda b: (b["name"] != default, b["name"]))  # default first, then alpha
    return out


def remote_synced(workspace: Workspace, timeout: int = 15) -> bool | None:
    """Whether the clone's current branch tip exists on ``origin`` at the same sha.

    The honesty seam behind "delivered but unpushed" (ADR-0102 slice H): ``False``
    means committed-locally-only (including a branch the remote has never seen);
    ``None`` is the honest unknown (no remote / offline / error) — the caller must
    render unknown as unknown, never as synced.
    """
    try:
        repo = workspace.repo
        if not any(r.name == "origin" for r in repo.remotes):
            return None
        out = repo.git.ls_remote(
            "origin", f"refs/heads/{repo.active_branch.name}", kill_after_timeout=timeout
        )
        sha = out.split()[0] if out.strip() else ""
        if not sha:
            return False  # the branch does not exist on the remote at all
        return sha == repo.head.commit.hexsha
    except Exception:
        return None  # ANY fault is the honest unknown — this must never break the diff


def branch_standing(workspace: Workspace, timeout: int = 15) -> dict[str, Any]:
    """Where the working branch stands against the base — ahead / in sync / behind / unknown.

    Deliberately FETCH-FREE. There is exactly one ``git fetch`` in this codebase
    (``check_base_drift``, on a fresh item-run launch, holding the project mutex); a fetch on a
    read path mutates ``.git`` and races a live run, which is why neither this nor
    ``local_branches`` may add one. That constraint shapes what can honestly be reported:

    - **ahead** is exact and offline — ``base..HEAD`` counted from objects we already hold.
    - **behind** is NOT countable. ``ls-remote`` (the same non-mutating call ``remote_synced``
      already makes) gives the base's true remote sha, but counting commits needs the objects,
      and without a fetch we may not have them. So: if the remote sha IS an ancestor we hold, we
      are provably not behind; if we hold it and it is not an ancestor, we are behind by a
      countable amount; if we do not hold it at all, we are behind by an UNKNOWN amount — which
      is a truthful state, and the one the operator most needs to see before merging.

    ``base_ref_age_hint`` is None here on purpose: the caller knows when the clone last fetched,
    this function does not. Never render ``unknown`` as ``in_sync`` (ADR-0102 slice H).
    """
    out: dict[str, Any] = {"state": "unknown", "ahead": None, "behind": None, "base": None}
    try:
        repo = workspace.repo
        base = project_base(workspace)
        out["base"] = base
        out["ahead"] = len(list(repo.iter_commits(f"{base}..HEAD", max_count=500)))
        if not any(r.name == "origin" for r in repo.remotes):
            out["state"] = "no_remote"
            return out
        raw = repo.git.ls_remote("origin", f"refs/heads/{base}", kill_after_timeout=timeout)
        remote_sha = raw.split()[0] if raw.strip() else ""
        if not remote_sha:
            out["state"] = "no_remote_base"
            return out
        try:
            remote_commit = repo.commit(remote_sha)  # do we hold the object at all?
        except Exception:
            # The remote base moved past anything this clone has seen since its last fetch.
            out["state"] = "behind_unknown"
            return out
        if repo.is_ancestor(remote_commit, repo.head.commit):
            out["behind"] = 0
            out["state"] = "ahead" if out["ahead"] else "in_sync"
        else:
            out["behind"] = len(list(repo.iter_commits(f"HEAD..{remote_sha}", max_count=500)))
            out["state"] = "behind"
        return out
    except Exception:
        return out  # ANY fault stays the honest unknown — this must never break the page


def project_diff(workspace: Workspace, max_chars: int = 200_000) -> tuple[str, str]:
    """The net accumulated change of the project branch vs the source default.

    Returns ``(base, diff)``; the diff is capped at ``max_chars`` for payload size.
    """
    base = project_base(workspace)
    diff = workspace.repo.git.diff(f"{base}...HEAD")
    if len(diff) > max_chars:
        diff = diff[:max_chars] + f"\n... (diff truncated at {max_chars} chars)"
    return base, diff


def project_item_diff(workspace: Workspace, base_branch: str, max_chars: int = 200_000) -> str:
    """The change a single item contributes vs its stacked predecessor.

    For the per-item stacked-MR model (ADR-0021): ``base_branch`` is the previously
    delivered item's branch (or the source default for the first item), so
    ``base_branch...HEAD`` is *just this item's* changes — the clean diff its MR shows.
    Capped at ``max_chars`` for payload size.
    """
    diff = workspace.repo.git.diff(f"{base_branch}...HEAD")
    if len(diff) > max_chars:
        diff = diff[:max_chars] + f"\n... (diff truncated at {max_chars} chars)"
    return diff


def parse_numstat(out: str) -> list[dict[str, Any]]:
    """``git diff --numstat`` lines → per-file stats.

    Lines are ``<adds>\\t<dels>\\t<path>``; binary files report ``-`` (→ None).
    Rename paths like ``dir/{old => new}.py`` are normalized to the new path.
    """
    stats: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        adds_raw, dels_raw, path = parts
        if "{" in path and " => " in path:
            path = re.sub(r"\{([^{}]*) => ([^{}]*)\}", r"\2", path).replace("//", "/")
        elif " => " in path:
            path = path.split(" => ", 1)[1]
        stats.append(
            {
                "path": path,
                "additions": int(adds_raw) if adds_raw != "-" else None,
                "deletions": int(dels_raw) if dels_raw != "-" else None,
            }
        )
    return stats


def project_diff_stats(workspace: Workspace) -> list[dict[str, Any]]:
    """Per-file additions/deletions vs the source default (accurate even when
    the text diff from :func:`project_diff` is truncated for payload size)."""
    base = project_base(workspace)
    return parse_numstat(workspace.repo.git.diff(f"{base}...HEAD", "--numstat"))


#: Bump whenever build_overview's OUTPUT RULES change — the skip set, the caps, the sections.
#:
#: The cached overview is keyed on the clone's HEAD (migration 0030), which answers "have the
#: FILES changed?" and silently misses "have the RULES changed?". Excluding tool caches from the
#: listing on 2026-08-19 fixed nothing on any live project, because no clone had moved: every
#: project kept serving text built under the old rules until it happened to receive a delivery.
#: That is the original stale-overview defect one level up — a cache keyed on its inputs but not
#: on its builder — so the builder is part of the key now.
OVERVIEW_RULES_VERSION = "2"


def build_overview(
    workspace: Workspace, *, listing_limit: int = 160, readme_chars: int = 4000
) -> str:
    """A repo overview for the PM: the file listing plus the README (if any).

    Changing what this emits requires bumping ``OVERVIEW_RULES_VERSION``, or existing projects
    keep their old text until their clone next moves.
    """
    listing = "\n".join(workspace.file_listing(limit=listing_limit))
    for name in ("README.md", "README.rst", "README.txt", "README"):
        try:
            readme = (workspace.root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return f"## Files\n{listing}\n\n## {name}\n{readme[:readme_chars]}"
    return f"## Files\n{listing}"


def hash_files(workspace: Workspace, paths: Iterable[str]) -> dict[str, str]:
    """SHA-256 of each file's NEWLINE-NORMALIZED content (a missing file → ""). Snapshots the
    tester's authored tests so tampering is detected deterministically.

    Normalize CRLF→LF before hashing (ADR-0068): the scaffold/Proctor author tests on the Windows
    host (``write_text`` → CRLF) but the sandbox round-trip / git normalize to LF, so a raw-byte
    hash straddles a CRLF↔LF flip and false-flags the engine's OWN test as tampered (measured: the
    dominant `thrash_park` cause). This matches ``testintegrity``'s normalized hash space. The guard
    is UNWEAKENED — a real content/assertion change still changes the hash; only newline noise is
    ignored."""
    out: dict[str, str] = {}
    for rel in paths:
        target = workspace.root / rel
        try:
            data = target.read_bytes().replace(b"\r\n", b"\n") if target.is_file() else None
            out[rel] = hashlib.sha256(data).hexdigest() if data is not None else ""
        except OSError:
            out[rel] = ""
    return out


def tampered_files(workspace: Workspace, baseline: Mapping[str, str]) -> list[str]:
    """Paths whose current content differs from a prior ``hash_files`` snapshot — a
    protected test was edited or deleted since it was authored. Defense-in-depth over
    the per-tool ``protected_paths`` refusal (ADR-0013)."""
    current = hash_files(workspace, baseline.keys())
    return sorted(rel for rel, digest in baseline.items() if current.get(rel, "") != digest)
