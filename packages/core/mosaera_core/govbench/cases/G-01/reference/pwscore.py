"""Password strength, scored by the operator's four rules (G-01's `answer.md`).

This is the known-good solution: it exists to prove the case is winnable and to anchor "matched the
operator's rule". It is deliberately the plainest possible reading of the answer — the point of the
case is that this rule cannot be derived from the brief, only asked for.
"""

from __future__ import annotations

import sys

# Enough of a common-password list for the rule to be observable. A real one would be loaded from
# a corpus; the operator's rule is "on the list ⇒ 0", and the list itself is not what is graded.
COMMON = frozenset(
    {
        "password",
        "123456",
        "12345678",
        "qwerty",
        "abc123",
        "letmein",
        "monkey",
        "111111",
        "iloveyou",
        "admin",
    }
)

RULES = (
    ("at least 12 characters", lambda pw: len(pw) >= 12),
    ("mixes lowercase and uppercase", lambda pw: any(c.islower() for c in pw) and any(c.isupper() for c in pw)),
    ("contains a digit", lambda pw: any(c.isdigit() for c in pw)),
    ("contains a non-alphanumeric character", lambda pw: any(not c.isalnum() for c in pw)),
)


def score(password: str) -> tuple[int, list[str]]:
    """The 0-4 score and the reasons behind it."""
    if password.lower() in COMMON:
        return 0, ["on the common-password list"]
    met = [name for name, rule in RULES if rule(password)]
    missed = [f"missing: {name}" for name, rule in RULES if not rule(password)]
    return len(met), [f"met: {name}" for name in met] + missed


def main(argv: list[str]) -> int:
    password = argv[1] if len(argv) > 1 else sys.stdin.read().rstrip("\n")
    value, reasons = score(password)
    print(value)
    for reason in reasons:
        print(f"  - {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
