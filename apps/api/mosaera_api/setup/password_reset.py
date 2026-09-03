"""Resetting a forgotten password, from the wizard.

**Why this is not a privilege escalation.** Running `mosaera-setup` already means read access to
the install's `.env`, which holds `MOSAERA_DB_URL` — so whoever can reach this screen can already
open the database and rewrite a password hash by hand. This adds convenience, not authority, and
that is the whole of the security argument: the wizard is a LOCAL tool for the machine's owner, and
the control that matters is who can run it at all.

What it does NOT do is matter to a remote caller: there is no route, no endpoint, and no token that
reaches this. `store.set_user_password` revokes the account's sessions and clears its login-backoff
bucket, so a reset also ends whatever was signed in with the old password — which is the behaviour
someone resetting a *forgotten* password wants, and the behaviour someone resetting a *stolen* one
needs.

Its screens live here rather than in `screens.py` because they are this flow's alone, and that
module is at its size ceiling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mosaera_api.setup.screens import Screen
from mosaera_api.setup.ui import DIM

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


def _store(app: SetupApp) -> tuple[Any, str]:
    from mosaera_memory import MemoryStore

    from mosaera_api.setup.steps import database_url, with_timeout

    return MemoryStore.open_or_reason(with_timeout(app.settings.db_url or database_url()))


def pick(users: list[dict[str, Any]]) -> Screen:
    """Which account. Shown even for a single user, because a password reset that does not name
    whose password it is resetting is a screen an operator has to guess at."""
    return Screen(
        title="Reset a password",
        body=(
            "The new password replaces the old one immediately, and signs that account out\n"
            "everywhere it is currently signed in."
        ),
        choices=[
            f"{u['username']}" + (f"  [{DIM}]admin[/]" if u.get("is_admin") else "") for u in users
        ]
        + ["Cancel"],
        hint="Enter to choose  ·  Esc to go back",
    )


async def enter(app: SetupApp) -> None:
    store, reason = _store(app)
    if store is None:
        from mosaera_api.setup.explain import explain

        app._note(f"Could not reach the database — {explain(reason).summary}", error=True)
        await app._goto(app._returns_to or "done")
        return
    users = store.list_users()
    if not users:
        # Nothing to reset is not a failure; it is the state a fresh instance is in.
        app._note("There are no accounts on this instance yet.", error=True)
        await app._goto(app._returns_to or "done")
        return
    app.step = "reset"
    app._reset_user = None
    app._paint(pick(users))


async def chose(app: SetupApp, index: int) -> None:
    # Re-read rather than hold the list that was drawn. `list_users` orders by id, so the row the
    # operator picked is the row this resolves — and a copy on the app would be one more piece of
    # state to leave stale behind a screen that can be returned to.
    store, _reason = _store(app)
    users = list(store.list_users()) if store is not None else []
    if index >= len(users):
        await app._goto(app._returns_to or "done")
        return
    app._reset_user = users[index]
    _ask(app, again=False)


def _ask(app: SetupApp, *, again: bool) -> None:
    from mosaera_api.passwords import MIN_LENGTH

    who = str((app._reset_user or {}).get("username", ""))
    app._paint(
        Screen(
            title=f"New password for {who}",
            body=(
                "Signing that account out everywhere is part of this — an old session would\n"
                "otherwise outlive the password it was created with."
            ),
        )
    )
    app._ask(
        "Confirm password" if again else "New password",
        secret=True,
        for_field="reset2" if again else "reset1",
        hint=(
            "Type it again — it is not shown, so this is the only check on a typo."
            if again
            else f"At least {MIN_LENGTH} characters — a passphrase of ordinary words is ideal."
        ),
    )


async def submit_first(app: SetupApp, value: str) -> None:
    """Validated BEFORE the confirmation, so a rejected password costs one entry rather than two."""
    from mosaera_api.passwords import problem_with

    who = str((app._reset_user or {}).get("username", ""))
    if err := problem_with(value, who):
        app._note(err, error=True)
        _ask(app, again=False)
        return
    app._password = value
    _ask(app, again=True)


async def submit_second(app: SetupApp, value: str) -> None:
    from mosaera_api.auth import hash_password, login_subject, normalize_username

    first, app._password = app._password, ""
    if value != first:
        # Back to the FIRST entry: the mismatch says nothing about which of the two was mistyped,
        # and the operator cannot see either of them.
        app._note("The passwords did not match — enter it again.", error=True)
        _ask(app, again=False)
        return
    store, reason = _store(app)
    if store is None:
        from mosaera_api.setup.explain import explain

        app._note(f"Could not reach the database — {explain(reason).summary}", error=True)
        return
    who = app._reset_user or {}
    # The NORMALIZED name, as `routes/auth.py` does it — the bucket is keyed on what the login path
    # hashes, and a reset that clears a different key would leave a locked-out account still locked
    # out with a password that now works.
    subject = login_subject(normalize_username(str(who.get("username", ""))))
    store.set_user_password(int(str(who["id"])), hash_password(first), subject_hash=subject)
    app._reset_user = None
    app._note(f"Password changed for {who.get('username', '')} — signed out everywhere.")
    await app._goto(app._returns_to or "done")
