"""Cloning a source into an isolated, per-run (or persistent per-project) workspace.

Agents only ever touch the clone; the source repository is never modified. A private
https source is authenticated with a clone token that is never persisted (``origin`` is
reset to the clean URL), and an empty source is initialized with a base commit so
downstream build/diff/merge have a branch to stand on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, Repo
from mosaera_connectors import inject_repo_token, is_gitlab_source
from mosaera_connectors.redact import scrub_credentials

from mosaera_core.tools.repo.workspace import Workspace


def _auth_url(source: str, token: str | None, gitlab_url: str | None) -> str:
    """A clone URL carrying token auth (``oauth2:<token>@host``) — but ONLY when the source is on
    the configured GitLab (host equality via ``is_gitlab_source``, ADR-0042).

    A project's scoped PAT must never be injected into an arbitrary host: a project whose
    ``source_repo`` points at an attacker-controlled look-alike would otherwise send the token
    there at clone time. Host trust is gated here; the scheme-safe injection (https, or
    http-to-loopback only — never a PAT over cleartext http to a networked host) is delegated to
    the shared ``inject_repo_token`` sink, the SAME one the ls-remote check uses (M-1). Non-GitLab,
    non-http, or tokenless sources → unchanged."""
    if not token:
        return source
    if not gitlab_url or not is_gitlab_source(source, gitlab_url):
        return source  # never leak the token off the configured GitLab host
    return inject_repo_token(source, token)


def _init_empty(repo: Repo, dest: Path, base: str) -> None:
    """Give a freshly cloned empty repo a real base branch with one commit, so
    build/diff/merge have something to stand on (the agent does real scaffolding)."""
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Mosaera")
        cw.set_value("user", "email", "mosaera@local")
    repo.git.checkout("-b", base)
    (dest / "README.md").write_text("# Project\n\nInitialized by Mosaera.\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("chore: initialize project (Mosaera)")


def _prepare_workspace(repo: Repo, dest: Path, branch: str) -> None:
    """Everything a usable working tree needs beyond its history: the working branch, the
    clone-local excludes, and the agent scratch dir.

    Shared by the clone path and the init path deliberately. The exclude list is load-bearing —
    it is what keeps `.venv`, `node_modules` and the agent's scratch space out of every diff and
    every delivery — and a second copy of it in a second function would rot without anyone
    noticing until something shipped that should not have.
    """
    repo.git.checkout("-b", branch)
    # Keep test byproducts out of diffs and commits without touching the cloned
    # working tree (.git/info/exclude is clone-local, unlike .gitignore).
    exclude = dest / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as fh:
        # .venv/node_modules hold the install-phase dependencies — excluded so
        # they never enter diff_all()/commit_all() and survive the run-start
        # `git clean -fd` (which honors info/exclude without -x). `.mosaera/` is the
        # agent scratch space (#59, ADR-0064): the SAME clone-local mechanism excludes
        # it from BOTH diff_all() (→ grading) and commit_all() (→ delivery), so nothing
        # the coder writes under .mosaera/scratch/ can ever ship or be graded.
        # `/.mosaera/` is ANCHORED to the clone root (the scratch namespace lives at the root) so a
        # legitimate nested `src/.mosaera/` deliverable is not silently dropped (#59 red-team). This
        # is only a FIRST layer — the load-bearing containment is workspace._stage_all at delivery.
        fh.write(
            "\n__pycache__/\n*.pyc\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n"
            ".coverage\n.venv/\n/node_modules/\n/.mosaera/\n"
        )
    # Pre-create the scratch dir so it exists for the coder from the first write.
    (dest / ".mosaera" / "scratch").mkdir(parents=True, exist_ok=True)


def _clone_into(
    source: str,
    dest: Path,
    run_id: str,
    branch: str,
    clone_token: str | None = None,
    gitlab_url: str | None = None,
) -> Workspace:
    """Clone ``source`` into ``dest`` on a fresh ``branch``. Agents only ever
    touch the clone; the source repository is never modified.

    ``clone_token`` authenticates the clone of a private https source, but is injected ONLY
    when the source is on ``gitlab_url`` (host equality — see ``_auth_url``); it is never
    persisted (``origin`` is reset to the clean URL afterward). An empty source is
    initialized with a ``main`` base commit so downstream steps have a base branch.
    """
    if not source.strip():
        # `Path("")` resolves to the CURRENT WORKING DIRECTORY, and `Path("").exists()` is True —
        # so a blank source would silently clone whatever directory the server happens to be
        # running in. That is the cwd-inheritance shape that cost this project its evidence store
        # on 2026-08-10. A project with no upstream takes `init_project`, never this.
        raise RuntimeError("clone failed: no source repository was given")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = source
    local = Path(source)
    if local.exists():
        src = str(local.resolve())
    try:
        repo = Repo.clone_from(_auth_url(src, clone_token, gitlab_url), dest)
    except GitCommandError as exc:
        # git echoes the auth URL (with the token) in its error — never let it
        # reach the API caller (this propagates to "could not start run: ...").
        raise RuntimeError(f"clone failed: {scrub_credentials(str(exc))}") from None
    if clone_token:
        repo.remotes.origin.set_url(src)  # never leave the token in .git/config
    if not repo.head.is_valid():
        _init_empty(repo, dest, "main")  # greenfield: establish the base branch
    _prepare_workspace(repo, dest, branch)
    return Workspace(root=dest.resolve(), run_id=run_id, branch=branch)


def clone_repo(source: str, workspaces_dir: Path, run_id: str) -> Workspace:
    """Clone ``source`` into an isolated, per-run workspace under ``workspaces_dir``."""
    return _clone_into(source, workspaces_dir / run_id, run_id, f"mosaera/{run_id}")


def clone_project(
    source: str,
    projects_dir: Path,
    project_id: str,
    clone_token: str | None = None,
    gitlab_url: str | None = None,
) -> Workspace:
    """Clone ``source`` into a project's persistent clone at
    ``projects_dir/<project_id>/repo`` on ``mosaera/project-<project_id>``.

    Unlike ``clone_repo``, this clone is long-lived: tasks accumulate work on the
    project branch across runs until the project is merged. ``clone_token`` enables
    cloning a private GitLab source (injected only when the source is on ``gitlab_url``);
    an empty source is initialized with a base.
    """
    return _clone_into(
        source,
        projects_dir / project_id / "repo",
        project_id,
        f"mosaera/project-{project_id}",
        clone_token=clone_token,
        gitlab_url=gitlab_url,
    )


def init_project(projects_dir: Path, project_id: str) -> Workspace:
    """A project's working repo with **no upstream** — the local-first path.

    The counterpart to ``clone_project``: same destination, same long-lived branch, same working
    tree preparation, but nothing is cloned because there is nothing to clone from. The project's
    code starts here and lives here; publishing it to a forge is a later, optional step.

    ``origin`` is deliberately NOT set. There is no upstream yet, and inventing one would make the
    publish step ambiguous about where it is meant to push.

    Reuses ``_init_empty`` — the same base commit a cloned-but-empty repository already gets — so
    a greenfield project looks identical whether it arrived by clone or by init, and every
    downstream step (``classify_repo_shape`` → ``"empty"``, diff, delivery) sees one shape.
    """
    dest = projects_dir / project_id / "repo"
    dest.parent.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(dest)
    _init_empty(repo, dest, "main")
    _prepare_workspace(repo, dest, f"mosaera/project-{project_id}")
    return Workspace(root=dest.resolve(), run_id=project_id, branch=f"mosaera/project-{project_id}")


@dataclass(frozen=True)
class DriftStatus:
    """How the project clone's base relates to ``origin/<base>`` (ADR-0102 slice D)."""

    # in_sync | fast_forwarded | diverged | no_remote_base | unreachable
    kind: str
    detail: str = ""


def check_base_drift(root: Path, base: str | None = None, *, timeout: int = 30) -> DriftStatus:
    """Fetch ``origin/<base>`` and classify the local tip against it — RUN-START ONLY,
    under the project mutex (the fast-forward case moves the current branch pointer).

    A stacked item branch is cut from the clone's current tip; when a merged MR has
    advanced the remote base past that tip, the next item's diff is wrong. The one
    honest set of behaviors (no knob, ADR-0102):

    - ``in_sync`` — ``origin/<base>`` is contained in the tip → proceed.
    - ``fast_forwarded`` — the tip is strictly behind ``origin/<base>`` and fully
      contained in it (a clean merge landed remotely): the current branch is hard-reset
      forward to ``origin/<base>`` so the next item stacks on reality. Nothing is lost —
      every local commit is already in the remote base.
    - ``diverged`` — both sides have commits the other lacks (e.g. a squash merge
      rewrote history): the CALLER must fail closed and surface it — cutting a branch
      here would produce a wrong MR diff.
    - ``no_remote_base`` — the remote has no ``<base>`` yet (greenfield, unpushed):
      nothing to drift against → proceed.
    - ``unreachable`` — no origin / offline / fetch failed: a correctness aid must not
      break offline or local-dir use → the caller proceeds with a recorded warning.
    """
    repo = Repo(root)
    if not any(r.name == "origin" for r in repo.remotes):
        return DriftStatus("unreachable", "clone has no origin remote")
    if base is None:
        # Same derivation as diff.project_base (import here to keep module layering flat).
        from mosaera_core.tools.repo.diff import project_base

        base = project_base(Workspace(root=root, run_id="drift", branch=repo.active_branch.name))
    try:
        repo.git.fetch("origin", base, kill_after_timeout=timeout)
    except GitCommandError as exc:
        msg = scrub_credentials(str(exc))
        if "couldn't find remote ref" in msg.lower():
            return DriftStatus("no_remote_base", f"origin has no '{base}' yet")
        return DriftStatus("unreachable", msg)
    try:
        remote_base = repo.commit(f"origin/{base}")
        tip = repo.head.commit
    except Exception:
        return DriftStatus("no_remote_base", f"origin/{base} not resolvable after fetch")
    if repo.is_ancestor(remote_base, tip):
        return DriftStatus("in_sync")
    if repo.is_ancestor(tip, remote_base):
        repo.git.reset("--hard", f"origin/{base}")
        return DriftStatus("fast_forwarded", f"{tip.hexsha[:8]} → {remote_base.hexsha[:8]}")
    return DriftStatus(
        "diverged",
        f"origin/{base} ({remote_base.hexsha[:8]}) and the local tip ({tip.hexsha[:8]}) "
        "each carry commits the other lacks — merge or reconcile the project clone "
        "before the next item run",
    )


def open_project_workspace(
    projects_dir: Path,
    project_id: str,
    run_id: str,
    *,
    reset: bool = False,
    item_branch: str | None = None,
) -> Workspace:
    """Return a ``Workspace`` over a project's **existing** persistent clone.

    Unlike ``clone_project`` this does not clone — it reopens the long-lived clone
    on its current project branch so item runs accumulate work there. Raises if the
    clone is missing (the project was never initialized).

    ``reset=True`` (run-start only, and only while holding the project mutex)
    sweeps UNCOMMITTED leftovers from cancelled/crashed/capped/unapproved runs —
    ``reset --hard`` + ``clean -fd`` — so they can never leak into the next
    run's ``diff_all``/``commit_all`` (which stage everything). The committed
    project-branch history is deliberately preserved: accumulation across item
    runs is the product model. ``clean`` without ``-x`` respects the clone-local
    ``.git/info/exclude``. Read paths (diff/patch/files/merge) MUST keep the
    default ``reset=False`` **and** ``item_branch=None`` — an unconditional reset or
    a branch checkout would destroy/rewrite a live run's uncommitted coder writes
    from a concurrent GET.

    ``item_branch`` (run-start only) cuts/reopens a per-item branch for the
    per-item stacked-MR model (ADR-0021): ``checkout -B <item_branch>`` at the
    current tip (the previously delivered item's branch, since the clone accumulates
    linearly) BEFORE the reset, so the item's commits land on its own branch while
    still building on all prior delivered work. ``None`` keeps the current active
    branch (the legacy single-branch behavior).
    """
    root = (projects_dir / project_id / "repo").resolve()
    if not (root / ".git").is_dir():
        raise FileNotFoundError(f"project clone not found at {root}; initialize the project first")
    repo = Repo(root)
    if item_branch and repo.head.is_valid():
        # Cut (or re-point) the item branch at the current tip before sweeping
        # uncommitted leftovers, so the reset below acts on the item branch.
        repo.git.checkout("-B", item_branch)
    if reset and repo.head.is_valid():
        repo.git.reset("--hard", "HEAD")
        repo.git.clean("-fd")
    return Workspace(root=root, run_id=run_id, branch=repo.active_branch.name)
