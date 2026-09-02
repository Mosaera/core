"""The ``Workspace`` clone abstraction + its path guard.

Agents only ever receive a ``Workspace`` pointing at a clone under
``.mosaera/workspaces/<run-id>/`` — never the source repository. Every path an
agent supplies is resolved and checked against the clone root (symlinks
included) before any read or write.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from git import Repo

_MAX_LISTING = 300
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".mosaera",
    # Tool caches. Added 2026-08-19 after live validation: the PM's repo overview is a SORTED
    # listing capped at 160 paths, so dot-directories sort to the front and spend the budget
    # first. On the LedgerCLI clone the first TWELVE paths were all cache — six from
    # `.pytest_cache`, six from `.ruff_cache`, which holds one entry per cached source file — and
    # Quincy, asked what he could see, answered that he had no visibility into the repository. He
    # was reading a real listing; it just contained nothing about the project.
    #
    # These are regenerable, never hand-authored, and never the subject of work. Skipping them
    # also steadies `tree_hash` (cache churn no longer invalidates a memo key) and keeps them out
    # of project-type detection and the coder's `list_files`.
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    ".tox",
    ".nox",
    "htmlcov",
}
# NOT skipped, deliberately: `dist/`, `build/` and `*.egg-info/` are sometimes TRACKED — a built
# site can be the deliverable — and on this very project a tracked `src/budget_tracker.egg-info/`
# is the subject of three backlog items. Hiding it would hide the thing the work is about.
# The agent scratch namespace (#59, ADR-0064): a workbench dir that must NEVER enter a diff or a
# commit. Enforced at the delivery seam below -- NOT via .git/info/exclude, which a coder .gitignore
# negation outranks and which misses source-tracked paths (#59 red-team).
_SCRATCH_NAMESPACE = ".mosaera"


class PathEscapeError(Exception):
    """An agent-supplied path resolved outside the workspace clone."""


class DeliveryContainmentError(RuntimeError):
    """A path that must never be delivered (the agent scratch namespace) was staged for commit.
    Raised to FAIL CLOSED — abort the delivery rather than ship scratch content."""


def _read_root_text(root: Path, name: str) -> str:
    """Root-file text for the config reader. Local to avoid importing `validation` from here."""
    try:
        path = root / name
        return (
            path.read_text(encoding="utf-8", errors="replace")[:200_000] if path.is_file() else ""
        )
    except OSError:
        return ""


@dataclass
class Workspace:
    """An isolated clone that agents are allowed to modify."""

    root: Path
    run_id: str
    branch: str

    @property
    def repo(self) -> Repo:
        return Repo(self.root)

    def resolve(self, relative: str) -> Path:
        """Resolve an agent-supplied path, rejecting anything outside the clone."""
        candidate = Path(relative)
        if candidate.is_absolute():
            raise PathEscapeError(f"absolute paths are not allowed: {relative}")
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise PathEscapeError(f"path escapes the workspace: {relative}")
        return resolved

    def file_listing(self, limit: int | None = _MAX_LISTING) -> list[str]:
        """A PRESENTATION listing: the repo overview, `list_files`, memo keys. NOT evidence.

        Prunes `_SKIP_DIRS` by directory name at any depth, which is what a human or a model
        reading a repo wants and what a security pin must never use — the delivery path commits
        `src/.mosaera/`, `htmlcov/` and friends that this cannot see. `committable_paths` is the
        evidence listing; `limit=None` remains for callers that want the whole walk."""
        root_resolved = self.root.resolve()
        # PRUNE _SKIP_DIRS DURING the walk (os.walk topdown, dirnames[:] in place) — never
        # DESCEND into them. `rglob("*")` would recurse INTO `.venv`/`node_modules` and stat
        # every entry before the skip-filter runs, so a build-artifact venv holding a
        # platform-incompatible symlink (a Linux `.venv/bin/python` on a Windows host) raises
        # `WinError 1920` during traversal — crashing tree_hash on any run that installs deps.
        # Collect first, then keep the old global-sort + limit semantics + symlink guard.
        candidates: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            candidates.extend(Path(dirpath) / name for name in filenames)
        paths: list[str] = []
        for path in sorted(candidates):
            rel = path.relative_to(self.root)
            try:
                # Never follow a symlink out of the clone: a hostile target repo can
                # commit a symlink (or a symlinked dir) pointing at a host file, and
                # this listing feeds the read-only `search`/`list_files` tools that run
                # host-side. Skip symlinks and anything that resolves outside the root — and
                # skip (never crash on) an entry that can't be stat'd (a broken symlink).
                if path.is_symlink() or not path.resolve().is_relative_to(root_resolved):
                    continue
                is_file = path.is_file()
            except OSError:
                continue
            if is_file:
                paths.append(rel.as_posix())
            if limit is not None and len(paths) >= limit:
                break
        return paths

    def tree_hash(self, limit: int | None = _MAX_LISTING) -> str:
        """A cheap, content-sensitive fingerprint of the working tree: a hash over
        the sorted ``(path, size, mtime)`` of every listed file. It changes when a
        file is added, removed, or edited — the memo key for within-run evidence
        reuse (#23 / ADR-0003: the repo overview and validation plan only change
        when the tree does). Stat-only (never reads file contents) so it stays
        cheap on the hot path; run/process-scoped, so no cross-run staleness.

        NOT THE EVIDENCE PIN. It was, briefly, via ``limit=None`` — and lifting the 300-path cap
        was necessary but nowhere near sufficient, because the blindness that mattered was
        `_SKIP_DIRS`, not the cap. See ``evidence_hash``, which the pins use instead."""
        h = hashlib.sha256()
        for rel in self.file_listing(limit=limit):
            try:
                st = (self.root / rel).stat()
            except OSError:
                continue
            h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8", "replace"))
        return h.hexdigest()

    def committable_paths(self) -> list[str]:
        """Every path the DELIVERY PATH could commit — git's own view, never a filesystem walk.

        THE EVIDENCE LISTING. `file_listing` is a PRESENTATION listing: it prunes `_SKIP_DIRS` by
        directory NAME AT ANY DEPTH, which is right for a repo overview, the coder's `list_files`
        and a memo key, and wrong as a security primitive. `_stage_all` excludes only the ROOT
        `.mosaera/` — anchored on purpose (#59 red team) so a legitimate nested `src/.mosaera/`
        deliverable is not silently dropped. Those two disagreed, and the gap was a ship path:
        red team 2026-08-22 wrote `src/.mosaera/backdoor.py` with the coder's ordinary `write_file`,
        the ADR-0108 stamp did not move (`is_fresh: True`), the gate emitted `reasons == []`, and
        git committed the file. `htmlcov/`, `node_modules/`, `__pycache__/` at any depth were the
        same hole.

        So this mirrors `_stage_all` EXACTLY rather than approximating it: `git add -A` honours
        `.gitignore` + `.git/info/exclude`, which is `ls-files -c -o --exclude-standard`; then the
        same root-anchored scratch reset. One origin, so the two cannot drift apart again — which
        is the property, not the path list.
        """
        out = self.repo.git.ls_files("-c", "-o", "--exclude-standard", "-z")
        return sorted(
            p
            for p in out.split("\0")
            if p and p != _SCRATCH_NAMESPACE and not p.startswith(_SCRATCH_NAMESPACE + "/")
        )

    def security_listing(self) -> list[str]:
        """The listing a SECURITY control must use. RAISES rather than degrading — read that twice.

        `file_listing` is capped at 300 globally-sorted paths, and `tests/` sorts late. Seven
        controls read it anyway, so on any repo above the cap their protected set was EMPTY:
        `integrity_paths() == []`, the coder's write tools refused nothing, and
        `close_oracle_gap`'s tamper check — `any(...)` over an empty dict — passed vacuously while
        an edited pre-existing test was promoted to the run's oracle. Verified on a 401-file repo,
        2026-08-22: the producer rewrote its acceptance test to `assert True` and
        `tampered_integrity` returned `[]`.

        = `committable_paths` (everything the delivery path could commit)
        + ignored COLLECTION CONTROLS only.

        That second term closes a hole a pure-git source would otherwise CREATE: the coder writes a
        `.gitignore` naming `conftest.py`, then an untracked `tests/conftest.py` carrying
        `collect_ignore`. `ls-files --exclude-standard` cannot see it, but **pytest runs the
        worktree, not the index**, so the suite silently shrinks and exits 0.

        Deliberately NOT widened to ignored TEST files — but not for the reason first given here.
        The original claim, "an ignored test can neither ship nor suppress collection", is half
        false: verified, pytest collects and RUNS a gitignored test. The true reason is narrower.
        A test that is *tracked* and ignored is listed by `ls-files -c` regardless of ignore rules,
        so it is already protected. A test that is *untracked* and ignored cannot have come from
        the clone — `git clone` copies no untracked files — so it is something the run created, not
        a pre-existing oracle anyone could weaken. The residual is a test the run creates, ignores,
        and then weakens within the same run; recorded, not closed.

        NOT the union with `file_listing(limit=None)`, which was the first design. `os.walk`
        descends what git will not: gitignored build trees, and NESTED CHECKOUTS (`ls-files` is
        boundary-aware as well as ignore-aware). Under the union, regenerating a build artifact or
        writing in a sibling checkout raises `tests_tampered`, which is TERMINAL — a silent hole
        traded for a park that bricks the run. `_SKIP_DIRS` names like `.tox/` and `node_modules/`
        are NOT the mechanism, since the walk prunes those anyway; the canary in
        `test_protected_set_blindness.py` is built on paths that genuinely differ, and it reds the
        union by execution.

        CORRECTION: this docstring first said the union "yields 1,616 integrity paths here against
        247". In a clean checkout it is 249 vs 249 — the 1,616 came from my own working tree holding
        five sibling worktrees under `.claude/`. That is the third time in this arc I published a
        number measured on my dev box as a property of the repo (see ADR-0108's retracted timings).
        The rejection stands on its own terms; the figure did not.

        RAISES on git failure, and the polarity is the whole point. `evidence_hash` returns `""`
        because an empty fingerprint can never equal a stamp — that fails CLOSED. Here there is no
        such value: an empty listing means refuses-nothing, baselines-nothing, guard-vacuously-true.
        So this degrades to nothing rather than to a wrong answer. A fallback to the walk would
        silently re-point a security control at the source just proven blind.

        What callers actually do, checked rather than asserted: `bench/layer2` catches and returns
        its ERROR verdict; `_open_author_context` is wrapped and parks the sweep. `plan_node`,
        `test_node`, `_proctor_authoring`, `disposition` and `bench/operator` all PROPAGATE — a
        loud crash, no delivery. An earlier version of this docstring said "each caller decides",
        which overstated it: most decide nothing, and crashing is the fail-closed outcome anyway.
        """
        # Local import: `testintegrity` imports `Workspace` from this package (the same cycle break
        # `factory._sanction` documents). Importing the predicate rather than restating it keeps one
        # origin for "what is a collection control" — restating it is the second-origin shape that
        # produced this whole class.
        from mosaera_core.pytestconfig import resolve_naming
        from mosaera_core.testintegrity import is_collection_control

        paths = set(self.committable_paths())
        # A collection control only matters where it can actually suppress something we protect:
        # a conftest governs its own directory subtree. Without this bound the term pulls in every
        # ignored conftest anywhere — `.tox/py312/lib/tests/conftest.py`, a vendored tree's — and
        # each becomes a TERMINAL tamper park the moment a tool regenerates it. Caught by this
        # change's own canary test, which is the second time over-protection has been the failure
        # mode rather than blindness.
        # The TARGET's naming, not pytest's defaults. With `is_test_file` here, `guarded` was empty
        # on exactly the repos this term exists to protect (a `python_files` repo has no
        # default-named tests), so the ignored-collection-control term became a no-op and the
        # `.gitignore` + untracked-conftest hole it closes was reopened. Second origin, one module
        # over from the surface that now knows the answer.
        naming = resolve_naming(
            lambda n: _read_root_text(self.root, n), lambda n: (self.root / n).is_file()
        )
        guarded = {
            p.rsplit("/", 1)[0] if "/" in p else "" for p in paths if naming.is_test_basename(p)
        }
        ignored = self.repo.git.ls_files("-o", "-i", "--exclude-standard", "-z")
        for p in ignored.split("\0"):
            if not p or not is_collection_control(p):
                continue
            if p == _SCRATCH_NAMESPACE or p.startswith(_SCRATCH_NAMESPACE + "/"):
                continue
            owner = p.rsplit("/", 1)[0] if "/" in p else ""
            if any(d == owner or d.startswith(owner + "/") if owner else True for d in guarded):
                paths.add(p)
        return sorted(paths)

    def evidence_hash(self) -> str:
        """The fingerprint the EVIDENCE PINS compare — ``""`` when there is nothing to vouch for.

        Same `(path, size, mtime_ns)` hash as `tree_hash`, over `committable_paths` instead of the
        walk. Stat-based deliberately: within one run "somebody wrote" is exactly the question
        (`_baseline._stat_key` documents why), and a content hash is successor work.

        FAILS CLOSED, and the distinction is the point. `tree_hash` builds from `os.walk`, which
        swallows traversal errors, so an unreadable OR empty tree returned `sha256("")` — a
        real-looking hash. Both sides then matched that same sentinel and the pin vouched for a
        tree it could not read. Here git either answers or raises, and an empty committable set is
        `""` rather than a hash of nothing: unreadable and empty are both "no fingerprint", and
        neither can ever equal a stamp.
        """
        try:
            paths = self.committable_paths()
        except Exception:
            return ""
        if not paths:
            return ""
        h = hashlib.sha256()
        for rel in paths:
            try:
                st = (self.root / rel).stat()
            except OSError:
                continue
            h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8", "replace"))
        return h.hexdigest()

    def _stage_all(self) -> None:
        """Stage the whole tree, then FORCE the agent scratch namespace out of the index.

        ``.mosaera/`` is the scratch workbench (#59, ADR-0064) — it must never enter a diff or a
        commit. ``.git/info/exclude`` is only a first layer: a coder ``.gitignore`` negation beats
        it, and it misses a source-TRACKED path (#59 red-team). So the real containment is HERE --
        after ``git add -A``, unstage every ``.mosaera/`` path back to HEAD (drops an untracked
        negation-re-included file, and reverts a modification to a source-tracked one), leaving the
        working tree untouched.
        """
        repo = self.repo
        repo.git.add("-A")
        repo.git.reset("-q", "--", _SCRATCH_NAMESPACE)

    def _assert_no_scratch_staged(self) -> None:
        """Fail closed: never deliver a ``.mosaera/`` path. ``_stage_all`` should already make this
        vacuous — this positive post-stage check is the real guarantee, catching any future
        regression in the one place delivery happens."""
        staged = self.repo.git.diff("--cached", "--name-only", "--diff-filter=ACMR").splitlines()
        leaked = [
            p for p in staged if p == _SCRATCH_NAMESPACE or p.startswith(_SCRATCH_NAMESPACE + "/")
        ]
        if leaked:
            raise DeliveryContainmentError(
                f"refusing to deliver: agent scratch paths staged for commit: {leaked[:5]}"
            )

    def diff_all(self) -> str:
        """Full diff of the working tree against HEAD, including new files (scratch excluded)."""
        self._stage_all()
        return self.repo.git.diff("--cached")

    def diff_readonly(self) -> str:
        """``diff_all`` without touching the workspace's own index.

        Same output, but staged into a THROWAWAY index via ``GIT_INDEX_FILE`` so the real one is
        left exactly as the run left it. That matters because the only caller is a GET (recovering
        a cancelled run's work, which is otherwise unreachable): a read endpoint that silently
        stages the tree would mutate state an operator may still be inspecting, and would make two
        successive reads of the same run behave differently.

        Scratch containment is identical — the same ``reset`` against ``_SCRATCH_NAMESPACE`` runs
        against the temporary index, so ``.mosaera/`` can no more leak here than through delivery.
        """
        repo = self.repo
        with tempfile.TemporaryDirectory() as tmp:
            with repo.git.custom_environment(GIT_INDEX_FILE=str(Path(tmp) / "index")):
                repo.git.read_tree("HEAD")
                repo.git.add("-A")
                repo.git.reset("-q", "--", _SCRATCH_NAMESPACE)
                return str(repo.git.diff("--cached"))

    def commit_all(self, message: str) -> str:
        repo = self.repo
        self._stage_all()
        self._assert_no_scratch_staged()  # never ship the scratch namespace (fail closed)
        # Nothing to commit → "" (no commit was made). Returning the PRIOR HEAD sha
        # here would let a caller record an unrelated commit as "this run's commit".
        if not repo.index.diff("HEAD") and not repo.untracked_files:
            return ""
        commit = repo.index.commit(message)
        return commit.hexsha

    def commit_onto(self, branch: str, message: str) -> str:
        """Commit the working tree onto ``branch``, then return to the branch we were on.

        QUARANTINE (the delivery backstop): when the tree about to ship fails its own suite, the
        work must survive without entering the line every later item is cut from. Item branches are
        cut at the clone's current tip, so committing red where it was headed means every
        subsequent item inherits it — and the next run's baseline then reports those failures as
        "already failing", blaming nobody and making the red permanent.

        The merge-queue answer is to isolate the offender rather than drop the batch, so the commit
        lands on its own branch and the original branch is left exactly where it was: still green,
        still the tip. Nothing is destroyed — which matters, because uncommitted work is swept by
        `reset --hard` + `clean -fd` at the next run's start.

        Returns the sha, or "" when there was nothing to commit.
        """
        repo = self.repo
        was_on = repo.active_branch.name
        repo.git.checkout("-B", branch)
        try:
            sha = self.commit_all(message)
        finally:
            # Restore unconditionally. Leaving the shared project clone parked on a quarantine
            # branch would silently re-target the NEXT item run, which is the exact harm this
            # method exists to prevent.
            repo.git.checkout(was_on)
        return sha
