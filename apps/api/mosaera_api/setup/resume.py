"""Acknowledging a run that did not finish.

THE POSITION IS NEVER RESTORED FROM A FILE. Every step of the wizard already probes the machine and
skips what is done, which is a stronger resume than a stored cursor: a cursor saying "you were at
images" is a lie the moment someone removes Docker in between, and acting on it would walk the
operator past a check that no longer passes.

So this module records a BREADCRUMB and turns it into a SENTENCE. That is all it does. It selects no
step, skips no check, and a stale, corrupt or absent breadcrumb degrades silently to the behaviour
of a first run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mosaera_core.settings_store import read_settings, write_settings

_KEY = "setup_progress"

#: What each step is called in the sentence. Only the ones an operator can be interrupted ON — the
#: bookends are not places you get stuck.
_NAMES = {
    "machine": "checking what this machine needs",
    "images": "building the sandbox images",
    "database": "the database step",
    "access": "choosing who can reach it",
    "admin": "creating the administrator",
}


@dataclass(frozen=True)
class Breadcrumb:
    """Where the last run was when it stopped."""

    step: str = ""

    @property
    def known(self) -> bool:
        return self.step in _NAMES


def record(home: Path, step: str) -> None:
    """Note the step being entered. Best effort: a read-only home must not take the wizard down —
    losing a breadcrumb costs one sentence, and raising here would cost the install."""
    if step not in _NAMES:
        return
    try:
        write_settings(home, {_KEY: {"step": step}})
    except OSError:
        pass


def clear(home: Path) -> None:
    """Setup finished. There is nothing to pick up, so the next run must not claim there is."""
    try:
        write_settings(home, {_KEY: None})
    except OSError:
        pass


def read(home: Path) -> Breadcrumb:
    raw = read_settings(home).get(_KEY)
    if not isinstance(raw, dict):
        return Breadcrumb()
    step = raw.get("step")
    return Breadcrumb(step) if isinstance(step, str) else Breadcrumb()


def sentence(crumb: Breadcrumb) -> str:
    """The acknowledgement, or "" when there is nothing honest to say."""
    if not crumb.known:
        return ""
    return (
        f"Picking up where you left off — the last run stopped at {_NAMES[crumb.step]}.\n"
        "Everything already done is skipped; nothing is repeated."
    )
