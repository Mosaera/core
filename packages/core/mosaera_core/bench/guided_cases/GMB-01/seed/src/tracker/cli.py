"""A tiny expense recorder."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from decimal import Decimal

FIELDS = ["date", "amount", "category", "note"]


def add_expense(path: str, row: dict[str, str]) -> None:
    """Append one expense row, writing the header when the file is new or empty."""
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker")
    sub = parser.add_subparsers(dest="command")
    add = sub.add_parser("add")
    add.add_argument("amount")
    add.add_argument("category")
    add.add_argument("--date")
    add.add_argument("--file", default="./expenses.csv")
    args = parser.parse_args(argv)
    if args.command != "add":
        parser.print_help()
        return 1
    amount = Decimal(args.amount).quantize(Decimal("0.01"))
    expense_date = args.date or date.today().isoformat()
    add_expense(
        args.file,
        {
            "date": expense_date,
            "amount": str(amount),
            "category": args.category,
            "note": "",
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
