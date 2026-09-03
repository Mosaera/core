#!/usr/bin/env python
"""Materialize a demo repo (``demos/<shape>``) as a throwaway git repo and print
how to drive it through Mosaera.

In-repo fixtures + local-path driving (#53): the host dev server clones a local
path directly, so no GitLab repos are needed. Reuses the bench's git-init pattern
(``bench/harness.py`` ``_existing_seed`` / ``_greenfield_seed``): greenfield is an
EMPTY repo (no commit) so cloning triggers the greenfield scaffold; the others get
one seed commit.

Usage::

    python demos/materialize.py brownfield              # materialize + print drive steps
    python demos/materialize.py greenfield --drive cli  # ...and run the CLI smoke (blind approve)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from git import Repo

DEMOS = Path(__file__).resolve().parent
SHAPES = ("greenfield", "brownfield", "spaghetti")
_META = {"BRIEF.md", "EXPECTED.md"}  # authoring metadata — never copied into the materialized repo


def _fixture_files(shape_dir: Path) -> list[Path]:
    """Every real fixture file under ``shape_dir`` (excludes the BRIEF/EXPECTED metadata
    and any ``__pycache__``)."""
    out: list[Path] = []
    for p in sorted(shape_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(shape_dir)
        if rel.parts[0] in _META or "__pycache__" in rel.parts:
            continue
        out.append(p)
    return out


def materialize(shape: str, dest: Path) -> Path:
    """Copy ``demos/<shape>`` (minus metadata) into ``dest`` as a git repo. Greenfield
    has no source → an empty repo with NO commit (the greenfield trigger); the others
    get one seed commit so cloning is an ordinary read-before-write clone."""
    src = DEMOS / shape
    if not src.is_dir():
        raise SystemExit(f"unknown shape {shape!r}; expected one of {', '.join(SHAPES)}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    repo = Repo.init(dest, initial_branch="main")
    # A committer identity may not exist headless — set it locally so the seed commit
    # never depends on global git config (mirrors bench/harness.py).
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Mosaera Demo")
        cw.set_value("user", "email", "demo@mosaera.local")
    files = _fixture_files(src)
    for f in files:
        target = dest / f.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    if files:  # greenfield has none → leave the repo empty (no commit) = the greenfield trigger
        repo.git.add(A=True)
        repo.index.commit("seed: initial project state")
    return dest


def brief(shape: str) -> str:
    return (DEMOS / shape / "BRIEF.md").read_text(encoding="utf-8").strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Materialize a demo repo and print how to drive it.")
    ap.add_argument("shape", choices=SHAPES)
    ap.add_argument("--dest", default=None, help="where to materialize (default: a temp dir)")
    ap.add_argument(
        "--drive",
        choices=("print", "cli"),
        default="print",
        help="print the drive steps (default), or run the CLI smoke (blindly approves)",
    )
    args = ap.parse_args(argv)

    dest = (
        Path(args.dest)
        if args.dest
        else Path(tempfile.mkdtemp(prefix=f"mosaera-demo-{args.shape}-"))
    )
    repo = materialize(args.shape, dest)
    task = " ".join(brief(args.shape).splitlines())  # one line for --task
    print(f"materialized {args.shape} -> {repo}")
    print()

    if args.drive == "cli":
        # CLI --approve-all is a BLIND smoke — it approves every gate and would "ship" a
        # validation_failed run. Use the webUI autonomous path for the faithful terminal
        # buckets (see demos/README.md). This is only a quick "does it run" check.
        cmd = [
            sys.executable,
            "-m",
            "mosaera_core.cli",
            "run",
            "--repo",
            str(repo),
            "--task",
            task,
            "--approve-all",
        ]
        print("CLI smoke (blindly approves):", " ".join(cmd))
        return subprocess.call(cmd)  # noqa: S603 — dev helper running a known command on a demo path

    print("drive it:")
    print(
        f'  CLI smoke (blind approve):  mosaera run --repo "{repo}" --task "<brief>" --approve-all'
    )
    print(f"  webUI (FAITHFUL gate):      new project with source_repo = {repo}, approve the")
    print(
        "                              overview, then run the item AUTONOMOUS (or start the sweep)."
    )
    print("  see demos/README.md for the full runbook + expected outcome per shape.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
