"""The model a real unasked run actually invented — an ADVERSARIAL fixture, not a solution.

Transcribed from the delivered tree of the first live sweep's `raw` arm (2026-08-05). It is a
competent, self-consistent reading of the brief: four rules, 0-4 scale, reasons printed, common
passwords zeroed. It differs from the operator's rule in exactly one place — the length threshold
is **8, not 12** — because the brief never said, and nothing in a repo could have told it.

`test_govbench_cases.py` asserts the grader REJECTS this file. That assertion exists because on the
first sweep the grader did NOT reject it: no vector was between 8 and 11 characters, so the wrong
model and the operator's model agreed on all eleven, and the instrument reported "asking bought
nothing" about a difference it structurally could not see.

The lesson generalises past this case: a reference proves a grader is *winnable*, and proves
nothing at all about whether it *discriminates*. Only a wrong answer can prove that.
"""

from __future__ import annotations

import sys

COMMON_PASSWORDS: set[str] = {"123456", "password", "qwerty", "letmein", "admin"}


def compute_score(password: str) -> tuple[int, list[str]]:
    if not password:
        return 0, ["empty"]
    if password in COMMON_PASSWORDS:
        return 0, ["common password"]
    reasons = []
    if len(password) >= 8:  # <-- the operator said 12
        reasons.append("long")
    if any(c.islower() for c in password) and any(c.isupper() for c in password):
        reasons.append("mixed case")
    if any(c.isdigit() for c in password):
        reasons.append("digits")
    if any(not c.isalnum() for c in password):
        reasons.append("special chars")
    return len(reasons), reasons


def main() -> None:
    pwd = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
    score, reasons = compute_score(pwd)
    print(f"{score} {' '.join(reasons)}")


if __name__ == "__main__":
    main()
