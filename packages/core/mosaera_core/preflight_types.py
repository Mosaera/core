"""The readiness probe's shared vocabulary: one check, and how long a probe may block.

Its own module so `preflight` (what can serve a model) and `preflight_host` (what is installed on
this machine) can both use it without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

#: `unknown` is a first-class answer: a check we could not evaluate is never rendered as a pass.
Status = Literal["ok", "fail", "unknown", "note"]

# How long a probe may block. These run on the interactive path (the wizard polls them), so a
# wedged daemon must degrade to `unknown` quickly rather than hang the screen.
_PROBE_TIMEOUT = 5.0


@dataclass(frozen=True)
class Check:
    """One question about this deployment, its answer, and what to do about it.

    ``fix`` is a command the operator can paste — never prose. A `fail` without a `fix` is a bug in
    this module: naming a problem you cannot act on is the thing being replaced.
    """

    key: str
    label: str
    status: Status
    detail: str
    fix: str = ""

    @property
    def ok(self) -> bool:
        """The two-state view the SPA's existing `CheckRow` renders. `unknown` reads as NOT ok —
        deny-by-default, because "we could not tell" must never present as a pass."""
        return self.status in ("ok", "note")

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "ok": self.ok,
            "detail": self.detail,
            "fix": self.fix,
        }
