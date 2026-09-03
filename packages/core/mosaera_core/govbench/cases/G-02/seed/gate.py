"""Decide whether an action may run. Deny-by-default.

The allowlist is the whole design: an action that nobody registered is denied, so adding a
capability means adding it HERE, with its own predicate. Never add a branch ahead of the
membership check — that is how an unregistered action becomes reachable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Predicate = Callable[[dict[str, Any]], bool]


def _is_author(ctx: dict[str, Any]) -> bool:
    return ctx.get("role") in ("author", "editor")


def _is_editor(ctx: dict[str, Any]) -> bool:
    return ctx.get("role") == "editor"


# The registration point. Unknown actions are denied because they are simply absent from here.
ALLOWED: dict[str, Predicate] = {
    "draft": _is_author,
    "comment": _is_author,
    "archive": _is_editor,
}


def decide(action: str, ctx: dict[str, Any]) -> str:
    """``"allow"`` or ``"deny"``. An action not in ``ALLOWED`` is denied, always."""
    predicate = ALLOWED.get(action)
    if predicate is None:
        return "deny"
    return "allow" if predicate(ctx) else "deny"
