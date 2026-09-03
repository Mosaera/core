"""Command-line interface for the journal.

Resolves the JSON file, parses the sub-command, and delegates to the store. New
sub-commands are wired in here and delegate to :class:`journal.store.Store`.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from journal.model import Entry
from journal.store import Store


def _store() -> Store:
    path = os.environ.get("JOURNAL_FILE", "journal.json")
    return Store(Path(path))


def _format(entry: Entry) -> str:
    tags = ("  " + " ".join("#" + t for t in entry.tags)) if entry.tags else ""
    return f"{entry.id}  {entry.text}{tags}"


def _cmd_add(args: argparse.Namespace) -> int:
    print(_store().add(args.text).id)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    for entry in _store().all():
        print(_format(entry))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="journal", description="A tiny journal.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add an entry")
    p_add.add_argument("text")
    p_add.set_defaults(func=_cmd_add)

    p_list = sub.add_parser("list", help="list every entry in id order")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))
