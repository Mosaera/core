"""Command-line interface for the journal (reference solution).

Wires the tag/find sub-commands through to the store, preserving add/list.
"""

from __future__ import annotations

import argparse
import os
import sys
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


def _cmd_tag(args: argparse.Namespace) -> int:
    if not _store().add_tag(args.id, args.label):
        print(f"no entry with id {args.id}", file=sys.stderr)
        return 1
    return 0


def _cmd_find(args: argparse.Namespace) -> int:
    for entry in _store().find(args.label):
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

    p_tag = sub.add_parser("tag", help="attach a tag to an entry")
    p_tag.add_argument("id", type=int)
    p_tag.add_argument("label")
    p_tag.set_defaults(func=_cmd_tag)

    p_find = sub.add_parser("find", help="list entries carrying a tag")
    p_find.add_argument("label")
    p_find.set_defaults(func=_cmd_find)

    args = parser.parse_args(argv)
    return int(args.func(args))
