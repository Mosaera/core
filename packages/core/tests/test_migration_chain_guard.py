"""The migration-chain guard must actually detect a fork (ADR-0114).

`check_migration_chain.py` exists because two parallel sessions each add a migration chaining the
current head, the FILENAMES differ, git merges both without a conflict, and Alembic silently ends up
with two heads. The only test that would notice — the schema-drift check — is `requires_db`-gated,
so it skips on `make test` and the break ships green. That is the *green-by-vacancy* shape this
repo has measured before (`#58`), and exactly why a guard for it must itself be tested: a guard
that cannot fire is worse than no guard, because it reads as coverage.

Every case below writes a throwaway migration into the real versions directory and removes it in a
`finally`, then re-asserts the guard passes again — a crash mid-test cannot leave the tree dirty.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "check_migration_chain.py"
_VERSIONS = _ROOT / "packages" / "memory" / "mosaera_memory" / "migrations" / "versions"


def _run() -> tuple[int, str]:
    # Fixed argv, both elements derived from this file's own location — no input.
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


def _migration(revision: str, down: str | None) -> str:
    down_literal = f'"{down}"' if down else "None"
    return (
        '"""throwaway (test)"""\n\n'
        "from __future__ import annotations\n\n"
        f'revision: str = "{revision}"\n'
        f"down_revision: str | None = {down_literal}\n"
        "branch_labels: str | None = None\n"
        "depends_on: str | None = None\n\n\n"
        "def upgrade() -> None: ...\n\n\ndef downgrade() -> None: ...\n"
    )


@contextmanager
def _extra(name: str, body: str) -> Iterator[None]:
    path = _VERSIONS / name
    assert not path.exists(), f"{name} already exists — pick another throwaway name"
    try:
        path.write_text(body, encoding="utf-8")
        yield
    finally:
        path.unlink(missing_ok=True)


def _head() -> str:
    """The current head, read the same way the guard does rather than hardcoded."""
    revisions, parents = set(), set()
    for path in _VERSIONS.glob("[0-9]*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("revision: str"):
                revisions.add(line.split('"')[1])
            elif line.startswith("down_revision: str") and '"' in line:
                parents.add(line.split('"')[1])
    heads = revisions - parents
    assert len(heads) == 1, f"the tree already has {len(heads)} heads: {sorted(heads)}"
    return heads.pop()


def test_the_tree_currently_passes() -> None:
    code, out = _run()
    assert code == 0, out
    assert "one linear chain" in out


def test_a_fork_is_caught__the_parallel_session_collision() -> None:
    """The real scenario: another branch's migration chains the same parent under a different
    filename. This is what git merges without complaint."""
    head = _head()
    parent = None
    for path in _VERSIONS.glob("[0-9]*.py"):
        text = path.read_text(encoding="utf-8")
        if f'revision: str = "{head}"' in text:
            for line in text.splitlines():
                if line.startswith("down_revision: str") and '"' in line:
                    parent = line.split('"')[1]
    assert parent, "could not find the head's parent"

    with _extra("9990_other_session.py", _migration("9990", parent)):
        code, out = _run()
        assert code == 1, "a fork must fail the guard"
        assert "children" in out or "HEADS" in out
    assert _run()[0] == 0, "the tree must be clean again"


def test_a_duplicate_revision_id_is_caught() -> None:
    head = _head()
    with _extra("9991_duplicate.py", _migration(head, "0001")):
        code, out = _run()
        assert code == 1 and "duplicate revision id" in out
    assert _run()[0] == 0


def test_a_dangling_down_revision_is_caught__a_half_finished_rebase() -> None:
    with _extra("9992_dangling.py", _migration("9992", "0999")):
        code, out = _run()
        assert code == 1 and "does not exist" in out
    assert _run()[0] == 0


def test_a_second_root_is_caught() -> None:
    with _extra("9993_second_root.py", _migration("9993", None)):
        code, out = _run()
        assert code == 1
        assert "no down_revision" in out or "HEADS" in out
    assert _run()[0] == 0
