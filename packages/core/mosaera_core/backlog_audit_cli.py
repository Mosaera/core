"""`mosaera-audit-backlog` — report which existing backlog items intake would question.

**Read-only. It opens the database, reads, prints, and exits.** No write path exists in this
module, which is deliberate rather than incidental: the first thing pointed at a real operator's
backlog must not be able to lock it. Three graders authored during the 2026-08-05 governance sweeps
were wrong in the over-strict direction; here the equivalent mistake would lock somebody's real
work, so the sweep reports and a human decides.

    uv run mosaera-audit-backlog                     # every project
    uv run mosaera-audit-backlog --project <id>      # one project
    uv run mosaera-audit-backlog --json out.json     # machine-readable, for a diff later

Needs `MOSAERA_DB_URL` (or the configured default). Prints and exits 0 whatever it finds — a
non-zero exit would make this awkward to run from a shell loop, and "found problems" is not an
error, it is the answer.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from mosaera_core.backlog_audit import audit_backlog, render_audit
from mosaera_core.clauses import load_clauses
from mosaera_core.config import Settings, load_env, undeclared_bundled_db


def _why(exc: BaseException) -> str:
    """The operator-facing reason, not the stack. Prefers the DRIVER's message — the useful line
    ("password authentication failed", "connection refused") is the innermost cause, and the
    SQLAlchemy wrapper around it adds a URL to a docs page, not information."""
    root = exc
    while root.__cause__ is not None:
        root = root.__cause__
    detail = " ".join(str(root).split())
    # psycopg appends a per-address retry log ("Multiple connection attempts failed. All failures
    # were: - host ... ::1 ...") which restates the same failure once per resolved address. The
    # first clause is the answer; the rest pushes it off the operator's screen.
    detail = detail.split("Multiple connection attempts failed")[0].strip()
    return f"{type(root).__name__}: {detail[:200]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", action="append", help="project id (repeatable); default: all")
    parser.add_argument("--json", dest="json_out", help="write the full report here")
    parser.add_argument(
        "--checkability-only",
        action="store_true",
        help="only the UNDER_SPECIFIED axis (what the launch gate refuses today); "
        "by default the decidability axis is reported too",
    )
    args = parser.parse_args(argv)

    # Honor `.env`, matching every other entrypoint (`mosaera-api`, `mosaera` CLI,
    # `scripts/db_migrate.py`). `Settings.from_env()` reads `os.environ` and does NOT load the
    # file itself, so an entrypoint that forgets this line sees an operator's configured database
    # as "no database configured" — which is exactly what this tool did on its first real run,
    # one command after `make db-migrate` succeeded against the very same `.env`.
    load_env()
    settings = Settings.from_env()
    if not settings.db_url:
        print("No database configured (MOSAERA_DB_URL). Nothing to audit.")
        # "Nothing to audit" is misleading when the bundled database is up and simply
        # undeclared — the state an operator lands in one command after `make up`.
        bundled = undeclared_bundled_db()
        if bundled:
            print(
                "\nA database IS reachable on this host but no MOSAERA_DB_URL is set — the\n"
                "bundled URL is composed inside scripts/dev-up.sh and exported only into the\n"
                "process `make up` starts. Declare it for this shell and re-run:\n\n"
                f'  export MOSAERA_DB_URL="{bundled}"\n\n'
                "Or uncomment MOSAERA_DB_URL in .env to make it the default for every entrypoint."
            )
        return 0

    from mosaera_memory import MemoryStore

    # A wrong password must not answer with 80 lines of SQLAlchemy traceback — an operator tool
    # that cannot explain its own failure is the ADR-0035 complaint ("infrastructure failure is
    # loud") satisfied in the letter and missed in the spirit: loud is not the same as clear.
    #
    # NOT `MemoryStore.open_or_reason`, which is what `db_migrate.py` uses and looks like the
    # obvious reuse: it calls `store.init()`, which runs MIGRATIONS. Borrowing it here would make
    # a tool whose entire promise is "changes nothing" quietly write to the operator's database.
    try:
        memory = MemoryStore.from_url(settings.db_url)
        project_ids = args.project or [str(p["id"]) for p in memory.list_projects()]
    except Exception as exc:
        print(f"backlog-audit: could not read the database — {_why(exc)}")
        print("Nothing was changed.")
        return 1
    if not project_ids:
        print("No projects found.")
        return 0

    everything: list[dict[str, Any]] = []
    for project_id in project_ids:
        items = memory.list_backlog_items(project_id)
        if not items:
            continue
        # Standing decisions are read UNCONDITIONALLY of the knob: a ratified clause settles a
        # question, and an audit that ignored them would report items as unaskable that the
        # operator has already decided — nagging about a settled thing is the fatigue ADR-0080
        # names, and it would be this tool's first impression.
        clauses = load_clauses(memory, project_id, enabled=True)
        open_asks = {
            int(i["id"]): ask
            for i in items
            if (ask := memory.item_clarification(int(i["id"]))) is not None
        }
        report = audit_backlog(
            items,
            clauses,
            open_asks=open_asks,
            decidability_asks=not args.checkability_only,
        )
        print(f"\n=== project {project_id} ===")
        print(render_audit(report, total_items=len(items)))
        everything.append(
            {
                "project_id": project_id,
                "total_items": len(items),
                "flagged": len(report.rows),
                "would_lock": len(report.would_lock),
                "already_asked": len(report.already_locked),
                "rows": report.as_dicts(),
            }
        )

    if args.json_out:
        from pathlib import Path

        Path(args.json_out).write_text(json.dumps(everything, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    total_lock = sum(p["would_lock"] for p in everything)
    print(f"\nTOTAL: {total_lock} item(s) across {len(everything)} project(s) would be locked.")
    print("Nothing was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
