"""Ask a project what it already knows about itself.

    mosaera-memory <project-id>
    mosaera-memory <project-id> --json out.json

Read-only: every query in `project_memory` is a SELECT, so this can be pointed at a live
database without touching the project it is reading.

Deliberately a CLI before it is a PM tool. The questions are worth answering by hand first —
what a project can say about itself is also a measurement of what it bothered to record, and
that is easier to read in a terminal than to infer from a chat reply. The output doubles as the
regression fixture: run it against a known project and the numbers should not move.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from mosaera_core.config import Settings
from mosaera_core.project_memory import (
    Answer,
    criteria_that_failed_here,
    item_history,
    open_work_and_blockers,
    orphaned_history,
    recurring_failures,
)
from mosaera_core.project_memory_render import render_answer


def _render(a: Answer, *, limit: int) -> None:
    """Print one answer. The text itself comes from `render_answer`, which the read-only history
    tool also uses — the CLI and the tool must not describe the same records differently."""
    print(render_answer(a, limit=limit, more_hint="use --json for all"), end="")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mosaera-memory", description=__doc__)
    p.add_argument("project_id")
    p.add_argument("--json", dest="json_out", default="", help="write the full result here")
    p.add_argument("--limit", type=int, default=8, help="findings shown per query (default 8)")
    p.add_argument("--min-runs", type=int, default=3, help="contested-item threshold (default 3)")
    args = p.parse_args(argv)

    # Imported here, not at module scope: the memory package is an optional dependency of a
    # core install, and a CLI that cannot connect should fail with a sentence rather than an
    # ImportError traceback at startup.
    try:
        from mosaera_memory import MemoryStore
    except ImportError:  # pragma: no cover - environment-dependent
        print("mosaera-memory needs the memory package installed.", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    if not settings.db_url:
        print("no database configured — set MOSAERA_DB_URL.", file=sys.stderr)
        return 2
    store = MemoryStore.from_url(settings.db_url)

    runs = store.history_runs(args.project_id)
    items = store.history_items(args.project_id)
    run_item_ids = store.history_run_item_ids(args.project_id)

    if not runs and not items:
        print(f"No history for project {args.project_id!r} — wrong id, or nothing has run yet.")
        return 1

    print(f"# project memory: {args.project_id}")
    print(f"  {len(runs)} run(s), {len(items)} backlog item(s) recorded")
    attributed = sum(1 for r in runs if r.get("item_id") is not None)
    print(f"  {attributed} of {len(runs)} run(s) attributable to an item")

    answers = [
        open_work_and_blockers(items),
        recurring_failures(runs),
        item_history(runs, items, min_runs=args.min_runs),
        criteria_that_failed_here(runs, items),
        orphaned_history(run_item_ids, items),
    ]
    for a in answers:
        _render(a, limit=args.limit)

    if args.json_out:
        payload: dict[str, Any] = {
            "project_id": args.project_id,
            "runs": len(runs),
            "items": len(items),
            "answers": [asdict(a) for a in answers],
        }
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
