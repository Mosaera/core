#!/usr/bin/env python3
"""Migration-chain guard — the Alembic revisions must form ONE linear chain with ONE head.

Why this exists. Two parallel sessions each add a migration; both chain from the current head
because both branched from it. The filenames differ (`0033_project_setup.py` vs
`0033_project_github_installation.py`), so **git merges both cleanly with no conflict** and the
repository silently acquires two Alembic heads. `alembic upgrade head` then fails at deploy
time, or worse, applies only one lineage.

Nothing offline catches it: the schema-drift test that would notice is `requires_db`-gated and
skips without `MOSAERA_TEST_DB_URL`, so `make test` stays green while the schema is broken.
That is the *green-by-vacancy* shape — a control that cannot fire on the path people actually
run. This guard fires on `make lint`, with no database.

It compares two facts already in the repo (each file's `revision` and `down_revision`), in the
spirit of `check_doc_claims.py`: no judgement, no new metadata to maintain.

Checks, in order of how badly they bite:
  1. more than one HEAD (nothing points at it) — the parallel-session collision above;
  2. a `down_revision` naming a revision that does not exist — a rebase re-pointed one file
     and not another;
  3. two files claiming the SAME `revision` id;
  4. two files sharing a `down_revision` (a fork, which becomes multiple heads);
  5. a cycle.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VERSIONS = _ROOT / "packages" / "memory" / "mosaera_memory" / "migrations" / "versions"

_REVISION = re.compile(r"^revision:\s*str\s*=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN = re.compile(r"^down_revision:\s*str\s*\|\s*None\s*=\s*(?:[\"']([^\"']+)[\"']|None)", re.M)


def _parse() -> tuple[dict[str, Path], list[str]]:
    """revision id → file, plus any file we could not read a revision out of."""
    revisions: dict[str, Path] = {}
    downs: dict[str, str | None] = {}
    problems: list[str] = []
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rev = _REVISION.search(text)
        if not rev:
            problems.append(f'{path.name}: no `revision: str = "..."` line')
            continue
        ident = rev.group(1)
        if ident in revisions:
            problems.append(
                f"duplicate revision id {ident!r}: {revisions[ident].name} and {path.name} "
                f"— two sessions almost certainly claimed the same number"
            )
            continue
        revisions[ident] = path
        down = _DOWN.search(text)
        downs[ident] = down.group(1) if down and down.group(1) else None
    _check_edges(revisions, downs, problems)
    return revisions, problems


def _check_edges(
    revisions: dict[str, Path], downs: dict[str, str | None], problems: list[str]
) -> None:
    parents: dict[str, list[str]] = {}
    for ident, down in downs.items():
        if down is None:
            continue
        if down not in revisions:
            problems.append(
                f"{revisions[ident].name}: down_revision {down!r} does not exist — a rebase "
                f"re-pointed some files and not this one"
            )
            continue
        parents.setdefault(down, []).append(ident)

    for down, children in sorted(parents.items()):
        if len(children) > 1:
            names = ", ".join(sorted(revisions[c].name for c in children))
            problems.append(
                f"revision {down!r} has {len(children)} children ({names}) — a fork; Alembic "
                f"will report multiple heads. Renumber the later one and re-point down_revision"
            )

    roots = [r for r, d in downs.items() if d is None]
    if len(roots) > 1:
        problems.append(f"{len(roots)} migrations have no down_revision: {sorted(roots)}")

    heads = sorted(r for r in revisions if r not in parents)
    if len(heads) > 1:
        names = ", ".join(revisions[h].name for h in heads)
        problems.append(f"{len(heads)} HEADS ({names}) — `alembic upgrade head` cannot resolve")

    # A cycle leaves nodes unreachable from the root even with exactly one head.
    if len(roots) == 1 and not any("HEADS" in p for p in problems):
        seen, cursor = set(), roots[0]
        while cursor is not None:
            if cursor in seen:
                problems.append(f"cycle in the migration chain at {cursor!r}")
                break
            seen.add(cursor)
            children = parents.get(cursor, [])
            cursor = children[0] if children else None
        unreachable = set(revisions) - seen
        if unreachable and not any("cycle" in p for p in problems):
            problems.append(f"unreachable migrations: {sorted(unreachable)}")


def main() -> int:
    if not _VERSIONS.is_dir():
        print(f"Migration-chain guard: no versions dir at {_VERSIONS}", file=sys.stderr)
        return 1
    revisions, problems = _parse()
    if problems:
        print("Migration-chain guard FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    heads = [r for r in revisions]
    print(
        f"Migration-chain guard OK: {len(revisions)} migrations, one linear chain, "
        f"head {max(heads) if heads else '(none)'}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
