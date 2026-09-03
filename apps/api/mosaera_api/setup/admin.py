"""Creating the first administrator from the terminal (ADR-0116).

THIS REPLACES THE ONE-TIME SETUP TOKEN. ADR-0040 minted a token and printed it to the server's
startup logs so that a browser form could prove the person filling it in had server access. The
wizard runs ON the server, so that proof is no longer needed — being able to run this command IS the
evidence the token stood in for.

The race ADR-0040 closed (CWE-1188: whoever reaches the URL first claims the instance) is closed
here by construction rather than by a token: there is no unauthenticated endpoint that creates an
account, and `POST /auth/users` already refuses when no users exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from mosaera_memory import MemoryStore

from mosaera_api.auth import hash_password, validate_credentials
from mosaera_api.passwords import problem_with


@dataclass(frozen=True)
class AdminOutcome:
    """What happened, in words a screen can render directly."""

    ok: bool
    message: str


def admin_exists(store: MemoryStore) -> bool:
    """Whether this instance already has an account.

    Fails CLOSED on a store that raises: a database we cannot read is not a database we may assume
    is empty, and assuming empty is how a wizard would offer to create a second 'first' admin.
    """
    try:
        return int(store.count_users()) > 0
    except Exception:
        return True


def create_admin(store: MemoryStore, username: str, password: str) -> AdminOutcome:
    """Create the first administrator, or say precisely why not.

    Every refusal names its own cause: the store distinguishes `user_limit` from `username_taken`,
    and collapsing those into "could not create the account" would leave the operator guessing at
    the one moment they cannot get past.
    """
    err = validate_credentials(username, password)
    if err:
        return AdminOutcome(False, err)
    if admin_exists(store):
        # Not an error the operator caused — the instance is already claimed, and the answer is to
        # sign in rather than to try again here.
        return AdminOutcome(False, "this instance already has an account — sign in instead")
    try:
        # `require_first` makes the claim atomic. `admin_exists` above is a courtesy check for a
        # better message; it is NOT the control — two wizards racing each other both passed it and
        # both created an administrator on a first-run instance.
        store.create_user(username, hash_password(password), is_admin=True, require_first=True)
    except ValueError as exc:
        reason = {
            "user_limit": "this instance has reached its account limit",
            "username_taken": "that username is taken",
            "already_claimed": "this instance already has an account — sign in instead",
        }.get(str(exc), str(exc))
        return AdminOutcome(False, reason)
    except Exception as exc:  # a dead or unmigrated store
        from mosaera_api.setup.explain import explain

        return AdminOutcome(False, f"could not reach the database: {explain(str(exc)).summary}")
    return AdminOutcome(True, f"administrator '{username}' created")


async def submit(app: object, field: str, value: str) -> None:
    """Handle one credential field. Lives here because the rules it enforces are this module's.

    Validated PER FIELD. An empty username used to sail through to the password screen and be
    rejected only afterwards, which cost the operator both fields to fix one.
    """
    from mosaera_memory import MemoryStore

    from mosaera_api.setup.steps import database_url, with_timeout

    if field == "username":
        from mosaera_api.auth import username_problem

        if err := username_problem(value.strip()):
            app._note(err, error=True)  # type: ignore[attr-defined]
            return
        app._username = value.strip()  # type: ignore[attr-defined]
        _ask_password(app, again=False)
        return

    if field == "password":
        # VALIDATED BEFORE THE SECOND ENTRY. Asking someone to type a 15-character passphrase twice
        # and only then telling them it was too short costs them both entries to fix one — the same
        # fault per-field validation was introduced to end for the username.
        if err := problem_with(value, app._username):  # type: ignore[attr-defined]
            app._note(err, error=True)  # type: ignore[attr-defined]
            _ask_password(app, again=False)
            return
        app._password = value  # type: ignore[attr-defined]
        _ask_password(app, again=True)
        return

    if field == "password2":
        first, app._password = app._password, ""  # type: ignore[attr-defined]
        if value != first:
            # Start over from the FIRST entry. Keeping it and re-asking only for the confirmation
            # would mean the operator retypes to match a password they cannot see and may have
            # mistyped — the mismatch says nothing about which of the two was wrong.
            app._note("The passwords did not match — enter it again.", error=True)  # type: ignore[attr-defined]
            _ask_password(app, again=False)
            return
        value = first

    settings = app.settings  # type: ignore[attr-defined]
    store, reason = MemoryStore.open_or_reason(with_timeout(settings.db_url or database_url()))
    if store is None:
        from mosaera_api.setup.explain import explain

        app._note(f"Could not reach the database — {explain(reason).summary}", error=True)  # type: ignore[attr-defined]
        return
    outcome = create_admin(store, app._username, value)  # type: ignore[attr-defined]
    app._note(outcome.message, error=not outcome.ok)  # type: ignore[attr-defined]
    if outcome.ok or "already has an account" in outcome.message:
        # The second case is not the operator's mistake and cannot be fixed by retyping — move on
        # rather than loop on it forever. But FORGET the name: the finished screen said
        # "Sign in as <name>" for an account that was never created, because another wizard won
        # the race for it.
        if not outcome.ok:
            app._username = ""  # type: ignore[attr-defined]
        await app._advance()  # type: ignore[attr-defined]
        return
    _ask_password(app, again=False)


def _ask_password(app: object, *, again: bool) -> None:
    """Ask for the password, or for the confirmation of one already given."""
    from mosaera_api.passwords import MIN_LENGTH

    app._password = "" if not again else app._password  # type: ignore[attr-defined]
    app._ask(  # type: ignore[attr-defined]
        "Confirm password" if again else "Password",
        secret=True,
        for_field="password2" if again else "password",
        hint=(
            "Type it again — it is not shown, so this is the only check on a typo."
            if again
            else f"At least {MIN_LENGTH} characters — a passphrase of ordinary words is ideal."
        ),
    )
