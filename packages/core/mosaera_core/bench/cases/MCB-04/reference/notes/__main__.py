"""Command-line entry point for the notes CLI.

Usage:
    python -m notes add "<text>"
    python -m notes list
    python -m notes search "<term>"
"""

from __future__ import annotations

import sys

from notes import storage


def cmd_add(args: list[str]) -> int:
    if not args:
        print("add requires note text", file=sys.stderr)
        return 2
    notes = storage.load()
    note = {"id": len(notes) + 1, "text": args[0]}
    notes.append(note)
    storage.save(notes)
    print(note["id"])
    return 0


def cmd_list(args: list[str]) -> int:
    for note in storage.load():
        print(f"{note['id']}: {note['text']}")
    return 0


def cmd_search(args: list[str]) -> int:
    if not args:
        print("search requires a term", file=sys.stderr)
        return 2
    term = args[0].lower()
    for note in storage.load():
        if term in str(note["text"]).lower():
            print(f"{note['id']}: {note['text']}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: notes <add|list|search> ...", file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    handlers = {"add": cmd_add, "list": cmd_list, "search": cmd_search}
    handler = handlers.get(command)
    if handler is None:
        print(f"unknown command: {command}", file=sys.stderr)
        return 2
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
