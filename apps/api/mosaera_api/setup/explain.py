"""Turn a driver exception into a sentence a person can act on.

WHAT THIS REPLACES. A failed connection used to be rendered verbatim, and what an operator saw was
ten lines of SQLAlchemy and psycopg internals — "OperationalError: (psycopg.OperationalError)
connection failed: … Multiple connection attempts failed. All failures were: - host: 'localhost',
port: 5432, hostaddr: '::1' … (Background on this error at: https://sqlalche.me/e/20/e3q8)". The one
sentence that mattered — `database "mosaera_try" does not exist` — was in the middle of it, and the
whole thing was centred. That is written to be ignored.

THE EVIDENCE IS NOT DISCARDED — but it is not always the most useful thing to show. Every
explanation carries the raw text as `detail` and says whether it RECOGNISED the failure. A screen
shows the raw line when it did not: an unrecognised cause is one this module could not translate, so
the original is the best available account of it. Where the failure IS recognised the summary is a
faithful translation of that line and the `action` says what to do about it, which is worth more
than a truncated `OperationalError: (psycopg.OperationalError) connection failed: connection to
serve…` sitting under a sentence that already said "nothing is listening on that address".

`MemoryStore.open_or_reason` deliberately returns the raw cause and says "the caller reports"; this
module is that caller's half of the bargain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mosaera_core.prereqs import (
    ABSENT,
    DAEMON_DOWN,
    NO_PERMISSION,
    PREREQS,
    Platform,
    detect_platform,
    plan_for,
)


@dataclass(frozen=True)
class Explanation:
    """One sentence, optionally an action that fixes it, and the raw text underneath."""

    summary: str
    #: What the operator can do. Empty when we genuinely do not know.
    action: str = ""
    detail: str = ""
    #: Whether a pattern matched — whether, in other words, `summary` is a translation of the raw
    #: text or merely its first line. A screen decides from this whether the raw text is worth the
    #: room it takes.
    recognised: bool = False


#: Not a command: a marker saying "ask `prereqs` for this one". The right command depends on the
#: platform, and this module is not the place that knows it.
_FROM_TABLE = "\x00table:"

#: Matched in order, first hit wins. Ordered by specificity: "database does not exist" is also a
#: connection failure, and the specific cause is the useful one.
_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        r'database "([^"]+)" does not exist',
        'The database "{0}" does not exist on that server.',
        "Create it, or point at the bundled one.",
    ),
    (
        r'role "([^"]+)" does not exist',
        'The user "{0}" does not exist on that server.',
        "Check the username in MOSAERA_DB_URL.",
    ),
    (
        r"password authentication failed for user \"([^\"]+)\"",
        'Postgres rejected the password for "{0}".',
        "Check the password in MOSAERA_DB_URL.",
    ),
    (
        r"[Cc]onnection refused",
        "Nothing is listening on that address and port.",
        "Start Postgres, or check MOSAERA_DB_PORT.",
    ),
    (
        r"[Nn]ame or service not known|could not translate host name",
        "That host name does not resolve.",
        "Check the host in MOSAERA_DB_URL.",
    ),
    (
        r"[Tt]imeout|timed out",
        "The server did not answer in time.",
        "Check that it is running and reachable.",
    ),
    (
        r"permission denied while trying to connect to the Docker daemon",
        "This user may not talk to the Docker daemon.",
        f"{_FROM_TABLE}docker:{NO_PERMISSION}",
    ),
    (
        r"[Cc]annot connect to the Docker daemon",
        "The Docker daemon is not running.",
        f"{_FROM_TABLE}docker:{DAEMON_DOWN}",
    ),
    (
        r"is not a docker command",
        "This Docker has no Compose v2 plugin.",
        f"{_FROM_TABLE}compose:{ABSENT}",
    ),
)


def _from_the_table(marker: str, plat: Platform) -> str:
    """The action for a Docker row, resolved through the one table that owns install commands.

    These three used to be literal strings — `sudo systemctl start docker`, a `usermod` with "then
    log out and back in", and a Debian package name — which made this module a THIRD origin for
    facts `prereqs` already owns, and every one of them was wrong somewhere: no systemd under WSL,
    no `systemctl` at all on macOS, and `docker-compose-plugin` is Debian's name for it.
    """
    key, _, reason = marker.partition(":")
    prereq = next(p for p in PREREQS if p.key == key)
    plan = plan_for(prereq, plat, reason)
    if not plan.runnable:
        return plan.note or f"See {plan.docs}"
    if key == "compose":
        # A missing Compose PLUGIN is not always a missing package. Where the plan installs a
        # CLI-plugin link, that link IS the answer: on macOS Homebrew puts the binary on PATH and
        # leaves the link to you, so `docker-compose` works while `docker compose` — the form the
        # probe uses — does not. Reinstalling the engine there fixes nothing.
        link = next((s.command for s in plan.steps if "cli-plugins" in s.command), "")
        # Otherwise the vendor script alone: on Linux a missing plugin is answered by reinstalling
        # the engine the one way that brings it, and the plan's `enable`/`usermod` steps answer a
        # different failure — pasting all three under "no Compose v2 plugin" is noise.
        return link or plan.steps[0].command
    parts = [step.command for step in plan.steps]
    if plan.note:
        parts.append(plan.note)
    return " — ".join(parts)


def explain(raw: str, plat: Platform | None = None) -> Explanation:
    """The best sentence available for `raw`. Never empty, and never a wall of driver text.

    `plat` is injectable for the same reason it is everywhere else in this codebase: the macOS and
    WSL wordings cannot be exercised on the machine that writes them.
    """
    text = (raw or "").strip()
    if not text:
        return Explanation("It failed, and said nothing about why.", detail="")
    for pattern, summary, action in _PATTERNS:
        match = re.search(pattern, text)
        if match:
            if action.startswith(_FROM_TABLE):
                action = _from_the_table(action[len(_FROM_TABLE) :], plat or detect_platform())
            return Explanation(summary.format(*match.groups()), action, _tidy(text), True)
    # Unrecognised: the FIRST line only. The rest is almost always the driver explaining itself to
    # other drivers, and it is still available under details.
    first = text.splitlines()[0].strip()
    return Explanation(_strip_wrapper(first), detail=_tidy(text))


def _strip_wrapper(line: str) -> str:
    """Drop the `SomeError: (driver.SomeError)` prefix a wrapped exception carries twice."""
    line = re.sub(r"^\w*Error: ", "", line)
    return re.sub(r"^\([\w.]+\)\s*", "", line).strip() or line


#: How much raw cause is worth keeping. It is a footnote under the sentence that matters — at 400
#: it wrapped to five lines and became the largest thing on the screen, which is the failure this
#: whole module exists to fix.
_DETAIL_LIMIT = 150


def _tidy(text: str) -> str:
    """The raw cause, on one line, with the parts that help nobody removed."""
    text = re.sub(r"\(Background on this error at: [^)]+\)", "", text)
    flat = " ".join(text.split())
    return flat if len(flat) <= _DETAIL_LIMIT else flat[: _DETAIL_LIMIT - 1].rstrip() + "\u2026"
